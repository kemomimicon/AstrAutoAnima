"""Offline searchable extension instructions and FAQ; actions are explicit and allowlisted."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
from urllib.parse import urlsplit

from first_run_checks import request_json
from first_run_config import validate_url

ACTIONS = {'guide', 'deploy', 'first_run', 'napcat', 'pool', 'users', 'importer'}
TOOL_ACTIONS = {'first_run': ('first_run_wizard.py', ''), 'napcat': ('napcat_setup.py', '--napcat-guide'),
                'pool': ('prompt_pool_manager.py', '--pool-manager'), 'users': ('hub_lite_user_manager.py', '--user-manager'),
                'importer': ('online_prompt_importer.py', '--online-importer')}


def base_path():
    return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]


def catalog_path(root=None):
    root = Path(root) if root is not None else base_path()
    return root / ('resources' if getattr(sys, 'frozen', False) and root == base_path() else 'tools') / 'extension_catalog.json'


def load_catalog(path=None):
    data = json.loads((Path(path) if path is not None else catalog_path()).read_text('utf-8-sig'))
    if data.get('schema_version') != 1 or not isinstance(data.get('items'), list): raise ValueError('扩展目录格式不兼容。')
    seen = set()
    for item in data['items']:
        if not isinstance(item, dict) or not re.fullmatch(r'[a-z][a-z0-9_]{0,40}', item.get('id', '')) or item['id'] in seen:
            raise ValueError('扩展ID错误或重复。')
        seen.add(item['id'])
        if item.get('action') not in ACTIONS: raise ValueError('扩展动作不在允许列表。')
        for key in ('title', 'category', 'availability', 'summary'):
            if not isinstance(item.get(key), str) or not item[key]: raise ValueError('扩展说明字段缺失。')
        if not isinstance(item.get('components'), list) or any(not isinstance(v, str) or not re.fullmatch('[a-z0-9_]+', v) for v in item['components']):
            raise ValueError('组件清单格式错误。')
        if item['components'] and item['action'] != 'deploy': raise ValueError('非部署项目不能指定下载组件。')
        if not isinstance(item.get('apis'), list): raise ValueError('API提示清单缺失。')
        for route in item['apis']:
            if (not isinstance(route, list) or len(route) != 2 or route[0] not in {'get', 'post', 'put', 'delete'} or
                    not isinstance(route[1], str) or not re.fullmatch(r'/api/v1/[a-z0-9/_{}-]+', route[1])):
                raise ValueError('API提示清单格式错误。')
    return data['items']


def read_sections(path):
    content = Path(path).read_text('utf-8-sig')
    sections = []
    for match in re.finditer(r'^## \[([a-z0-9_]+)\] (.+)$', content, re.M):
        sections.append({'id': match[1], 'title': match[2], 'start': match.start()})
    for index, section in enumerate(sections):
        end = sections[index + 1]['start'] if index + 1 < len(sections) else len(content)
        section['body'] = content[section['start']:end].strip()
    if len({s['id'] for s in sections}) != len(sections): raise ValueError('说明页存在重复主题。')
    return sections


def filter_records(records, query, category='全部'):
    words = query.casefold().split()
    return [record for record in records if (category == '全部' or record.get('category') == category) and
            all(word in ' '.join(str(record.get(k, '')) for k in ('id', 'title', 'summary', 'body', 'availability', 'category')).casefold() for word in words)]


def component_selection(identifier, root=None):
    root = Path(root) if root is not None else base_path()
    items = load_catalog(root / 'tools/extension_catalog.json')
    item = next((v for v in items if v['id'] == identifier), None)
    if item is None or item['action'] != 'deploy': raise ValueError('此项不是自动下载组件，只提供操作说明。')
    known = json.loads((root / 'tools/optional_components.json').read_text('utf-8-sig'))['components']
    index = {v['id']: v for v in known}
    if any(v not in index for v in item['components']): raise ValueError('本包缺少所需下载清单；不能从名称猜测下载。')
    return [index[v] for v in item['components']]


def preview_plan(item, root=None):
    root = Path(root) if root is not None else base_path()
    if item['action'] != 'deploy': return '此项不自动安装；请按说明在对应程序配置。'
    if not (root / 'tools/deploy_project.py').is_file(): return '独立首图工具不包含完整部署器。请打开对应系统懒人包，不会静默下载部署器。'
    selected = component_selection(item['id'], root)
    lines = ['仅预览，不创建配置、不下载、不安装。', '打开仅补装扩展工具，只处理所列节点/模型，不运行全量部署；仍需确认路径、依赖与许可：']
    total = 0
    for entry in selected:
        lines.append('• ' + entry['name'])
        if entry['kind'] == 'git': lines.append('  ' + entry['url'] + '；提交：' + entry.get('commit', '未锁定，升级前需独立验证'))
        for file in entry.get('files', []):
            total += file.get('size', 0)
            lines.append('  ' + file['target'] + '；SHA256：' + file.get('sha256', '缺失'))
    if total: lines.append(f'已列模型 {total / 10**9:.2f} GB（十进制）；另需依赖、缓存及运行空间，不能当成总容量。')
    lines.append('选择已有ComfyUI及实际Python；正常停止目标ComfyUI后确认。此路径不复制Hub、插件、工作流，也不改配置、词库或启动服务。')
    return '\n'.join(lines)


def action_command(item, root=None):
    root = Path(root) if root is not None else base_path()
    action = item['action']
    if action == 'guide': raise ValueError('此扩展只提供指引，不执行安装。')
    if action == 'deploy':
        script = root / 'tools/deploy_project.py'
        if getattr(sys, 'frozen', False) or not script.is_file(): raise ValueError('请在完整懒人包的安装中心打开部署器；独立EXE不代替完整安装包。')
        component_selection(item['id'], root)
        return [sys.executable, str(script), '--extension', item['id']]
    script, flag = TOOL_ACTIONS[action]
    if getattr(sys, 'frozen', False): return [sys.executable] + ([flag] if flag else [])
    target = root / 'tools' / script
    if not target.is_file(): raise ValueError('本包没有该工具，请使用对应新版完整包。')
    return [sys.executable, str(target)]


def inspect_hub(base, *, consent=False):
    if not consent: raise ValueError('未确认只读检查，不会联网。')
    base = validate_url(base)
    parsed = urlsplit(base)
    if parsed.scheme != 'https' and parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
        raise ValueError('远程检查请用 HTTPS；HTTP 仅允许本机。')
    health = request_json(base, '/api/v1/health', limit=65536)
    if health.get('service') != 'astr-auto-anima-hub': raise ValueError('此地址未返回 AAA Hub 身份；不要混用6185/8188。')
    version = health.get('version', '未知')
    if not isinstance(version, str) or not re.fullmatch(r'[0-9A-Za-z.+_-]{1,60}', version): version = '未知'
    mode = health.get('execution_mode', '未提供')
    if mode not in {'local', 'remote'}: mode = '未提供'
    result = {'version': version, 'mode': mode, 'apis': set(), 'schema_known': False}
    try:
        schema = request_json(base, '/openapi.json', limit=4 * 1024 * 1024)
        paths = schema.get('paths')
        if not isinstance(paths, dict): raise ValueError()
        wanted = {(method, path) for item in load_catalog() for method, path in item['apis']}
        result['apis'] = {(method, path) for method, path in wanted if isinstance(paths.get(path), dict) and method in paths[path]}
        result['schema_known'] = True
    except Exception:
        # A reverse proxy can disable OpenAPI. Absence is not proof of an unsupported feature.
        pass
    return result


def capability_text(item, snapshot=None):
    if snapshot is None: return '目标服务尚未检查；“本包有说明/工具”不等于你的服务已启用。'
    if not item['apis']: return '此项不能仅靠API目录确认；请按详细页人工验收客户端、模式、模型和权限。'
    if not snapshot.get('schema_known'): return 'Hub有响应，但API定义未取得；功能状态未知，不据此要求重装。'
    missing = [(m, p) for m, p in item['apis'] if (m, p) not in snapshot['apis']]
    if missing: return '目标API定义缺少此项所需接口；请核对服务版本或代理路由。本窗口不启用该功能。'
    return '目标API定义包含所需接口；尚未验证管理员鉴权、客户端匹配或实际功能。'


def launch_gui(smoke=False):
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    root = tk.Tk(); root.title('AAA · 扩展装配与问题解答')
    root.geometry(f'{min(1120, max(960, root.winfo_screenwidth() - 80))}x{min(820, max(550, root.winfo_screenheight() - 100))}'); root.minsize(960, 550)
    if smoke: root.withdraw()
    items = load_catalog()
    details = {s['id']: s['body'] for s in read_sections(base_path() / 'docs/EXTENSIONS_GUIDE.md')}
    questions = read_sections(base_path() / 'docs/SETUP_QA.md')
    if any(item['id'] not in details for item in items): raise ValueError('扩展目录与详细说明不完整，请完整解压。')
    ttk.Label(root, text='按需要装配，不要为了第一张图安装所有扩展', font=('Microsoft YaHei UI', 17, 'bold')).pack(anchor='w', padx=18, pady=12)
    ttk.Label(root, text='所有操作默认关闭 · 说明与FAQ离线可读 · 不收集令牌 · 新版功能必须匹配服务与客户端').pack(anchor='w', padx=18)
    controls = ttk.Frame(root); controls.pack(fill='x', padx=18, pady=8)
    query = tk.StringVar(); category = tk.StringVar(value='全部'); mode = tk.StringVar(value='扩展说明')
    ttk.Combobox(controls, textvariable=mode, values=['扩展说明', '常见问题 Q&A'], state='readonly', width=18).pack(side='left')
    ttk.Combobox(controls, textvariable=category, values=['全部'] + list(dict.fromkeys(i['category'] for i in items)), state='readonly', width=18).pack(side='left', padx=6)
    ttk.Label(controls, text='搜索：').pack(side='left'); ttk.Entry(controls, textvariable=query).pack(side='left', fill='x', expand=True)
    pane = ttk.Panedwindow(root, orient='horizontal'); pane.pack(fill='both', expand=True, padx=18, pady=6)
    left = ttk.Frame(pane); right = ttk.Frame(pane); pane.add(left, weight=1); pane.add(right, weight=3)
    listing = tk.Listbox(left, width=36, exportselection=False); listing.pack(side='left', fill='both', expand=True)
    scroll = ttk.Scrollbar(left, command=listing.yview); scroll.pack(side='right', fill='y'); listing.configure(yscrollcommand=scroll.set)
    view = tk.Text(right, wrap='word', padx=14, pady=10, state='disabled'); view.pack(side='left', fill='both', expand=True)
    bar = ttk.Scrollbar(right, command=view.yview); bar.pack(side='right', fill='y'); view.configure(yscrollcommand=bar.set)
    state = {'visible': [], 'snapshot': None, 'checked_url': '', 'busy': False}; messages = queue.Queue()
    status = tk.StringVar(value='浏览说明不会下载、安装或发送请求。')
    action = ttk.Button(root); action.pack(anchor='e', padx=18, pady=5)
    def show(text):
        view.configure(state='normal'); view.delete('1.0', 'end'); view.insert('1.0', text); view.configure(state='disabled')
    def current():
        selected = listing.curselection()
        return state['visible'][selected[0]] if selected else None
    def selected(_=None):
        item = current()
        action.configure(state='disabled', text='先选择一项')
        if item is None: show('没有匹配结果。可搜索：401、下载、QQ、CL、Studio、群、保存等。'); return
        if mode.get() != '扩展说明': show(item['body']); return
        show(item['title'] + '\n状态：' + item['availability'] + '\n' + capability_text(item, state['snapshot']) + '\n\n' + details[item['id']] + '\n\n' + preview_plan(item))
        action.configure(text='仅阅读说明' if item['action'] == 'guide' else '打开对应工具（需确认）', state='disabled' if item['action'] == 'guide' else 'normal')
    def refresh(*_):
        records = [dict(i, body=details[i['id']]) for i in items] if mode.get() == '扩展说明' else questions
        state['visible'] = filter_records(records, query.get(), category.get() if mode.get() == '扩展说明' else '全部')
        listing.delete(0, 'end')
        for item in state['visible']: listing.insert('end', item['title'])
        if state['visible']: listing.selection_set(0)
        selected()
    for var in (query, category, mode): var.trace_add('write', refresh)
    listing.bind('<<ListboxSelect>>', selected)
    def open_action():
        try:
            item = current()
            if not item or mode.get() != '扩展说明': return
            command = action_command(item)
            if messagebox.askyesno('打开工具，不自动执行', item['title'] + '\n将打开独立窗口。下载、保存、服务器同步仍须在该窗口确认。\n尚未完成的部署不要重复开第二个安装器。继续？', parent=root):
                subprocess.Popen(command, **({'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}))
        except Exception as exc: messagebox.showerror('需要处理', str(exc), parent=root)
    action.configure(command=open_action)
    probes = ttk.LabelFrame(root, text='可选：只读识别目标 Hub（不填令牌）', padding=8); probes.pack(fill='x', padx=18, pady=5)
    url = tk.StringVar(value='http://127.0.0.1:6278'); ttk.Entry(probes, textvariable=url).pack(side='left', fill='x', expand=True)
    def invalidate(*_):
        state['snapshot'] = None; state['checked_url'] = ''; status.set('地址已改变，旧检查结果已清除。'); selected()
    url.trace_add('write', invalidate)
    def probe():
        if state['busy']: return
        address = url.get()
        if not messagebox.askyesno('只读联网检查', '将请求当前地址的 health 与 OpenAPI，不读取配置、不带令牌，不提交任务。继续？', parent=root): return
        state['busy'] = True
        def worker():
            try: messages.put((address, inspect_hub(address, consent=True), ''))
            except Exception as exc: messages.put((address, None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()
    ttk.Button(probes, text='检查（确认后联网）', command=probe).pack(side='left', padx=6)
    def export():
        # Export curated instructions only: never the address, health response, config, logs or tokens.
        item = current()
        if not item: return
        body = details[item['id']] if mode.get() == '扩展说明' else item['body']
        path = filedialog.asksaveasfilename(parent=root, initialfile=item['id'] + '_说明.txt', defaultextension='.txt')
        if not path: return
        try:
            with open(path, 'x', encoding='utf-8') as stream: stream.write(body + '\n')
            status.set('只导出了该页的公共说明；没有导出地址、配置、日志或密钥。')
        except FileExistsError: messagebox.showerror('保留原文件', '所选文件已存在，请换一个名字。', parent=root)
        except OSError: messagebox.showerror('保存失败', '请检查文件夹权限，原配置不受影响。', parent=root)
    ttk.Button(root, text='导出当前说明 / Q&A（不含个人配置）', command=export).pack(anchor='w', padx=18, pady=5)
    ttk.Label(root, textvariable=status, wraplength=1060).pack(fill='x', padx=18, pady=8)
    def poll():
        while not messages.empty():
            address, result, error = messages.get(); state['busy'] = False
            if address != url.get(): continue
            state['snapshot'] = result; state['checked_url'] = address
            status.set(error or ('识别Hub：' + result['version'] + '；执行模式：' + result['mode'] + '。接口存在不代表验收通过。'))
            selected()
        root.after(100, poll)
    refresh(); root.after(100, poll)
    if smoke:
        for item in items: assert details[item['id']]
        if getattr(sys, 'frozen', False):
            for item in items:
                if item['action'] != 'deploy': continue
                try: action_command(item)
                except ValueError as exc: assert '完整懒人包' in str(exc)
                else: raise AssertionError('Standalone EXE must not run the full installer')
        query.set('401'); mode.set('常见问题 Q&A'); root.update_idletasks(); assert state['visible']
        query.set(''); mode.set('扩展说明'); root.update_idletasks(); assert len(state['visible']) == len(items)
        root.destroy(); print(f'PASS: extension guide {len(items)} entries / {len(questions)} FAQs; offline smoke'); return 0
    root.mainloop(); return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--smoke-test', action='store_true')
    raise SystemExit(launch_gui(parser.parse_args().smoke_test))
