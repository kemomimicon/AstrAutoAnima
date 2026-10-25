"""Installer stage events, live command output and a Tk progress panel.

No installation decisions depend on progress. Tk is imported only by the view.
"""
from __future__ import annotations

import copy
import queue
import subprocess
import threading
import time


def report(log, **event):
    callback = getattr(log, 'progress', None)
    if callable(callback):
        callback(event)


class ProgressLog:
    def __init__(self, write, progress):
        self.write = write
        self.progress = progress

    def __call__(self, message):
        self.write(str(message))


class StageProgress:
    def __init__(self, steps, log, save=None):
        self.steps = dict(steps)
        self.log, self.save = log, save
        self.data = {'schema': 1, 'status': 'running', 'stage': '', 'completed': [],
                     'states': {name: 'waiting' for name in self.steps}}

    def stage(self, name):
        if name not in self.steps:
            raise ValueError('未知部署阶段')
        previous = self.data['stage']
        if previous and previous != name:
            if self.data['states'][previous] == 'running':
                self.data['states'][previous] = 'done'
            if previous not in self.data['completed']:
                self.data['completed'].append(previous)
        self.data['stage'] = name
        self.data['states'][name] = 'running'
        self.write()
        self.log(f'步骤 {list(self.steps).index(name) + 1}/{len(self.steps)}：{self.steps[name]}')

    def skip(self, reason):
        current = self.data['stage']
        if current:
            self.data['states'][current] = 'skipped'
        self.log('跳过：' + reason)
        self.write()

    def finish(self, status):
        if status not in {'completed', 'needs_attention', 'failed'}:
            raise ValueError('未知部署结果')
        self.data['status'] = status
        current = self.data['stage']
        if current:
            if status == 'failed':
                self.data['states'][current] = 'failed'
            else:
                if self.data['states'][current] == 'running':
                    self.data['states'][current] = 'done'
                if current not in self.data['completed']:
                    self.data['completed'].append(current)
        self.write()

    def attention(self, reason):
        current = self.data['stage']
        if current:
            self.data['states'][current] = 'attention'
        self.log('待处理：' + reason)
        self.write()

    def write(self):
        self.data['updated_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        if self.save:
            self.save(copy.deepcopy(self.data))
        report(self.log, kind='stages', **copy.deepcopy(self.data))


def stream_command(command, log, *, cwd=None, stdin=None, error_type=RuntimeError,
                   heartbeat=15):
    """Drain output in a reader thread so a quiet pip/git command still has a heartbeat."""
    log('执行：' + ' '.join(map(str, command)))
    report(log, kind='activity', name='执行安装命令，等待输出', current=None, total=None)
    started = last_output = time.monotonic()
    with subprocess.Popen(list(map(str, command)), cwd=cwd, stdin=stdin,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding='utf-8', errors='replace',
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as process:
        lines = queue.Queue()
        def read():
            try:
                for line in process.stdout:
                    lines.put(('line', line.rstrip()))
            except Exception:
                lines.put(('error', '无法读取安装命令输出，请检查安装环境。'))
            finally:
                lines.put(('end', None))
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            while True:
                try:
                    kind, value = lines.get(timeout=min(0.5, heartbeat))
                except queue.Empty:
                    now = time.monotonic()
                    if now - last_output >= heartbeat:
                        log(f'安装命令仍在运行，已用时 {int(now - started)} 秒；暂未收到新输出。')
                        last_output = now
                    continue
                if kind == 'end':
                    break
                if kind == 'error':
                    raise error_type(value)
                log(value)
                last_output = time.monotonic()
            code = process.wait()
        except BaseException:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            raise
        finally:
            reader.join(timeout=1)
    if code:
        raise error_type(f'安装命令失败，退出码 {code}。请查看上方输出；保留安装目录，修正后重试。')


class ProgressModel:
    """Presentation state only; does not read runtime credentials or resume work."""
    def __init__(self, steps, clock=time.monotonic):
        self.clock = clock
        self.reset(steps)

    def reset(self, steps):
        self.steps = dict(steps)
        self.states = {k: 'waiting' for k in self.steps}
        self.stage, self.status, self.detail = '', 'idle', '尚未开始'
        self.current = self.total = self.rate = None
        self.started = self.last_output = self.stage_started = self.clock()

    def update(self, event):
        now = self.clock()
        if event['kind'] == 'stages':
            if event['stage'] != self.stage:
                self.stage_started = now
                self.detail = self.steps.get(event['stage'], '准备中')
                self.current = self.total = self.rate = None
            self.stage, self.status = event['stage'], event['status']
            self.states.update(event['states'])
        elif event['kind'] in {'activity', 'transfer'}:
            if 'name' in event:
                self.detail = event['name']
            for key in ('current', 'total', 'rate'):
                if key in event:
                    setattr(self, key, event[key])
        self.last_output = now

    def finish(self, status, detail):
        self.status, self.detail = status, detail
        self.current = self.total = self.rate = None
        if status == 'failed' and self.stage:
            self.states[self.stage] = 'failed'

    @property
    def completed(self):
        return sum(s in {'done', 'skipped', 'attention'} for s in self.states.values())

    @property
    def file_percent(self):
        if self.current is None or not self.total or self.total <= 0:
            return None
        return min(100, max(0, self.current / self.total * 100))


class ProgressPanel:
    LABELS = {'waiting': ('待执行', '#8a8a8a'), 'running': ('进行中', '#2474d2'),
              'done': ('完成', '#258344'), 'skipped': ('跳过', '#767676'),
              'attention': ('待处理', '#9a6500'),
              'failed': ('失败', '#c63232')}

    def __init__(self, parent, steps):
        import tkinter as tk
        from tkinter import ttk
        self.model = ProgressModel(steps)
        self.frame = ttk.LabelFrame(parent, text='安装进度与阶段状态', padding=8)
        self.summary = tk.StringVar(value='尚未开始')
        self.detail = tk.StringVar(value='灰色待执行 · 蓝色进行中 · 绿色完成 · 黄色待处理 · 红色失败')
        self.timing = tk.StringVar(value='阶段进度按完成项计算；下载百分比仅针对当前文件。')
        self.summary_label = ttk.Label(self.frame, textvariable=self.summary, font=('Microsoft YaHei UI', 11, 'bold'))
        self.summary_label.pack(anchor='w')
        self.stage_bar = ttk.Progressbar(self.frame, maximum=100, mode='determinate')
        self.stage_bar.pack(fill='x', pady=3)
        self.lights = ttk.Frame(self.frame); self.lights.pack(fill='x')
        self.light_widgets = {}
        self.activity = ttk.Progressbar(self.frame, maximum=100, mode='indeterminate')
        self.activity.pack(fill='x', pady=3)
        ttk.Label(self.frame, textvariable=self.detail, wraplength=890).pack(anchor='w')
        ttk.Label(self.frame, textvariable=self.timing).pack(anchor='w')
        self.animating = False
        self.reset(steps)

    def reset(self, steps):
        import tkinter as tk
        from tkinter import ttk
        self.model.reset(steps)
        for child in self.lights.winfo_children(): child.destroy()
        self.light_widgets = {}
        for i, (key, title) in enumerate(steps):
            cell = ttk.Frame(self.lights); cell.grid(row=i // 3, column=i % 3, sticky='w', padx=(0, 10))
            light = tk.Canvas(cell, width=14, height=16, highlightthickness=0)
            light.pack(side='left'); dot = light.create_oval(2, 4, 11, 13, fill='#8a8a8a', outline='')
            label = ttk.Label(cell); label.pack(side='left')
            self.light_widgets[key] = (light, dot, label, title)
        self.render()

    def update(self, event):
        self.model.update(event); self.render()

    def note(self):
        self.model.last_output = self.model.clock()

    def finish(self, status, detail):
        self.model.finish(status, detail); self.render()

    def render(self):
        m = self.model
        titles = {'idle': '尚未开始', 'running': '正在执行', 'completed': '完成',
                  'needs_attention': '部署已结束，仍有配置待完成', 'failed': '失败，已停止'}
        self.summary.set(f'{titles.get(m.status, m.status)} · 已处理 {m.completed}/{len(m.steps)} 阶段（含跳过）')
        self.summary_label.configure(foreground={'failed': '#c63232', 'needs_attention': '#9a6500',
                                                'completed': '#258344', 'running': '#2474d2'}.get(m.status, '#555555'))
        self.stage_bar['value'] = m.completed / max(1, len(m.steps)) * 100
        for key, (canvas, dot, label, title) in self.light_widgets.items():
            state, color = self.LABELS[m.states[key]]
            canvas.itemconfigure(dot, fill=color); label.configure(text=f'{title}：{state}')
        percent = m.file_percent if m.status == 'running' else None
        animate = m.status == 'running' and percent is None
        if animate != self.animating:
            self.activity.stop()
            self.activity.configure(mode='indeterminate' if animate else 'determinate')
            if animate: self.activity.start(35)
            self.animating = animate
        if not animate: self.activity['value'] = percent if percent is not None else 0
        detail = m.detail
        if m.current is not None:
            detail += f' · {m.current / 1024**2:.1f} MiB'
            if m.total: detail += f' / {m.total / 1024**2:.1f} MiB（{percent if percent is not None else m.file_percent:.1f}%）'
            if m.rate is not None: detail += f' · {m.rate / 1024:.0f} KiB/s'
        self.detail.set(detail)
        if m.status == 'running':
            now = m.clock()
            self.timing.set(f'总用时 {int(now-m.started)} 秒 · 当前阶段 {int(now-m.stage_started)} 秒 · 距最近输出 {int(now-m.last_output)} 秒；无输出时请查看当前阶段与日志。')
