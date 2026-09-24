"""Chinese beginner-friendly post-install wizard; standard library only."""
from __future__ import annotations

import argparse
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import base64
import json
import webbrowser

from first_run_config import SetupError, SetupSession, probe_health, target_record, validate_targets, validate_url, read_object
import first_run_checks as checks


def launch_gui(smoke: bool = False) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title('AstrAutoAnima · 首张图向导 1.1')
    root.geometry('1080x800')
    root.minsize(920, 700)
    if smoke:
        root.withdraw()
    state = {'session': None, 'saved': False, 'editing': None, 'busy': False,
             'job': None, 'image': None, 'submission': False}
    messages = queue.Queue()
    status = tk.StringVar(value='欢迎。先选择实际安装目录中的配置文件，读取不会修改任何内容。')
    ttk.Label(root, text='把服务配置好，再开始第一张图', font=('Microsoft YaHei UI', 18, 'bold')).pack(anchor='w', padx=22, pady=(16, 4))
    ttk.Label(root, text='无需手写 JSON · 保存前确认 · 自动备份 · 不自动重启或发群消息').pack(anchor='w', padx=22, pady=(0, 10))
    notebook = ttk.Notebook(root)
    notebook.pack(fill='both', expand=True, padx=20, pady=6)
    pages = []
    for title in ('① 安装', '② 授权', '③ 投递', '④ 用户', '⑤ 词库', '⑥ 角色词典', '⑦ 保存', '⑧ 首张图', '⑨ 工具与帮助'):
        frame = ttk.Frame(notebook, padding=18)
        frame.columnconfigure(1, weight=1)
        notebook.add(frame, text=title)
        pages.append(frame)

    def note(frame, text, row):
        ttk.Label(frame, text=text, wraplength=890, justify='left').grid(row=row, column=0, columnspan=3, sticky='w', pady=8)

    def field(frame, label, variable, row, secret=False):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=6)
        entry = ttk.Entry(frame, textvariable=variable, show='●' if secret else '')
        entry.grid(row=row, column=1, sticky='ew', pady=6)
        if secret:
            visible = tk.BooleanVar(value=False)
            ttk.Checkbutton(frame, text='显示', variable=visible,
                command=lambda: entry.configure(show='' if visible.get() else '●')).grid(row=row, column=2, padx=6)
        return entry

    def protect(action):
        def run():
            try:
                if state['busy']:
                    raise SetupError('当前检查或下载尚未结束，请稍候；不会自动重复提交生图。')
                return action()
            except Exception as exc:
                # Only explicit validation messages; unexpected errors can contain user data.
                text = str(exc) if isinstance(exc, SetupError) else '操作未完成，请检查所选文件的格式、权限和路径。原配置不会自动删除。'
                messagebox.showerror('请先处理这一项', text, parent=root)
        return run

    def work(action, done):
        state['busy'] = True
        def run():
            try:
                result = action()
                messages.put(('done', lambda: done(result)))
            except Exception as exc:
                detail = str(exc) if isinstance(exc, SetupError) else '操作失败：检查网络、文件格式及本机日志；未自动重试或覆盖原文件。'
                messages.put(('done', lambda detail=detail: messagebox.showerror('需要处理', detail, parent=root)))
        threading.Thread(target=run, daemon=True).start()

    def session():
        if state['session'] is None:
            raise SetupError('请先到第 ① 页选择并读取已有安装配置。')
        return state['session']

    def refresh_lists():
        current = session()
        for tree in (target_tree, user_tree):
            tree.delete(*tree.get_children())
        for i, row in enumerate(current.targets['targets']):
            target_tree.insert('', 'end', iid=str(i), values=(row['id'], row['label'], row.get('kind', ''), '是' if row.get('enabled', True) else '否'))
        for row in current.users['users']:
            user_tree.insert('', 'end', values=(row['qq'], row['label'], '允许' if row.get('allow_group', True) else '不允许', '启用' if row.get('enabled', True) else '停用'))
        pool_info.set(f'当前暂存词库：{len(current.pool["prompts"])} 条；自定义组 {len(current.pool.get("custom_group_definitions", []))} 个。')

    # 1. Installation selection
    frame = pages[0]
    note(frame, '适合：在安装了懒人包的那台电脑配置服务。Windows 可双击 EXE；Linux 需要桌面和 Tkinter。\n远程云服务器不能仅填 IP 就修改文件；此向导不提供 SSH，也不会把 Linux 路径当成 Windows 目录。', 0)
    config_path = tk.StringVar()
    field(frame, '已有安装配置', config_path, 1)
    def choose():
        name = filedialog.askopenfilename(title='选择安装目录中的 runtime-env.json', filetypes=[('安装配置', 'runtime-env.json'), ('JSON', '*.json')])
        if name:
            config_path.set(name)
    ttk.Button(frame, text='浏览…', command=choose).grid(row=1, column=2, padx=6)
    install_info = tk.StringVar(value='怎么找：打开原来的安装目录，找到 Start.cmd / Start.sh，旁边就是 runtime-env.json。\n不要选 ZIP 内部文件，不要新建空配置。已有配置会保留未修改字段。')
    ttk.Label(frame, textvariable=install_info, wraplength=870, justify='left').grid(row=3, column=0, columnspan=3, sticky='w', pady=14)
    def load():
        if state['session'] is not None and state['session'].pending_tokens and not state['session'].changes():
            if not messagebox.askyesno('请先保存令牌', '重新读取会清除本次生成令牌的明文。确认已经私下保存了吗？', parent=root):
                return
        if state['session'] is not None and state['session'].changes():
            if not messagebox.askyesno('重新读取', '将放弃未保存的修改，是否继续？', parent=root):
                return
        current = SetupSession(config_path.get())
        state.update(session=current, saved=False, editing=None, job=None, image=None)
        for key, var in connections.items():
            var.set(current.env.get(key, ''))
        bot_var.set(current.env.get('AAH_ASTRBOT_BOT_ID', ''))
        hub_url.set('http://' + ('127.0.0.1' if current.env.get('AAH_HOST') in {'', None, '0.0.0.0'} else current.env['AAH_HOST']) + ':' + current.env.get('AAH_PORT', '6278'))
        install_info.set('读取成功。插件运行数据目录：\n' + str(current.data_path) + '\n\n未修改、未上传任何文件。请点击“下一步”。')
        refresh_lists()
        dictionary_info.set(f'当前词典：{len(current.dictionary.get("characters", []))} 条；目标：{current.paths["角色词典"]}')
        status.set('配置已载入。所有后续修改先暂存，直到第 ⑦ 页确认才写入。')
    ttk.Button(frame, text='读取已有配置', command=protect(load)).grid(row=2, column=1, sticky='w', pady=8)
    note(frame, '找不到文件？\n• 如果没有完成懒人包部署，请先回部署器安装。\n• 纯手动环境若只有 .env，请使用原启动方式配置；本版向导不会猜测或新建第二套运行配置。\n• 如果提示数据目录不存在，先启动 AstrBot 插件完成初始化，再读取。', 4)

    # 2. Credentials
    frame = pages[1]
    note(frame, '三种凭据不要混淆：管理员令牌给 Admin；每人独立令牌给 Service；AstrBot API Key 仅给服务器。\nBot ID 从 QQ /sid 回复复制，不是群号或机器人 QQ。密钥默认隐藏，不会写进检测结果。', 0)
    connections = {}
    for row, (key, label, secret) in enumerate([
        ('AAH_ASTRBOT_URL', 'AstrBot 地址', False), ('AAH_COMFYUI_URL', 'ComfyUI 地址', False),
        ('AAH_ASTRBOT_BOT_ID', '实际 Bot ID', False), ('AAH_ASTRBOT_API_KEY', 'AstrBot API Key', True),
        ('AAH_ADMIN_TOKEN', 'Hub 管理员令牌', True)], 1):
        connections[key] = tk.StringVar()
        field(frame, label, connections[key], row, secret)
    def new_admin():
        session()
        if connections['AAH_ADMIN_TOKEN'].get() and not messagebox.askyesno('更换管理员令牌', '保存并重启 Hub 后，旧管理员令牌会失效。确定生成新令牌？', parent=root):
            return
        connections['AAH_ADMIN_TOKEN'].set(secrets.token_urlsafe(48))
    ttk.Button(frame, text='缺少／泄漏时才生成新管理令牌', command=protect(new_admin)).grid(row=6, column=1, sticky='w', pady=6)
    hub_url = tk.StringVar(value='http://127.0.0.1:6278')
    field(frame, 'Hub 检测／App 地址', hub_url, 7)
    def test_hub():
        url = validate_url(hub_url.get())
        status.set('正在检查 Hub 健康接口，不发送密钥…')
        threading.Thread(target=lambda: messages.put(probe_health(url)), daemon=True).start()
    ttk.Button(frame, text='检查 Hub 是否在线', command=protect(test_hub)).grid(row=7, column=2, padx=6)
    def stage_connections():
        session().set_connections({key: var.get() for key, var in connections.items()})
        bot_var.set(connections['AAH_ASTRBOT_BOT_ID'].get().strip())
        status.set('连接配置已暂存，尚未写盘；请继续配置投递目标。')
    ttk.Button(frame, text='暂存连接设置', command=protect(stage_connections)).grid(row=8, column=1, sticky='w', pady=8)
    note(frame, '在 AstrBot 桌面程序／WebUI → 设置 → OpenAPI 创建 Key：复制创建弹窗的完整 47 位 abk_ 密钥，不能复制列表中的 12 位前缀。\n权限 chat / file / im；不是登录密码或 Hub 令牌。没填可先保存其他配置。这里不改端口和防火墙。', 9)
    def auth_check():
        url = validate_url(connections['AAH_ASTRBOT_URL'].get())
        key = connections['AAH_ASTRBOT_API_KEY'].get()
        if not messagebox.askyesno('只读鉴权检测', f'将 API Key 仅发送至：{url}\n读取会话列表以验证 chat 权限，不发送消息、不生图。是否继续？', parent=root): return
        work(lambda: checks.check_astrbot(url, key), lambda result: status.set(result))
    ttk.Button(frame, text='验证 AstrBot 完整 Key（不生图）', command=protect(auth_check)).grid(row=10, column=1, sticky='w')

    # 3. Destinations
    frame = pages[2]
    note(frame, '填写群号就能生成投递配置，不需要写 JSON。新目标默认只允许 N，首次请用测试群。\n注意：允许群投递的普通用户能看见全部启用群目标；不是逐人逐群授权。', 0)
    target_tree = ttk.Treeview(frame, columns=('id', 'label', 'kind', 'enabled'), show='headings', height=5)
    for key, label in [('id', '内部 ID'), ('label', '显示名称'), ('kind', '类型'), ('enabled', '启用')]:
        target_tree.heading(key, text=label); target_tree.column(key, width=160)
    target_tree.grid(row=1, column=0, columnspan=3, sticky='ew')
    target_id = tk.StringVar(value='test-group'); target_label = tk.StringVar(value='我的测试群')
    target_kind = tk.StringVar(value='群聊'); bot_var = tk.StringVar(); number = tk.StringVar()
    field(frame, '名称（给人看）', target_label, 2)
    field(frame, '内部 ID（不要重名）', target_id, 3)
    ttk.Combobox(frame, textvariable=target_kind, values=('群聊', '私聊'), state='readonly', width=12).grid(row=2, column=2, padx=6)
    field(frame, '平台 Bot ID', bot_var, 4); field(frame, '群号／收图人的 QQ', number, 5)
    flags = ttk.Frame(frame); flags.grid(row=6, column=0, columnspan=3, sticky='w', pady=6)
    enabled = tk.BooleanVar(value=True)
    levels = {key: tk.BooleanVar(value=key == 'N') for key in ('N', 'H', 'S')}
    ttk.Checkbutton(flags, text='启用目标', variable=enabled).pack(side='left', padx=5)
    for key, label in [('N', '允许 N'), ('H', '允许 H（敏感）'), ('S', '允许 S（仅私聊）')]:
        ttk.Checkbutton(flags, text=label, variable=levels[key]).pack(side='left', padx=5)
    def reset_target():
        state['editing'] = None
        target_id.set('target-' + secrets.token_hex(3)); target_label.set(''); number.set('')
        target_kind.set('群聊'); enabled.set(True)
        for key in levels: levels[key].set(key == 'N')
    def select_target(event=None):
        selected = target_tree.selection()
        if not selected: return
        index = int(selected[0]); state['editing'] = index
        row = session().targets['targets'][index]
        bot, kind, ident = row['umo'].split(':')
        target_id.set(row['id']); target_label.set(row['label']); bot_var.set(bot); number.set(ident)
        target_kind.set('群聊' if kind == 'GroupMessage' else '私聊'); enabled.set(row.get('enabled', True))
        for key in levels: levels[key].set(key in row.get('allow_safety', ['N', 'H'] if kind == 'GroupMessage' else ['N', 'H', 'S']))
    target_tree.bind('<<TreeviewSelect>>', select_target)
    def stage_target():
        current = session()
        row = target_record(target_id.get(), target_label.get(), bot_var.get(), number.get(), 'group' if target_kind.get() == '群聊' else 'private')
        row.update(enabled=enabled.get(), allow_safety=[key for key, var in levels.items() if var.get()])
        if row['kind'] == 'group' and 'S' in row['allow_safety']:
            raise SetupError('群投递不支持 S，请取消该选项。')
        index = state['editing']
        rows = [dict(item) for item in current.targets['targets']]
        if index is None: rows.append(row)
        else: rows[index] = {**rows[index], **row}
        validate_targets({'targets': rows})
        current.targets['targets'] = rows
        refresh_lists(); reset_target(); status.set('投递目标已暂存。需要最终确认保存才会生效。')
    buttons = ttk.Frame(frame); buttons.grid(row=7, column=0, columnspan=3, sticky='w')
    ttk.Button(buttons, text='新增空白目标', command=reset_target).pack(side='left', padx=5)
    ttk.Button(buttons, text='暂存这个目标', command=protect(stage_target)).pack(side='left', padx=5)
    note(frame, '点击已有行可编辑或取消“启用”；向导不直接删除目标。\n管理员私聊需单独添加；普通用户绑定 QQ 后自动出现“我的 QQ 私聊”，不要创建名为 self-private 的目标。', 8)

    # 4. Tokens
    frame = pages[3]
    note(frame, '建议先给自己创建一个普通用户：用 Admin 管理，用 Service 日常跑图。\n新用户令牌只在最终保存成功后交付；关闭向导后无法恢复明文。已有账号不会自动换发令牌。', 0)
    user_tree = ttk.Treeview(frame, columns=('qq', 'label', 'group', 'enabled'), show='headings', height=7)
    for key, label in [('qq', '绑定 QQ'), ('label', '备注'), ('group', '群投递'), ('enabled', '状态')]:
        user_tree.heading(key, text=label); user_tree.column(key, width=170)
    user_tree.grid(row=1, column=0, columnspan=3, sticky='ew')
    user_qq = tk.StringVar(); user_label = tk.StringVar(); allow_group = tk.BooleanVar(value=False)
    field(frame, '用户自己的 QQ 号', user_qq, 2); field(frame, '备注', user_label, 3)
    ttk.Checkbutton(frame, text='允许此用户向所有已启用群目标投递（默认关闭）', variable=allow_group).grid(row=4, column=0, columnspan=3, sticky='w', pady=8)
    def stage_user():
        session().add_user(user_qq.get(), user_label.get(), allow_group.get())
        user_qq.set(''); user_label.set(''); allow_group.set(False)
        refresh_lists(); status.set('新用户已暂存，保存后可私下领取令牌。')
    ttk.Button(frame, text='暂存新增用户', command=protect(stage_user)).grid(row=5, column=1, sticky='w', pady=8)
    note(frame, '已有账号的停用、删除和令牌换发，请在 Admin → 用户页操作。\n不要把管理员令牌当成普通用户令牌发给群友。不要在其他管理员修改账号时回写旧配置。', 6)

    # 5. Pool
    frame = pages[4]
    note(frame, '公共词库为空是正常设计。普通英文生图不需要词库，“来张好图”需要导入自己的审核库。\n此处按 ID 合并，并保留完整自定义分组。默认跳过重复 ID，不覆盖原条目。', 0)
    pool_info = tk.StringVar(value='请先读取安装配置。')
    ttk.Label(frame, textvariable=pool_info).grid(row=1, column=0, columnspan=3, sticky='w', pady=10)
    overwrite = tk.BooleanVar(value=False)
    ttk.Checkbutton(frame, text='覆盖相同 ID 的旧条目（确认需要更新时才勾选）', variable=overwrite).grid(row=2, column=0, columnspan=3, sticky='w', pady=8)
    def import_pool():
        current = session()
        path = filedialog.askopenfilename(title='选择审核后的词库 JSON', filetypes=[('JSON', '*.json')])
        if not path: return
        try:
            added, updated = current.import_pool(Path(path), overwrite.get())
        except Exception:
            raise SetupError('词库导入未完成。请用配套词库编辑器检查 ID、来源、等级和 JSON 格式；尚未修改运行词库。') from None
        refresh_lists(); status.set(f'词库已暂存：新增 {added} 条，更新 {updated} 条。请到最后一步确认保存。')
    ttk.Button(frame, text='选择文件并预览导入统计…', command=protect(import_pool)).grid(row=3, column=1, sticky='w', pady=10)
    def editor():
        command = [sys.executable, '--pool-manager'] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).resolve()), '--pool-manager']
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
    ttk.Button(frame, text='打开配套词库编辑器（独立窗口）', command=protect(editor)).grid(row=4, column=1, sticky='w', pady=10)
    note(frame, '没有合适词库？先跳过，完成普通英文生图后再整理。\n编辑器建议使用工作副本，保存后在这里导入；若编辑器修改了运行文件，本向导会要求重新读取以避免覆盖。\n本版编辑器支持 B/G/D/C/R 基础来源；发现其他专用格式时会停止，不会静默丢弃条目。', 5)

    # 6. Optional character dictionary: staged with the other local configuration.
    frame = pages[5]
    note(frame, '角色词典是“中文名字 → 角色标签／外貌词”，不是 LoRA，也不是随机词库；普通生图可以跳过。\n导入替换主词典但不删除角色 edits、收藏或预设；原词典在最终保存时备份。', 0)
    dictionary_info = tk.StringVar(value='请先读取安装配置。')
    ttk.Label(frame, textvariable=dictionary_info, wraplength=850).grid(row=1, column=0, columnspan=3, sticky='w', pady=12)
    def dictionary_ready(payload):
        count = session().stage_dictionary(payload)
        dictionary_info.set(f'已暂存 {count} 个角色；尚未写盘。目标：{session().paths["角色词典"]}')
        status.set('角色词典已暂存，请到第 ⑦ 页核对并保存。')
    def dictionary_local():
        session()
        name = filedialog.askopenfilename(title='选择包含 characters 数组的词典 JSON', filetypes=[('角色词典', '*.json')])
        if name: dictionary_ready(read_object(Path(name)))
    def dictionary_online():
        session()
        explanation = ('将从以下公开来源下载角色结构和中文译名并在本机装配：\n\n' + checks.CHARACTERS_URL + '\n\n' + checks.TRANSLATIONS_URL +
            '\n\n只在本机使用；请先确认上游许可和适用性。下载可能需要数分钟，不随软件捆绑分发。\n不会上传你的配置、密钥或词库；成功后也只暂存，需另行保存。是否继续？')
        if messagebox.askyesno('授权本次公开数据下载', explanation, parent=root):
            work(lambda: checks.build_online_dictionary(lambda text: messages.put(text)), dictionary_ready)
    ttk.Button(frame, text='导入本地角色词典 JSON…', command=protect(dictionary_local)).grid(row=2, column=1, sticky='w', pady=8)
    ttk.Button(frame, text='确认来源后在线装配中文词典…', command=protect(dictionary_online)).grid(row=3, column=1, sticky='w', pady=8)
    note(frame, '保存后：AstrBot → AAA 插件设置 → 启用“中文角色名词典”；词典路径须与上面目标一致。\n本向导不猜测 AstrBot Desktop 配置位置，也不会自动覆盖插件配置。\n在 App“角色词典”搜索名字，先选弱模式（角色标签），强模式会额外加入外貌词。\n词典命中不代表底模认识角色；效果不足时再配置对应角色 LoRA。在线源不可用时可导入已装配 JSON。', 4)

    # 7. Commit, delivery and tests
    frame = pages[6]
    note(frame, '最后核对。请先暂停群友任务及其他管理操作；备份也可能含密钥，不能上传或发群。\n确认只保存列表中显示的文件。程序不会安装模型、改防火墙、结束进程或发测试消息。', 0)
    summary_box = tk.Text(frame, height=11, wrap='word', state='disabled')
    summary_box.grid(row=1, column=0, columnspan=3, sticky='nsew')
    def review():
        stage_connections()
        summary_box.configure(state='normal'); summary_box.delete('1.0', 'end')
        summary_box.insert('1.0', session().summary()); summary_box.configure(state='disabled')
    consent = tk.BooleanVar(value=False)
    ttk.Checkbutton(frame, text='我已暂停其他配置编辑，确认目标路径正确，并同意备份后保存', variable=consent).grid(row=2, column=0, columnspan=3, sticky='w', pady=8)
    def save():
        review()
        if not consent.get(): raise SetupError('请先阅读变更列表，再勾选确认。')
        if not session().changes():
            status.set('没有变更，无需保存。'); return
        if not messagebox.askyesno('确认写入', session().summary(), parent=root): return
        backups = session().commit(); state['saved'] = True; consent.set(False)
        status.set(f'保存成功，备份 {len(backups)} 个原文件。连接设置变更后请正常重启 Hub；新用户令牌请点击领取。')
        messagebox.showinfo('保存完成', '已保存。备份在原文件同目录，文件名含 .backup_first_run_。\n\n请领取并私下保存新用户令牌。修改连接设置后需要正常重启 Hub；单击 Start 不能重启旧进程。', parent=root)
    def tokens():
        current = session()
        if current.changes() or not state['saved']:
            raise SetupError('请先完成最终保存，再领取令牌。')
        if not current.pending_tokens:
            raise SetupError('本次没有新增用户。原用户令牌不能从哈希找回。')
        dialog = tk.Toplevel(root); dialog.title('私密令牌交付 · 请勿截屏发群'); dialog.geometry('850x350')
        dialog.transient(root); dialog.grab_set()
        ttk.Label(dialog, text='明文只存在于本次向导内存中。请逐人私发；关闭程序后不能找回。').pack(padx=16, pady=14)
        qq_var = tk.StringVar(value=next(iter(current.pending_tokens)))
        combo = ttk.Combobox(dialog, textvariable=qq_var, values=list(current.pending_tokens), state='readonly')
        combo.pack(fill='x', padx=16, pady=8)
        secret_var = tk.StringVar(value=current.pending_tokens[qq_var.get()])
        combo.bind('<<ComboboxSelected>>', lambda event: secret_var.set(current.pending_tokens[qq_var.get()]))
        entry = ttk.Entry(dialog, textvariable=secret_var, show='●', state='readonly'); entry.pack(fill='x', padx=16, pady=8)
        def copy_token():
            if messagebox.askyesno('复制敏感信息', '剪贴板将含此用户令牌，请只私下交付，完成后清理剪贴板。', parent=dialog):
                root.clipboard_clear(); root.clipboard_append(secret_var.get())
        ttk.Button(dialog, text='复制所选用户令牌', command=copy_token).pack(pady=8)
        def export():
            from hub_lite_user_manager import write_delivery
            name = filedialog.asksaveasfilename(parent=dialog, title='私密交付 CSV（不能选已有文件）', initialfile='private-token-delivery.csv', defaultextension='.csv')
            if name:
                try:
                    write_delivery(Path(name), list(current.pending_tokens.items()))
                    messagebox.showinfo('已导出', '此文件含明文令牌，请逐人私发后妥善处理。', parent=dialog)
                except Exception:
                    messagebox.showerror('未导出', '无法写入，或目标文件已存在。请选择新的私密文件名。', parent=dialog)
        ttk.Button(dialog, text='全部导出到私密 CSV…', command=export).pack(pady=8)
    buttons = ttk.Frame(frame); buttons.grid(row=3, column=0, columnspan=3, sticky='w', pady=8)
    for label, command in [('刷新变更预览', review), ('确认保存并备份', save), ('领取新用户令牌', tokens)]:
        ttk.Button(buttons, text=label, command=protect(command)).pack(side='left', padx=5)
    note(frame, '接下来由你完成：\n1. 正常重启 Hub（若修改连接字段）→ Admin 填 Hub 地址和管理员令牌。\n2. Service 填同一个地址和自己的用户令牌 → 选择“我的 QQ 私聊”。\n3. 普通英文生图一张 → 在记录中确认图片 → 再测试群投递和本地保存。\n4. 已导入词库后测试“来张好图”B/N，最后再启用 HQ／反推。\n没有 GPU 时可以先配置，生图验收等显卡可用后再做。', 4)

    # 8. Existing Hub API only; explicit submission, resumable read-only polling.
    frame = pages[7]
    note(frame, '先保存并正常重启 Hub，然后验证首次图片。默认不投递 QQ，不调用中文 LLM、随机库、角色或 HQ。\n服务健康 ≠ 能出图；只有任务成功且图片下载校验通过，才完成首张图验收。', 0)
    workflow_path = tk.StringVar()
    field(frame, 'AAA 当前 API 工作流', workflow_path, 1)
    def pick_workflow():
        value = filedialog.askopenfilename(title='选择 AAA 插件当前 workflow_path 对应的 API JSON', filetypes=[('JSON', '*.json')])
        if value: workflow_path.set(value)
    ttk.Button(frame, text='浏览…', command=pick_workflow).grid(row=1, column=2)
    report = tk.Text(frame, height=7, wrap='word', state='disabled')
    report.grid(row=3, column=0, columnspan=3, sticky='ew', pady=6)
    def report_text(text):
        report.configure(state='normal'); report.delete('1.0', 'end'); report.insert('1.0', text); report.configure(state='disabled')
        status.set('检测结果已更新。请阅读本页说明。')
    def preflight():
        base = validate_url(connections['AAH_COMFYUI_URL'].get())
        path = workflow_path.get()
        if not path: raise SetupError('请选择 AAA 实际使用的 API 工作流文件；不要选择另一个工作流冒充验收。')
        work(lambda: checks.check_workflow(base, path), report_text)
    ttk.Button(frame, text='检查节点 / 模型名称 / GPU（只读）', command=protect(preflight)).grid(row=2, column=1, sticky='w')
    target_choice = tk.StringVar(); target_options = {}
    target_select = ttk.Combobox(frame, textvariable=target_choice, state='readonly')
    target_select.grid(row=4, column=1, sticky='ew')
    ttk.Label(frame, text='本次目标').grid(row=4, column=0, sticky='w')
    def credentials():
        current = session()
        if current.changes() or any(v.get() != current.env.get(k, '') for k, v in connections.items()):
            raise SetupError('请先到第 ⑦ 页保存配置，再正常重启 Hub。')
        return validate_url(hub_url.get()), current.env.get('AAH_ADMIN_TOKEN', '')
    def read_targets():
        base, token = credentials()
        if not messagebox.askyesno('授权读取 Hub', f'将管理员令牌发送至 {base} 读取可用目标。请确认是自己的 Hub。', parent=root): return
        def done(rows):
            target_options.clear()
            target_options.update({f'{x["label"]} [{x["id"]}]': x['id'] for x in rows})
            target_select.configure(values=list(target_options)); target_choice.set(next(iter(target_options), ''))
            report_text(f'Hub 管理员鉴权成功；可用目标 {len(rows)} 个。没有目标请在第 ③ 页添加并保存，再重新读取。')
        work(lambda: checks.targets(base, token), done)
    ttk.Button(frame, text='读取目标', command=protect(read_targets)).grid(row=4, column=2)
    deliver = tk.BooleanVar(value=False)
    ttk.Checkbutton(frame, text='本次同时向所选 QQ 私聊／群投递（默认关闭；发群须自行确认）', variable=deliver).grid(row=5, column=0, columnspan=3, sticky='w', pady=6)
    job_id = tk.StringVar(); field(frame, '任务 ID（可恢复查询）', job_id, 6)
    def submitted(job):
        checks.job_path(job.get('id', ''))
        state['job'] = job; job_id.set(job['id'])
        report_text('任务已提交：' + job['id'] + '\n点击“查询 / 取图”查看进度；无需再次提交。关闭向导不会取消服务器任务。')
    def generate():
        base, token = credentials()
        if state['submission']:
            raise SetupError('本窗口已经尝试提交过。请查询现有任务或在 App 记录中核对；如需重试，确认旧任务已结束后再点击“新一轮”。')
        target = target_options.get(target_choice.get(), '')
        if not target: raise SetupError('请先读取并选择目标。')
        if not messagebox.askyesno('确认生成一张测试图片', f'请求发往：{base}\n目标：{target_choice.get()}\n投递 QQ：{"是" if deliver.get() else "否，仅取回图片"}\n\n将消耗显卡资源。基础工作流中的 batch_size 应先设为 1。\n提示词：{checks.TEST_PROMPT}\n是否提交一次？', parent=root): return
        send = deliver.get(); state['submission'] = True; state['image'] = None
        work(lambda: checks.submit_test(base, token, target, send), submitted)
    def query_job():
        base, token = credentials(); ident = job_id.get().strip(); checks.job_path(ident)
        def query():
            job = checks.job_status(base, token, ident)
            result = checks.fetch_image(base, token, job) if job.get('status') == 'succeeded' and job.get('images') else None
            return job, result
        def done(result):
            job, image = result; state['job'] = job; state['image'] = image
            if image:
                report_text('首张图链路通过：Hub → AstrBot → 插件 / ComfyUI → Hub 图片取回，大小与 SHA256 校验通过。\n可预览或另存图片。QQ 实际收到仍需收件人确认；Service 用户权限还需用个人令牌验收。')
            else:
                labels = {'queued': '排队中', 'running': '生成中', 'failed': '失败', 'succeeded': '任务结束但未返回图片'}
                report_text('状态：' + labels.get(job.get('status'), '未知') + '\n任务 ID：' + ident + '\n排队或运行时稍后再次查询；失败时在 App“记录”打开该任务及本机日志。不要反复提交。')
        work(query, done)
    def reset_test():
        if messagebox.askyesno('确认旧任务已处理', '请先在 App 记录确认旧任务已经结束。网络超时不代表任务未创建。确定允许下一次手动提交？', parent=root):
            state.update(submission=False, image=None, job=None); job_id.set('')
    buttons = ttk.Frame(frame); buttons.grid(row=7, column=0, columnspan=3, sticky='w')
    for label, command in [('提交测试图', generate), ('查询 / 取图', query_job), ('旧任务结束后新一轮', reset_test)]:
        ttk.Button(buttons, text=label, command=protect(command)).pack(side='left', padx=4)
    def preview():
        item = state['image']
        if not item: raise SetupError('请先查询并成功取回图片。')
        if not item[2]: raise SetupError('该图片格式或尺寸不适合内置预览。请另存后用系统图片查看器打开。')
        dialog = tk.Toplevel(root); dialog.title('首张图预览')
        image = tk.PhotoImage(data=base64.b64encode(item[0]))
        factor = max(1, (max(image.width(), image.height()) + 719) // 720)
        image = image.subsample(factor)
        label = ttk.Label(dialog, image=image); label.image = image; label.pack()
    def save_image():
        item = state['image']
        if not item: raise SetupError('请先查询并成功取回图片。')
        name = filedialog.asksaveasfilename(title='另存首张图（不覆盖已有文件）', defaultextension=item[1], initialfile='AAA-first-image' + item[1])
        if name:
            try:
                with open(name, 'xb') as stream: stream.write(item[0])
            except FileExistsError: raise SetupError('文件已存在，请换一个名字；向导不覆盖已有图片。') from None
            status.set('图片已保存到你选择的位置。')
    buttons = ttk.Frame(frame); buttons.grid(row=8, column=0, columnspan=3, sticky='w', pady=8)
    ttk.Button(buttons, text='预览返回图片', command=protect(preview)).pack(side='left', padx=4)
    ttk.Button(buttons, text='另存图片到本地…', command=protect(save_image)).pack(side='left', padx=4)

    # 9. Offline help and bundled tools.
    frame = pages[8]
    note(frame, '不用在终端输入代码：先按“首张图逐项操作”完成基础生图，再启用词库、角色、HQ 或反推。\n这是一份安装后向导，不会替代 ComfyUI / AstrBot / NapCat 的安装器，也不会偷偷改模型或启动服务。', 0)
    def doc(name):
        base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
        path = base / 'docs' / name
        dialog = tk.Toplevel(root); dialog.title(name); dialog.geometry('950x720')
        view = tk.Text(dialog, wrap='word', padx=15, pady=15)
        scroll = ttk.Scrollbar(dialog, command=view.yview); scroll.pack(side='right', fill='y')
        view.configure(yscrollcommand=scroll.set); view.pack(fill='both', expand=True)
        view.insert('1.0', path.read_text('utf-8')); view.configure(state='disabled')
    for i, (label, name) in enumerate([
        ('首张图逐项操作 / 模型配置 / 失败排查', 'FIRST_IMAGE_WALKTHROUGH.md'),
        ('完整首次配置手册（含角色和群投递）', 'FIRST_RUN.md'),
        ('各小工具用途、输入输出与操作步骤', 'TOOLS.md'),
        ('Windows 部署 / 模型下载说明', 'DEPLOY_WINDOWS.md'),
        ('Linux 部署说明', 'DEPLOY_LINUX.md'),
        ('Anima Master 0.7.1 配置指引', 'ANIMA_MASTER.md'),
        ('常见错误速查', 'TROUBLESHOOTING.md')], 1):
        ttk.Button(frame, text=label, command=protect(lambda name=name: doc(name))).grid(row=i, column=1, sticky='w', pady=5)
    def user_editor():
        command = [sys.executable] + ([] if getattr(sys, 'frozen', False) else [str(Path(__file__).resolve())]) + ['--user-manager']
        subprocess.Popen(command, **({'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}))
    ttk.Button(frame, text='打开离线用户令牌管理器（建议编辑副本）', command=protect(user_editor)).grid(row=8, column=1, sticky='w', pady=5)
    ttk.Button(frame, text='打开离线词库编辑器', command=protect(editor)).grid(row=9, column=1, sticky='w', pady=5)
    def open_service(key):
        address = validate_url(hub_url.get() if key == 'Hub' else connections[key].get())
        if messagebox.askyesno('打开浏览器', f'打开 {address}（不会在 URL 携带密钥）。是否继续？', parent=root): webbrowser.open(address)
    links = ttk.Frame(frame); links.grid(row=10, column=0, columnspan=3, sticky='w', pady=8)
    for label, key in [('打开 AstrBot 后台', 'AAH_ASTRBOT_URL'), ('打开 ComfyUI', 'AAH_COMFYUI_URL'), ('打开 Hub / App', 'Hub')]:
        ttk.Button(links, text=label, command=protect(lambda key=key: open_service(key))).pack(side='left', padx=4)

    footer = ttk.Frame(root); footer.pack(fill='x', padx=20, pady=10)
    ttk.Label(footer, textvariable=status, wraplength=770, justify='left').pack(side='left', fill='x', expand=True)
    def previous(): notebook.select(max(0, notebook.index('current') - 1))
    def next_page():
        index = notebook.index('current')
        session()
        if index == 1: stage_connections()
        if index == 5: review()
        notebook.select(min(len(pages) - 1, index + 1))
    ttk.Button(footer, text='上一步', command=previous).pack(side='left', padx=5)
    ttk.Button(footer, text='下一步', command=protect(next_page)).pack(side='left', padx=5)
    def close():
        if state['busy'] and not messagebox.askyesno('后台操作未结束', '关闭不会取消已提交的服务器任务；尚未保存的下载结果会丢失。确认关闭？', parent=root): return
        current = state['session']
        form_changed = current is not None and any(var.get() != current.env.get(key, '') for key, var in connections.items())
        if current is not None and (current.changes() or current.pending_tokens or form_changed):
            if not messagebox.askyesno('关闭向导', '未保存的修改会放弃；本次新增令牌的明文也会清除。确认已经处理了吗？', parent=root): return
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    def poll():
        while not messages.empty():
            item = messages.get_nowait()
            if isinstance(item, tuple):
                state['busy'] = False
                protect(item[1])()
            else: status.set(item)
        root.after(150, poll)
    root.after(150, poll)
    if smoke:
        import json
        import tempfile
        import time
        import hashlib
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix='aaa-wizard-smoke-') as temporary:
            base = Path(temporary).resolve()
            data = base / 'data'; data.mkdir()
            runtime = base / 'runtime-env.json'
            runtime.write_text(json.dumps({'AAH_PLUGIN_DATA_DIR': str(data),
                'AAH_ADMIN_TOKEN': 'test-' + 'a' * 48, 'AAH_ASTRBOT_URL': 'http://127.0.0.1:6185',
                'AAH_COMFYUI_URL': 'http://127.0.0.1:8188', 'AAH_ASTRBOT_BOT_ID': 'demo-bot'}), encoding='utf-8')
            config_path.set(str(runtime)); load()
            user_qq.set('123456789'); user_label.set('测试用户'); stage_user()
            number.set('123456789'); stage_target()
            dictionary_ready({'schema_version': '1.1', 'characters': [{'tag': 'example', 'aliases': ['示例']}]})
            review()
            assert '测试用户' in str(user_tree.item(user_tree.get_children()[0]))
            assert session().pending_tokens['123456789'] not in summary_box.get('1.0', 'end')
            session().commit()
            assert len(SetupSession(runtime).targets['targets']) == 1
            assert len(SetupSession(runtime).dictionary['characters']) == 1
            png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN6sAAAAASUVORK5CYII=')
            mock_job = {'id': 'b' * 32, 'status': 'succeeded', 'images': [{'id': 'image', 'size_bytes': len(png), 'sha256': hashlib.sha256(png).hexdigest()}]}
            def finish():
                deadline = time.monotonic() + 5
                while state['busy'] and time.monotonic() < deadline:
                    root.update(); time.sleep(0.01)
                assert not state['busy'], 'mock worker timed out'
            with patch.object(messagebox, 'askyesno', return_value=True), \
                 patch.object(checks, 'targets', return_value=[{'id': 'test-group', 'label': '测试目标'}]), \
                 patch.object(checks, 'submit_test', return_value=mock_job) as submit, \
                 patch.object(checks, 'job_status', return_value=mock_job), \
                 patch.object(checks, 'fetch_image', return_value=(png, '.png', True)):
                read_targets(); finish(); generate(); finish(); query_job(); finish()
                assert submit.call_args.args[-1] is False
                assert '首张图链路通过' in report.get('1.0', 'end')
                assert state['image'][0] == png
                try:
                    generate()
                except SetupError:
                    pass
                else:
                    raise AssertionError('duplicate submission not blocked')
            root.update_idletasks(); root.update()
            for page in pages:
                notebook.select(page); root.update_idletasks()
            assert len(notebook.tabs()) == 9
        root.destroy()
        print('PASS: nine pages, dictionary staging, private save and mocked first-image UI flow; no real GPU/QQ')
        return 0
    root.mainloop()
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--pool-manager', action='store_true')
    parser.add_argument('--user-manager', action='store_true')
    args = parser.parse_args()
    if args.pool_manager:
        import prompt_pool_manager
        raise SystemExit(prompt_pool_manager.launch_gui())
    if args.user_manager:
        import hub_lite_user_manager
        raise SystemExit(hub_lite_user_manager.launch_gui())
    raise SystemExit(launch_gui(args.smoke_test))
