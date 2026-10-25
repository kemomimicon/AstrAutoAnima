"""Offline Windows managed-install relocation. Never removes the source or starts services."""
from __future__ import annotations

import argparse
import ast
import copy
from dataclasses import dataclass
import hashlib
import io
import json
import locale
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import tokenize

VERSION = '1.0-candidate.3'
DEFAULT_TARGET = r'D:\QQ-comfyui'
MARKER = '.aaa-managed-install'
ENV_PATHS = {
    'AAH_PLUGIN_DIR', 'AAH_PLUGIN_DATA_DIR', 'AAH_COMFYUI_ROOT', 'AAH_WEB_ROOT',
    'AAH_PROMPT_POOL_PATH', 'AAH_KP_PROMPT_POOL_PATH', 'AAH_PRESET_PATH',
    'AAH_LORA_CATALOG_PATH', 'AAH_PERSONAL_STYLES_PATH', 'AAH_DELIVERY_TARGETS_PATH',
    'AAH_LITE_USERS_PATH', 'AAH_CHARACTER_DICTIONARY_PATH',
    'AAH_CHARACTER_DICTIONARY_EDITS_PATH', 'AAH_CHARACTER_FAVORITES_PATH',
}
PLAN_PATHS = {'destination', 'astrbot', 'comfyui', 'comfy_python', 'astrbot_python',
              'unet', 'clip', 'vae', 'am_archive'}
PLUGIN_PATHS = {'workflow_path', 'workflow_registry_path', 'hq_workflow_path',
    'refine_workflow_path', 'seedvr2_workflow_path', 'detail_repair_workflow_path',
    'reverse_workflow_path', 'preset_store_path', 'prompt_pool_path', 'kp_dynamic_modules_path',
    'character_dictionary_path', 'character_dictionary_edits_path', 'job_store_path',
    'input_dir', 'output_dir', 'reverse_history_dir', 'comfyui_output_root'}
ASTRO_RUNNER = ("import sys; from importlib.metadata import distribution; "
    "sys.argv[0]='astrbot'; "
    "ep=next(e for e in distribution('astrbot').entry_points "
    "if e.group=='console_scripts' and e.name=='astrbot'); sys.exit(ep.load()())")
MAX_CONFIG = 8 * 1024 * 1024


class RepairError(ValueError):
    pass


def safe_path(raw):
    value = str(raw).strip()
    if not value or any(c in value for c in '\x00\r\n"'):
        raise RepairError('路径为空或包含引号/换行，请重新选择目录。')
    path = Path(value).absolute()
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise RepairError('拒绝符号链接、目录联接或重解析路径：' + str(item))
    return path


def install_root(raw, allow_incomplete=False):
    root = safe_path(raw)
    if root == Path(root.anchor) or root == Path.home():
        raise RepairError('不能选择磁盘根或整个用户目录。')
    if not allow_incomplete and (root / '.aaa-migration-incomplete').exists():
        raise RepairError('这是未完成的搬家副本，请保留原目录；不要将半成品当作完整安装继续修复。')
    for name in (MARKER, 'services.json', 'runtime-env.json', 'Start.cmd', 'hub/pyproject.toml'):
        item = safe_path(root / name)
        if not item.is_file():
            raise RepairError('不是完整的 Windows 懒人包安装目录，缺少：' + name)
    return root


def read_bytes(path):
    path = safe_path(path)
    if not path.is_file() or path.stat().st_size > MAX_CONFIG:
        raise RepairError('配置/环境索引文件不存在或过大：' + path.name)
    return path.read_bytes()


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RepairError('JSON 含重复字段，不能安全自动修复。')
        result[key] = value
    return result


def read_json(path):
    return decode_json(read_bytes(path), path.name)


def decode_json(content, name):
    try:
        return json.loads(content.decode('utf-8-sig'), object_pairs_hook=reject_duplicates)
    except (UnicodeError, json.JSONDecodeError):
        raise RepairError('JSON 格式损坏，请保留原文件：' + name) from None


