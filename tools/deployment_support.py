"""Cross-platform path discovery and pinned, opt-in upstream installation."""
from pathlib import Path
import json
import os
import re
import shutil
import tempfile
import zipfile

AM_VERSION = '0.7.1'
AM_COMMIT = '34375c86b35f1c94fa3ee8129e98c2127706eb5a'
AM_URL = f'https://codeload.github.com/YayiMiko/anima-master/zip/{AM_COMMIT}'
AM_SHA256 = 'd797a6811d71f7b6e8782ca1b1afbcd521e29fc05f073988a614cf350b142b38'


def host_platform():
    return 'windows' if os.name == 'nt' else 'linux'


def clean_path(value):
    value = os.path.expandvars(str(value).strip())
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if any(c in value for c in ('"', '\0', '\r', '\n')):
        raise ValueError('路径包含无效引号或换行，请用“选择”按钮重新选择')
    return str(Path(value).expanduser()) if value else ''


def no_links(path):
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ValueError('为避免写入错误目录，不支持符号链接/目录联接：' + str(item))


def astrbot_root(value, mode):
    candidate = Path(clean_path(value)) if value else Path.home() / '.astrbot'
    no_links(candidate)
    if candidate.name == 'data' and candidate.is_dir():
        candidate = candidate.parent
    if (candidate / 'data').is_dir():
        return candidate.resolve()
    if mode == 'desktop':
        default = Path.home() / '.astrbot'
        no_links(default)
        if (default / 'data').is_dir():
            return default.resolve()
        raise ValueError('未找到桌面版数据：请先运行一次 AstrBot Desktop，再选择含 data 的 .astrbot 目录；不要选择 EXE 安装目录或新建空 data')
    raise ValueError('AstrBot 根目录须包含真实 data；也可直接选择 data 文件夹')


def comfy_root(value):
    candidate = Path(clean_path(value))
    no_links(candidate)
    no_links(candidate / 'ComfyUI')
    if (candidate / 'main.py').is_file():
        return candidate.resolve()
    if (candidate / 'ComfyUI/main.py').is_file():
        return (candidate / 'ComfyUI').resolve()
    raise ValueError('找不到 ComfyUI/main.py：选择源码根目录，或 Windows portable 的外层目录')


def discover_python(root, explicit='', portable=False):
    if explicit:
        path = Path(clean_path(explicit)).absolute()
        if not path.is_file():
            raise ValueError('指定的 Python 文件不存在：' + str(path))
        return path
    candidates = [root / '.venv/Scripts/python.exe', root / 'venv/Scripts/python.exe'] if os.name == 'nt' else [root / '.venv/bin/python', root / 'venv/bin/python']
    if portable:
        candidates = [root.parent / 'python_embeded/python.exe', root.parent / 'python_embedded/python.exe', *candidates]
    found = next((p for p in candidates if p.is_file()), None)
    if found is None:
        raise ValueError('无法识别 Python 环境，请显式选择该服务使用的 Python：' + str(root))
    return found.absolute()


def windows_start_script():
    # Never pass a quoted path ending in a backslash to Python's argv parser.
    return ('@echo off\r\nsetlocal DisableDelayedExpansion\r\nchcp 65001 >nul\r\nset "PYTHONUTF8=1"\r\ncd /d "%~dp0."\r\n'
            'if errorlevel 1 goto :failed\r\n'
            'if not exist "hub\\.venv\\Scripts\\python.exe" goto :missing\r\n'
            '"hub\\.venv\\Scripts\\python.exe" "deploy_project.py" --start "."\r\n'
            'goto :done\r\n:missing\r\necho Hub Python missing. Resume the deployment wizard.\r\n'
            ':failed\r\necho Start failed. Keep this window for diagnostics.\r\n:done\r\npause\r\n')


