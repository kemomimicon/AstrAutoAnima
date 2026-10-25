"""Opt-in NapCat installation preparation and local, read-only connection checks.

Never edits QQ login data, AstrBot adapters, firewall rules, or existing NapCat files.
The upstream installer remains interactive; its dependencies are not bundled here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import queue
import secrets
import shlex
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import webbrowser
import zipfile

from deployment_support import clean_path, no_links
from download_network import DownloadNetwork
from easy_installer import download_file, sha256_file

OFFICIAL_GUIDE = 'https://napneko.github.io/guide/boot/Shell'
ASTRBOT_GUIDE = 'https://docs.astrbot.app/en/platform/aiocqhttp.html'
ASSETS = {
    'windows': {
        'version': 'v4.18.38', 'name': 'NapCat.Shell.Windows.OneKey.zip', 'size': 994134,
        'url': 'https://github.com/NapNeko/NapCatQQ/releases/download/v4.18.38/NapCat.Shell.Windows.OneKey.zip',
        'sha256': '46c3ec155aa61f12e89bbf97013a21243d00b0019b5565992a88852d7627f39c',
    },
    'linux': {
        'version': 'bc668fdc29bf3a7a53a3cff34572734322df8d17', 'name': 'napcat-install.sh', 'size': 43826,
        'url': 'https://raw.githubusercontent.com/NapNeko/NapCat-Installer/bc668fdc29bf3a7a53a3cff34572734322df8d17/script/install.sh',
        'sha256': 'eafcc4594198f60d9f6649665bce57acbc9432a0cf534bbdead2f0c561837b33',
    },
}
# Also revalidate the installer and all adjacent DLLs before a later explicit launch.
WINDOWS_FILES = {
    '7z.dll': '34ad9bb80fe8bf28171e671228eb5b64a55caa388c31cb8c0df77c0136735891',
    '7z.exe': '344f076bb1211cb02eca9e5ed2c0ce59bcf74ccbc749ec611538fa14ecb9aad2',
    'bootmain/napcat.bat': 'fc01e7fe80e64eecce58d0a652a7f85e37b640c4cf4e2de15e3023cbec627863',
    'bootmain/napcat.kill.qq.bat': 'c528968d694d217a66b8b225056f8ad79fc2f7dae8f99d32c42e8a23935b8434',
    'bootmain/napcat.quick.bat': '610716ba7e0a3e49529015146debbe62db149cc635511e75406aa82933bd8896',
    'bootmain/NapCatWinBootHook.dll': 'e7f9d3aec57b82e2fdb8ee2c874845641d8ed60ba7741fe2b20be2de9305d172',
    'bootmain/NapCatWinBootMain.exe': '8b860a0be0993211c8664a08097d09979fb7e3406f63247c5a3b4251dad8e744',
    'bootmain/ReadMe.txt': 'd986a6ce9cd9f1b6caace866bee3a6a410f52f69c82cb2aad809ad39646e73e4',
    'NapCatInstaller.exe': 'c1545743f1f62c0aad892b3ad0a7b2fb40b263a841353748d303fec461a501f2',
}


def platform_name():
    if sys.platform == 'win32': return 'windows'
    if sys.platform.startswith('linux'): return 'linux'
    raise ValueError('本向导仅支持 Windows / Linux；不在其他系统上执行安装。')


def verify_file(path, digest, size=0):
    path = Path(path)
    no_links(path)
    if not path.is_file() or (size and path.stat().st_size != size) or sha256_file(path) != digest:
        raise ValueError('安装文件大小或 SHA256 不匹配；保留原文件，不会执行：' + path.name)


def safe_extract(archive, destination):
    """Extract into a newly allocated empty directory, never an existing installation."""
    destination = Path(destination)
    no_links(destination)
    if not destination.is_dir() or any(destination.iterdir()):
        raise ValueError('解压目标必须是新建空目录。')
    with zipfile.ZipFile(archive) as package:
        members = package.infolist()
        if len(members) > 100 or sum(m.file_size for m in members) > 32 * 1024**2:
            raise ValueError('安装入口 ZIP 内容超出预期。')
        seen = set()
        for member in members:
            # ZipInfo can silently normalize backslashes / NUL on Windows.
            name = member.orig_filename
            parts = PurePosixPath(name).parts
            if (not parts or name.startswith('/') or '\\' in name or ':' in name or
                    any(p in {'..', '.'} or p.endswith((' ', '.')) or
                        p.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM' + str(i) for i in range(1, 10)), *('LPT' + str(i) for i in range(1, 10))}
                        for p in parts) or any(c in name for c in '<>"|?*') or
                    any(ord(c) < 32 for c in name) or stat.S_ISLNK(member.external_attr >> 16)):
                raise ValueError('ZIP 路径不安全，停止解压。')
            key = name.rstrip('/').casefold()
            if key in seen: raise ValueError('ZIP 存在重复路径。')
            seen.add(key)
            target = destination.joinpath(*parts)
            target.resolve().relative_to(destination.resolve())
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.filename).parts)
            no_links(target)
            if member.is_dir(): target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as out, package.open(member) as source:
                    import shutil
                    shutil.copyfileobj(source, out)


def verify_windows_tree(folder):
    folder = Path(folder)
    no_links(folder)
    actual = set()
    for item in folder.rglob('*'):
        no_links(item)
        if item.is_file(): actual.add(item.relative_to(folder).as_posix())
    if actual != set(WINDOWS_FILES):
        raise ValueError('安装入口目录内容已变化。请重新准备安装入口；不要覆盖已有 NapCat。')
    for name, digest in WINDOWS_FILES.items(): verify_file(folder / name, digest)


def prepare(platform, directory, *, consent=False, local_file='', network=None, log=print):
    if not consent: raise ValueError('未确认准备安装文件，不会下载、解压或安装。')
    if platform not in ASSETS: raise ValueError('请选择 Windows 或 Linux。')
    raw = clean_path(directory)
    root = Path(raw)
    if not raw or not root.is_absolute(): raise ValueError('请选择绝对路径的独立准备目录。')
    no_links(root)
    if root == Path(root.anchor) or root.resolve() == Path.home().resolve():
        raise ValueError('不要选择磁盘根目录或个人主目录本身。')
    asset = ASSETS[platform]
    source = Path(clean_path(local_file)) if local_file else root / 'downloads' / asset['name']
    if local_file:
        verify_file(source, asset['sha256'], asset['size'])
    else:
        download_file(asset['url'], source, log, expected_sha256=asset['sha256'],
                      expected_size=asset['size'], network=network or DownloadNetwork())
    verify_file(source, asset['sha256'], asset['size'])
    root.mkdir(parents=True, exist_ok=True)
    if platform == 'linux':
        # Copy rather than run; preserve verified source bytes including LF endings.
        folder = Path(tempfile.mkdtemp(prefix='napcat-linux-', dir=root))
        result = folder / asset['name']
        with result.open('xb') as out: out.write(source.read_bytes())
    else:
        folder = Path(tempfile.mkdtemp(prefix='napcat-windows-', dir=root))
        safe_extract(source, folder)
        verify_windows_tree(folder)
        result = folder / 'NapCatInstaller.exe'
    log('安装入口已校验并准备好；尚未安装 NapCat、登录 QQ 或连接 OneBot。')
    return result


def linux_install_command(path):
    path = Path(path)
    verify_file(path, ASSETS['linux']['sha256'], ASSETS['linux']['size'])
    return 'bash ' + shlex.quote(str(path.resolve())) + ' --docker n --cli y --github-proxy 0'


def launch_installer(path, *, confirmed=False):
    if not confirmed: raise ValueError('未确认运行官方安装器。')
    if platform_name() != 'windows': raise ValueError('Linux 请在自己的交互式终端运行已校验脚本。')
    path = Path(path)
    if path.name != 'NapCatInstaller.exe': raise ValueError('请选择已校验的 NapCatInstaller.exe。')
    verify_windows_tree(path.parent)
    return subprocess.Popen([str(path.resolve())], cwd=str(path.parent.resolve()))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


def local_url(value):
    value = value.strip().rstrip('/')
    try:
        parts = urlsplit(value)
        valid = (parts.scheme in {'http', 'https'} and parts.hostname in {'127.0.0.1', 'localhost', '::1'}
                 and not parts.username and not parts.password and not parts.query and not parts.fragment
                 and not parts.path and parts.port != 0 and not any(c.isspace() for c in value))
        if not valid: raise ValueError()
    except ValueError: raise ValueError('检查只允许本机地址，例如 http://127.0.0.1:6099；远程服务器请在服务器上操作。') from None
    return value


def api_call(base, route, body, credential=''):
    # No environment proxy, redirects, cookies, automatic login or retries.
    if route not in {'/auth/login', '/QQLogin/CheckLoginStatus'}: raise ValueError('非只读状态检查接口。')
    headers = {'Content-Type': 'application/json'}
    if credential: headers['Authorization'] = 'Bearer ' + credential
    request = urllib.request.Request(local_url(base) + '/api' + route,
                                     json.dumps(body).encode('utf-8'), headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=10) as response:
            data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024: raise ValueError('响应超过限制。')
        result = json.loads(data)
    except urllib.error.HTTPError as exc:
        raise ValueError(f'NapCat HTTP {exc.code}：核对 WebUI 地址、Token 和版本；不会跟随重定向或输出密钥。') from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ValueError('NapCat 无法连接或响应无效；先启动 NapCat，再在浏览器检查 WebUI。') from None
    if not isinstance(result, dict) or result.get('code') != 0:
        raise ValueError('NapCat 拒绝检查；核对 WebUI Token / 动态码。不是 OneBot Token，也不是 AstrBot API Key。')
    return result.get('data')


def check_login(base, token, totp='', *, consent=False):
    local_url(base)
    if not consent: raise ValueError('请确认将 WebUI Token 的认证摘要发送给选定的本机 NapCat。')
    if not token.strip(): raise ValueError('请填写 NapCat WebUI Token；不会从 QQ 缓存自动读取。')
    auth = api_call(base, '/auth/login', {
        'hash': hashlib.sha256((token.strip() + '.napcat').encode()).hexdigest(), 'totpCode': totp.strip()})
    if isinstance(auth, dict) and auth.get('require2FA'):
        return '需要双重验证动态码；请填写后重新检测，不会关闭验证。'
    if not isinstance(auth, dict) or not isinstance(auth.get('Credential'), str) or not auth['Credential']:
        raise ValueError('NapCat 认证响应不兼容；请在官方 WebUI 检查。')
    state = api_call(base, '/QQLogin/CheckLoginStatus', {}, auth['Credential'])
    if not isinstance(state, dict): raise ValueError('NapCat 登录状态格式不兼容。')
    if state.get('isOffline') is True: return 'QQ 已掉线：请在 NapCat WebUI 重新登录。OneBot 尚需单独验证。'
    if state.get('isLogin') is True: return 'QQ 已登录；这不代表 OneBot 已连接，请继续第三页。'
    if state.get('isLogin') is False: return 'QQ 未登录：到 NapCat WebUI 扫码，手机 QQ 自行确认。'
    return '未返回可识别的 QQ 状态；请到 NapCat WebUI 查看。'


def onebot_values(port='6199'):
    if not str(port).isascii() or not str(port).isdecimal() or not 1 <= int(port) <= 65535:
        raise ValueError('OneBot 端口须为 1～65535 的整数。')
    return f'ws://127.0.0.1:{int(port)}/ws'


def probe_listener(port):
    onebot_values(port)
    try:
        with socket.create_connection(('127.0.0.1', int(port)), timeout=3): pass
    except OSError: return '本机 TCP 端口未连通：先启用并保存 AstrBot OneBot 适配器。不要先重装 NapCat。'
    return '本机 TCP 端口可达（仅端口检查，不能证明 OneBot 握手或鉴权成功）。请看 AstrBot 连接日志并发 /sid。'


def launch_gui(smoke=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk(); root.title('NapCat · 部署、QQ 登录与 OneBot 引导')
    root.geometry(f'1020x{min(800, max(600, root.winfo_screenheight() - 100))}')
    root.minsize(900, 600)
    if smoke: root.withdraw()
    ttk.Label(root, text='三道验收：安装入口 ≠ QQ 登录 ≠ OneBot 连通', font=('Microsoft YaHei UI', 16, 'bold')).pack(padx=18, pady=12, anchor='w')
    ttk.Label(root, text='已有 NapCat 直接跳到②。不改已有配置、QQ 登录缓存或系统防火墙；外部安装器另行确认。').pack(anchor='w', padx=18)
    notebook = ttk.Notebook(root); notebook.pack(fill='both', expand=True, padx=16, pady=10)
    pages = []
    for name in ('① 准备 / 安装', '② 启动 / QQ 登录', '③ OneBot 对接', '④ 失败后恢复'):
        tab = ttk.Frame(notebook); canvas = tk.Canvas(tab, highlightthickness=0)
        scroll = ttk.Scrollbar(tab, orient='vertical', command=canvas.yview)
        scroll.pack(side='right', fill='y'); canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        page = ttk.Frame(canvas, padding=14); page.columnconfigure(1, weight=1)
        window = canvas.create_window((0, 0), window=page, anchor='nw')
        page.bind('<Configure>', lambda e, c=canvas: c.configure(scrollregion=c.bbox('all')))
        canvas.bind('<Configure>', lambda e, c=canvas, w=window: c.itemconfigure(w, width=e.width))
        notebook.add(tab, text=name); pages.append(page)
    status = tk.StringVar(value='未执行安装或检查。已有环境不要重复安装。')
    ttk.Label(root, textvariable=status, wraplength=960).pack(fill='x', padx=18, pady=10)
    messages = queue.Queue(); state = {'busy': False, 'prepared': None}

    def protect(fn):
        def invoke():
            try: fn()
            except Exception as exc: messagebox.showerror('请先处理这一项', str(exc), parent=root)
        return invoke

    def work(fn, done):
        if state['busy']: raise ValueError('当前操作尚未结束，请勿重复执行。')
        state['busy'] = True; status.set('处理中，请保持窗口打开。')
        def worker():
            try: messages.put(('done', (done, fn())))
            except Exception as exc: messages.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll():
        while not messages.empty():
            kind, value = messages.get()
            if kind == 'log': status.set(value)
            elif kind == 'error': state['busy'] = False; status.set(value)
            else:
                state['busy'] = False; callback, result = value; protect(lambda: callback(result))()
        root.after(100, poll)

    def text(page, row, value):
        ttk.Label(page, text=value, wraplength=870, justify='left').grid(row=row, column=0, columnspan=3, sticky='w', pady=8)

    def entry(page, row, label, value, secret=False):
        ttk.Label(page, text=label).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=5)
        ttk.Entry(page, textvariable=value, show='●' if secret else '').grid(row=row, column=1, sticky='ew', pady=5)

    page = pages[0]; host = platform_name()
    text(page, 0, '新安装才需要本页。默认不下载。Windows 准备官方 OneKey 安装入口；Linux 准备官方脚本。\n它们执行后还会下载 QQ / NapCat / 依赖，网络方式不自动传给上游安装器。阅读官方说明并自行确认。')
    dest = tk.StringVar(value=str(Path.home() / 'AAA-NapCat-setup'))
    entry(page, 1, '独立准备目录', dest)
    ttk.Button(page, text='选择…', command=lambda: dest.set(filedialog.askdirectory(parent=root) or dest.get())).grid(row=1, column=2)
    local = tk.StringVar(); entry(page, 2, '已有官方入口文件（可选）', local)
    ttk.Button(page, text='选择…', command=lambda: local.set(filedialog.askopenfilename(parent=root) or local.get())).grid(row=2, column=2)
    mode = tk.StringVar(value='official')
    ttk.Label(page, text='下载方式').grid(row=3, column=0, sticky='w')
    ttk.Combobox(page, textvariable=mode, values=['official', 'mirror', 'proxy', 'local'], state='readonly').grid(row=3, column=1, sticky='ew')
    mirror = tk.StringVar(); proxy = tk.StringVar()
    entry(page, 4, '自选 GitHub HTTPS 镜像前缀', mirror); entry(page, 5, '自选下载代理', proxy)
    fallback = tk.BooleanVar(); revoke = tk.BooleanVar(); consent = tk.BooleanVar()
    ttk.Checkbutton(page, text='镜像失败后允许回退官方', variable=fallback).grid(row=6, column=0, columnspan=3, sticky='w')
    if host == 'windows': ttk.Checkbutton(page, text='仅遇 CRYPT_E_REVOCATION_OFFLINE：证书吊销离线兼容（不关闭 TLS 校验）', variable=revoke).grid(row=7, column=0, columnspan=3, sticky='w')
    ttk.Checkbutton(page, text='同意准备官方安装入口（未选本地文件时会联网）；不会自动运行安装器', variable=consent).grid(row=8, column=0, columnspan=3, sticky='w', pady=8)
    prepared_label = tk.StringVar(value='未准备。安装器校验不等于完整 NapCat 依赖已校验或安装成功。')
    ttk.Label(page, textvariable=prepared_label, wraplength=870).grid(row=10, column=0, columnspan=3, sticky='w', pady=10)
    command = tk.StringVar(); entry(page, 11, 'Linux 安装命令 / Windows 入口', command)
    def prepared(path):
        state['prepared'] = path
        command.set(str(path) if host == 'windows' else linux_install_command(path))
        prepared_label.set('入口已准备：' + str(path)); status.set('下一步需要你确认并运行官方安装器。QQ 扫码由你完成。')
    def start_prepare():
        network = DownloadNetwork(mode.get(), github_mirror=mirror.get().strip(), proxy=proxy.get().strip(),
                                  fallback_official=fallback.get(), revoke_best_effort=revoke.get())
        network.validate()
        if not consent.get(): raise ValueError('先阅读并勾选准备授权。')
        args = (host, dest.get()); selected = local.get()
        work(lambda: prepare(*args, consent=True, local_file=selected, network=network,
                             log=lambda s: messages.put(('log', s))), prepared)
    ttk.Button(page, text='准备 / 断网后重试（含校验）', command=protect(start_prepare)).grid(row=9, column=0, columnspan=2, sticky='w')
    def run_installer():
        if state['busy']: raise ValueError('请等待当前操作完成。')
        if not state['prepared']: raise ValueError('先准备安装入口。')
        if host == 'linux':
            command.set(linux_install_command(state['prepared']))
            messagebox.showinfo('Linux 安装', '复制命令到此 Linux 机器的终端运行。脚本可能询问 sudo 并安装系统依赖。\n优先普通用户；已有安装请退出，不使用 --force。桌面向导不会代输密码或静默提权。', parent=root)
        elif messagebox.askyesno('运行官方安装器', '安装器会继续联网下载 QQ / NapCat / 依赖，可能请求系统权限。\n若已有 NapCat 请取消，勿覆盖旧目录。继续打开官方安装器？', parent=root):
            launch_installer(state['prepared'], confirmed=True)
            status.set('仅提交了安装器启动。完成后打开实际生成的 NapCat.XXXX.Shell/napcat.bat，再到②。')
    ttk.Button(page, text='下一步：运行入口 / Linux 操作说明', command=protect(run_installer)).grid(row=12, column=0, columnspan=3, sticky='w', pady=8)
    ttk.Button(page, text='查看 NapCat 官方安装文档', command=lambda: webbrowser.open(OFFICIAL_GUIDE)).grid(row=13, column=0, columnspan=3, sticky='w')

    page = pages[1]
    text(page, 0, 'Windows：在安装器生成的 NapCat.XXXX.Shell 目录双击 napcat.bat；不要运行准备目录 bootmain 的模板。\nLinux：安装完成后按官方提示运行 napcat。容器或已有服务使用原启动方式。\n终端出现 WebUI 地址后打开；从自己的启动输出取得 WebUI Token，登录后手机 QQ 扫码确认。不要把 QR / Token 发群里。')
    base = tk.StringVar(value='http://127.0.0.1:6099'); token = tk.StringVar(); totp = tk.StringVar()
    entry(page, 1, '本机 NapCat WebUI', base); entry(page, 2, 'WebUI Token（仅本窗口内存）', token, True); entry(page, 3, '动态码（启用 2FA 才填）', totp, True)
    ttk.Button(page, text='打开本机 WebUI（不把 Token 放进网址）', command=protect(lambda: webbrowser.open(local_url(base.get()) + '/webui'))).grid(row=4, column=0, columnspan=3, sticky='w', pady=8)
    def check():
        url = local_url(base.get()); secret = token.get(); code = totp.get()
        if messagebox.askyesno('本机认证检查', '仅向 ' + url + ' 发送认证摘要并读取 QQ 登录状态。\n不登录/切换 QQ、不读取账户列表、不保存 Token、不自动配置 OneBot。继续？', parent=root):
            work(lambda: check_login(url, secret, code, consent=True), status.set)
    ttk.Button(page, text='检查 QQ 登录状态', command=protect(check)).grid(row=5, column=0, columnspan=2, sticky='w')
    ttk.Button(page, text='清空本页 Token / 动态码', command=lambda: (token.set(''), totp.set(''))).grid(row=6, column=0, columnspan=2, sticky='w', pady=8)
    text(page, 7, '6099 页面能打开 ≠ QQ 已登录。QQ 已登录 ≠ AstrBot 已连通。\n远程服务器：在服务器上运行检查，或使用你已有的安全访问方式打开 WebUI；本工具不向远程地址发送 Token。')

    page = pages[2]
    text(page, 0, '先以“NapCat 与 AstrBot 在同一台机器、都非容器”为例。无需手改 JSON：\n1. AstrBot → 消息平台 / 机器人 → 新增 OneBot v11（aiocqhttp）。启用，记下你设置的平台 Bot ID。\n2. AstrBot 作为反向 WebSocket 服务端：监听 127.0.0.1，端口默认 6199。\n3. NapCat → 网络配置 → 新建 WebSocket 客户端，填写下面 URL，消息格式选 Array（数组）。\n4. 两端填同一个 OneBot access_token，然后分别保存。不要把此 Token 填入 Hub 或 AstrBot OpenAPI。')
    port = tk.StringVar(value='6199'); ws = tk.StringVar(value=onebot_values()); access = tk.StringVar()
    entry(page, 1, 'AstrBot OneBot 监听端口', port); entry(page, 2, 'NapCat WebSocket 客户端 URL', ws); entry(page, 3, 'OneBot 共享 Token（仅内存）', access, True)
    ttk.Button(page, text='按端口生成本机 URL', command=protect(lambda: ws.set(onebot_values(port.get())))).grid(row=4, column=0, columnspan=2, sticky='w')
    def new_token():
        if messagebox.askyesno('仅生成供你填写的新 Token', '不会保存或替换任何配置。已有连接正常不要更换；新值须在 NapCat 和 AstrBot 两端一致填写。继续？', parent=root):
            access.set(secrets.token_urlsafe(32))
    def copy_token():
        if not access.get(): raise ValueError('先生成或填写 OneBot Token。')
        if messagebox.askyesno('复制密钥', '系统剪贴板可能被剪贴板历史或同步记录。确认复制？使用后请自行清除。', parent=root):
            root.clipboard_clear(); root.clipboard_append(access.get())
    ttk.Button(page, text='生成 OneBot Token', command=protect(new_token)).grid(row=5, column=0, sticky='w', pady=6)
    ttk.Button(page, text='复制 Token（确认后）', command=protect(copy_token)).grid(row=5, column=1, sticky='w')
    def probe():
        value = port.get(); onebot_values(value); work(lambda: probe_listener(value), status.set)
    ttk.Button(page, text='只检查本机端口', command=protect(probe)).grid(row=6, column=0, sticky='w', pady=8)
    text(page, 7, '真正验收：AstrBot 日志出现 OneBot / aiocqhttp adapter connected；再私聊机器人发送 /sid，应收到会话标识。\n将实际 Bot ID 与私聊 / 群目标填入 AAA 首次配置向导。先自己的私聊，确认收图后再开放群投递。\n容器 / 两台机器：127.0.0.1 指向各自容器 / 主机，不能照抄。使用容器网络服务名或私网地址，并核对监听接口。不要直接向公网开放无 TLS 的 WebUI / OneBot。')
    ttk.Button(page, text='查看 AstrBot 官方 OneBot 指引', command=lambda: webbrowser.open(ASTRBOT_GUIDE)).grid(row=8, column=0, columnspan=3, sticky='w')

    text(pages[3], 0, '失败后只回到对应步骤：\n\n下载超时 → ①选可信镜像 / 代理，或导入同版本完整入口文件；不会跳过 SHA256。\n安装器里面下载失败 → 查看官方安装器日志；这里的下载选项不会改变安装器内部网络。\n入口已准备但没有6099 → 尚未启动实际 NapCat；先运行生成目录里的 napcat.bat / Linux napcat。\nWebUI认证失败 → 核对 WebUI Token 与 2FA，不要拿 OneBot Token 或 AstrBot Key 代替。\nQQ掉线 → ②自行扫码，不删除 QQ 配置或登录缓存。\n端口可达但机器人无回复 → ③检查“WebSocket客户端”、/ws、两端Token、平台启用状态及日志。\n/sid可回复但App报401 → 回AAA授权页检查完整 AstrBot OpenAPI Key / Hub令牌，不要重装NapCat。\n\n本窗口不保存 WebUI / OneBot Token。关闭后未填入上游的 Token 会丢失；这不影响上游已经保存的配置。\n安装器、模型、服务数据和日志均不删除。需要反馈时只提供错误码与遮盖后的日志，不发完整配置。')
    def close():
        if state['busy']:
            messagebox.showinfo('请等待', '操作仍在进行，关闭窗口会中断下载/检测。请等待本轮完成。', parent=root); return
        token.set(''); totp.set(''); access.set(''); root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    root.after(100, poll)
    if smoke:
        for tab in notebook.tabs(): notebook.select(tab); root.update_idletasks()
        assert state['prepared'] is None and not consent.get() and not token.get()
        root.destroy(); print('PASS: NapCat four-page UI; no download, installer, QQ or credential action'); return 0
    root.mainloop(); return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--prepare', type=Path, help='Headless: prepare verified installer files only')
    parser.add_argument('--allow-prepare', action='store_true', help='Explicit opt-in; no automatic execution')
    parser.add_argument('--platform', choices=['windows', 'linux'])
    parser.add_argument('--local-file', default='')
    parser.add_argument('--download-mode', choices=['official', 'mirror', 'proxy', 'local'], default='official')
    parser.add_argument('--github-mirror', default=''); parser.add_argument('--proxy', default='')
    parser.add_argument('--fallback-official', action='store_true')
    args = parser.parse_args(argv)
    if args.prepare:
        selected = args.platform or platform_name()
        network = DownloadNetwork(args.download_mode, github_mirror=args.github_mirror,
                                  proxy=args.proxy, fallback_official=args.fallback_official)
        result = prepare(selected, args.prepare, consent=args.allow_prepare, local_file=args.local_file, network=network)
        print(linux_install_command(result) if selected == 'linux' else str(result))
        return 0
    return launch_gui(args.smoke_test)


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (ValueError, OSError, RuntimeError) as exc:
        print('NapCat 准备中止：' + str(exc), file=sys.stderr); raise SystemExit(1)