def encode_json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def norm(value):
    return str(value).replace('\\', '/').rstrip('/').casefold()


class PathMap:
    def __init__(self, roots, target):
        self.target = str(target)
        self.roots = []
        for raw in roots:
            value = str(raw).rstrip('/\\')
            if not Path(value).is_absolute() or Path(value) in (Path(Path(value).anchor), Path.home()):
                raise RepairError('旧安装根目录不明确，拒绝猜测替换。')
            if '..' in value.replace('\\', '/').split('/'):
                raise RepairError('旧根目录包含上级跳转。')
            if norm(value) != norm(target) and norm(value) not in [norm(v) for v in self.roots]:
                self.roots.append(value)
        self.roots.sort(key=len, reverse=True)

    def __call__(self, value):
        if not isinstance(value, str):
            return value
        comparable = norm(value)
        for old in self.roots:
            if comparable == norm(old) or comparable.startswith(norm(old) + '/'):
                suffix = value.replace('\\', '/')[len(old):].lstrip('/')
                if '..' in suffix.split('/'):
                    raise RepairError('路径字段含上级跳转，停止自动修复。')
                return str(Path(self.target) / Path(suffix)) if suffix else self.target
        return value


@dataclass
class Change:
    path: Path
    before: bytes
    after: bytes


@dataclass
class RepairPlan:
    root: Path
    changes: list[Change]
    services: list
    warnings: list[str]
    guards: dict[Path, bytes]

    def preview(self):
        lines = ['目标目录：' + str(self.root), f'计划修改 {len(self.changes)} 个小型配置/环境索引文件：']
        lines.extend('  ' + str(c.path.relative_to(self.root)) for c in self.changes)
        lines.extend(self.warnings)
        lines.append('不下载、不删除、不改模型/词库内容、不改密钥值，不启动服务。备份可能含密钥，请私密保管。')
        return '\n'.join(lines)


def map_fields(data, keys, mapper):
    if not isinstance(data, dict):
        raise RepairError('配置必须是 JSON 对象。')
    result = copy.deepcopy(data)
    for key in keys & data.keys():
        if not isinstance(data[key], str):
            raise RepairError('路径字段不是字符串：' + key)
        result[key] = mapper(data[key])
    return result


def decode_environment_text(content, path, python_source=False):
    """Match Python's UTF-8/locale index handling; never use lossy decoding.

    Python source uses its declared PEP 263 encoding instead of an ANSI guess.
    Return the codec so changes keep the original encoding, BOM and line endings.
    """
    if python_source:
        try:
            encoding, _ = tokenize.detect_encoding(io.BytesIO(content).readline)
            return content.decode(encoding), encoding
        except (UnicodeError, SyntaxError, LookupError):
            raise RepairError('Python 索引编码无效，请保留原文件；未执行该文件：' + str(path)) from None
    if content.startswith(b'\xef\xbb\xbf'):
        encodings = ['utf-8-sig']
    else:
        # getencoding(), unlike getpreferredencoding(), ignores UTF-8 mode.
        # The packaged interpreter must not impose its UTF-8 mode on old .pth files.
        native_encoding = locale.getencoding() if hasattr(locale, 'getencoding') else locale.getpreferredencoding(False)
        encodings = list(dict.fromkeys(['utf-8', native_encoding]))
    for encoding in encodings:
        try:
            text = content.decode(encoding)
            if '\x00' in text or text.encode(encoding) != content:
                continue
            return text, encoding
        except (UnicodeError, LookupError):
            continue
    raise RepairError('无法安全识别环境索引编码（UTF-8 或本机 ANSI），未修改该文件：' + str(path))


def encode_environment_text(text, encoding, path):
    try:
        return text.encode(encoding)
    except (UnicodeError, LookupError):
        raise RepairError('新路径无法用原编码 ' + encoding + ' 保存，请改用该编码支持的目标目录名；未修改文件：' + str(path)) from None