def download_base_models(root, comfy, plan, log):
    from easy_installer import download_file
    catalog = json.loads((root / 'tools/model_catalog.json').read_text('utf-8'))
    for entry in catalog['profiles']['anima-base-1.0']['files']:
        key = entry['field']
        if getattr(plan, key):  # Explicit user model wins over the profile default.
            continue
        target = comfy / entry['target']
        no_links(target)
        log(f"下载 {entry['filename']} ({entry['size']:,} bytes)，来源：{entry['url']}")
        download_file(entry['url'], target, log, expected_sha256=entry['sha256'])
        if target.stat().st_size != entry['size']:
            raise ValueError('模型大小不符合发布清单：' + target.name)
        setattr(plan, key, str(target))


def install_anima_master(astro, root, log, copy_source):
    from easy_installer import download_file
    target = astro / 'data/plugins/astrbot_plugin_anima_master'
    no_links(target)
    if target.exists():
        metadata = target / 'metadata.yaml'
        text = metadata.read_text('utf-8-sig') if metadata.is_file() else ''
        if re.search(r'^version:\s*[\"\']?0\.7\.1[\"\']?\s*$', text, re.M):
            log('已有 Anima Master 0.7.1，保留代码与配置，不覆盖')
            return target
        raise ValueError('已有 Anima Master 目录不是 0.7.1；不会自动覆盖或降级。请备份并在 AstrBot 插件页人工处理')
    archive = root / 'downloads/anima-master-0.7.1.zip'
    no_links(archive)
    download_file(AM_URL, archive, log, expected_sha256=AM_SHA256)
    with tempfile.TemporaryDirectory(prefix='aaa-am-') as temporary:
        staging = Path(temporary)
        prefix = 'anima-master-' + AM_COMMIT
        with zipfile.ZipFile(archive) as z:
            total = 0
            for entry in z.infolist():
                name = entry.filename.replace('\\', '/')
                parts = Path(name).parts
                total += entry.file_size
                if not parts or parts[0] != prefix or '..' in parts or ':' in name or name.startswith('/') or (entry.external_attr >> 16) & 0o170000 == 0o120000 or total > 50_000_000:
                    raise ValueError('上游 ZIP 路径或大小异常，停止安装')
            z.extractall(staging)
        source = staging / prefix
        if not re.search(r'^version:\s*[\"\']?0\.7\.1[\"\']?\s*$', (source / 'metadata.yaml').read_text('utf-8-sig'), re.M):
            raise ValueError('上游包版本校验失败')
        copy_source(source, target)
    log('Anima Master 0.7.1 已安装；已固定官方提交 ' + AM_COMMIT)
    return target


def configure_anima_master(astro, comfy, root, json_write):
    path = astro / 'data/config/astrbot_plugin_anima_master_config.json'
    no_links(path)
    existing = json.loads(path.read_text('utf-8-sig')) if path.is_file() else {}
    before = json.loads(json.dumps(existing))
    graph_path = comfy / 'user/default/workflows/AAA_Quick_Local_api.json'
    defaults = {'anima_master_comfyui_connection': {
        'comfyui_base_url': 'http://127.0.0.1:8188', 'auto_start': False,
        'custom_workflow_override_parameters': False,
    }, 'anima_master_basic': {'chiyo_preset': ''}}
    if graph_path.is_file():
        graph = json.loads(graph_path.read_text('utf-8'))
        defaults['anima_master_comfyui_connection'].update(custom_workflow_enabled=True, custom_workflow_path=str(graph_path))
        defaults['anima_master_models'] = {key: graph[node]['inputs'][key] for key, node in [('unet_name', '1'), ('clip_name', '2'), ('vae_name', '3')]}
    for section, entries in defaults.items():
        group = existing.setdefault(section, {})
        if not isinstance(group, dict):
            raise ValueError('AM 配置分组不是对象，需人工检查：' + section)
        for key, value in entries.items():
            group.setdefault(key, value)
    if path.is_file() and before != existing:
        backup = root / 'am-config-backups'
        backup.mkdir(parents=True, exist_ok=True)
        import time
        import secrets
        shutil.copy2(path, backup / (str(time.time_ns()) + '_' + secrets.token_hex(3) + '.json'))
    json_write(path, existing, True)
