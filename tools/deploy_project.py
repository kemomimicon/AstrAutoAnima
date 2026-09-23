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
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass
from deployment_support import (host_platform, clean_path, no_links, astrbot_root,
    comfy_root, discover_python, windows_start_script, download_base_models,
    install_anima_master, configure_anima_master)

ROOT = Path(__file__).resolve().parents[1]
MARKER = '.aaa-managed-install'


@dataclass
class Plan:
    destination: str
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


def json_write(path, data, private=False):
    path = Path(path)
    no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never follow a configuration symlink.
    if path.is_symlink():
        raise ValueError(f'拒绝写入符号链接：{path.name}')
    with path.open('w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
    if private and os.name != 'nt':
        path.chmod(0o600)


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


def validate(plan):
    if plan.platform not in ('auto', 'windows', 'linux') or plan.platform not in ('auto', host_platform()):
        raise ValueError('操作系统选择不匹配：Windows 包只能在 Windows 执行，Linux 包只能在 Linux 执行')
    if plan.astrbot_mode not in ('cli', 'desktop'):
        raise ValueError('AstrBot 模式必须为 cli 或 desktop')
    if plan.astrbot_mode == 'desktop' and (host_platform() != 'windows' or plan.install_astrbot):
        raise ValueError('桌面版接入只用于已有 Windows AstrBot Desktop，不能同时勾选下载全新 AstrBot')
    for key in ('destination', 'astrbot', 'comfyui', 'astrbot_python', 'comfy_python', 'unet', 'clip', 'vae'):
        setattr(plan, key, clean_path(getattr(plan, key)))
    root = checked_root(plan.destination)
    if (plan.install_astrbot or plan.install_comfyui) and not plan.install_dependencies:
        raise ValueError('全新环境需要勾选“允许安装依赖”')
    if plan.install_astrbot and sys.version_info < (3, 12):
        raise ValueError('全新 AstrBot 环境需要 Python 3.12+；请用 Python 3.12 运行向导')
    if plan.install_comfyui and not shutil.which('git'):
        raise ValueError('下载 ComfyUI 需要 Git：https://git-scm.com/downloads')
    if not plan.install_astrbot:
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
    for value in (plan.astrbot, plan.comfyui):
        if value:
            no_links(Path(value))
            if root == Path(value) or Path(value) in root.parents:
                raise ValueError('独立安装目录不能嵌套在已有 AstrBot/ComfyUI 目录中')
    if plan.download_models and not plan.accept_model_license:
        raise ValueError('请阅读并确认模型许可后再勾选下载 Anima Base 1.0')
    if (plan.download_models or plan.install_am) and not shutil.which('curl'):
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
    return root


def run(command, log, cwd=None):
    # Commands never contain credentials. Full pip/git output goes to the install log.
    log('执行：' + ' '.join(map(str, command)))
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    with subprocess.Popen(list(map(str, command)), cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', **flags) as process:
        for line in process.stdout:
            log(line.rstrip())
        if process.wait():
            raise RuntimeError('命令执行失败。已保留部署目录和日志；修正网络/依赖后重新运行，不会删除已有数据')


def python_at(folder):
    return Path(folder) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def make_env(path, log):
    python = python_at(path)
    if not python.is_file():
        run([sys.executable, '-m', 'venv', path], log)
    return python


def copy_source(source, target):
    # Reject directory junctions and symbolic links before recursive copies/overwrites.
    for root in (Path(source), Path(target)):
        for parent in (root, *root.parents):
            if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
                raise ValueError('项目复制路径含符号链接或联接：' + str(parent))
        if root.is_dir():
            for parent, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = [d for d in dirs if d not in {'.venv', '__pycache__', 'tests'}]
                for name in dirs + files:
                    item = Path(parent) / name
                    if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
                        raise ValueError('项目目录包含链接，请先人工检查：' + str(item))
    shutil.copytree(source, target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('tests', '__pycache__', '*.pyc', '.env', '.venv', '.git'))


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
                      'reverse_history_dir': 'reverse_history'}.items():
        config.setdefault(key, str(plugin_data / name))
    json_write(config_file, config, True)
    env_file = root / 'runtime-env.json'
    env = json.loads(env_file.read_text('utf-8')) if env_file.exists() else {}
    defaults = {
        'AAH_HOST': '127.0.0.1', 'AAH_PORT': '6278', 'AAH_ADMIN_TOKEN': secrets.token_urlsafe(48),
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
    json_write(env_file, env, True)
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


def start_services(root, log=print):
    root = checked_root(str(root))
    for filename in ('runtime-env.json', 'services.json'):
        if not (root / filename).is_file():
            raise ValueError(f'缺少 {filename}：请先完成部署，不要手动新建空配置；当前目录：{root}')
    settings = json.loads((root / 'runtime-env.json').read_text('utf-8'))
    services = json.loads((root / 'services.json').read_text('utf-8'))
    reports = []
    for service in services:
        if service.get('mode') == 'desktop':
            reports.append('AstrBot Desktop：' + ('6185 端口已有服务，请在桌面端确认插件已加载' if port_open(service['port']) else '请手动打开 AstrBot Desktop；本入口不会启动第二套后端'))
            continue
        if port_open(service['port']):
            check = health(service['health']) if service.get('health') else None
            if (service['name'] == 'Hub' and isinstance(check, dict) and check.get('service') == 'astr-auto-anima-hub') or (
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
        while time.monotonic() < deadline and process.poll() is None:
            result = health(service['health']) if service.get('health') else None
            if (isinstance(result, dict) and (result.get('service') == 'astr-auto-anima-hub' or 'system' in result)) or (not service.get('health') and port_open(service['port'])):
                reports.append(service['name'] + ' 已启动并通过' + ('健康检查' if service.get('health') else '端口检查（仍需登录配置）'))
                break
            time.sleep(1)
        else:
            reports.append(service['name'] + ' 尚未就绪；日志：' + str(logfile))
    for line in reports:
        log(line)
    json_write(root / 'health-report.json', {'services': reports, 'time': time.time()})
    return reports


def deploy(plan, log=print):
    root = validate(plan)
    root.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        root.chmod(0o700)
    (root / MARKER).touch()
    lock = root / '.deploy.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError('另一次安装正在进行；若已异常结束，请检查后手动移除 .deploy.lock')
    os.close(fd)
    try:
        astro = (root / 'astrbot') if plan.install_astrbot else Path(plan.astrbot).resolve()
        comfy = (root / 'ComfyUI') if plan.install_comfyui else Path(plan.comfyui).resolve()
        # Existing apps are not installed over; this operation only adds project files.
        for name, port in (('AstrBot', 6185), ('ComfyUI', 8188), ('Hub', 6278)):
            if port_open(port):
                raise ValueError(f'{name} 正在运行或端口 {port} 已占用；请先正常关闭，再部署。不会自动强杀进程')
        hub_python = python_at(root / 'hub/.venv')
        if plan.install_dependencies:
            hub_python = make_env(root / 'hub/.venv', log)
        elif not hub_python.is_file():
            raise ValueError('首次部署 Hub 需要勾选“允许安装依赖”；不会擅自联网')
        apy = Path(plan.astrbot_python) if plan.astrbot_python else python_at(astro / '.venv')
        cpy = Path(plan.comfy_python) if plan.comfy_python else python_at(comfy / '.venv')
        if plan.install_astrbot:
            astro.mkdir(parents=True, exist_ok=True)
            apy = make_env(astro / '.venv', log)
            run([apy, '-m', 'pip', 'install', 'astrbot==4.27.2'], log)
            executable = apy.parent / ('astrbot.exe' if os.name == 'nt' else 'astrbot')
            if not (astro / 'data/cmd_config.json').is_file():
                run([executable, 'init', '--yes'], log, astro)
        if plan.install_comfyui:
            if not (comfy / 'main.py').exists():
                run(['git', 'clone', '--branch', 'v0.21.1', '--depth', '1', 'https://github.com/Comfy-Org/ComfyUI.git', comfy], log)
            cpy = make_env(comfy / '.venv', log)
            index = 'https://download.pytorch.org/whl/cu128' if plan.gpu else 'https://download.pytorch.org/whl/cpu'
            run([cpy, '-m', 'pip', 'install', 'torch', 'torchvision', 'torchaudio', '--index-url', index], log)
            run([cpy, '-m', 'pip', 'install', '-r', comfy / 'requirements.txt'], log)
        plugin = astro / 'data/plugins/astrbot_plugin_comfy_bridge'
        node = comfy / 'custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools'
        backup = root / ('backup_' + time.strftime('%Y%m%d_%H%M%S') + '_' + secrets.token_hex(3))
        for source, target, name in ((ROOT / 'plugin/astrbot_plugin_comfy_bridge', plugin, 'plugin'),
                                      (ROOT / 'comfyui/custom_nodes/ComfyUI-AstrAutoAnima-Workflow-Tools', node, 'nodes'),
                                      (ROOT / 'hub/service', root / 'hub', 'hub')):
            if target.exists():
                copy_source(target, backup / name)
            copy_source(source, target)
        workflows = comfy / 'user/default/workflows'
        workflows.mkdir(parents=True, exist_ok=True)
        for file in (ROOT / 'comfyui/workflows').glob('*.json'):
            dest = workflows / file.name
            if not dest.exists():
                shutil.copy2(file, dest)
        if plan.install_dependencies:
            run([hub_python, '-m', 'pip', 'install', '-e', root / 'hub'], log)
            if plan.astrbot_mode != 'desktop' and apy.is_file():
                run([apy, '-m', 'pip', 'install', '-r', plugin / 'requirements.txt'], log)
            if cpy.is_file():
                run([cpy, '-m', 'pip', 'install', '-r', node / 'requirements.txt'], log)
        if plan.external:
            from easy_installer import InstallPlan, install_external
            install_external(InstallPlan(ROOT, astro / 'data', comfy, root / 'hub',
                             external=set(plan.external.split(',')), comfy_python=cpy,
                             install_external_requirements=plan.install_dependencies, apply=True), backup, log)
        if plan.download_models:
            download_base_models(ROOT, comfy, plan, log)
        flow = quick_workflow(plan, comfy, log)
        if flow is not None and not (workflows / 'AAA_Quick_Local_api.json').exists():
            json_write(workflows / 'AAA_Quick_Local_api.json', flow)
        config = astro / 'data/config/astrbot_plugin_comfy_bridge_config.json'
        if config.exists():
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(config, backup / 'plugin_config.json')
        env = configure(plan, root, astro, comfy)
        if plan.install_am:
            am = install_anima_master(astro, root, log, copy_source)
            if plan.install_dependencies and plan.astrbot_mode != 'desktop':
                run([apy, '-m', 'pip', 'install', '-r', am / 'requirements.txt'], log)
            configure_anima_master(astro, comfy, root, json_write)
        # API key never goes into the reusable plan.
        safe_plan = asdict(plan)
        safe_plan['api_key'] = ''
        json_write(root / 'last-plan.json', safe_plan, True)
        services = [
            {'name': 'ComfyUI', 'command': [str(cpy), 'main.py', '--listen', '127.0.0.1', '--port', '8188'] + ([] if plan.gpu else ['--cpu']), 'cwd': str(comfy), 'port': 8188, 'health': 'http://127.0.0.1:8188/system_stats'},
            {'name': 'AstrBot', 'mode': plan.astrbot_mode, 'command': [str(apy.parent / ('astrbot.exe' if os.name == 'nt' else 'astrbot')), 'run', '--port', '6185'], 'cwd': str(astro), 'port': 6185},
            {'name': 'Hub', 'command': [str(hub_python), '-m', 'astr_auto_anima_hub'], 'cwd': str(root / 'hub'), 'port': 6278, 'health': 'http://127.0.0.1:6278/api/v1/health'},
        ]
        json_write(root / 'services.json', services)
        # Self-contained start entry survives moving/deleting the downloaded release.
        shutil.copy2(Path(__file__), root / 'deploy_project.py')
        shutil.copy2(Path(__file__).with_name('deployment_support.py'), root / 'deployment_support.py')
        if os.name == 'nt':
            (root / 'Start.cmd').write_text(windows_start_script(), 'ascii', newline='')
        else:
            (root / 'Start.sh').write_text('#!/bin/sh\nset -eu\nD=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "$D/hub/.venv/bin/python" "$D/deploy_project.py" --start "$D"\n', 'utf-8')
            (root / 'Start.sh').chmod(0o700)
        missing = []
        if plan.astrbot_mode == 'desktop':
            missing.append('手动启动 AstrBot Desktop；若插件缺依赖，请通过其插件管理器安装 requests / pillow，勿给内置运行时盲目 pip 升级')
        missing.append('Anima Master：兼容基线 0.7.1；上游 0.9.1（2026-09-23 核对）未联调，不自动升级。详细配置见发布包 docs/ANIMA_MASTER.md')
        if not (astro / 'data/plugins/astrbot_plugin_anima_master/metadata.yaml').is_file():
            missing.append('尚未安装核心上游 Anima Master：重新运行向导显式勾选安装 0.7.1，或在插件页安装固定版本')
        if not (workflows / 'AAA_Quick_Local_api.json').exists():
            missing.append('选择 Anima UNET / CLIP / VAE 或自行设置工作流；模型未随包分发')
        if not env.get('AAH_ASTRBOT_API_KEY'):
            missing.append('AstrBot 设置 → OpenAPI 创建 chat/message 所需授权 API Key，重新运行向导填写（不绕过授权）')
        if env.get('AAH_ASTRBOT_BOT_ID') == 'your-bot-id':
            missing.append('在 AstrBot 配置实际平台 Bot ID；使用 QQ 时还需 NapCat 登录及 OneBot 对接')
        (root / '下一步.txt').write_text('部署后仍需完成：\n' + '\n'.join(missing) + '\n管理员令牌仅保存在 runtime-env.json；不要分享此文件。\n', 'utf-8')
        log('文件及依赖部署完成，开始启动与健康检查；这不等于已经通过实际生图验收。')
        start_services(root, log)
        for message in missing:
            log('待配置：' + message)
        log('运行目录：' + str(root) + '；以后双击 Start.cmd 或执行 Start.sh 即可启动。')
    finally:
        lock.unlink()  # Exact lock created above, never a directory or glob.


def wizard(platform='auto'):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    app = tk.Tk()
    app.title('AstrAutoAnima 0.5.0 Beta 一键部署')
    app.geometry('980x850')
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
    fields = [('destination', '独立安装目录', str(ROOT.parent / 'AstrAutoAnima-install')),
              ('astrbot', '已有 AstrBot 根目录（含 data）', ''), ('comfyui', '已有 ComfyUI 根目录', ''),
              ('astrbot_python', '已有 AstrBot Python（可选）', ''), ('comfy_python', '已有 ComfyUI Python（可选）', ''),
              ('unet', 'Anima UNET 文件（可稍后填写）', ''), ('clip', 'CLIP 文件', ''), ('vae', 'VAE 文件', ''),
              ('bot_id', 'AstrBot 平台 Bot ID（可稍后填写）', ''), ('api_key', 'AstrBot OpenAPI Key（仅存本机）', '')]
    for row, (key, label, default) in enumerate(fields):
        value = tk.StringVar(value=default)
        values[key] = value
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w')
        ttk.Entry(frame, textvariable=value, show='*' if key == 'api_key' else '').grid(row=row, column=1, sticky='ew', pady=2)
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
    output = tk.Text(frame, height=13, wrap='word')
    output.grid(row=22, column=0, columnspan=3, sticky='nsew')
    messages = queue.Queue()
    busy = False
    def start():
        nonlocal busy
        if busy:
            return
        plan = Plan(**{k: v.get().strip() for k, v in values.items()}, **{k: v.get() for k, v in opts.items()},
                    platform=platform_value.get(), astrbot_mode=mode_value.get(),
                    external=','.join(k for k, v in optional.items() if v.get()))
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
                        '已有服务请先正常停止。不会下载未选模型，不会自动登录 QQ。')
        if not messagebox.askyesno('确认解析后的真实目录', confirmation):
            return
        busy = True
        button.config(state='disabled')
        def work():
            try:
                deploy(plan, lambda line: messages.put(('log', line)))
                messages.put(('done', '部署流程结束，请查看健康报告和待配置项。'))
            except Exception as exc:
                messages.put(('done', '部署中断：' + str(exc)))
        threading.Thread(target=work, daemon=True).start()
    button = ttk.Button(frame, text='预检并一键部署 / 启动', command=start)
    button.grid(row=21, column=0, columnspan=3, pady=8)
    def poll():
        nonlocal busy
        while not messages.empty():
            kind, line = messages.get_nowait()
            output.insert('end', line + '\n')
            output.see('end')
            if kind == 'done':
                busy = False
                button.config(state='normal')
        app.after(100, poll)
    def close():
        if busy:
            messagebox.showinfo('正在部署', '请等待安装结束，避免中断依赖安装；进度会持续显示。')
        else:
            app.destroy()
    app.protocol('WM_DELETE_WINDOW', close)
    poll()
    app.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, help='无桌面服务器使用 JSON 计划，字段见 Plan')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--start', type=Path)
    parser.add_argument('--platform', choices=['auto', 'windows', 'linux'], default='auto')
    args = parser.parse_args()
    if args.start:
        start_services(args.start)
    elif args.plan:
        plan = Plan(**json.loads(args.plan.read_text('utf-8-sig')))
        if args.platform != 'auto':
            plan.platform = args.platform
        validate(plan)
        if args.apply:
            deploy(plan)
        else:
            print('预检通过，未写入、未联网。追加 --apply 执行。')
    else:
        if host_platform() == 'linux' and not (os.getenv('DISPLAY') or os.getenv('WAYLAND_DISPLAY')):
            raise ValueError('Linux 无桌面环境：使用 --plan examples/deployment-plan.linux.json 预检，再追加 --apply；见 docs/DEPLOY_LINUX.md')
        wizard(args.platform)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('部署失败：' + str(exc), file=sys.stderr)
        raise SystemExit(1)