def map_python_literals(content, mapper, path='<editable finder>'):
    text, encoding = decode_environment_text(content, path, python_source=True)
    raw = text.encode('utf-8')
    offsets = [0]
    for line in raw.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    replacements = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        raise RepairError('可编辑安装索引语法异常，未执行该文件：' + str(path)) from None
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            changed = mapper(node.value)
            if changed != node.value:
                replacements.append((offsets[node.lineno - 1] + node.col_offset,
                    offsets[node.end_lineno - 1] + node.end_col_offset, ascii(changed).encode('ascii')))
    for start, end, value in sorted(replacements, reverse=True):
        raw = raw[:start] + value + raw[end:]
    if not replacements:
        return content
    ast.parse(raw.decode('utf-8'))
    return encode_environment_text(raw.decode('utf-8'), encoding, path)


def prepare_repair(raw, extra_roots=(), allow_incomplete=False):
    root = install_root(raw, allow_incomplete)
    guards = {}
    def content(path):
        if path not in guards: guards[path] = read_bytes(path)
        return guards[path]
    def load(path):
        return decode_json(content(path), path.name)
    services = load(root / 'services.json')
    env = load(root / 'runtime-env.json')
    if (not isinstance(services, list) or not services or not isinstance(env, dict)
            or any(not isinstance(s, dict) or not isinstance(s.get('cwd'), str) for s in services)):
        raise RepairError('启动配置结构不受支持。')
    if len({s.get('name') for s in services}) != len(services):
        raise RepairError('服务名称重复。')
    hubs = [s for s in services if s.get('name') == 'Hub']
    if len(hubs) != 1 or Path(hubs[0].get('cwd', '')).name.lower() != 'hub':
        raise RepairError('无法从 Hub 工作目录识别原安装根目录。')
    roots = [str(Path(hubs[0]['cwd']).parent), *extra_roots]
    last_path = root / 'last-plan.json'
    last = load(last_path) if last_path.is_file() else None
    if isinstance(last, dict) and last.get('destination'):
        roots.append(last['destination'])
    mapper = PathMap(roots, root)
    changes = {}
    warnings = []
    def add(path, after):
        path = safe_path(path)
        if not path.is_relative_to(root):
            raise RepairError('不修改安装目录外的文件：' + str(path))
        before = content(path)
        if before != after:
            changes[path] = Change(path, before, after)
    def add_json(path, before, after):
        if before != after:
            add(path, encode_json(after))
    updated = copy.deepcopy(services)
    for service in updated:
        if service.get('name') not in {'Hub', 'AstrBot', 'ComfyUI'}:
            raise RepairError('发现未知服务类型，需人工确认，未更改。')
        command = service.get('command')
        if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
            raise RepairError('启动命令结构不受支持。')
        service['cwd'] = mapper(service['cwd'])
        service['command'] = [mapper(arg) for arg in command]
        # distlib .exe contains the OLD interpreter path. Do not rewrite executable bytes.
        if service['name'] == 'AstrBot' and service.get('mode') != 'desktop':
            executable = Path(service['command'][0])
            if executable.name.lower() == 'astrbot.exe' and executable.is_relative_to(root):
                service['command'] = [str(executable.with_name('python.exe')), '-c', ASTRO_RUNNER,
                                      *service['command'][1:]]
        if service.get('mode') != 'desktop':
            for item in (Path(service['cwd']), Path(service['command'][0])):
                safe_path(item)
                if not item.exists():
                    raise RepairError('修复后所需目录/程序仍缺失：' + str(item))
    add_json(root / 'services.json', services, updated)
    new_env = map_fields(env, ENV_PATHS, mapper)
    add_json(root / 'runtime-env.json', env, new_env)
    if last is not None:
        add_json(last_path, last, map_fields(last, PLAN_PATHS, mapper))

    astro = next((Path(s['cwd']) for s in updated if s['name'] == 'AstrBot'), None)
    if astro and astro.is_relative_to(root):
        config = astro / 'data/config/astrbot_plugin_comfy_bridge_config.json'
        if config.is_file():
            before = load(config)
            after = map_fields(before, PLUGIN_PATHS, mapper)
            add_json(config, before, after)
            registry_name = after.get('workflow_registry_path', '')
            plugin_root = Path(new_env.get('AAH_PLUGIN_DIR', str(astro / 'data/plugins/astrbot_plugin_comfy_bridge')))
            if registry_name:
                registry = Path(registry_name)
                if not registry.is_absolute(): registry = plugin_root / registry
                registry = safe_path(registry)
                if registry.is_relative_to(root) and registry.is_file():
                    doc = load(registry)
                    changed = copy.deepcopy(doc)
                    for workflow in changed.get('workflows', []):
                        if isinstance(workflow.get('workflow_file'), str):
                            workflow['workflow_file'] = mapper(workflow['workflow_file'])
                    add_json(registry, doc, changed)
                else:
                    warnings.append('外部或缺失 Registry 未修改；如有绝对路径请另行核对。')
        am = astro / 'data/config/astrbot_plugin_anima_master_config.json'
        if am.is_file():
            before = load(am)
            after = copy.deepcopy(before)
            section = after.get('anima_master_comfyui_connection', {})
            if isinstance(section.get('custom_workflow_path'), str):
                section['custom_workflow_path'] = mapper(section['custom_workflow_path'])
            add_json(am, before, after)
    elif astro:
        warnings.append('外部 AstrBot/Desktop 数据不在搬迁范围内；未修改其插件配置。')

    # Only inspect directly referenced, in-root virtual environments; no model/corpus traversal.
    environments = {root / 'hub/.venv'}
    for service in updated:
        executable = Path(service['command'][0])
        if executable.is_relative_to(root) and executable.parent.name.lower() == 'scripts':
            environments.add(executable.parent.parent)
    for environment in environments:
        cfg = environment / 'pyvenv.cfg'
        if cfg.is_file():
            original = content(cfg)
            text, encoding = decode_environment_text(original, cfg)
            lines = []
            for line in text.splitlines(keepends=True):
                match = re.match(r'(home|executable)(\s*=\s*)(.*?)(\r?\n)?$', line)
                if match:
                    line = match[1] + match[2] + mapper(match[3]) + (match[4] or '')
                lines.append(line)
            if ''.join(lines) != text:
                add(cfg, encode_environment_text(''.join(lines), encoding, cfg))
        site = safe_path(environment / 'Lib/site-packages')
        if not site.is_dir(): continue
        for item in site.iterdir():
            name = item.name.lower()
            if item.suffix.lower() in {'.pth', '.egg-link'}:
                original = content(item)
                text, encoding = decode_environment_text(original, item)
                lines = text.splitlines(keepends=True)
                changed = []
                for line in lines:
                    value = line.rstrip('\r\n')
                    changed.append(mapper(value) + line[len(value):])
                if ''.join(changed) != text:
                    add(item, encode_environment_text(''.join(changed), encoding, item))
            elif name.startswith('__editable__') and name.endswith('_finder.py'):
                original = content(item)
                add(item, map_python_literals(original, mapper, item))
        # direct_url.json is audit metadata, not used for import. Leave it untouched.
    return RepairPlan(root, list(changes.values()), updated, warnings, guards)


