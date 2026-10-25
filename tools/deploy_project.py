"""Public deployment wizard: prepare -> configure -> start -> verify.

Does not install graphics drivers, bypass QQ login, or silently download models.
All external installation must be explicitly selected. No shell=True commands.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import tempfile
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from install_progress import StageProgress, ProgressLog, ProgressPanel, report, stream_command
from deployment_support import (host_platform, clean_path, no_links, astrbot_root,
    comfy_root, discover_python, windows_start_script, download_base_models,
    install_anima_master, configure_anima_master, default_install_directory, relocation_notice)

ROOT = Path(__file__).resolve().parents[1]
MARKER = '.aaa-managed-install'

DEPLOY_STEPS = (
    ('prepare', '检查服务是否已关闭与创建独立环境'),
    ('environments', '准备所选 AstrBot / ComfyUI 环境'),
    ('project', '备份并安装 AAA 插件、节点与 Hub'),
    ('dependencies', '安装已授权的项目依赖'),
    ('optional', '安装已勾选可选组件'),
    ('models', '准备基础模型与 Quick 工作流'),
    ('configuration', '保存连接配置与安装 Anima Master'),
    ('launchers', '生成后续启动入口'),
    ('services', '启动服务并检查健康状态'),
)
DISPLAY_STEPS = tuple(zip((key for key, _ in DEPLOY_STEPS), (
    '检查与准备', '应用环境', 'AAA 项目文件', 'Python 依赖', '可选扩展',
    '模型与工作流', '连接配置与 AM', '启动入口', '服务健康检查')))


def load_previous_plan(path):
    """Read-only resume form; never import credentials or execute a plan automatically."""
    source = Path(clean_path(str(path))).absolute()
    no_links(source)
    if source.name != 'last-plan.json' or not source.is_file():
        raise ValueError('请选择原安装目录中的 last-plan.json；它不是 runtime-env.json。')
    raw = json.loads(source.read_text('utf-8-sig'))
    if not isinstance(raw, dict) or set(raw) - set(Plan.__dataclass_fields__):
        raise ValueError('上次填写记录格式不兼容；请保留原文件并手动核对。')
    defaults = asdict(Plan(''))
    for key, value in raw.items():
        if type(value) is not type(defaults[key]):
            raise ValueError('上次填写记录字段类型不正确：' + key)
    raw['api_key'] = ''
    return Plan(**raw)


class DeploymentProgress(StageProgress):
    """Informational journal only: retries always revalidate, never trust it to skip writes."""
    def __init__(self, root, log):
        self.path = root / 'deployment-status.json'
        super().__init__(DEPLOY_STEPS, log, lambda data: json_write(self.path, data, True))


def progress_text(root):
    path = Path(root) / 'deployment-status.json'
    no_links(path)
    if not path.is_file(): return '没有阶段记录（旧包或尚未执行）；可以先载入填写记录，再只做预检。'
    try:
        data = json.loads(path.read_text('utf-8-sig'))
        if not isinstance(data, dict): raise ValueError('not object')
    except (OSError, ValueError):
        return '上次阶段记录不可读；不代表模型或配置损坏。表单已载入，先只做预检；不要手工伪造成功记录。'
    stages = dict(DEPLOY_STEPS)
    stage = stages.get(data.get('stage'), '未知阶段')
    status = {'running': '上次未写入结束状态；可能仍在执行，也可能异常关闭',
              'failed': '已中断，保留现有文件', 'needs_attention': '文件已部署，服务或首次配置仍需处理',
              'completed': '部署流程结束，仍需完成首张图验收'}.get(data.get('status'), '未知状态')
    return f'上次阶段：{stage}\n状态：{status}\n重试会重新预检，不凭进度记录跳过检查；不会自动删除目录。'


@dataclass
class Plan:
    destination: str
    deployment_profile: str = "full"
    platform: str = 'auto'
    astrbot_mode: str = 'cli'
    astrbot: str = ''
    comfyui: str = ''
    comfy_python: str = ''
    astrbot_python: str = ''
    install_astrbot: bool = False
    install_comfyui: bool = False
    install_dependencies: bool = False
    gpu: bool = True
    unet: str = ''
    clip: str = ''
    vae: str = ''
    bot_id: str = ''
    api_key: str = ''
    external: str = ''
    download_models: bool = False
    accept_model_license: bool = False
    install_am: bool = False
    download_mode: str = 'official'
    hf_mirror: str = ''
    github_mirror: str = ''
    download_proxy: str = ''
    fallback_official: bool = False
    revoke_best_effort: bool = False
    am_archive: str = ''
    install_gufeng: bool = False
    gufeng_module: str = ''


def json_write(path, data, private=False):
    path = Path(path)
    no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never follow a configuration symlink.
    if path.is_symlink():
        raise ValueError(f'拒绝写入符号链接：{path.name}')
    # Atomic promotion keeps the last usable form/config if writing is interrupted.
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.aaa-config-', dir=path.parent)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        if os.name != 'nt':
            mode = 0o600 if private else (path.stat().st_mode & 0o777 if path.is_file() else 0o644)
            os.chmod(temporary, mode)
        no_links(path)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def checked_root(raw):
    if not clean_path(raw):
        raise ValueError('请填写独立安装目录')
    original = Path(clean_path(raw)).absolute()
    resolved = original.resolve()
    no_links(original)
    source_inside = (ROOT / '.astr_auto_anima_public_root').is_file() and (resolved == ROOT or ROOT in resolved.parents)
    if resolved == Path(resolved.anchor) or resolved == Path.home() or source_inside:
        raise ValueError('请选择独立安装目录，不能使用磁盘根、用户目录或发布源码内部')
    if resolved.exists() and not resolved.is_dir():
        raise ValueError('安装目标是文件，请选择目录')
    no_links(resolved / MARKER)
    if resolved.exists() and any(resolved.iterdir()) and not (resolved / MARKER).is_file():
        raise ValueError('目标目录非空且非本向导创建；请选择新目录。既有服务通过路径接入，不会被覆盖')
    return resolved


def guard_runtime_versions(plan, root):
    """Fail closed before writes; an old installer must not downgrade a newer runtime."""
    astro = (root / 'astrbot' if plan.install_astrbot else Path(plan.astrbot)) if plan.deployment_profile == 'full' else root / '.no-astrbot-local'
    for name, source, target in (
        ('插件', ROOT / 'plugin/astrbot_plugin_comfy_bridge/metadata.yaml', astro / 'data/plugins/astrbot_plugin_comfy_bridge/metadata.yaml'),
        ('Hub', ROOT / 'hub/service/pyproject.toml', root / 'hub/pyproject.toml'),
    ):
        no_links(target)
        if not target.exists(): continue
        def version(path):
            if not path.is_file() or path.stat().st_size > 1024 * 1024: raise ValueError('版本文件异常：' + name)
            match = re.search(r'^version\s*[:=]\s*[\"\']?([0-9][0-9A-Za-z.+_-]*)', path.read_text('utf-8-sig'), re.M)
            if not match: raise ValueError('无法识别已有或包内' + name + '版本；停止覆盖，请人工核对。')
            core = re.match(r'(\d+)\.(\d+)\.(\d+)', match[1])
            if not core: raise ValueError('无法比较' + name + '版本，停止覆盖。')
            return tuple(map(int, core.groups())), match[1]
        incoming, existing = version(source), version(target)
        if existing[0] > incoming[0] or (existing[0] == incoming[0] and existing[1] != incoming[1]):
            raise ValueError(f'已有{name} {existing[1]} 与包内 {incoming[1]} 不适合自动覆盖；禁止降级或混装。只补节点/模型请用扩展中心专用入口，更新服务请使用匹配版本包。')


def validate(plan):
    for required in ('.astr_auto_anima_public_root', 'hub/service/pyproject.toml', 'plugin/astrbot_plugin_comfy_bridge/metadata.yaml', 'comfyui/workflows'):
        if not (ROOT / required).exists(): raise ValueError('部署包不完整，请完整解压对应系统懒人包；独立工具包不能执行全量部署。')
    from download_network import DownloadNetwork
    DownloadNetwork.from_plan(plan).validate()
    plan.gufeng_module = clean_path(plan.gufeng_module)
    from gufeng_resource import selected_module, inspect_module, validate_destination
    gufeng_module = selected_module(plan, ROOT)
    if plan.am_archive:
        plan.am_archive = clean_path(plan.am_archive)
        no_links(Path(plan.am_archive).absolute())
        if not Path(plan.am_archive).is_file():
            raise ValueError('本地 AM ZIP 不存在，请重新选择文件')
    if plan.download_mode == 'local':
        if plan.download_models and not all((plan.unet, plan.clip, plan.vae)):
            raise ValueError('本地文件模式请选齐 UNET / CLIP / VAE，并取消自动下载模型')
        if plan.install_am and not plan.am_archive:
            raise ValueError('本地文件模式安装 AM 需要选择固定版本 ZIP')
        if plan.external:
            raise ValueError('本地文件模式请取消可选节点 / 模型下载；可先手动安装这些组件')
    if plan.platform not in ('auto', 'windows', 'linux') or plan.platform not in ('auto', host_platform()):
        raise ValueError('操作系统选择不匹配：Windows 包只能在 Windows 执行，Linux 包只能在 Linux 执行')
    if plan.deployment_profile not in ('local', 'full'):
        raise ValueError('部署档位必须为 local 或 full')
    if plan.deployment_profile == 'local' and (plan.install_astrbot or plan.install_am or plan.external):
        raise ValueError('本机轻量部署不安装 AstrBot、Anima Master 或外部节点；以后可在同一目录补齐完整服务')
    if plan.astrbot_mode not in ('cli', 'desktop'):
        raise ValueError('AstrBot 模式必须为 cli 或 desktop')
    if plan.astrbot_mode == 'desktop' and (host_platform() != 'windows' or plan.install_astrbot):
        raise ValueError('桌面版接入只用于已有 Windows AstrBot Desktop，不能同时勾选下载全新 AstrBot')
    for key in ('destination', 'astrbot', 'comfyui', 'astrbot_python', 'comfy_python', 'unet', 'clip', 'vae'):
        setattr(plan, key, clean_path(getattr(plan, key)))
    root = checked_root(plan.destination)
    if plan.install_gufeng:
        validate_destination(root, inspect_module(gufeng_module))
    if (plan.install_astrbot or plan.install_comfyui) and not plan.install_dependencies:
        raise ValueError('全新环境需要勾选“允许安装依赖”')
    if plan.deployment_profile == 'full' and plan.install_astrbot and sys.version_info < (3, 12):
        raise ValueError('全新 AstrBot 环境需要 Python 3.12+；请用 Python 3.12 运行向导')
    if plan.install_comfyui and not shutil.which('git'):
        raise ValueError('下载 ComfyUI 需要 Git：https://git-scm.com/downloads')
    if plan.deployment_profile == 'full' and not plan.install_astrbot:
        if not plan.astrbot and plan.astrbot_mode != 'desktop':
            raise ValueError('请选择已有 AstrBot 根目录，或勾选下载全新环境')
        plan.astrbot = str(astrbot_root(plan.astrbot, plan.astrbot_mode))
        if plan.astrbot_mode != 'desktop':
            plan.astrbot_python = str(discover_python(Path(plan.astrbot), plan.astrbot_python))
            executable = Path(plan.astrbot_python).parent / ('astrbot.exe' if os.name == 'nt' else 'astrbot')
            if not executable.is_file():
                raise ValueError('该 Python 环境没有 AstrBot CLI 启动器；桌面版请选择 desktop 模式，源码版请使用含 astrbot 命令的环境')
    if not plan.install_comfyui:
        if not plan.comfyui:
            raise ValueError('请选择 ComfyUI 根目录或 portable 外层目录')
        plan.comfyui = str(comfy_root(plan.comfyui))
        plan.comfy_python = str(discover_python(Path(plan.comfyui), plan.comfy_python, portable=True))
    for value in ((plan.astrbot if plan.deployment_profile == 'full' else ''), plan.comfyui):
        if value:
            no_links(Path(value))
            if root == Path(value) or Path(value) in root.parents:
                raise ValueError('独立安装目录不能嵌套在已有 AstrBot/ComfyUI 目录中')
    if plan.download_models and not plan.accept_model_license:
        raise ValueError('请阅读并确认模型许可后再勾选下载 Anima Base 1.0')
    if ((plan.download_models and not all((plan.unet, plan.clip, plan.vae))) or
            (plan.install_am and not plan.am_archive)) and not shutil.which('curl'):
        raise ValueError('模型/AM 下载需要 curl；Windows 请检查 curl.exe，Linux 请安装 curl')
    from easy_installer import load_optional_components
    known = {item['id'] for item in load_optional_components(ROOT)}
    if set(filter(None, plan.external.split(','))) - known:
        raise ValueError('可选组件 ID 不存在，请检查部署计划')
    for value in (plan.api_key, plan.bot_id):
        if any(c in value for c in '\r\n\0'):
            raise ValueError('凭据和 Bot ID 不能含换行')
    for value in (plan.unet, plan.clip, plan.vae):
        if value and not Path(value).is_file():
            raise ValueError('所选模型文件不存在；可暂时留空，部署后再配置')
    guard_runtime_versions(plan, root)
    return root


def run(command, log, cwd=None):
    # Commands never contain credentials. Full pip/git output goes to the install log.
    stream_command(command, log, cwd=cwd, stdin=subprocess.DEVNULL)


def python_at(folder):
    return Path(folder) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def make_env(path, log):
    python = python_at(path)
    if not python.is_file():
        run([sys.executable, '-m', 'venv', path], log)
    return python


def copy_source(source, target, *, preserve_gufeng=False):
    # Reject directory junctions and symbolic links before recursive copies/overwrites.
    for root in (Path(source), Path(target)):
        for parent in (root, *root.parents):
            if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
                raise ValueError('项目复制路径含符号链接或联接：' + str(parent))
        if root.is_dir():
            for parent, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = [d for d in dirs if d not in {'.venv', '__pycache__', 'tests'}]
                if preserve_gufeng and Path(parent).relative_to(root) == Path('resources'):
                    dirs[:] = [d for d in dirs if d != 'gufeng']
                for name in dirs + files:
                    item = Path(parent) / name
                    if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
                        raise ValueError('项目目录包含链接，请先人工检查：' + str(item))
    def ignore(folder, names):
        excluded = shutil.ignore_patterns('tests', '__pycache__', '*.pyc', '.env', '.venv', '.git')(folder, names)
        if preserve_gufeng and Path(folder).relative_to(source) == Path('resources'):
            excluded.add('gufeng')
        return excluded
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=ignore)


def quick_workflow(plan, comfy, log):
    model_names = []
    for value, folder in ((plan.unet, 'diffusion_models'), (plan.clip, 'text_encoders'), (plan.vae, 'vae')):
        if not value:
            return None
        source = Path(value).resolve()
        model_root = comfy / 'models' / folder
        no_links(model_root)
        model_root.mkdir(parents=True, exist_ok=True)
        if source.is_relative_to(model_root.resolve()):
            model_names.append(source.relative_to(model_root.resolve()).as_posix())
        else:
            target = model_root / source.name
            if target.exists() and target.resolve() != source:
                raise ValueError(f'模型目标已存在，请直接选择已安装文件：{target}')
            if not target.exists():
                log('复制所选模型：' + source.name)
                shutil.copy2(source, target)
            model_names.append(source.name)
    def node(kind, **inputs):
        return {'class_type': kind, 'inputs': inputs}
    return {
        '1': node('UNETLoader', unet_name=model_names[0], weight_dtype='default'),
        '2': node('CLIPLoader', clip_name=model_names[1], type='stable_diffusion', device='default'),
        '3': node('VAELoader', vae_name=model_names[2]),
        '11': node('CLIPTextEncode', clip=['2', 0], text=''),
        '12': node('CLIPTextEncode', clip=['2', 0], text=''),
        '28': node('EmptyLatentImage', width=1024, height=1536, batch_size=1),
        '19': node('KSampler', model=['1', 0], positive=['11', 0], negative=['12', 0], latent_image=['28', 0],
                   seed=1, steps=30, cfg=5.0, sampler_name='er_sde', scheduler='normal', denoise=1.0),
        '8': node('VAEDecode', samples=['19', 0], vae=['3', 0]),
        '9': node('SaveImage', images=['8', 0], filename_prefix='AstrAutoAnima'),
    }


def configured_anima_workflow(workflows, quick, template_name, target_name):
    """Bind selected base models in a new copy, bypassing only release placeholder LoRAs."""
    template, target = workflows / template_name, workflows / target_name
    if target.exists():
        return target
    if quick is None:
        return template
    graph = json.loads(template.read_text('utf-8-sig'))
    for ident, field, source in (('44', 'unet_name', '1'), ('45', 'clip_name', '2'), ('15', 'vae_name', '3')):
        if str(graph[ident]['inputs'][field]).startswith('YOUR_ANIMA_'):
            graph[ident]['inputs'][field] = quick[source]['inputs'][field]
    for ident in reversed(list(graph)):
        node = graph[ident]
        if node.get('class_type') != 'LoraLoader' or not str(node['inputs'].get('lora_name', '')).startswith('YOUR_STYLE_LORA_'):
            continue
        for other in graph.values():
            for field, value in other.get('inputs', {}).items():
                if isinstance(value, list) and len(value) == 2 and value[0] == ident:
                    if value[1] not in (0, 1):
                        raise ValueError('画风占位节点输出索引错误：' + ident)
                    other['inputs'][field] = list(node['inputs']['model' if value[1] == 0 else 'clip'])
        del graph[ident]
    json_write(target, graph)
    return target


def prepare_comfy_source(comfy, root, plan, log):
    if (comfy / 'main.py').is_file():
        return
    try:
        run(['git', 'clone', '--branch', 'v0.21.1', '--depth', '1', 'https://github.com/Comfy-Org/ComfyUI.git', comfy], log)
        return
    except (ValueError, RuntimeError, subprocess.CalledProcessError):
        log('Git 传输中断，改用同版本官方 ZIP。已有目录保留为备份。')
    from easy_installer import download_file
    from download_network import DownloadNetwork
    archive = root / 'downloads/ComfyUI-v0.21.1.zip'
    download_file('https://codeload.github.com/Comfy-Org/ComfyUI/zip/refs/tags/v0.21.1', archive, log,
                  expected_sha256='85ed01bf9c737c42f5e36b6935c872fb1a1691041914ebe632c653ef5430b071',
                  expected_size=11504590, network=DownloadNetwork.from_plan(plan))
    with tempfile.TemporaryDirectory(prefix='aaa-comfy-', dir=root) as directory:
        staging = Path(directory)
        with zipfile.ZipFile(archive) as z:
            total = 0
            for entry in z.infolist():
                name = entry.filename.replace('\\', '/')
                total += entry.file_size
                if (not name.startswith('ComfyUI-0.21.1/') or '..' in Path(name).parts or ':' in name
                        or (entry.external_attr >> 16) & 0o170000 == 0o120000 or total > 100_000_000):
                    raise ValueError('ComfyUI ZIP 路径或大小异常')
            if z.testzip():
                raise ValueError('ComfyUI ZIP 校验失败')
            z.extractall(staging)
        source = staging / 'ComfyUI-0.21.1'
        if not (source / 'main.py').is_file() or not (source / 'requirements.txt').is_file():
            raise ValueError('ComfyUI ZIP 缺少入口文件')
        if comfy.exists():
            comfy.rename(comfy.with_name(comfy.name + '.clone-backup-' + secrets.token_hex(4)))
        shutil.copytree(source, comfy)


def configure(plan, root, astro, comfy):
    data = astro / 'data'
    plugin = data / 'plugins/astrbot_plugin_comfy_bridge'
    plugin_data = data / 'plugin_data/astrbot_plugin_comfy_bridge'
    config_file = data / 'config/astrbot_plugin_comfy_bridge_config.json'
    # Preserve ALL existing settings and presets; generate only missing configuration keys.
    config = json.loads(config_file.read_text('utf-8-sig')) if config_file.exists() else {}
    config.setdefault('comfyui_output_root', str(comfy / 'output'))
    config.setdefault('style_lora_node_ids', '')
    config.setdefault('hq_use_seedvr2', False)
    workflows = comfy / 'user/default/workflows'
    quick_path = workflows / 'AAA_Quick_Local_api.json'
    quick = json.loads(quick_path.read_text('utf-8-sig')) if quick_path.is_file() else None
    for key, template, target in (
        ('hq_workflow_path', 'Anima_HQ_Txt2Img_Beta_api.json', 'AAA_Anima_HQ_Configured_api.json'),
        ('refine_workflow_path', 'Anima_Refine_Existing_Beta_api.json', 'AAA_Anima_Refine_Configured_api.json'),
    ):
        if key not in config and quick is not None:
            config[key] = str(configured_anima_workflow(workflows, quick, template, target))
    selected = set(plan.external.split(','))
    if 'booru_tagger_node' in selected and 'joycaption_node' not in selected:
        config.setdefault('reverse_workflow_path', str(workflows / 'Anima_WD_Only_Reverse_api.json'))
    for key, file in {
        'workflow_path': 'AAA_Quick_Local_api.json', 'hq_workflow_path': 'Anima_HQ_Txt2Img_Beta_api.json',
        'refine_workflow_path': 'Anima_Refine_Existing_Beta_api.json',
        'seedvr2_workflow_path': 'Anima_SeedVR2_Refine_Beta_api.json',
        'detail_repair_workflow_path': 'Anima_Detail_Repair_Beta_api.json',
        'reverse_workflow_path': 'Anima_WD_CT_JoyCaption_Reverse_Beta_api.json',
    }.items():
        config.setdefault(key, str(comfy / 'user/default/workflows' / file))
    for key, name in {'preset_store_path': 'presets.json', 'prompt_pool_path': 'anima_random_prompt_pool.json',
                      'output_dir': 'outputs', 'input_dir': 'inputs', 'job_store_path': 'job_store',
                      'reverse_history_dir': 'reverse_history', 'character_dictionary_edits_path': 'hub_state/character_dictionary_edits.json'}.items():
        config.setdefault(key, str(plugin_data / name))
    json_write(config_file, config, True)
    env_file = root / 'runtime-env.full.json'
    if not env_file.exists() and (root / 'runtime-env.json').is_file():
        previous = json.loads((root / 'runtime-env.json').read_text('utf-8'))
        if previous.get('AAH_EXECUTION_MODE', 'remote') != 'local':
            env_file = root / 'runtime-env.json'
    env = json.loads(env_file.read_text('utf-8')) if env_file.exists() else {}
    defaults = {
        'AAH_EXECUTION_MODE': 'remote', 'AAH_HOST': '127.0.0.1', 'AAH_PORT': '6278',
        'AAH_ADMIN_TOKEN': secrets.token_urlsafe(48),
        'AAH_PLUGIN_DIR': str(plugin), 'AAH_PLUGIN_DATA_DIR': str(plugin_data), 'AAH_COMFYUI_ROOT': str(comfy),
        'AAH_ASTRBOT_URL': 'http://127.0.0.1:6185', 'AAH_COMFYUI_URL': 'http://127.0.0.1:8188',
        'AAH_ASTRBOT_API_KEY': plan.api_key, 'AAH_ASTRBOT_BOT_ID': plan.bot_id or 'your-bot-id',
    }
    for key, value in defaults.items():
        env.setdefault(key, value)
    if (root / 'hub/web/index.html').is_file():
        env.setdefault('AAH_WEB_ROOT', str(root / 'hub/web'))
    # Explicitly entered credentials may be added after initial bootstrap, never logged.
    if plan.api_key:
        env['AAH_ASTRBOT_API_KEY'] = plan.api_key
    if plan.bot_id:
        env['AAH_ASTRBOT_BOT_ID'] = plan.bot_id
    json_write(root / 'runtime-env.full.json', env, True)
    json_write(root / 'runtime-env.json', env, True)
    return env


def health(url):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=2) as response:
            return json.load(response)
    except Exception:
        return None


def port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.3):
            return True
    except OSError:
        return False


def start_services(root, log=print, profile=None):
    root = checked_root(str(root))
    if profile not in (None, 'local', 'full'):
        raise ValueError('启动档位必须为 local 或 full')
    suffix = '.' + profile if profile else ''
    env_name, services_name = 'runtime-env' + suffix + '.json', 'services' + suffix + '.json'
    for filename in (env_name, services_name):
        if not (root / filename).is_file():
            raise ValueError(f'缺少 {filename}：请先完成部署，不要手动新建空配置；当前目录：{root}')
    settings = json.loads((root / env_name).read_text('utf-8'))
    services = json.loads((root / services_name).read_text('utf-8'))
    notice = relocation_notice(root, services)
    if notice:
        log(notice)
        return [notice]
    expected_mode = settings.get('AAH_EXECUTION_MODE', 'remote')
    if expected_mode not in ('local', 'remote'):
        raise ValueError('Hub 执行模式无效')
    if port_open(6278):
        existing = health('http://127.0.0.1:6278/api/v1/health')
        if isinstance(existing, dict) and existing.get('service') == 'astr-auto-anima-hub':
            actual_mode = existing.get('execution_mode', 'remote')
            if actual_mode != expected_mode:
                raise ValueError(f'Hub 当前运行 {actual_mode} 模式；请先正常停止，再启动 {expected_mode} 模式')
    reports = []
    for service in services:
        log("正在检查服务：" + service["name"])
        report(log, kind="activity", name=service["name"], current=None, total=None)
        if service.get('mode') == 'desktop':
            reports.append('AstrBot Desktop：' + ('6185 端口已有服务，请在桌面端确认插件已加载' if port_open(service['port']) else '请手动打开 AstrBot Desktop；本入口不会启动第二套后端'))
            continue
        if port_open(service['port']):
            check = health(service['health']) if service.get('health') else None
            if (service['name'] == 'Hub' and isinstance(check, dict) and check.get('service') == 'astr-auto-anima-hub'
                    and check.get('execution_mode', 'remote') == expected_mode) or (
                    service['name'] == 'ComfyUI' and isinstance(check, dict) and 'system' in check):
                reports.append(service['name'] + ' 已就绪（复用）')
            else:
                reports.append(service['name'] + ' 端口已被占用，未启动第二份；请确认原服务')
            continue
        command = service['command']
        if not Path(service['cwd']).is_dir():
            reports.append(service['name'] + ' 工作目录不存在，请恢复原目录或重新配置：' + service['cwd'])
            continue
        if not Path(command[0]).is_file():
            reports.append(service['name'] + ' 未配置可执行环境，需手动启动原服务')
            continue
        options = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS} if os.name == 'nt' else {'start_new_session': True}
        logfile = root / (service['name'] + '.log')
        with logfile.open('ab') as stream:
            process = subprocess.Popen(command, cwd=service['cwd'], env={**os.environ, **settings},
                                       stdin=subprocess.DEVNULL, stdout=stream, stderr=stream, **options)
        deadline = time.monotonic() + 120
        last_wait = time.monotonic()
        while time.monotonic() < deadline and process.poll() is None:
            result = health(service['health']) if service.get('health') else None
            if (isinstance(result, dict) and (result.get('service') == 'astr-auto-anima-hub' or 'system' in result)) or (not service.get('health') and port_open(service['port'])):
                reports.append(service['name'] + ' 已启动并通过' + ('健康检查' if service.get('health') else '端口检查（仍需登录配置）'))
                break
            if time.monotonic() - last_wait >= 10:
                log(service["name"] + " 启动中；日志：" + str(logfile))
                last_wait = time.monotonic()
            time.sleep(1)
        else:
            reports.append(service['name'] + ' 尚未就绪；日志：' + str(logfile))
    for line in reports:
        log(line)
    json_write(root / 'health-report.json', {'services': reports, 'time': time.time()})
    return reports


def deploy(plan, log=print):
    root = validate(plan)
    if plan.deployment_profile == 'local' and not (ROOT / 'hub/service/src/astr_auto_anima_hub/local_jobs.py').is_file():
        raise ValueError('发布包内 Hub 不支持本机执行；请换用包含本机工作站的新版懒人包')
    root.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        root.chmod(0o700)
    (root / MARKER).touch()
    no_links(root / '.deploy.lock')
    if (root / '.deploy.lock').exists():
        raise ValueError('检测到旧版 .deploy.lock，请先确认旧安装器已退出；不会删除旧标记。')
    from easy_installer import download_lock
    with download_lock(root / '.deploy-session'):
        progress = DeploymentProgress(root, log)
        try:
            safe_plan = asdict(plan); safe_plan['api_key'] = ''
            json_write(root / 'last-plan.json', safe_plan, True)
            progress.stage('prepare')
            full = plan.deployment_profile == 'full'
            astro = ((root / 'astrbot') if plan.install_astrbot else Path(plan.astrbot).resolve()) if full else None
            comfy = (root / 'ComfyUI') if plan.install_comfyui else Path(plan.comfyui).resolve()
            # Existing apps are not installed over; this operation only adds project files.
            ports = ([('AstrBot', 6185)] if full else []) + [('ComfyUI', 8188), ('Hub', 6278)]
            for name, port in ports:
                if port_open(port):
                    raise ValueError(f'{name} 正在运行或端口 {port} 已占用；请先正常关闭，再部署。不会自动强杀进程')
            hub_python = python_at(root / 'hub/.venv')
            if plan.install_dependencies:
                hub_python = make_env(root / 'hub/.venv', log)
            elif not hub_python.is_file():
                raise ValueError('首次部署 Hub 需要勾选“允许安装依赖”；不会擅自联网')
            apy = (Path(plan.astrbot_python) if plan.astrbot_python else python_at(astro / '.venv')) if full else None
            cpy = Path(plan.comfy_python) if plan.comfy_python else python_at(comfy / '.venv')
            progress.stage('environments')
            if not (full and plan.install_astrbot) and not plan.install_comfyui:
                progress.skip('复用已有环境')
            if full and plan.install_astrbot:
                astro.mkdir(parents=True, exist_ok=True)
                apy = make_env(astro / '.venv', log)
                run([apy, '-m', 'pip', 'install', 'astrbot==4.27.2'], log)
                executable = apy.parent / ('astrbot.exe' if os.name == 'nt' else 'astrbot')
                if not (astro / 'data/cmd_config.json').is_file():
                    run([executable, 'init', '--yes'], log, astro)
            if plan.install_comfyui:
                prepare_comfy_source(comfy, root, plan, log)
                cpy = make_env(comfy / '.venv', log)
                index = 'https://download.pytorch.org/whl/cu128' if plan.gpu else 'https://download.pytorch.org/whl/cpu'
                # Separate the large Torch wheel source from ordinary Python/CUDA dependencies.
                variant = 'cu128' if plan.gpu else 'cpu'
                run([cpy, '-m', 'pip', 'install', f'torch==2.11.0+{variant}', f'torchvision==0.26.0+{variant}', f'torchaudio==2.11.0+{variant}', '--extra-index-url', index], log)
                run([cpy, '-m', 'pip', 'install', '-r', comfy / 'requirements.txt'], log)
            progress.stage('project')
            plugin = astro / 'data/plugins/astrbot_plugin_comfy_bridge' if full else None
            node = comfy / 'custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools'
            backup = root / ('backup_' + time.strftime('%Y%m%d_%H%M%S') + '_' + secrets.token_hex(3))
            targets = [(ROOT / 'hub/service', root / 'hub', 'hub')]
            if full:
                targets.insert(0, (ROOT / 'plugin/astrbot_plugin_comfy_bridge', plugin, 'plugin'))
                targets.insert(1, (ROOT / 'comfyui/custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools', node, 'nodes'))
            for source, target, name in targets:
                if target.exists():
                    # The optional 1 GB catalog is immutable and hash checked by its
                    # own installer. Do not duplicate it in every code backup.
                    copy_source(target, backup / name, preserve_gufeng=name == 'hub')
                copy_source(source, target, preserve_gufeng=name == 'hub')
            workflows = comfy / 'user/default/workflows'
            workflows.mkdir(parents=True, exist_ok=True)
            for file in (ROOT / 'comfyui/workflows').glob('*.json'):
                dest = workflows / file.name
                if not dest.exists():
                    shutil.copy2(file, dest)
            progress.stage('dependencies')
            if plan.install_dependencies:
                run([hub_python, '-m', 'pip', 'install', '-e', root / 'hub'], log)
                if full and plan.astrbot_mode != 'desktop' and apy.is_file():
                    run([apy, '-m', 'pip', 'install', '-r', plugin / 'requirements.txt'], log)
                if full and cpy.is_file():
                    run([cpy, '-m', 'pip', 'install', '-r', node / 'requirements.txt'], log)
            if not plan.install_dependencies:
                progress.skip('未勾选安装依赖')
            progress.stage('optional')
            if full and plan.external:
                from easy_installer import InstallPlan, install_external
                from download_network import DownloadNetwork
                install_external(InstallPlan(ROOT, astro / 'data', comfy, root / 'hub',
                                 external=set(plan.external.split(',')), comfy_python=cpy,
                                 install_external_requirements=plan.install_dependencies, apply=True,
                                 download_network=DownloadNetwork.from_plan(plan)), backup, log)
            if not (full and plan.external):
                progress.skip('未勾选外部扩展')
            progress.stage('models')
            if plan.download_models:
                download_base_models(ROOT, comfy, plan, log)
            flow = quick_workflow(plan, comfy, log)
            if flow is not None and not (workflows / 'AAA_Quick_Local_api.json').exists():
                json_write(workflows / 'AAA_Quick_Local_api.json', flow)
            progress.stage('configuration')
            gufeng_catalog = None
            if plan.install_gufeng:
                from gufeng_resource import install_module, selected_module
                gufeng_catalog = install_module(selected_module(plan, ROOT), root, log)
            if full:
                config = astro / 'data/config/astrbot_plugin_comfy_bridge_config.json'
                if config.exists():
                    backup.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(config, backup / 'plugin_config.json')
                env = configure(plan, root, astro, comfy)
                # Full installation retains a local route without installing a second
                # Hub/ComfyUI. Preserve any previously customized local profile.
                if not (root / 'runtime-env.local.json').exists() or gufeng_catalog is not None:
                    local_flow = local_hq_workflow(comfy, workflows, flow)
                    configure_local(root, comfy, local_flow, activate=False, gufeng_catalog=gufeng_catalog)
            else:
                local_flow = local_hq_workflow(comfy, workflows, flow)
                env = configure_local(root, comfy, local_flow, gufeng_catalog=gufeng_catalog)
            from project_components import prepare_components, initialize_local_data
            prepare_components(ROOT, root, plan.deployment_profile, json_write)
            initialize_local_data(root, json_write)
            if full and plan.install_am:
                from download_network import DownloadNetwork
                am = install_anima_master(astro, root, log, copy_source,
                                         local_archive=plan.am_archive, network=DownloadNetwork.from_plan(plan))
                if plan.install_dependencies and plan.astrbot_mode != 'desktop':
                    run([apy, '-m', 'pip', 'install', '-r', am / 'requirements.txt'], log)
                configure_anima_master(astro, comfy, root, json_write)
            progress.stage('launchers')
            # API key never goes into the reusable plan.
            safe_plan = asdict(plan)
            safe_plan['api_key'] = ''
            json_write(root / 'last-plan.json', safe_plan, True)
            services = [
                {'name': 'ComfyUI', 'command': [str(cpy), 'main.py', '--listen', '127.0.0.1', '--port', '8188'] + ([] if plan.gpu else ['--cpu']), 'cwd': str(comfy), 'port': 8188, 'health': 'http://127.0.0.1:8188/system_stats'},
            ]
            if full:
                services.append({'name': 'AstrBot', 'mode': plan.astrbot_mode,
                                 'command': [str(apy.parent / ('astrbot.exe' if os.name == 'nt' else 'astrbot')), 'run', '--port', '6185'],
                                 'cwd': str(astro), 'port': 6185})
            services.append({'name': 'Hub', 'command': [str(hub_python), '-m', 'astr_auto_anima_hub'],
                             'cwd': str(root / 'hub'), 'port': 6278, 'health': 'http://127.0.0.1:6278/api/v1/health'})
            json_write(root / ('services.' + plan.deployment_profile + '.json'), services)
            json_write(root / 'services.json', services)
            if full and not (root / 'services.local.json').exists():
                json_write(root / 'services.local.json',
                           [service for service in services if service['name'] != 'AstrBot'])
            # Self-contained start entry survives moving/deleting the downloaded release.
            shutil.copy2(Path(__file__), root / 'deploy_project.py')
            shutil.copy2(Path(__file__).with_name('deployment_support.py'), root / 'deployment_support.py')
            shutil.copy2(Path(__file__).with_name('download_network.py'), root / 'download_network.py')
            shutil.copy2(Path(__file__).with_name('install_progress.py'), root / 'install_progress.py')
            shutil.copy2(Path(__file__).with_name('project_components.py'), root / 'project_components.py')
            shutil.copy2(Path(__file__).with_name('gufeng_resource.py'), root / 'gufeng_resource.py')
            if os.name == 'nt':
                (root / 'Start.cmd').write_text(windows_start_script(plan.deployment_profile), 'ascii', newline='')
                for profile in (('local', 'full') if full else ('local',)):
                    (root / ('Start-' + profile.capitalize() + '.cmd')).write_text(
                        windows_start_script(profile), 'ascii', newline='')
            else:
                content = ('#!/bin/sh\nset -eu\nD=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
                           'exec "$D/hub/.venv/bin/python" "$D/deploy_project.py" --start "$D" --profile '
                           + plan.deployment_profile + '\n')
                for name in ('Start.sh', 'Start-' + plan.deployment_profile.capitalize() + '.sh'):
                    (root / name).write_text(content, 'utf-8')
                    (root / name).chmod(0o700)
                if full:
                    (root / 'Start-Local.sh').write_text(content.replace('--profile full', '--profile local'), 'utf-8')
                    (root / 'Start-Local.sh').chmod(0o700)
            missing = []
            if full and plan.astrbot_mode == 'desktop':
                missing.append('手动启动 AstrBot Desktop；若插件缺依赖，请通过其插件管理器安装 requests / pillow，勿给内置运行时盲目 pip 升级')
            if full:
                missing.append('已包含 Start-Local 本机入口，无需重复安装；先正常停止远程 Hub 再切换，本机数据/令牌独立。')
                missing.append('Anima Master：兼容基线 0.7.1；上游 0.9.1 未联调，不自动升级。详细配置见发布包 docs/ANIMA_MASTER.md')
                if not (astro / 'data/plugins/astrbot_plugin_anima_master/metadata.yaml').is_file():
                    missing.append('尚未安装核心上游 Anima Master：重新运行向导显式勾选安装 0.7.1，或在插件页安装固定版本')
            if not (workflows / 'AAA_Quick_Local_api.json').exists():
                missing.append('选择 Anima UNET / CLIP / VAE 或自行设置工作流；模型未随包分发')
            if full and not env.get('AAH_ASTRBOT_API_KEY'):
                missing.append('AstrBot 设置 → OpenAPI 创建 chat/message 所需授权 API Key，重新运行向导填写（不绕过授权）')
            if full and env.get('AAH_ASTRBOT_BOT_ID') == 'your-bot-id':
                missing.append('在 AstrBot 配置实际平台 Bot ID；使用 QQ 时还需 NapCat 登录及 OneBot 对接')
            if not full:
                missing.append('本机 Hub 无需 AstrBot/QQ；英文生图可直接使用，中文生图请配置 AAH_LOCAL_LLM_BASE_URL 和 AAH_LOCAL_LLM_MODEL。')
                if flow is None:
                    missing.append('尚未指定完整 UNET/CLIP/VAE；请在本机工作流设置真实模型文件名后再生图。')
                missing.append('日后可在同一目录选择完整服务部署；先正常停止本机 Hub，再运行 Start-Full。')
            (root / '下一步.txt').write_text('部署后仍需完成：\n' + '\n'.join(missing) + '\n管理员令牌仅保存在 runtime-env.json；不要分享此文件。\n', 'utf-8')
            log('文件及依赖部署完成，开始启动与健康检查；这不等于已经通过实际生图验收。')
            progress.stage('services')
            reports = start_services(root, log, profile=plan.deployment_profile)
            attention = any(any(word in row for word in ('尚未就绪','占用','不存在','未配置','请手动','搬迁','尚未完成')) for row in reports)
            progress.finish('needs_attention' if attention or missing else 'completed')
            for message in missing:
                log('待配置：' + message)
            log('运行目录：' + str(root) + '；以后双击 Start.cmd 或执行 Start.sh 即可启动。')
            return {'status': progress.data['status'], 'reports': reports, 'pending': missing}
        except BaseException:
            try: progress.finish('failed')
            except OSError: pass
            log('部署已中断，保留安装目录和日志。修正后重新预检，不删除重装。')
            raise

def wizard(platform='auto', smoke=False, extension=''):
    if extension:
        if platform not in ('auto', host_platform()): raise ValueError('扩展安装平台与本机不匹配。')
        from extension_installer import launch_gui
        return launch_gui(extension, smoke=smoke)
    from extension_guide import component_selection
    selected_components = [c['id'] for c in component_selection(extension, ROOT)] if extension else []
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    app = tk.Tk()
    app.title('AstrAutoAnima 0.5.0 Beta 一键部署')
    app.geometry(f'980x{min(850, max(600, app.winfo_screenheight() - 100))}')
    if smoke: app.withdraw()
    heading = ttk.Frame(app, padding=12); heading.pack(fill='x')
    ttk.Label(heading, text='先部署文件，再配置授权，最后验收首张图', font=('Microsoft YaHei UI', 15, 'bold')).pack(anchor='w')
    ttk.Label(heading, text='首次：①目录与环境 → ②模型与下载 → ③只做预检 → ④确认部署\n安装目录要长期保留，不要选下载/临时文件夹；安装后不能直接改名/移动。\n已安装：载入上次填写；日常用“仅启动已有服务”，搬家先停止服务并使用专用工具。', wraplength=900).pack(anchor='w', pady=4)
    progress_hint = tk.StringVar(value='所有外部下载默认不选。词库、角色、HQ、反推可等普通生图成功后再配置。')
    ttk.Label(heading, textvariable=progress_hint, wraplength=900).pack(anchor='w')
    # Outside the scrolling form: always visible during a long-running install.
    monitor = ProgressPanel(app, DISPLAY_STEPS)
    monitor.frame.pack(fill='x', padx=12, pady=(0, 6))
    canvas = tk.Canvas(app)
    scrollbar = ttk.Scrollbar(app, orient='vertical', command=canvas.yview)
    scrollbar.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    canvas.configure(yscrollcommand=scrollbar.set)
    frame = ttk.Frame(canvas, padding=12)
    window = canvas.create_window((0, 0), window=frame, anchor='nw')
    frame.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda event: canvas.itemconfigure(window, width=event.width))
    frame.columnconfigure(1, weight=1)
    values = {}
    explanations = {
        'destination': '选固定位置，例如 D:\\AAA-install。默认在用户目录的 AstrAutoAnima-install，不跟随下载包位置。不要选下载/临时文件夹；安装后直接改名会使路径失效，需要用搬家工具。首次可创建；失败续接选原目录。',
        'astrbot': '已有 CLI：选真正含 data 的运行目录。已有桌面版：类型选 desktop，通常数据根是用户目录下 .astrbot，不是含 backend/webui/exe 的程序安装目录。新装则勾选下载全新 AstrBot，可留空。',
        'comfyui': '选含 main.py 的 ComfyUI 目录，或 portable 的外层目录；不要选 models/output。Comfy Desktop 请找到其实际安装的 ComfyUI，不是桌面快捷方式。全新下载可留空。',
        'astrbot_python': '已有 CLI 自动查找 .venv，找不到才选择实际 python.exe / bin/python；同目录应有 astrbot 启动器。桌面版 desktop 不填，不修改其内置运行时。',
        'comfy_python': '通常自动发现 .venv 或 portable/python_embeded。找不到才选平时启动这套 ComfyUI 使用的 Python；不要随便选系统 Python。',
        'unet': '基础模型：选择 Anima 的 diffusion model .safetensors，不是 LoRA。没有则勾选下载默认三件套并阅读许可；留空允许先部署，但无法生图。',
        'clip': '文本编码器：默认三件套对应 qwen_3_06b_base.safetensors，放入 models/text_encoders。不是把 UNET 再选一次。',
        'vae': '图像编解码器：默认对应 qwen_image_vae.safetensors，放入 models/vae。已有模型选原文件，不必复制到新的目录。',
        'bot_id': 'QQ 对话发 /sid 后获得平台 Bot ID，不是群号或机器人 QQ。暂时不知道可留空，部署后在首次配置向导补齐。',
        'api_key': 'AstrBot 设置 → OpenAPI 创建时复制完整密钥；不是列表短前缀、登录密码或 Hub 令牌。留空不会清除已保存 Key；第一次可稍后在首次配置向导填写。不要截图发群。',
    }
    fields = [('destination', '独立安装目录', default_install_directory()),
              ('astrbot', '已有 AstrBot 根目录（含 data）', ''), ('comfyui', '已有 ComfyUI 根目录', ''),
              ('astrbot_python', '已有 AstrBot Python（可选）', ''), ('comfy_python', '已有 ComfyUI Python（可选）', ''),
              ('unet', 'Anima UNET 文件（可稍后填写）', ''), ('clip', 'CLIP 文件', ''), ('vae', 'VAE 文件', ''),
              ('bot_id', 'AstrBot 平台 Bot ID（可稍后填写）', ''), ('api_key', 'AstrBot OpenAPI Key（仅存本机）', '')]
    for row, (key, label, default) in enumerate(fields):
        value = tk.StringVar(value=default)
        values[key] = value
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w')
        ttk.Entry(frame, textvariable=value, show='*' if key == 'api_key' else '').grid(row=row, column=1, sticky='ew', pady=2)
        ttk.Button(frame, text='怎么填', command=lambda key=key, label=label: messagebox.showinfo(label, explanations[key], parent=app)).grid(row=row, column=3, padx=3)
        if key not in {'api_key', 'bot_id'}:
            def choose(v=value, directory=key in {'destination', 'astrbot', 'comfyui'}, must_exist=key != 'destination'):
                chosen = filedialog.askdirectory(mustexist=must_exist) if directory else filedialog.askopenfilename()
                if chosen:
                    v.set(chosen)
            ttk.Button(frame, text='选择', command=choose).grid(row=row, column=2)
    platform_value = tk.StringVar(value=host_platform() if platform == 'auto' else platform)
    mode_value = tk.StringVar(value='cli')
    ttk.Label(frame, text='目标系统（必须与当前机器一致）').grid(row=10, column=0, sticky='w')
    ttk.Combobox(frame, textvariable=platform_value, values=['windows', 'linux'], state='readonly').grid(row=10, column=1, sticky='ew')
    ttk.Label(frame, text='AstrBot 类型：cli / 已有桌面版 desktop').grid(row=11, column=0, sticky='w')
    ttk.Combobox(frame, textvariable=mode_value, values=['cli', 'desktop'] if host_platform() == 'windows' else ['cli'], state='readonly').grid(row=11, column=1, sticky='ew')
    opts = {}
    for row, (key, label, default) in enumerate([
        ('install_dependencies', '允许联网安装 Python 依赖（首次 Hub 必选）', False),
        ('install_astrbot', '下载全新 AstrBot 4.27.2（需 Python 3.12+，不修改已有服务）', False),
        ('install_comfyui', '下载全新 ComfyUI v0.21.1 和 PyTorch（数 GB）', False),
        ('gpu', '使用 NVIDIA GPU（驱动须已安装；取消则 CPU 仅供部署验证）', True),
        ('download_models', '下载默认 Anima Base 1.0 + CLIP + VAE（约 5.63 GB；已选本地文件优先）', False),
        ('accept_model_license', '已阅读并同意模型许可（请先打开下方模型说明）', False),
        ('install_am', '安装核心上游 Anima Master 0.7.1（固定版本，外部下载）', False),
    ], start=12):
        opts[key] = tk.BooleanVar(value=default)
        ttk.Checkbutton(frame, text=label, variable=opts[key]).grid(row=row, column=0, columnspan=3, sticky='w')
    from easy_installer import load_optional_components
    optional = {}
    box = ttk.LabelFrame(frame, text='可选节点 / 模型下载（默认不选；训练组件不包含）')
    box.grid(row=20, column=0, columnspan=3, sticky='ew')
    import webbrowser
    ttk.Button(frame, text='官方模型 / 下载链接 / 许可', command=lambda: webbrowser.open('https://huggingface.co/circlestone-labs/Anima')).grid(row=19, column=0, columnspan=3)
    for i, item in enumerate(load_optional_components(ROOT)):
        optional[item['id']] = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text=item['name'], variable=optional[item['id']]).grid(row=i // 2, column=i % 2, sticky='w')
    network_box = ttk.LabelFrame(frame, text='公开文件下载：模型 / AM ZIP（不修改服务 API；Git / pip / winget 另用各自网络设置）')
    network_box.grid(row=21, column=0, columnspan=3, sticky='ew', pady=8)
    network_box.columnconfigure(1, weight=1)
    values['download_mode'] = tk.StringVar(value='official')
    ttk.Label(network_box, text='方式：官方 / 镜像 / 魔搭 / 代理 / 本地').grid(row=0, column=0, sticky='w')
    ttk.Combobox(network_box, textvariable=values['download_mode'], state='readonly',
                 values=['official', 'mirror', 'modelscope', 'proxy', 'local']).grid(row=0, column=1, sticky='ew')
    def choose_hf_mirror():
        if messagebox.askyesno('选择第三方模型镜像', '将模型来源切换为 https://hf-mirror.com（非 Hugging Face 官方服务）。\n会替换当前 HF 镜像设置，不发送任何令牌；下载后仍核对固定 SHA256。\n镜像可用性随网络变化，是否使用？'):
            values['hf_mirror'].set('https://hf-mirror.com')
            values['download_mode'].set('mirror')
    ttk.Button(network_box, text='选用 HF-Mirror…', command=choose_hf_mirror).grid(row=0, column=2)
    for row, key, label in [(1, 'hf_mirror', 'HF 镜像 HTTPS 根地址（自行选择可信站点）'),
                            (2, 'github_mirror', 'GitHub 文件镜像 HTTPS 前缀（拼接完整原 URL）'),
                            (3, 'download_proxy', '文件代理 URL（如 http://127.0.0.1:7890）'),
                            (4, 'am_archive', '本地 Anima Master 0.7.1 ZIP（固定提交）')]:
        values[key] = tk.StringVar(value='')
        ttk.Label(network_box, text=label).grid(row=row, column=0, sticky='w')
        ttk.Entry(network_box, textvariable=values[key]).grid(row=row, column=1, sticky='ew')
    def choose_am():
        selected = filedialog.askopenfilename(filetypes=[('ZIP', '*.zip')])
        if selected:
            values['am_archive'].set(selected)
    ttk.Button(network_box, text='选择 ZIP', command=choose_am).grid(row=4, column=2)
    opts['revoke_best_effort'] = tk.BooleanVar(value=False)
    ttk.Checkbutton(network_box, text='仅 Windows：同意证书吊销离线兼容（仅 0x80092013；仍校验证书，降低吊销检查保障）',
                    variable=opts['revoke_best_effort'], state='normal' if os.name == 'nt' else 'disabled').grid(row=5, column=0, columnspan=3, sticky='w')
    ttk.Label(network_box, text='modelscope：仅 Anima 三件套走魔搭同哈希文件；其他文件仍走原官方源。已有 .part 可续传；所有渠道保留校验。本地模式并非离线安装依赖。', wraplength=850).grid(row=6, column=0, columnspan=3, sticky='w')
    opts['fallback_official'] = tk.BooleanVar(value=False)
    ttk.Checkbutton(network_box, text='镜像 / 魔搭失败后允许回退原官方源（可选；仍校验同一 SHA256）',
                    variable=opts['fallback_official']).grid(row=7, column=0, columnspan=3, sticky='w')
    ttk.Button(network_box, text='下载故障与本地导入说明', command=lambda: webbrowser.open((ROOT / 'docs/DOWNLOAD_NETWORK.md').as_uri())).grid(row=8, column=0, columnspan=3)
    output = tk.Text(frame, height=13, wrap='word')
    output.grid(row=23, column=0, columnspan=3, sticky='nsew')
    messages = queue.Queue()
    busy = False
    profiles = ttk.LabelFrame(frame, text='部署档位 / 本机可选资源（不随公开包分发私人资源）')
    profiles.grid(row=26, column=0, columnspan=3, sticky='ew')
    values['deployment_profile'] = tk.StringVar(value='full')
    ttk.Combobox(profiles, textvariable=values['deployment_profile'], values=['full','local'], state='readonly').pack(fill='x')
    ttk.Label(profiles, text='full：完整 AstrBot/QQ 服务；local：只装本机 Hub+ComfyUI，不选 AstrBot/AM/外部扩展。').pack(anchor='w')
    opts['install_gufeng'] = tk.BooleanVar(value=False)
    values['gufeng_module'] = tk.StringVar(value='')
    ttk.Checkbutton(profiles, text='显式安装自己已有的国风离线资源包（非必需，不随本包提供）', variable=opts['install_gufeng']).pack(anchor='w')
    ttk.Entry(profiles, textvariable=values['gufeng_module']).pack(fill='x')
    def collect_plan():
        return Plan(**{k: v.get().strip() for k, v in values.items()}, **{k: v.get() for k, v in opts.items()},
                    platform=platform_value.get(), astrbot_mode=mode_value.get(),
                    external=','.join(k for k, v in optional.items() if v.get()))
    def guard(action):
        def callback():
            if busy:
                messagebox.showinfo('操作进行中', '请等待本轮操作结束；不并发执行恢复或启动。', parent=app); return
            try: action()
            except Exception as exc: messagebox.showerror('需要处理', str(exc), parent=app)
        return callback
    def fill_plan(plan):
        for key, var in values.items(): var.set(getattr(plan, key))
        for key, var in opts.items(): var.set(getattr(plan, key))
        platform_value.set(host_platform() if plan.platform == 'auto' else plan.platform)
        mode_value.set(plan.astrbot_mode)
        for key, var in optional.items(): var.set(key in plan.external.split(','))
        for key in selected_components: optional[key].set(True)
    def restore_form():
        selected = filedialog.askopenfilename(title='选择原安装目录的 last-plan.json（不含 API Key）', filetypes=[('上次填写', 'last-plan.json')], parent=app)
        if not selected: return
        previous = load_previous_plan(selected)
        if not messagebox.askyesno('载入上次填写', '替换当前表单内容，API Key 输入框清空；已保存的运行密钥不变。\n不会安装、启动或修改磁盘配置。确认后请重新检查路径和下载勾选项。', parent=app): return
        fill_plan(previous)
        progress_hint.set(progress_text(Path(selected).parent))
    reset_groups = {
        '环境路径（保留独立安装目录）': ('astrbot', 'comfyui', 'astrbot_python', 'comfy_python'),
        '本地模型选择（不删除模型）': ('unet', 'clip', 'vae'),
        '下载方式（恢复官方；撤销镜像、代理与兼容授权）': ('download_mode', 'hf_mirror', 'github_mirror', 'download_proxy', 'am_archive', 'fallback_official', 'revoke_best_effort'),
        '外部下载勾选（全部取消，不卸载）': ('install_astrbot', 'install_comfyui', 'download_models', 'accept_model_license', 'install_am'),
    }
    def reset_group(name):
        defaults = Plan('')
        for key in reset_groups[name]: (values[key] if key in values else opts[key]).set(getattr(defaults, key))
        if name.startswith('外部'):
            for var in optional.values(): var.set(False)
        progress_hint.set('只重置了本窗口填写项；磁盘文件、模型、配置和令牌未改动。请先预检。')
    def reset_form():
        dialog = tk.Toplevel(app); dialog.title('只重置填写内容，不清空安装'); dialog.geometry('700x250')
        dialog.transient(app); dialog.grab_set()
        ttk.Label(dialog, text='用于填错路径、选错模型或切换网络。不会删除文件、恢复出厂或回滚已保存配置。', wraplength=650).pack(padx=15, pady=15)
        choice = tk.StringVar(value=next(iter(reset_groups)))
        ttk.Combobox(dialog, textvariable=choice, values=list(reset_groups), state='readonly', width=75).pack(padx=15, pady=10)
        def confirm():
            if messagebox.askyesno('确认仅重置这一组', choice.get() + '\n只改变表单，未执行安装。继续？', parent=dialog):
                reset_group(choice.get()); dialog.destroy()
        ttk.Button(dialog, text='重置所选填写组', command=confirm).pack(pady=10)
    def help_steps():
        dialog = tk.Toplevel(app); dialog.title('第一次部署 / 失败后继续'); dialog.geometry('880x680')
        view = tk.Text(dialog, wrap='word', padx=15, pady=15)
        scroll = ttk.Scrollbar(dialog, command=view.yview); scroll.pack(side='right', fill='y')
        view.configure(yscrollcommand=scroll.set); view.pack(fill='both', expand=True)
        view.insert('1.0', (ROOT / 'docs/EASY_INSTALL.md').read_text('utf-8')); view.configure(state='disabled')
    def preflight_only():
        monitor.reset((('preflight', '表单与目录预检'),))
        monitor.update({'kind': 'stages', 'stage': 'preflight', 'status': 'running', 'states': {'preflight': 'running'}})
        plan = collect_plan()
        try:
            target = validate(plan)
        except Exception as exc:
            monitor.finish('failed', '预检未通过：' + str(exc)); raise
        warnings = [f'{name} 的 {port} 端口占用；安装前需正常关闭。只启动则不会重复拉起。'
                    for name, port in [('AstrBot', 6185), ('ComfyUI', 8188), ('Hub', 6278)] if port_open(port)]
        text = f'表单预检通过。未安装、未下载、未写入。\n安装目录：{target}\nAstrBot 模式：{plan.astrbot_mode}\n\n' + '\n'.join(warnings)
        text += '\n这不验证远端下载速度、显卡或实际生图能力。'
        monitor.update({'kind': 'stages', 'stage': 'preflight', 'status': 'completed', 'states': {'preflight': 'done'}})
        monitor.finish('needs_attention' if warnings else 'completed', '预检通过，尚未开始安装。' + ('需先关闭占用端口的服务。' if warnings else ''))
        messagebox.showinfo('只做预检', text, parent=app)
    def launch(action, completed, services_only=False):
        nonlocal busy
        busy = True; button.config(state='disabled')
        monitor.reset((('services', '服务健康检查'),) if services_only else DISPLAY_STEPS)
        monitor.finish('running', '正在检查当前选择，请稍候…')
        def work():
            logger = ProgressLog(lambda line: messages.put(('log', line)), lambda event: messages.put(('progress', event)))
            try:
                tracker = StageProgress((('services', '服务健康检查'),), logger) if services_only else None
                if tracker: tracker.stage('services')
                result = action(logger)
                if isinstance(result, dict):
                    status = result.get('status', 'completed')
                else:
                    status = 'needs_attention' if any(any(w in row for w in ('尚未就绪', '占用', '不存在', '未配置', '请手动', '停止启动')) for row in (result or [])) else 'completed'
                if tracker:
                    if status == 'needs_attention': tracker.attention('服务仍有待处理项')
                    tracker.finish(status)
                message = completed
                if status == 'needs_attention':
                    message = '文件部署／启动检查已结束，仍有项目需处理。请看下方待配置项或安装目录中的“下一步.txt”，不要重复点击部署。'
                messages.put(('done', (status, message)))
            except Exception as exc:
                messages.put(('done', ('failed', '操作中断：' + str(exc) + '\n保留原目录。修正后载入上次填写；只是服务未就绪时用“仅启动已有服务”。')))
        threading.Thread(target=work, daemon=True).start()
    def start_existing():
        target = checked_root(values['destination'].get())
        if not all((target / name).is_file() for name in ('runtime-env.json', 'services.json')):
            raise ValueError('还没有完整启动配置，请先继续部署。不要手动创建空文件。')
        if messagebox.askyesno('仅启动已有服务', f'目录：{target}\n不复制源码、不安装依赖、不下载模型、不重新生成令牌。\n已有运行服务只检查不重启；AstrBot Desktop 请手动打开。继续？', parent=app):
            launch(lambda log: start_services(target, log), '启动检查结束。请查看各服务结果；需修改连接时打开首次配置向导。', services_only=True)
    def first_run():
        script = ROOT / 'tools/first_run_wizard.py'
        if not script.is_file(): raise ValueError('当前包未包含首次配置向导，请使用对应的独立向导包。')
        subprocess.Popen([sys.executable, str(script)], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    helpers = ttk.Frame(heading); helpers.pack(anchor='w', pady=6)
    for label, callback in [('第一次 / 恢复操作说明', help_steps), ('载入上次填写', restore_form), ('重置某组填写', reset_form), ('打开首次配置向导', first_run)]:
        ttk.Button(helpers, text=label, command=guard(callback)).pack(side='left', padx=3)
    def start():
        if busy: return
        plan = collect_plan()
        try:
            validate(plan)
        except Exception as exc:
            messagebox.showerror('预检未通过', str(exc))
            return
        confirmation = ('按勾选项部署并启动服务？\n'
                        f'系统：{plan.platform}；AstrBot：{plan.astrbot_mode}\n'
                        f'安装目录：{plan.destination}\n'
                        f'AstrBot 数据根：{plan.astrbot or "新建独立实例"}\n'
                        f'ComfyUI：{plan.comfyui or "新建独立实例"}\n'
                        '该安装目录必须长期保留，安装后不要直接改名/移动。\n已有服务请先正常停止。不会下载未选模型，不会自动登录 QQ。')
        if not messagebox.askyesno('确认解析后的真实目录', confirmation):
            return
        launch(lambda log: deploy(plan, log), '部署流程结束。若未就绪先处理服务日志；随后打开首次配置向导，完成授权与首图，不需再部署。')
    actions = ttk.Frame(frame); actions.grid(row=22, column=0, columnspan=3, pady=8)
    ttk.Button(actions, text='① 只做预检（不安装）', command=guard(preflight_only)).pack(side='left', padx=5)
    button = ttk.Button(actions, text='② 确认部署 / 修正后重试', command=start)
    button.pack(side='left', padx=5)
    ttk.Button(actions, text='已有安装：仅启动服务', command=guard(start_existing)).pack(side='left', padx=5)
    def poll():
        nonlocal busy
        # Bound each UI batch so verbose pip output cannot starve animations/timers.
        for _ in range(150):
            if messages.empty(): break
            kind, line = messages.get_nowait()
            if kind == 'progress':
                monitor.update(line); continue
            if kind == 'log':
                monitor.note()
                output.insert('end', line + '\n'); output.see('end')
            if kind == 'done':
                busy = False
                button.config(state='normal')
                status, message = line
                monitor.finish(status, message)
                progress_hint.set(message)
                output.insert('end', message + '\n'); output.see('end')
                if status == 'failed': messagebox.showerror('安装／启动失败', message, parent=app)
                elif status == 'needs_attention': messagebox.showwarning('流程结束，仍需配置', message, parent=app)
                else: messagebox.showinfo('完成', message, parent=app)
        monitor.render()
        app.after(100, poll)
    def close():
        if busy:
            messagebox.showinfo('正在部署', '请等待安装结束，避免中断依赖安装；进度会持续显示。')
        else:
            app.destroy()
    app.protocol('WM_DELETE_WINDOW', close)
    def save_log():
        path = filedialog.asksaveasfilename(parent=app, title='保存本窗口安装日志', defaultextension='.txt', filetypes=[('文本日志', '*.txt')])
        if path:
            Path(path).write_text(output.get('1.0', 'end'), encoding='utf-8-sig')
    ttk.Button(actions, text='保存安装日志', command=save_log).pack(side='left', padx=5)
    poll()
    if selected_components:
        for key in selected_components: optional[key].set(True)
        progress_hint.set('按扩展说明预勾选了组件，尚未下载/安装。载入原计划会保留此次新增勾选；请核对路径、依赖和许可证。')
    if smoke:
        fill_plan(Plan('C:/test-only' if os.name == 'nt' else '/tmp/test-only', hf_mirror='https://example.invalid', fallback_official=True))
        assert set(selected_components) <= set(collect_plan().external.split(','))
        reset_group(next(key for key in reset_groups if key.startswith('下载')))
        assert collect_plan().download_mode == 'official' and not collect_plan().fallback_official
        assert collect_plan().destination.endswith('test-only')
        monitor.reset(DISPLAY_STEPS)
        monitor.update({'kind': 'stages', 'stage': 'models', 'status': 'running', 'states': {'models': 'running'}})
        monitor.update({'kind': 'transfer', 'name': '测试文件', 'current': 50, 'total': 100, 'rate': 10})
        assert monitor.model.file_percent == 50
        monitor.finish('failed', '测试错误状态，未执行安装')
        assert monitor.model.states['models'] == 'failed'
        app.update_idletasks(); app.destroy()
        print('PASS: deployment form, restore/reset controls, no install/network/services')
        return
    app.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, help='无桌面服务器使用 JSON 计划，字段见 Plan')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--start', type=Path)
    parser.add_argument('--profile', choices=['local', 'full'])
    parser.add_argument('--platform', choices=['auto', 'windows', 'linux'], default='auto')
    parser.add_argument('--install-gufeng', action='store_true', help='显式选装 V · 国风古韵本机离线词库，配合 --plan')
    parser.add_argument('--gufeng-module', type=Path, help='离线私有候选资源 ZIP 或目录；配合 --plan --install-gufeng')
    parser.add_argument('--smoke-test', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--extension', default='')
    args = parser.parse_args()
    if args.extension and (args.plan or args.start or args.apply): parser.error('--extension 不能与部署/启动混用')
    if args.smoke_test or args.extension:
        wizard(args.platform, smoke=args.smoke_test, extension=args.extension)
        return
    if (args.install_gufeng or args.gufeng_module) and (not args.plan or args.start):
        parser.error('--install-gufeng / --gufeng-module 必须与 --plan 配合使用')
    if args.start:
        start_services(args.start, profile=args.profile)
    elif args.plan:
        plan = Plan(**json.loads(args.plan.read_text('utf-8-sig')))
        if args.platform != 'auto':
            plan.platform = args.platform
        if args.install_gufeng:
            plan.install_gufeng = True
        if args.gufeng_module:
            plan.gufeng_module = str(args.gufeng_module)
        validate(plan)
        if args.apply:
            deploy(plan)
        else:
            print('预检通过，未写入、未联网。追加 --apply 执行。')
    else:
        if host_platform() == 'linux' and not (os.getenv('DISPLAY') or os.getenv('WAYLAND_DISPLAY')):
            raise ValueError('Linux 无桌面环境：使用 --plan examples/deployment-plan.linux.json 预检，再追加 --apply；见 docs/DEPLOY_LINUX.md')
        wizard(args.platform)




def configure_local(root, comfy, workflow, *, activate=True, gufeng_catalog=None):
    env_file = root / 'runtime-env.local.json'
    if not env_file.is_file() and (root / 'runtime-env.json').is_file():
        previous = json.loads((root / 'runtime-env.json').read_text('utf-8'))
        if previous.get('AAH_EXECUTION_MODE') == 'local':
            env_file = root / 'runtime-env.json'
    env = json.loads(env_file.read_text('utf-8')) if env_file.is_file() else {}
    defaults = {
        'AAH_EXECUTION_MODE': 'local', 'AAH_HOST': '127.0.0.1', 'AAH_PORT': '6278',
        'AAH_ADMIN_TOKEN': secrets.token_urlsafe(48),
        'AAH_PLUGIN_DATA_DIR': str(root / 'data/local'),
        'AAH_PLUGIN_DIR': str(root / 'hub/resources'),
        'AAH_COMFYUI_ROOT': str(comfy), 'AAH_COMFYUI_URL': 'http://127.0.0.1:8188',
        'AAH_LOCAL_WORKFLOW_PATH': str(workflow),
    }
    for key, value in defaults.items():
        env.setdefault(key, value)
    if (root / 'hub/web/index.html').is_file():
        env.setdefault('AAH_WEB_ROOT', str(root / 'hub/web'))
    if env.get('AAH_EXECUTION_MODE') != 'local' or env.get('AAH_HOST') != '127.0.0.1':
        raise ValueError('本机配置必须为 local 模式且仅监听 127.0.0.1')
    if gufeng_catalog is not None:
        from gufeng_resource import ENV_KEY
        existing = env.get(ENV_KEY)
        if existing and Path(existing).absolute() != Path(gufeng_catalog).absolute():
            raise ValueError('已有本机国风路径不同，不覆盖用户配置')
        env[ENV_KEY] = str(gufeng_catalog)
    json_write(root / 'runtime-env.local.json', env, True)
    if activate:
        json_write(root / 'runtime-env.json', env, True)
    return env



def local_hq_workflow(comfy, workflows, quick):
    """Create a private HQ template with the explicitly selected model files."""
    template = workflows / 'Anima_HQ_Txt2Img_Beta_api.json'
    if not template.is_file():
        raise ValueError('发布包缺少本机 HQ API 工作流')
    if quick is None:
        return template
    return configured_anima_workflow(workflows, quick, template.name, 'AAA_Local_HQ_api.json')


if __name__ == '__main__':
    # Redirected consoles on non-Chinese Windows may default to cp1252/ASCII.
    # Encoding a successful Chinese status message must not fail deployment.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        main()
    except Exception as exc:
        print('部署失败：' + str(exc), file=sys.stderr)
        raise SystemExit(1)
