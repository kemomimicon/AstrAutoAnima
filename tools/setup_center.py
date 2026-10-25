"""One entry for deployment, NapCat wiring, first-image setup and daily recovery."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def tool_command(name, platform='auto'):
    if name not in {'deploy_project', 'first_run_wizard', 'napcat_setup', 'extension_guide', 'relocate_install'}:
        raise ValueError('未知向导。')
    path = ROOT / 'tools' / (name + '.py')
    if not path.is_file(): raise ValueError('当前包不完整：缺少 ' + path.name + '，请完整解压懒人包。')
    command = [sys.executable, str(path)]
    if name == 'deploy_project': command.extend(['--platform', platform])
    return command


def launch_gui(platform='auto', smoke=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from deploy_project import progress_text
    root = tk.Tk(); root.title('AstrAutoAnima · 安装与启动中心（候选版）')
    root.geometry(f'1000x{min(850, max(520, root.winfo_screenheight() - 100))}'); root.minsize(900, 520)
    if smoke: root.withdraw()
    children = {}
    ttk.Label(root, text='第一次，从这里开始；出错只回到对应步骤', font=('Microsoft YaHei UI', 17, 'bold')).pack(anchor='w', padx=22, pady=(18, 8))
    ttk.Label(root, text='安装中心不会自动下载、启动或重置服务。打开某一步后，再确认具体操作。\n完成按钮不代表验收通过；模型、授权、QQ 登录仍需你确认。', justify='left').pack(anchor='w', padx=22, pady=6)
    body = ttk.Frame(root); body.pack(fill='both', expand=True)
    canvas = tk.Canvas(body, highlightthickness=0)
    scrollbar = ttk.Scrollbar(body, orient='vertical', command=canvas.yview)
    scrollbar.pack(side='right', fill='y'); canvas.pack(side='left', fill='both', expand=True)
    canvas.configure(yscrollcommand=scrollbar.set)
    content = ttk.Frame(canvas)
    canvas_window = canvas.create_window((0, 0), window=content, anchor='nw')
    content.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(canvas_window, width=e.width))

    def launch(name):
        try:
            child = children.get(name)
            if child is not None and child.poll() is None:
                messagebox.showinfo('窗口已打开', '请切回已经打开的这个向导，不要同时重复部署。', parent=root); return
            children[name] = subprocess.Popen(tool_command(name, platform), cwd=str(ROOT))
        except Exception as exc: messagebox.showerror('无法打开', str(exc), parent=root)

    steps = [
        ('① 部署环境 / 继续失败的安装', '选择 Win / Linux 对应环境和模型 → 只做预检 → 确认部署。失败后载入原 last-plan.json，不删除重装。', 'deploy_project'),
        ('② NapCat 安装与 QQ / OneBot 对接', '已有安装直接跳过下载；新安装按系统准备官方入口。自行扫码 → 两端配置反向 WebSocket → /sid 验收。', 'napcat_setup'),
        ('③ 授权、私聊目标与第一张图', '读取 runtime-env.json → 填完整 AstrBot Key → 设自己的私聊 → 保存 → 提交一次并取回图片。词库 / 角色可后补。', 'first_run_wizard'),
        ('④ 已经装好：日常启动 / 故障恢复', '日常用安装目录的 Start.cmd / Start.sh；Desktop 与 NapCat 按原方式启动。忘密码 / 401 等在首图向导看故障恢复。', 'first_run_wizard'),
        ('⑤ 配置建议 / 量化模型 / 扩展 / 常见问题', '先看最低与推荐配置，再选JoyCaption Q4/Q6或SeedVR2 Q4/Q8；模型可选下载，参数需按说明装配，不自动改动现有工作流。', 'extension_guide'),
    ]
    if sys.platform == 'win32':
        steps.append(('⑥ 搬家 / 改名后路径修复', '安装目录不能直接改名或移动。先关闭服务：已改名用就地修复；搬家完整复制后修复、保留原目录，自动备份，不改模型/词库内容及密钥。', 'relocate_install'))
    for title, description, tool in steps:
        frame = ttk.LabelFrame(content, text=title, padding=12); frame.pack(fill='x', padx=22, pady=5)
        ttk.Label(frame, text=description, wraplength=650, justify='left').pack(side='left', fill='x', expand=True)
        ttk.Button(frame, text='打开这一步', command=lambda n=tool: launch(n)).pack(side='right', padx=(10, 0))
    stage = tk.StringVar(value='可选：选择实际安装目录，只读查看上次部署记录；这不是服务健康证明。')
    ttk.Label(content, textvariable=stage, wraplength=810, justify='left').pack(fill='x', padx=22, pady=10)

    def inspect():
        value = filedialog.askdirectory(title='选择 Start.cmd / Start.sh 所在的独立安装目录', parent=root)
        if not value: return
        folder = Path(value)
        existing = [name for name in ('last-plan.json', 'runtime-env.json', 'services.json', 'Start.cmd', 'Start.sh') if (folder / name).is_file()]
        stage.set('目录：' + str(folder) + '\n找到：' + ('、'.join(existing) or '未发现部署文件；不要新建空配置冒充') + '\n' + progress_text(folder))
    footer = ttk.Frame(content); footer.pack(fill='x', padx=22, pady=6)
    ttk.Button(footer, text='只读查看原安装位置 / 进度', command=inspect).pack(side='left')
    ttk.Label(footer, text='管理员 / Hub / AstrBot / OneBot / WebUI 凭据不可混用，不要公开配置。', wraplength=530).pack(side='left', padx=10)
    if smoke:
        root.update_idletasks(); assert not children
        for name in ('deploy_project', 'first_run_wizard', 'napcat_setup', 'extension_guide'): tool_command(name, platform)
        root.destroy(); print('PASS: setup center; no child process, download or config writes'); return 0
    root.mainloop(); return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', choices=['auto', 'windows', 'linux'], default='auto')
    parser.add_argument('--smoke-test', action='store_true')
    args, extra = parser.parse_known_args(argv)
    if extra:
        # Preserve existing headless deployment commands, including their exit status.
        return subprocess.call(tool_command('deploy_project', args.platform) + extra)
    return launch_gui(args.platform, args.smoke_test)


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'): stream.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
