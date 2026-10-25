"""External components only: never deploy the bundled Hub/plugin or rewrite configuration."""
from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import queue
import shutil
import socket
import threading

from deployment_support import clean_path, comfy_root, discover_python, no_links
from download_network import DownloadNetwork
from easy_installer import InstallPlan, download_lock, install_external
from extension_guide import component_selection
from install_progress import ProgressPanel, ProgressLog, StageProgress

ROOT = Path(__file__).resolve().parents[1]


def prepare(identifier, directory, python='', dependencies=False, network=None):
    if not (ROOT / '.astr_auto_anima_public_root').is_file():
        raise ValueError('需要完整懒人包；此工具不下载或安装AAA服务代码。')
    if not clean_path(directory): raise ValueError('请选择已安装的ComfyUI目录。')
    comfy = comfy_root(directory)
    network = network or DownloadNetwork(); network.validate()
    if network.mode == 'local': raise ValueError('此入口用于可选下载；已有本地文件请按详细页手动装配。')
    selected = component_selection(identifier, ROOT)
    for item in selected:
        records = [item] if item['kind'] == 'git' else item.get('files', [])
        for record in records:
            relative = PurePosixPath(record['target'])
            expected = 'custom_nodes' if item['kind'] == 'git' else 'models'
            if relative.is_absolute() or '..' in relative.parts or ':' in str(relative) or '\\' in str(relative) or len(relative.parts) < 2 or relative.parts[0] != expected:
                raise ValueError('组件目标越出节点/模型范围，停止。')
            target = comfy.joinpath(*relative.parts); no_links(target)
            if not target.resolve().is_relative_to(comfy): raise ValueError('组件目标越出ComfyUI目录。')
            if target.exists() and (target.is_dir() != (item['kind'] == 'git')):
                raise ValueError('已有目标类型不匹配，不覆盖：' + target.name)
    cpy = discover_python(comfy, python, portable=True) if dependencies else None
    return InstallPlan(ROOT, comfy, comfy, comfy, components=set(), external={i['id'] for i in selected},
                       comfy_python=cpy, install_external_requirements=dependencies, download_network=network)


def execute(identifier, directory, python='', dependencies=False, network=None, *, consent=False, stopped=False, port=8188, log=print):
    if not consent or not stopped: raise ValueError('需确认所选下载与许可，并正常停止目标ComfyUI后再安装。')
    if type(port) is not int or not 1 <= port <= 65535: raise ValueError('请填写目标ComfyUI实际端口。')
    plan = prepare(identifier, directory, python, dependencies, network)
    try:
        connection = socket.create_connection(('127.0.0.1', port), timeout=0.5)
    except OSError: pass
    else:
        connection.close(); raise ValueError('目标端口仍有服务，请先正常停止；本工具不强杀进程。')
    from easy_installer import load_optional_components
    selected = [i for i in load_optional_components(ROOT) if i['id'] in plan.external]
    if any(i['kind'] == 'git' and not (plan.comfyui_root / i['target']).exists() for i in selected) and not shutil.which('git'):
        raise ValueError('缺少Git；未开始安装，请先按部署说明准备Git。')
    if any(i['kind'] == 'download_set' for i in selected) and not shutil.which('curl'):
        raise ValueError('缺少curl；未开始安装，请先准备curl或手动导入。')
    # No calls to deploy/execute_plan/configure/install_hub and no service restarts.
    with download_lock(plan.comfyui_root / 'custom_nodes/.aaa-extension-session'):
        install_external(plan, plan.comfyui_root, log)
    log('所选组件处理结束。未修改Hub/插件代码、配置、词库或工作流；请自行重启ComfyUI并按详细页验收。')


