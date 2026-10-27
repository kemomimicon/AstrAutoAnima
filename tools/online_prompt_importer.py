"""Explicit text-only import to a compatible Hub; no overwrite, no saved credentials."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
import queue
import re
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from first_run_checks import NoRedirect
from first_run_config import validate_url

MAX_FILE = 16 * 1024 * 1024
MAX_PROMPTS = 10000
MAX_BATCH_PROMPTS = 100000
MAX_BATCH_BYTES = 64 * 1024 * 1024


class ImportFailure(ValueError):
    pass


def checked_token(value):
    # Reject malformed headers without allowing an encoding error to echo the credential.
    if not isinstance(value, str): raise ValueError('请填写合法的Hub管理员令牌。')
    token = value.strip()
    if not re.fullmatch(r'[!-~]{1,4096}', token): raise ValueError('请粘贴完整Hub令牌，不要加入中文、空格或控制字符。')
    return token


def parse_file(path, *, max_prompts=MAX_PROMPTS):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_FILE: raise ValueError('请选择不超过16MiB的JSON/CSV/TXT文件。')
    with path.open('rb') as stream: raw = stream.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE: raise ValueError('文件超过大小限制。')
    for encoding in ('utf-8-sig', 'gb18030'):
        try: text = raw.decode(encoding); break
        except UnicodeDecodeError: pass
    else: raise ValueError('文件编码无法识别，请另存为UTF-8。')
    if path.suffix.lower() == '.json':
        data = json.loads(text)
        if isinstance(data, dict): data = data.get('prompts', data.get('items'))
        if not isinstance(data, list): raise ValueError('JSON需为列表，或包含prompts/items列表。')
        values = []
        for item in data:
            if isinstance(item, dict): item = item.get('prompt', item.get('tags', item.get('text')))
            if not isinstance(item, str): raise ValueError('每条提示词必须是文本；不导入对象、数字、图片或脚本。')
            values.append(item)
    elif path.suffix.lower() == '.csv':
        reader = csv.DictReader(io.StringIO(text))
        field = next((k for k in reader.fieldnames or [] if k.strip().casefold() in {'prompt', 'tags', 'text', '提示词'}), None)
        if not field: raise ValueError('CSV需要prompt/tags/text/提示词表头。')
        values = [row.get(field) or '' for row in reader]
    elif path.suffix.lower() == '.txt': values = text.splitlines()
    else: raise ValueError('仅支持JSON/CSV/TXT。')
    prompts, seen = [], set()
    for value in values:
        value = value.strip()
        if not value or value.startswith('#'): continue
        if len(value) > 20000 or '\0' in value: raise ValueError('单条提示词过长或包含NUL字符。')
        marker = ' '.join(value.casefold().split())
        if marker not in seen: seen.add(marker); prompts.append(value)
        if len(prompts) > max_prompts: raise ValueError(f'去重后超过{max_prompts}条，请分文件导入。')
    if not prompts: raise ValueError('未找到可导入的非空文本。')
    return prompts


def parse_files(paths):
    """Validate the entire selection before exposing any submit-ready preview."""
    paths = [Path(p) for p in paths]
    if not 1 <= len(paths) <= 64:
        raise ValueError('请选择1至64个JSON/CSV/TXT文件。')
    if sum(p.stat().st_size for p in paths) > MAX_BATCH_BYTES:
        raise ValueError('本批文件合计超过64MiB，请拆分导入。')
    prompts, seen, files = [], set(), []
    for path in paths:
        try:
            values = parse_file(path, max_prompts=MAX_BATCH_PROMPTS)
        except (ValueError, OSError) as exc:
            raise ValueError(f'文件 {path.name} 读取失败：{exc}') from None
        added = 0
        for value in values:
            marker = ' '.join(value.casefold().split())
            if marker not in seen:
                seen.add(marker); prompts.append(value); added += 1
            if len(prompts) > MAX_BATCH_PROMPTS:
                raise ValueError('本批去重后超过100000条，请拆分导入。')
        files.append({'name': path.name, 'unique_in_file': len(values),
                      'added_to_batch': added, 'duplicates_in_batch': len(values) - added})
    return prompts, files


def dropped_files(environ):
    """CMD transports each dropped path as data, not expanded shell code."""
    count = environ.get('AAA_IMPORT_COUNT', '0')
    if not count.isdecimal() or not 0 <= int(count) <= 64:
        raise ValueError('拖入文件数量无效，最多64个。')
    paths = [environ.get(f'AAA_IMPORT_FILE_{i}', '') for i in range(1, int(count) + 1)]
    if any(not p or '\0' in p for p in paths):
        raise ValueError('拖入文件路径无效。')
    return paths


def hub_url(value):
    base = validate_url(value); parsed = urlsplit(base)
    if parsed.scheme != 'https' and parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
        raise ValueError('远程Hub必须HTTPS；HTTP仅限本机。')
    return base


def request(base, token, method, route, payload=None, revision=None):
    allowed = {('GET', '/api/v1/prompts/groups'), ('PUT', '/api/v1/prompts/groups'),
               ('GET', '/api/v1/prompts?page=1&page_size=1'), ('POST', '/api/v1/prompts/import')}
    if (method, route) not in allowed: raise ValueError('接口不在导入器允许范围内。')
    headers = {'Authorization': 'Bearer ' + checked_token(token), 'Accept': 'application/json'}
    if revision is not None:
        if not isinstance(revision, str) or not revision or any(c in revision for c in '\r\n\0'): raise ValueError('服务返回的版本标记无效。')
        headers['If-Match'] = revision
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    if body is not None: headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(hub_url(base) + route, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=40) as response: raw = response.read(4 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        hints = {401:'管理令牌无效', 403:'没有管理员权限', 404:'缺少新版分组/导入接口，请升级匹配的Hub或使用离线编辑器',
                 409:'并发版本冲突，未自动覆盖，请刷新后重新核对', 422:'服务器拒绝数据格式'}
        raise ImportFailure(f'HTTP {exc.code}：' + hints.get(exc.code, '请求被拒绝，停止；不跟随重定向')) from None
    except (OSError, urllib.error.URLError):
        raise ImportFailure('网络未返回确定结果；当前写入可能已完成，请先在Hub核对，不自动重试。') from None
    try:
        if len(raw) > 4 * 1024 * 1024: raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, dict): raise ValueError()
        return data
    except (ValueError, UnicodeError): raise ImportFailure('响应格式无效，写入结果需在Hub核对；不输出原始响应。') from None


def sync(base, token, group_id, name, allow_private, source, safety, prompts, *, consent=False, progress=lambda text: None):
    if not consent: raise ValueError('未确认同步，服务器不会被修改。')
    base = hub_url(base)
    token = checked_token(token)
    if not re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}', group_id): raise ValueError('组ID应为小写字母、数字、下划线或短横线，最长64位。')
    if not name.strip() or len(name) > 100 or type(allow_private) is not bool: raise ValueError('请核对显示名和私聊权限。')
    if source not in {'B', 'G', 'D', 'C', 'R'} or safety not in {'N', 'H', 'S'}: raise ValueError('来源或安全分级不合法。')
    if not isinstance(prompts, list) or not 1 <= len(prompts) <= MAX_BATCH_PROMPTS or any(not isinstance(p, str) or not p.strip() or len(p) > 20000 or '\0' in p for p in prompts):
        raise ValueError('提示词数量或文本不合法。')
    registry = request(base, token, 'GET', '/api/v1/prompts/groups')
    groups = registry.get('groups')
    if not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get('id'), str) for g in groups):
        raise ValueError('分组接口格式不兼容，未写入。')
    if len({g['id'] for g in groups}) != len(groups): raise ValueError('服务器分组ID重复，停止写入。')
    if any(set(g) - {'id', 'name', 'allow_private', 'allow_group', 'enabled', 'safety_codes'} for g in groups):
        raise ValueError('服务器分组含本工具未知字段，不能安全重写分组清单；请使用对应新版管理端。')
    for group in groups:
        if any(k in group and type(group[k]) is not bool for k in ('allow_private', 'allow_group', 'enabled')):
            raise ValueError('服务器分组权限格式无效，未写入。')
        if 'safety_codes' in group and (not isinstance(group['safety_codes'], list)
                or not group['safety_codes'] or any(v not in {'N', 'H', 'S'} for v in group['safety_codes'])):
            raise ValueError('服务器分组内容级别无效，未写入。')
    existing = next((g for g in groups if g['id'] == group_id), None)
    desired = {'id': group_id, 'name': name.strip(), 'allow_private': allow_private}
    if existing and any(existing.get(k) != v for k, v in desired.items()):
        raise ValueError('该组已有不同名称或私聊权限；请在管理端核对，不在导入时覆盖权限。')
    imported, batches = 0, 0
    try:
        if existing is None:
            revision = registry.get('revision')
            if not isinstance(revision, str) or not revision: raise ValueError('分组接口缺少版本标记，未写入。')
            request(base, token, 'PUT', '/api/v1/prompts/groups', {'groups': groups + [desired]}, revision)
            progress('分组已登记。后续批次失败时该分组仍保留，不自动回滚。')
        for start in range(0, len(prompts), 500):
            batch = prompts[start:start + 500]
            current = request(base, token, 'GET', '/api/v1/prompts?page=1&page_size=1')
            revision = current.get('revision')
            if not isinstance(revision, str) or not revision: raise ValueError('词库接口缺少版本标记。')
            result = request(base, token, 'POST', '/api/v1/prompts/import', {'prompts': [
                {'prompt': p, 'name': p[:80], 'source_code': source, 'safety_code': safety, 'custom_groups': [group_id]} for p in batch]}, revision)
            count = result.get('count')
            if type(count) is not int or not 0 <= count <= len(batch): raise ValueError('返回计数异常，须在管理端核对。')
            imported += count; batches += 1
            progress(f'已确认完成 {batches} 批；新增 {imported} 条。')
    except (ValueError, OSError) as exc:
        raise ImportFailure(f'同步未全部完成：已确认 {batches} 批、新增 {imported} 条。已登记组和已导入记录保留。\n{exc}\n不要删除整库；当前批次结果不确定时先核对，再人工决定是否重试。') from None
    return imported, len(prompts) - imported


def launch_gui(smoke=False, paths=()):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    window = tk.Tk(); window.title('AAA · 多文件词库批量导入')
    window.geometry(f'880x{min(770, max(520, window.winfo_screenheight() - 100))}'); window.minsize(850, 520)
    if smoke: window.withdraw()
    canvas = tk.Canvas(window, highlightthickness=0)
    scrollbar = ttk.Scrollbar(window, orient='vertical', command=canvas.yview)
    scrollbar.pack(side='right', fill='y'); canvas.pack(side='left', fill='both', expand=True)
    canvas.configure(yscrollcommand=scrollbar.set)
    frame = ttk.Frame(canvas, padding=16); frame.columnconfigure(1, weight=1)
    canvas_window = canvas.create_window((0, 0), window=frame, anchor='nw')
    frame.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(canvas_window, width=e.width))
    ttk.Label(frame, text='可将多个文件拖到启动CMD，或点下方按钮多选文件。先预览，确认后每500条导入；Hub自动备份。\n本工具提取提示词正文，统一采用下方来源/分级/自定义组；JSON原有分类、ID、分级不沿用。原库记录保留，令牌不保存。', wraplength=790).grid(row=0, column=0, columnspan=2, sticky='w', pady=10)
    defaults = {'url':'http://127.0.0.1:6278', 'token':'', 'id':'batch_import', 'name':'批量导入'}
    fields = {k: tk.StringVar(value=v) for k, v in defaults.items()}
    for row, (key, label) in enumerate([('url','Hub根地址'), ('token','Hub管理员令牌'), ('id','自定义组ID'), ('name','组显示名')], 1):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', pady=6)
        ttk.Entry(frame, textvariable=fields[key], show='●' if key == 'token' else '').grid(row=row, column=1, sticky='ew')
    private = tk.BooleanVar(value=False); source = tk.StringVar(value='B'); safety = tk.StringVar(value='N'); reviewed = tk.BooleanVar(value=False)
    ttk.Checkbutton(frame, text='允许在私聊抽取这个组（默认不允许）', variable=private).grid(row=5, column=0, columnspan=2, sticky='w')
    options = ttk.Frame(frame); options.grid(row=6, column=0, columnspan=2, sticky='w', pady=8)
    ttk.Label(options, text='来源').pack(side='left'); ttk.Combobox(options, textvariable=source, values=['B','G','D','C','R'], state='readonly', width=8).pack(side='left')
    ttk.Label(options, text='人工安全分级').pack(side='left', padx=8); ttk.Combobox(options, textvariable=safety, values=['N','H','S'], state='readonly', width=8).pack(side='left')
    preview = tk.Text(frame, height=12, wrap='word', state='disabled'); preview.grid(row=7, column=0, columnspan=2, sticky='nsew', pady=8); frame.rowconfigure(7, weight=1)
    status = tk.StringVar(value='尚未读取文件。'); state = {'prompts': [], 'busy': False}; messages = queue.Queue()
    def load_selection(paths):
        try:
            prompts, files = parse_files(paths)
            state['prompts'] = prompts; reviewed.set(False)
            summary = '\n'.join(f'{r["name"]}：文件内去重后{r["unique_in_file"]}条，加入本批{r["added_to_batch"]}条，跨文件重复{r["duplicates_in_batch"]}条' for r in files)
            preview.configure(state='normal'); preview.delete('1.0', 'end'); preview.insert('1.0', summary + '\n\n=== 提示词预览（最多20条） ===\n\n' + '\n\n'.join(prompts[:20])); preview.configure(state='disabled')
            status.set(f'已读取{len(files)}个文件，本批去重后{len(prompts)}条；尚未写入服务器。')
        except Exception as exc:
            state['prompts'] = []; reviewed.set(False)
            preview.configure(state='normal'); preview.delete('1.0', 'end'); preview.configure(state='disabled')
            status.set('读取失败，本批文件均未提交；请修正后重新选择。'); messagebox.showerror('读取失败', str(exc), parent=window)
    def choose():
        if state['busy']: return
        chosen = filedialog.askopenfilenames(parent=window, filetypes=[('词库文本', '*.json *.csv *.txt')])
        if chosen: load_selection(chosen)
    ttk.Button(frame, text='多选 JSON / CSV / TXT 并预览', command=choose).grid(row=8, column=0, columnspan=2, sticky='w')
    ttk.Checkbutton(frame, text='我已审核完整源文件，并确认本次统一来源与N/H/S分级（不是只看前20条）', variable=reviewed).grid(row=9, column=0, columnspan=2, sticky='w', pady=8)
    def submit():
        if state['busy']: return
        if not state['prompts'] or not reviewed.get(): messagebox.showinfo('先审核', '先读取文件并审核完整内容及分级。', parent=window); return
        try: base = hub_url(fields['url'].get())
        except ValueError as exc: messagebox.showerror('地址错误', str(exc), parent=window); return
        args = (base, fields['token'].get(), fields['id'].get(), fields['name'].get(), private.get(), source.get(), safety.get(), list(state['prompts']))
        if not messagebox.askyesno('确认服务器写入', f'向 {base} 登记组 {args[2]} 并导入 {len(args[-1])} 条。\n所有条目统一使用来源 {args[5]} / 分级 {args[6]}；不会保留文件中的旧分级。\n不覆盖已有组权限；失败可能已完成部分批次。确认已备份词库并继续？', parent=window): return
        state['busy'] = True; button.configure(state='disabled')
        def worker():
            try: messages.put(('done', sync(*args, consent=True, progress=lambda s: messages.put(('progress', s)))))
            except Exception as exc: messages.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()
    button = ttk.Button(frame, text='确认并同步（此时才联网）', command=submit); button.grid(row=10, column=0, columnspan=2, sticky='e', pady=8)
    ttk.Label(frame, textvariable=status, wraplength=790, justify='left').grid(row=11, column=0, columnspan=2, sticky='w')
    def poll():
        while not messages.empty():
            kind, value = messages.get()
            if kind == 'progress': status.set(value); continue
            state['busy'] = False; button.configure(state='normal'); reviewed.set(False)
            status.set(value if kind == 'error' else f'同步完成：新增{value[0]}条，跳过{value[1]}条。请到管理端抽查；未发送任何图片。')
        window.after(100, poll)
    def close():
        if state['busy']: messagebox.showinfo('正在同步', '请等待结果，避免不知道哪些批次已写入。', parent=window); return
        fields['token'].set(''); window.destroy()
    window.protocol('WM_DELETE_WINDOW', close); window.after(100, poll)
    if smoke:
        window.update_idletasks(); assert not reviewed.get() and not state['prompts'] and not fields['token'].get()
        window.destroy(); print('PASS: online importer offline UI smoke'); return 0
    if paths: window.after_idle(lambda: load_selection(paths))
    window.mainloop(); return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--files-from-env', action='store_true'); parser.add_argument('files', nargs='*')
    args = parser.parse_args()
    raise SystemExit(launch_gui(args.smoke_test, dropped_files(os.environ) if args.files_from_env else args.files))
