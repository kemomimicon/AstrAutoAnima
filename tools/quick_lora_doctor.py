"""Read-only Quick/LoRA diagnosis. Never import the user's plugin or submit jobs."""
from __future__ import annotations
import argparse
import ast
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import tokenize

VERSION = '1.0-candidate.1'
PLUGIN = 'astrbot_plugin_comfy_bridge'
OLD_ERROR = '未配置用于定位基础 MODEL/CLIP 的画风 LoRA 节点。'
LIMIT = 8 * 1024**2


class CheckError(ValueError): pass


def read(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > LIMIT:
        raise CheckError('文件缺失或超过读取限制：' + path.name)
    return path.read_bytes()


def document(path):
    try:
        result = json.loads(read(path))
    except (ValueError, UnicodeError):
        raise CheckError('JSON 格式或编码异常：' + Path(path).name) from None
    if not isinstance(result, dict): raise CheckError('需要 JSON 对象：' + Path(path).name)
    return result


def candidates(directory):
    root = Path(directory).absolute()
    options = [root, root / 'data/plugins' / PLUGIN, root / 'plugins' / PLUGIN,
               root / 'astrbot/data/plugins' / PLUGIN]
    # Managed installations explicitly record AstrBot's runtime cwd. Do not read runtime-env.json.
    service_file = root / 'services.json'
    if service_file.is_file():
        try:
            services = json.loads(read(service_file))
            if isinstance(services, list):
                for item in services:
                    if isinstance(item, dict) and item.get('name') == 'AstrBot' and isinstance(item.get('cwd'), str):
                        cwd = Path(item['cwd'])
                        if cwd.is_absolute(): options.append(cwd / 'data/plugins' / PLUGIN)
        except (CheckError, ValueError, UnicodeError): pass
    found = []
    for path in options:
        if (path / 'preset_runtime.py').is_file() and path not in found: found.append(path)
    return found


@dataclass
class Finding:
    level: str
    title: str
    detail: str


def patch_state(path):
    raw = read(path)
    try:
        import io
        codec, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
        tree = ast.parse(raw.decode(codec))
    except (SyntaxError, UnicodeError, LookupError):
        raise CheckError('插件源码语法／编码异常；未导入或执行该源码：' + Path(path).name) from None
    functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    apply = functions.get('apply_lora_plan')
    calls = set() if apply is None else {n.func.id for n in ast.walk(apply) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    old = any(isinstance(n, ast.Raise) and n.exc is not None and any(
        isinstance(c, ast.Constant) and c.value == OLD_ERROR for c in ast.walk(n.exc)) for n in ast.walk(tree))
    fixed = '_slotless_style_sources' in functions and '_slotless_style_sources' in calls
    fixed = fixed or hashlib.sha256(raw).hexdigest() == 'ae242543f1c7899de39fde10225d61d1595f1df1be9f159224487ca67fea2f23'
    return ('fixed' if fixed and not old else 'old' if old else 'unknown'), hashlib.sha256(raw).hexdigest()


def graph_findings(workflow, config):
    if not workflow or 'nodes' in workflow or not all(isinstance(v, dict) and isinstance(v.get('class_type'), str) for v in workflow.values()):
        return [Finding('FAIL', '工作流格式', '需要 Save (API Format) 导出的 API 工作流，不能用含 nodes 的编辑器格式。')]
    result = []
    loras = [k for k, v in workflow.items() if 'lora' in v['class_type'].lower()]
    mode = str(config.get('style_lora_mode', 'dynamic')).strip().lower()
    raw_slots = config.get('style_lora_node_ids', '46,47,48,49')
    if not isinstance(raw_slots, str):
        return [Finding('FAIL', '槽位配置', '画风槽位应为逗号分隔的节点 ID 字符串，请在 AAA 插件设置中核对。')]
    slots = [s.strip() for s in raw_slots.split(',') if s.strip()]
    result.append(Finding('INFO', '工作流概况', f'节点 {len(workflow)} 个；LoRA 节点 {len(loras)} 个；加载模式 {mode if mode in {"dynamic", "fixed"} else "无法识别"}；配置槽位 {len(slots)} 个。'))
    if mode not in {'fixed', 'dynamic'}:
        return result + [Finding('FAIL', '画风加载模式', '应在 AAA 插件设置中选择 fixed 或 dynamic。')]
    present = [s for s in slots if s in workflow]
    if mode == 'fixed' and not slots:
        return result + [Finding('FAIL', '固定槽位缺失', 'fixed 模式需要真实 LoraLoader 槽位；无 LoRA 的 Quick 应改为 dynamic，槽位留空。')]
    if (mode == 'fixed' or present) and len(present) != len(slots):
        return result + [Finding('FAIL', '槽位与工作流不一致', '配置的槽位只有部分存在或全部不存在，请按当前 API 工作流核对，不能猜填 46–49。')]
    if present:
        if any(workflow[s]['class_type'] != 'LoraLoader' for s in present):
            return result + [Finding('FAIL', '槽位类型不匹配', '插件槽位要求标准 LoraLoader；LoRA 堆等自定义节点不能直接冒充标准槽位。')]
        return result + [Finding('PASS', '真实槽位', '配置槽位存在且为标准 LoraLoader。此项未验证 LoRA 文件或 GPU 运行。')]
    if loras:
        return result + [Finding('FAIL', '未登记的 LoRA 节点', '工作流有 LoRA 节点却未配置对应槽位，请填写真实标准槽位 ID；自定义堆需另行适配。')]
    if slots:
        result.append(Finding('WARN', '遗留槽位编号', '无 LoRA 图中配置的编号均不存在；热修允许此情况，建议在 dynamic 下清空旧槽位。'))
    def inputs(key, default):
        node = workflow.get(str(config.get(key, default)).strip(), {})
        value = node.get('inputs')
        if not isinstance(value, dict): raise CheckError('找不到配置的采样器／提示词节点，请核对实际节点 ID。')
        return value
    try:
        model = inputs('sampler_node_id', '19').get('model')
        clip = inputs('positive_prompt_node_id', '11').get('clip')
        for value in (model, clip):
            if not (isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] in workflow and type(value[1]) is int and value[1] >= 0):
                raise CheckError('采样器 MODEL 或正向 CLIP 接线无效，不能安全定位基础模型。')
        negative = str(config.get('negative_prompt_node_id', '12')).strip()
        if negative and inputs('negative_prompt_node_id', '12').get('clip') != clip:
            raise CheckError('正负提示词的 CLIP 接线不一致，请先核对工作流。')
    except CheckError as exc:
        return result + [Finding('FAIL', '基础接线', str(exc))]
    return result + [Finding('PASS', '无槽位动态画风', '采样器 MODEL 和正向／负向 CLIP 接线可定位。无 LoRA 的 Quick 可继续使用；dynamic 模式槽位留空，不需要增加 46–49。')]


def process_clues(plugin):
    if os.name != 'nt': return [Finding('WARN', '运行实例', '此版本只在 Windows 提供进程线索。')]
    # Keep command lines inside PowerShell: output only PID, executable and start time.
    script = """[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$r = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='astrbot.exe' OR Name='astrbot-desktop-tauri.exe'" -ErrorAction Stop | Where-Object { $_.Name -like 'astrbot*' -or $_.CommandLine -match '(?i)astrbot' } | ForEach-Object { [PSCustomObject]@{pid=$_.ProcessId; exe=$_.ExecutablePath} })
ConvertTo-Json -InputObject $r -Compress
"""
    try:
        completed = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
            capture_output=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if completed.returncode or len(completed.stdout) > 128 * 1024: raise ValueError()
        rows = json.loads(completed.stdout.decode('utf-8-sig'))
        if not isinstance(rows, list): raise ValueError()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return [Finding('WARN', '运行实例', '无法读取本机进程线索；不影响磁盘检查。请在 AstrBot 中确认实际数据目录。')]
    if not rows:
        return [Finding('INFO', '运行实例', '未发现可识别的 AstrBot 进程。磁盘通过不代表运行时已加载补丁。')]
    clues = []
    for row in rows[:12]:
        if not isinstance(row, dict) or type(row.get('pid')) is not int: continue
        exe = row.get('exe')
        if isinstance(exe, str) and len(exe) < 1000:
            clues.append(f'PID {row["pid"]}：{exe}')
    return [Finding('WARN', '运行实例线索', '\n'.join(clues) + '\n进程路径只是线索，不能证明其数据目录或模块已加载。文件有热修但仍报同一句错误时，先保存任务结果，完整退出并重启对应 AstrBot，再检查是否更新错实例。')]


def diagnose(plugin, workflow_override='', processes=False, notify=lambda s: None):
    plugin = Path(plugin).absolute()
    rows = []
    def add(level, title, detail): rows.append(Finding(level, title, detail))
    notify('检查插件文件与补丁…')
    add('INFO', '所选插件目录', str(plugin))
    try:
        state, digest = patch_state(plugin / 'preset_runtime.py')
        add('INFO', '模块 SHA256', digest)
        metadata = plugin / 'metadata.yaml'
        if metadata.is_file():
            match = re.search(rb'^version:\s*[\"\']?([0-9A-Za-z._+-]{1,90})', read(metadata), re.M)
            add('INFO', '磁盘版本', match[1].decode('ascii') if match else '未识别。单文件热修不会改变版本显示。')
        if state == 'old':
            add('FAIL', '发现旧版报错分支', '磁盘模块仍含“未配置用于定位基础 MODEL/CLIP”的旧异常。无槽位 Quick 选画风会触发；应更新当前实例的 AAA 插件代码，不是只更新 App 或 Hub。')
        elif state == 'fixed':
            add('PASS', '磁盘包含 Quick 热修分支', '发现无槽位 MODEL/CLIP 定位函数及实际调用，未发现旧异常。此结论仅针对磁盘，不证明 AstrBot 当前进程已重载。')
        else:
            add('WARN', '补丁状态无法归类', '源码可解析，但不符合本工具识别的旧／新分支。可能是其他版本或自定义修改，不建议盲目覆盖。')
    except (CheckError, OSError) as exc:
        add('FAIL', '插件文件检查', str(exc) if isinstance(exc, CheckError) else '无法读取插件文件，请检查所选目录。')
    notify('定位配置与 API 工作流…')
    config_path = plugin.parent.parent / 'config' / (PLUGIN + '_config.json')
    config = None
    try:
        config = document(config_path)
        add('INFO', '配置位置', str(config_path))
    except (CheckError, OSError):
        add('WARN', '未找到标准位置的插件配置', '可手选当前 API 工作流检测结构。若工作流在其他实例／容器内，请在对应机器运行工具；不要新建空配置。')
    flow_name = workflow_override or (config or {}).get('workflow_path', '')
    if isinstance(flow_name, str) and flow_name.strip():
        flow = Path(flow_name)
        if not flow.is_absolute(): flow = plugin / flow
        add('INFO', '本次读取工作流', str(flow))
        try:
            result = graph_findings(document(flow), config or {'style_lora_mode': 'dynamic', 'style_lora_node_ids': ''})
            rows.extend(result)
            if config is None: add('WARN', '仅结构检查', '未读取真实配置，上面仅按 dynamic 无槽位结构检查；请另核对实际加载模式及节点 ID。')
        except (CheckError, OSError) as exc:
            add('FAIL', '读取工作流', str(exc) if isinstance(exc, CheckError) else '无法读取工作流文件，请手动选择当前 API JSON。')
    else:
        add('WARN', '缺少工作流路径', '请选择 AAA 插件实际使用的 API 工作流，再检测。')
    if processes:
        notify('读取本机 AstrBot 进程线索（最多等待 15 秒）…')
        rows.extend(process_clues(plugin))
    notify('整理下一步操作…')
    add('INFO', '处理顺序', '① 磁盘仍是旧分支：备份实际插件目录，停 AstrBot，按相同版本补丁更新代码，再启动。\n② 磁盘有热修但配置不匹配：在 AAA 插件中修正加载模式、真实槽位及节点 ID。\n③ 磁盘与配置都通过但旧错误仍在：完整退出并重启 AstrBot，确认没有另一套实例。\n④ 先选一个已安装画风、不选角色测试一张；再加角色。\n0.5.1/0.5.2 或自改源码不要拿 0.5.0 公开补丁覆盖。工具不更新代码，也不提交生图。')
    return rows


def format_report(rows):
    return ('AAA Quick / LoRA 检测引导 ' + VERSION + '\n只读检查；未修改配置、模型、词库、密钥或插件。\n磁盘检查不等于运行模块或 GPU 出图验收。\n\n' +
            '\n\n'.join(f'[{r.level}] {r.title}\n{r.detail}' for r in rows))


def gui(smoke=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk(); root.title('AAA Quick / LoRA 检测引导 · ' + VERSION); root.geometry('990x750')
    if smoke: root.withdraw()
    frame = ttk.Frame(root, padding=14); frame.pack(fill='both', expand=True); frame.columnconfigure(1, weight=1)
    ttk.Label(frame, text='检查“未配置用于定位基础 MODEL/CLIP”的原因', font=('Microsoft YaHei UI', 14, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
    ttk.Label(frame, text='选择真实安装目录或 AAA 插件目录。只读，不导入用户插件、不自动下载或修复。\n支持懒人包目录、AstrBot 数据目录和插件目录；多个候选时请手动选实际运行的一份。').grid(row=1, column=0, columnspan=3, sticky='w', pady=8)
    directory = tk.StringVar(); selected = tk.StringVar(); flow = tk.StringVar(); status = tk.StringVar(value='先选择目录，再点“开始只读检测”。')
    processes = tk.BooleanVar(value=True); state = {'busy': False, 'rows': []}; messages = queue.Queue()
    ttk.Label(frame, text='安装／数据目录').grid(row=2, column=0, sticky='w')
    ttk.Entry(frame, textvariable=directory).grid(row=2, column=1, sticky='ew')
    choices = ttk.Combobox(frame, textvariable=selected, state='readonly', width=90); choices.grid(row=3, column=1, columnspan=2, sticky='ew', pady=6)
    ttk.Label(frame, text='实际插件候选').grid(row=3, column=0, sticky='w')
    def scan(value=None):
        if state['busy']: return
        if value is None: value = filedialog.askdirectory(parent=root, title='选择安装目录、AstrBot 数据目录或 AAA 插件目录')
        if not value: return
        directory.set(value)
        try: found = candidates(value)
        except OSError: found = []
        choices['values'] = [str(p) for p in found]; selected.set(str(found[0]) if len(found) == 1 else '')
        status.set('找到 ' + str(len(found)) + ' 份候选；' + ('请选择实际运行的一份。' if len(found) > 1 else '未找到时请直接选含 preset_runtime.py 的插件目录。' if not found else '可以开始检测。'))
    ttk.Button(frame, text='浏览…', command=scan).grid(row=2, column=2, padx=5)
    ttk.Label(frame, text='API 工作流（可选）').grid(row=4, column=0, sticky='w')
    ttk.Entry(frame, textvariable=flow).grid(row=4, column=1, sticky='ew')
    def choose_flow():
        if state['busy']: return
        value = filedialog.askopenfilename(parent=root, filetypes=[('API 工作流', '*.json')])
        if value: flow.set(value)
    ttk.Button(frame, text='选择 JSON', command=choose_flow).grid(row=4, column=2, padx=5)
    ttk.Checkbutton(frame, text='读取本机 AstrBot 进程线索（不输出命令行、不结束进程）', variable=processes).grid(row=5, column=0, columnspan=3, sticky='w', pady=6)
    actions = ttk.Frame(frame); actions.grid(row=6, column=0, columnspan=3, sticky='w')
    ttk.Label(frame, textvariable=status, wraplength=940).grid(row=7, column=0, columnspan=3, sticky='w', pady=8)
    output = tk.Text(frame, wrap='word', state='disabled'); output.grid(row=8, column=0, columnspan=3, sticky='nsew'); frame.rowconfigure(8, weight=1)
    scroll = ttk.Scrollbar(frame, command=output.yview); scroll.grid(row=8, column=3, sticky='ns'); output.configure(yscrollcommand=scroll.set)
    output.tag_configure('FAIL', foreground='#b52626'); output.tag_configure('WARN', foreground='#946200'); output.tag_configure('PASS', foreground='#267c40')
    def start():
        if state['busy']: return
        if not selected.get(): messagebox.showinfo('先选择插件', '选择目录后，在候选列表中选实际运行的 AAA 插件。', parent=root); return
        args = (selected.get(), flow.get().strip(), processes.get())
        state['busy'] = True; status.set('正在只读检测…')
        def worker():
            try: messages.put(('done', diagnose(*args, notify=lambda s: messages.put(('status', s)))))
            except Exception: messages.put(('error', '检测未完成，请检查文件访问权限；没有修改任何文件。'))
        threading.Thread(target=worker, daemon=True).start()
    def save():
        if state['busy'] or not state['rows']: return
        path = filedialog.asksaveasfilename(parent=root, defaultextension='.txt', initialfile='AAA_Quick_LoRA_检测报告.txt')
        if path: Path(path).write_text(format_report(state['rows']), encoding='utf-8-sig')
    ttk.Button(actions, text='检测桌面版默认目录', command=lambda: scan(str(Path.home() / '.astrbot'))).pack(side='left', padx=4)
    ttk.Button(actions, text='重新查找填写的目录', command=lambda: scan(directory.get())).pack(side='left', padx=4)
    ttk.Button(actions, text='开始只读检测', command=start).pack(side='left', padx=4)
    ttk.Button(actions, text='导出检测报告', command=save).pack(side='left', padx=4)
    def poll():
        while not messages.empty():
            kind, value = messages.get()
            if kind == 'status': status.set(value); continue
            state['busy'] = False
            if kind == 'error': status.set(value); continue
            state['rows'] = value; output.configure(state='normal'); output.delete('1.0', 'end')
            for row in value: output.insert('end', f'[{row.level}] {row.title}\n{row.detail}\n\n', row.level)
            output.configure(state='disabled')
            status.set(f'检查结束：{sum(r.level=="FAIL" for r in value)} 项异常、{sum(r.level=="WARN" for r in value)} 项待核对。请按报告最后的操作顺序处理。未提交生图。')
        root.after(100, poll)
    def close():
        if state['busy']: messagebox.showinfo('正在检测', '请等待文件／进程检查结束。', parent=root)
        else: root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    if smoke:
        root.update_idletasks(); assert not state['busy'] and not state['rows']; root.destroy(); return 0
    poll(); root.mainloop(); return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--check', type=Path, help='Read-only explicit plugin path; prints a filtered report')
    parser.add_argument('--workflow', default='')
    args = parser.parse_args()
    if args.check:
        rows = diagnose(args.check, args.workflow); print(format_report(rows))
        return 1 if any(r.level == 'FAIL' for r in rows) else 0
    return gui(args.smoke_test)


if __name__ == '__main__': raise SystemExit(main())
