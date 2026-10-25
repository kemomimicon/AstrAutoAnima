"""Built-in components are copied once; activating one never installs services."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from deployment_support import no_links


def component_catalog(profile: str) -> dict:
    if profile not in {'local', 'full'}:
        raise ValueError('Unknown deployment profile')
    return {
        'schema_version': 1, 'deployment_profile': profile,
        'components': [
            {'id': 'multi_instance', 'bundled': True, 'activation': 'client',
             'note': '客户端按连接隔离凭据；切换不重新安装服务，不同时启动两条 Hub 路线'},
            {'id': 'local_workstation', 'bundled': True, 'activation': 'Start-Local',
             'note': '仅回环地址；本机与完整服务共用代码/模型，配置和数据隔离'},
            {'id': 'chat_groups', 'bundled': True, 'available': profile == 'full',
             'enabled_by_default': False, 'activation': 'remote_admin'},
            {'id': 'platforms', 'bundled': True, 'available': profile == 'full',
             'note': '使用已有 AstrBot 适配器；QQ 保持现有设置，TG/DC 新装默认不接单'},
            {'id': 'qq_composer', 'bundled': True, 'activation': 'client_setting',
             'note': '只复制指令，不代替用户发送 QQ 消息'},
            {'id': 'bilingual_tags', 'bundled': True, 'activation': 'client_setting',
             'note': '本地候选词库，不依赖联网翻译'},
            {'id': 'connection_guidance', 'bundled': True, 'activation': 'client_setting',
             'note': '仅说明局域网/私有组网/隧道的利害，不自动开端口或安装网络服务'},
            {'id': 'prompt_importer', 'bundled': True, 'activation': 'manual',
             'entry': 'optional/prompt_importer/importer.py'},
            {'id': 'studio_connector', 'bundled': True, 'activation': 'manual',
             'entry': 'tools/studio_optional.py', 'upstream_installed': False,
             'note': 'AnimaLoraStudio 是外部项目，已有安装不自动覆盖、降级或重复安装'},
        ],
    }


def prepare_components(source: Path, destination: Path, profile: str, write_json) -> None:
    """Install declared helper files, not arbitrary user directories or tokens."""
    files = [
        ('optional/prompt_importer/importer.py', 'optional/prompt_importer/importer.py'),
        ('optional/prompt_importer/README.md', 'optional/prompt_importer/README.md'),
        ('tools/studio_optional.py', 'tools/studio_optional.py'),
        ('optional/studio/README.txt', 'optional/studio/README.txt'),
        ('optional/studio/package.json', 'optional/studio/package.json'),
        ('optional/studio/AAA_Studio025_Connector-0.1.1.zip',
         'optional/studio/AAA_Studio025_Connector-0.1.1.zip'),
        ('plugin/astrbot_plugin_comfy_bridge/data/aaa_anima_lighting_material_presets_v1.json',
         'hub/resources/data/aaa_anima_lighting_material_presets_v1.json'),
    ]
    for relative, target in files:
        src, dst = source / relative, destination / target
        no_links(src)
        no_links(dst)
        if not src.is_file():
            raise ValueError('完整项目缺少内置资源：' + relative)
        if dst.exists():
            if not dst.is_file():
                raise ValueError('内置资源目标类型异常：' + target)
            # Preserve manually changed helpers: no destructive override on resume.
            if hashlib.sha256(src.read_bytes()).digest() != hashlib.sha256(dst.read_bytes()).digest():
                raise ValueError('已有内置资源与包体不同，请备份后人工核对：' + target)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    write_json(destination / ('components.' + profile + '.json'), component_catalog(profile))


def initialize_local_data(root: Path, write_json) -> None:
    """Empty resources for a new local workstation, never overwrite its library."""
    for name, value in {
        'presets.json': {'characters': {}, 'styles': {}},
        'anima_random_prompt_pool.json': {'schema_version': 3, 'prompts': []},
        'character_dictionary.json': {'schema_version': 1, 'characters': []},
    }.items():
        path = root / 'data/local' / name
        no_links(path)
        if not path.exists():
            write_json(path, value)