def launch_gui(identifier, smoke=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    selected = component_selection(identifier, ROOT)
    root = tk.Tk(); root.title('AAA · 仅补装外部节点 / 模型')
    root.geometry(f'940x{min(800, max(550, root.winfo_screenheight() - 100))}')
    if smoke: root.withdraw()
    steps = (('prepare', '检查目标与选项'), ('install', '安装所选节点／模型'))
    monitor = ProgressPanel(root, steps); monitor.frame.pack(fill='x', padx=12, pady=6)
    canvas = tk.Canvas(root, highlightthickness=0); bar = ttk.Scrollbar(root, command=canvas.yview)
    bar.pack(side='right', fill='y'); canvas.pack(fill='both', expand=True); canvas.configure(yscrollcommand=bar.set)
    frame = ttk.Frame(canvas, padding=18); frame.columnconfigure(1, weight=1)
    win = canvas.create_window((0, 0), window=frame, anchor='nw')
    frame.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(win, width=e.width))
    ttk.Label(frame, text='仅补装本页列出的外部组件，不运行全量部署，不降级Hub或插件。\n新环境请先完成基础部署；已有节点不更新，已有模型校验后复用。', wraplength=850).grid(row=0, column=0, columnspan=3, sticky='w', pady=8)
    ttk.Label(frame, text='本次组件：\n' + '\n'.join('• ' + i['name'] for i in selected), wraplength=850).grid(row=1, column=0, columnspan=3, sticky='w', pady=8)
    fields = {key: tk.StringVar(value=value) for key, value in {'directory':'', 'python':'', 'port':'8188', 'hf':'', 'proxy':''}.items()}
    for row, (key, label) in enumerate([('directory','已有ComfyUI根目录'), ('python','ComfyUI实际Python（装依赖时必需）'), ('port','ComfyUI实际端口'), ('hf','可选Hugging Face镜像HTTPS地址'), ('proxy','可选下载代理URL（仅公开文件）')], 2):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', pady=4)
        ttk.Entry(frame, textvariable=fields[key]).grid(row=row, column=1, sticky='ew')
        if key in {'directory', 'python'}:
            def choose(k=key):
                value = filedialog.askdirectory(parent=root) if k == 'directory' else filedialog.askopenfilename(parent=root)
                if value: fields[k].set(value)
            ttk.Button(frame, text='选择', command=choose).grid(row=row, column=2, padx=5)
    ttk.Label(frame, text='镜像和代理二选一；Git/pip不受此设置控制。量化档只下载模型，不自动切换工作流；显存不是文件大小，请先读“最低/推荐配置与量化取舍”。', wraplength=850).grid(row=7, column=0, columnspan=3, sticky='w', pady=6)
    deps = tk.BooleanVar(value=False); stopped = tk.BooleanVar(value=False); consent = tk.BooleanVar(value=False)
    for row, (variable, text) in enumerate([(deps,'安装所选节点依赖（会改变ComfyUI Python；已有节点也会检查依赖，请先备份环境）'),
        (stopped,'我已正常停止目标ComfyUI，并填写其实际端口；未同时运行另一安装器'),
        (consent,'我已确认所列组件的许可、来源及磁盘空间，允许下载这些组件')], 8):
        ttk.Checkbutton(frame, text=text, variable=variable).grid(row=row, column=0, columnspan=3, sticky='w', pady=4)
    messages = queue.Queue(); state = {'busy':False}
    output = tk.Text(frame, height=12, wrap='word', state='disabled'); output.grid(row=12, column=0, columnspan=3, sticky='ew', pady=8)
    def network():
        hf, proxy = fields['hf'].get().strip(), fields['proxy'].get().strip()
        if hf and proxy: raise ValueError('镜像和代理请二选一。')
        return DownloadNetwork(mode='proxy' if proxy else 'mirror' if hf else 'official', hf_mirror=hf, proxy=proxy)
    def start(apply):
        if state['busy']: return
        try:
            args = (identifier, fields['directory'].get(), fields['python'].get(), deps.get(), network())
            plan = prepare(*args)
            if not apply:
                messagebox.showinfo('只读预检', '路径与清单通过。未下载、未写入；不证明依赖或GPU可用。\n目标：' + str(plan.comfyui_root), parent=root); return
            port = int(fields['port'].get())
            if not consent.get() or not stopped.get(): raise ValueError('请先完成许可及停服确认。')
            if not messagebox.askyesno('仅补装所选扩展', '目标：' + str(plan.comfyui_root) + '\n不更改Hub、插件、工作流或词库。若勾选依赖，会运行所选节点requirements。继续？', parent=root): return
        except Exception as exc: messagebox.showerror('请检查', str(exc), parent=root); return
        state['busy'] = True
        monitor.reset(steps)
        def worker():
            logger = ProgressLog(lambda v: messages.put(('log', v)), lambda e: messages.put(('progress', e)))
            tracker = StageProgress(steps, logger)
            try:
                tracker.stage('prepare'); tracker.stage('install')
                execute(*args, consent=True, stopped=True, port=port, log=logger)
                tracker.finish('completed')
                messages.put(('done', ('completed', '所选组件处理完成。请重启 ComfyUI 并按说明验收。')))
            except Exception as exc:
                tracker.finish('failed')
                messages.put(('done', ('failed', '中断：' + str(exc) + '\n保留文件；先查看当前组件状态。')))
        threading.Thread(target=worker, daemon=True).start()
    buttons = ttk.Frame(frame); buttons.grid(row=11, column=0, columnspan=3, pady=8)
    def hardware_help():
        page = ROOT / 'docs/HARDWARE_AND_QUANTIZATION.md'
        if page.is_file():
            window = tk.Toplevel(root); window.title('配置与量化方案'); window.geometry('850x620')
            from tkinter.scrolledtext import ScrolledText
            text = ScrolledText(window, wrap='word'); text.pack(fill='both', expand=True)
            text.insert('1.0', page.read_text('utf-8-sig')); text.configure(state='disabled')
        else: messagebox.showerror('缺少说明', '请完整解压新版包的docs目录。', parent=root)
    ttk.Button(buttons, text='先看配置与量化说明', command=hardware_help).pack(side='left', padx=5)
    ttk.Button(buttons, text='只做预检', command=lambda: start(False)).pack(side='left', padx=5)
    ttk.Button(buttons, text='确认仅补装扩展', command=lambda: start(True)).pack(side='left', padx=5)
    def close():
        if state['busy']: messagebox.showinfo('正在安装', '请等待当前操作结束，不中断依赖安装。', parent=root)
        else: root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    def poll():
        for _ in range(150):
            if messages.empty(): break
            kind, value = messages.get()
            if kind == 'progress': monitor.update(value); continue
            if kind == 'done':
                state['busy'] = False
                status, message = value; monitor.finish(status, message)
                if status == 'failed': messagebox.showerror('补装失败', message, parent=root)
                else: messagebox.showinfo('补装完成', message, parent=root)
                continue
            monitor.note()
            output.configure(state='normal'); output.insert('end', value + '\n'); output.see('end'); output.configure(state='disabled')
        monitor.render()
        root.after(150, poll)
    if smoke:
        root.update_idletasks(); assert not deps.get() and not consent.get() and not stopped.get()
        root.destroy(); print('PASS: extension-only UI; no deployment, downloads or services'); return 0
    poll(); root.mainloop(); return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--extension', required=True); parser.add_argument('--smoke-test', action='store_true')
    args = parser.parse_args(); raise SystemExit(launch_gui(args.extension, args.smoke_test))