def assert_idle(plan):
    for service in plan.services:
        # Outside ComfyUI is not changed. Hub/AstrBot can hold config even outside root.
        if service['name'] == 'ComfyUI' and not Path(service['cwd']).is_relative_to(plan.root):
            continue
        port = service.get('port')
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise RepairError('服务端口无效，不能判断是否停止。')
        for address in ('127.0.0.1', '::1'):
            try:
                connection = socket.create_connection((address, port), timeout=0.3)
            except (OSError, RepairError):
                continue
            connection.close()
            raise RepairError(f'{service["name"]} 端口 {port} 仍占用。请正常停止对应服务后再试；工具不会强杀进程。')


def assert_unchanged(plan):
    for path, before in plan.guards.items():
        if read_bytes(path) != before:
            raise RepairError('检查后文件被其他程序改动，停止：' + str(path.relative_to(plan.root)))


def atomic_write(path, content):
    safe_path(path)
    temporary = path.with_name(path.name + '.aaa-tmp-' + secrets.token_hex(6))
    try:
        with temporary.open('xb') as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.is_file(): temporary.unlink()


def run_python_probe(command, cwd):
    env = {k: v for k, v in os.environ.items() if k not in {'PYTHONHOME', 'PYTHONPATH', 'TCL_LIBRARY', 'TK_LIBRARY'}}
    kernel, previous = None, None
    if os.name == 'nt' and getattr(sys, 'frozen', False):
        # Do not let the standalone tool's bundled DLL search path contaminate
        # the user's independent Python interpreter (possibly another version).
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetDllDirectoryW.argtypes = (wintypes.DWORD, wintypes.LPWSTR)
        kernel.GetDllDirectoryW.restype = wintypes.DWORD
        kernel.SetDllDirectoryW.argtypes = (wintypes.LPCWSTR,)
        kernel.SetDllDirectoryW.restype = wintypes.BOOL
        value = ctypes.create_unicode_buffer(32768)
        count = kernel.GetDllDirectoryW(len(value), value)
        if count >= len(value): raise RepairError('无法安全读取独立工具的 DLL 搜索路径。')
        previous = value.value or None
        if not kernel.SetDllDirectoryW(None): raise RepairError('无法隔离 Python 检查环境。')
    try:
        return subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    finally:
        if kernel is not None and not kernel.SetDllDirectoryW(previous):
            raise RepairError('无法恢复独立工具运行环境，停止后请重新打开工具。')


def check_runtime(plan):
    # Probe imports only; do not start a server, import ComfyUI, or run GPU jobs.
    for service in plan.services:
        if service.get('mode') == 'desktop': continue
        executable = Path(service['command'][0])
        if not executable.is_relative_to(plan.root) or executable.name.lower() != 'python.exe': continue
        script = 'import sys; assert sys.version_info >= (3, 10)'
        if service['name'] == 'Hub':
            script += "; import importlib.util as u; s=u.find_spec('astr_auto_anima_hub'); assert s is not None; from pathlib import Path; assert Path(s.origin).resolve().is_relative_to(Path(sys.argv[1]).resolve())"
        elif service['name'] == 'AstrBot':
            script += "; from importlib.metadata import distribution; assert any(e.name=='astrbot' and e.group=='console_scripts' for e in distribution('astrbot').entry_points)"
        try:
            result = run_python_probe([str(executable), '-I', '-B', '-c', script, str(plan.root / 'hub')], service['cwd'])
        except (OSError, subprocess.TimeoutExpired):
            raise RepairError(service['name'] + ' Python 无法启动/检查超时。可能基础 Python 已删除；不能仅靠改路径修好。') from None
        if result.returncode:
            raise RepairError(service['name'] + ' Python/包定位检查未通过。没有重装环境；原始输出不展示，避免泄露配置。')


def apply_repair(plan, log=print):
    assert_idle(plan); assert_unchanged(plan)
    if not plan.changes:
        check_runtime(plan)
        log('未发现需要改动的路径；Python 定位检查通过。仍需自行启动并验收。')
        return None
    lock = safe_path(plan.root / '.aaa-path-repair.lock')
    try:
        handle = lock.open('x', encoding='ascii')
    except FileExistsError:
        raise RepairError('存在修复锁。先确认其他工具已退出，不要同时修复。') from None
    backup = plan.root / ('path-backup_' + time.strftime('%Y%m%d_%H%M%S') + '_' + secrets.token_hex(4))
    written = []
    try:
        with handle:
            handle.write(str(os.getpid()))
        assert_unchanged(plan)
        backup.mkdir()
        entries = []
        for change in plan.changes:
            relative = change.path.relative_to(plan.root)
            target = safe_path(backup / 'originals' / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as original: original.write(change.before)
            if read_bytes(target) != change.before: raise RepairError('备份回读不一致，未开始修复。')
            entries.append({'path': relative.as_posix(), 'before_sha256': digest(change.before),
                            'after_sha256': digest(change.after)})
        (backup / 'manifest.json').write_bytes(encode_json({'tool_version': VERSION, 'files': entries}))
        log('所有待修改文件已备份并回读校验：' + str(backup))
        assert_idle(plan); assert_unchanged(plan)
        for change in plan.changes:
            if read_bytes(change.path) != change.before: raise RepairError('写入前检测到并发修改。')
            atomic_write(change.path, change.after)
            written.append(change)
            if read_bytes(change.path) != change.after: raise RepairError('修复写入回读校验失败。')
            log('已修复：' + str(change.path.relative_to(plan.root)))
        check_runtime(plan)
        (backup / 'result.txt').write_text('路径修复与 Python 定位检查通过。未启动服务，未验证生图。\n', encoding='utf-8')
        log('路径修复与 Python 定位检查通过。请从新目录运行 Start.cmd，再检查 Hub 与普通单图。')
        return backup
    except Exception:
        incomplete = []
        for change in reversed(written):
            try:
                if read_bytes(change.path) != change.after:
                    incomplete.append(str(change.path.relative_to(plan.root))); continue
                atomic_write(change.path, change.before)
                if read_bytes(change.path) != change.before: incomplete.append(str(change.path.relative_to(plan.root)))
            except OSError:
                incomplete.append(str(change.path.relative_to(plan.root)))
        log('操作失败；已写入项已尝试回滚。备份保留：' + str(backup))
        if incomplete:
            raise RepairError('部分文件被占用或发生并发修改，未强制覆盖。需用备份人工恢复：' + '、'.join(incomplete)) from None
        raise
    finally:
        lock.unlink()


def empty_destination(destination):
    """Allow a fresh path or a genuinely empty directory, including hidden files."""
    destination = safe_path(destination)
    if destination.exists():
        if not destination.is_dir():
            raise RepairError('搬家目标不是文件夹，请选择空目录或尚未创建的目录：' + str(destination))
        if next(destination.iterdir(), None) is not None:
            raise RepairError('目标目录非空，不能合并或覆盖。请选择空目录；已经完整复制好请用“就地修复”。目标：' + str(destination))
    return destination


def migration_inventory(source, destination):
    source = install_root(source)
    destination = safe_path(destination)
    if destination == Path(destination.anchor) or destination == Path.home():
        raise RepairError('新目录不能是磁盘根或整个用户目录。')
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise RepairError('新旧目录不能相同或互相嵌套。')
    empty_destination(destination)
    files, directories, total = [], [], 0
    for directory, dirs, names in os.walk(source, followlinks=False):
        parent = safe_path(directory)
        for name in dirs:
            item = safe_path(parent / name)
            directories.append(item.relative_to(source))
        for name in names:
            item = safe_path(parent / name)
            info = item.stat()
            if not stat.S_ISREG(info.st_mode): raise RepairError('发现非普通文件，停止搬家。')
            if name in {'.aaa-path-repair.lock', '.deploy-session.lock', '.deploy.lock'}:
                raise RepairError('发现运行锁，请先确认部署/修复工具已经退出。')
            files.append((item.relative_to(source), info.st_size, info.st_mtime_ns))
            total += info.st_size
    ancestor = destination.parent
    while not ancestor.exists(): ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < total + max(256 * 1024**2, total // 20):
        raise RepairError('目标磁盘剩余空间不足（需要完整副本及安全余量）。')
    return source, destination, directories, files, total


def migrate_install(source, destination, log=print):
    log('正在只读盘点源目录、检查冲突与剩余空间；尚未开始复制。')
    source, destination, dirs, files, total = migration_inventory(source, destination)
    # Build once before copying so malformed configurations fail before a large transfer.
    source_plan = prepare_repair(source)
    assert_idle(source_plan); assert_unchanged(source_plan)
    # Recheck immediately before copying: browsing an empty folder is allowed,
    # but another process may have populated/replaced it since inventory.
    empty_destination(destination)
    log(f'准备复制 {len(files)} 个文件，共 {total / 1024**3:.2f} GiB；原目录保留。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    safe_path(destination.parent)
    destination.mkdir(exist_ok=True)
    empty_destination(destination)
    receipt = destination / '.aaa-migration-incomplete'
    with receipt.open('x', encoding='utf-8') as handle:
        handle.write('复制未完成或尚未验收，不能当作完整安装启动。\n')
    copied, last_notice = 0, time.monotonic()
    try:
        for relative in dirs:
            safe_path(destination / relative).mkdir()
        for relative, size, mtime in files:
            original, target = safe_path(source / relative), safe_path(destination / relative)
            info = original.stat()
            if (info.st_size, info.st_mtime_ns) != (size, mtime): raise RepairError('复制前源文件已变化，请关闭相关程序。')
            target.parent.mkdir(parents=True, exist_ok=True)
            checksum = hashlib.sha256()
            with original.open('rb') as reader, target.open('xb') as writer:
                while True:
                    block = reader.read(4 * 1024**2)
                    if not block: break
                    writer.write(block); checksum.update(block); copied += len(block)
                    if time.monotonic() - last_notice > 1:
                        log(f'正在复制：{copied / 1024**3:.2f}/{total / 1024**3:.2f} GiB')
                        last_notice = time.monotonic()
            verify = hashlib.sha256()
            with target.open('rb') as reader:
                for block in iter(lambda: reader.read(4 * 1024**2), b''):
                    verify.update(block)
                    if time.monotonic() - last_notice > 1:
                        log(f'正在回读校验已复制文件；进度 {copied / 1024**3:.2f}/{total / 1024**3:.2f} GiB')
                        last_notice = time.monotonic()
            info = original.stat()
            if checksum.digest() != verify.digest() or (info.st_size, info.st_mtime_ns) != (size, mtime):
                raise RepairError('复制回读不一致或源文件被修改；原目录保留。')
            shutil.copystat(original, target)
        assert_idle(source_plan); assert_unchanged(source_plan)
        for relative, size, mtime in files:
            info = safe_path(source / relative).stat()
            if (info.st_size, info.st_mtime_ns) != (size, mtime):
                raise RepairError('复制期间源文件发生变动，请保持服务关闭后重新使用新目标搬家。')
        log('全部文件复制与 SHA256 回读完成；开始备份并修复新目录路径。')
        plan = prepare_repair(destination, extra_roots=(source,), allow_incomplete=True)
        log(plan.preview())
        result = apply_repair(plan, log)
        receipt.unlink()
        log('搬家复制与路径检查完成。原目录未删除；新目录验收成功前不要清理原目录。')
        return result
    except Exception:
        log('搬家未完成；原目录未删除。新目标保留诊断，不自动清理，也不继续启动。')
        raise


def launch_gui(smoke=False):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk(); root.title('AAA 搬家与路径修复 · ' + VERSION)
    root.geometry('900x680'); root.minsize(780, 560)
    if smoke: root.withdraw()
    mode = tk.StringVar(value='repair')
    current = tk.StringVar(value=DEFAULT_TARGET)
    target = tk.StringVar(value=str(Path.home() / 'AstrAutoAnima-install'))
    ttk.Label(root, text='已改名：就地修复；准备搬家：复制到新位置后修复', font=('Microsoft YaHei UI', 15, 'bold')).pack(padx=18, pady=14, anchor='w')
    ttk.Label(root, text='先停止 Hub、AstrBot，以及位于安装目录内的 ComfyUI。不会强杀、联网、重装或启动服务。\n原目录不删除；模型/词库内容与密钥值不修改。备份含私密配置，不要发群。', wraplength=850).pack(padx=18, anchor='w')
    choices = ttk.Frame(root); choices.pack(fill='x', padx=18, pady=10)
    ttk.Radiobutton(choices, text='就地修复（已经改名/复制）', variable=mode, value='repair').pack(side='left')
    ttk.Radiobutton(choices, text='搬家（完整复制，保留原目录）', variable=mode, value='move').pack(side='left', padx=20)
    for label, variable, existing in [('当前安装目录（含 Start.cmd）', current, True), ('搬家目标（空目录或未创建）', target, False)]:
        frame = ttk.Frame(root); frame.pack(fill='x', padx=18, pady=5)
        ttk.Label(frame, text=label, width=31).pack(side='left')
        ttk.Entry(frame, textvariable=variable).pack(side='left', fill='x', expand=True)
        def choose(v=variable, must=existing):
            value = filedialog.askdirectory(mustexist=must, parent=root)
            if value: v.set(value)
        ttk.Button(frame, text='浏览', command=choose).pack(side='right', padx=6)
    text = tk.Text(root, wrap='word', height=22); text.pack(fill='both', expand=True, padx=18, pady=12)
    messages, state = queue.Queue(), {'busy': False}
    def report(line):
        text.insert('end', line + '\n'); text.see('end')
    def perform():
        if state['busy']: return
        operation, source, destination = mode.get(), current.get(), target.get()
        notice = ('就地修复：' + source if operation == 'repair' else f'完整复制：{source}\n新目录：{destination}')
        notice += '\n\n确认相关服务已正常关闭？将先检查，修复前备份所有待改文件；原文件内容不发到网络。'
        if not messagebox.askyesno('确认操作范围', notice, parent=root): return
        state['busy'] = True; action.configure(state='disabled')
        def work():
            try:
                if os.name != 'nt': raise RepairError('本工具只支持同一 Windows 电脑的改名/目录搬迁，不支持跨系统或换电脑。')
                if operation == 'repair':
                    plan = prepare_repair(source); messages.put(plan.preview())
                    apply_repair(plan, messages.put)
                else:
                    migrate_install(source, destination, messages.put)
                messages.put('结束：尚未启动服务。请在目标目录运行 Start.cmd，再验收 Hub、授权和一张普通图。')
            except Exception as exc:
                # Only project-generated messages or OS type; never raw JSON/key values.
                messages.put('已停止：' + (str(exc) if isinstance(exc, RepairError) else type(exc).__name__ + '；请检查权限、文件完整性和备份。'))
            finally: messages.put(None)
        threading.Thread(target=work, daemon=True).start()
    action = ttk.Button(root, text='检查并执行（自动备份）', command=perform)
    action.pack(pady=(0, 12))
    def poll():
        while not messages.empty():
            line = messages.get()
            if line is None:
                state['busy'] = False; action.configure(state='normal')
            else: report(line)
        root.after(150, poll)
    def close():
        if state['busy']:
            messagebox.showwarning('操作进行中', '请等待复制/修复结束，不要强行关闭；原目录不会删除。', parent=root)
        else: root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    if smoke:
        root.update_idletasks(); assert mode.get() == 'repair' and current.get() == DEFAULT_TARGET
        assert not state['busy']; root.destroy(); print('PASS relocation GUI: no write/copy/start'); return 0
    poll(); root.mainloop(); return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke-test', action='store_true')
    parser.add_argument('--check', type=Path, help='Read-only path/config preflight')
    parser.add_argument('--repair', type=Path, help='Explicit CLI in-place repair; requires --confirm')
    parser.add_argument('--confirm', action='store_true', help='Confirm CLI repair, including private backup')
    args = parser.parse_args()
    if args.check:
        if os.name != 'nt': raise RepairError('仅支持 Windows。')
        print(prepare_repair(args.check).preview()); return 0
    if args.repair:
        if os.name != 'nt' or not args.confirm: return 2
        try:
            apply_repair(prepare_repair(args.repair))
            return 0
        except Exception:
            # Windowed build has no console; exit status is for scripted diagnostics.
            # Do not emit third-party exception text which may contain credentials.
            return 1
    return launch_gui(args.smoke_test)


if __name__ == '__main__':
    raise SystemExit(main())
