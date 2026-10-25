"""Read-only discovery for optional Web connectors. No training code is bundled.

Registry validation alone never reports a package as runnable. The optional host
adds availability only after checking the installed package and upstream.
"""
from pathlib import Path, PurePosixPath
from typing import Literal
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth import require_admin


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Compatibility(StrictModel):
    hub: str
    client: str
    studio: str


class Navigation(StrictModel):
    group: Literal['standalone']
    label: str = Field(min_length=1, max_length=40)
    icon: Literal['science', 'extension'] = 'science'
    order: int = Field(default=40, ge=0, le=1000)
    admin_only: Literal[True] = True


class Web(StrictModel):
    root: str
    index: str
    base_path: str
    preferred_viewport: Literal['desktop', 'responsive'] = 'desktop'
    allow_external_browser: bool = True


class Proxy(StrictModel):
    upstream_setting: Literal['anima_studio_upstream']
    allowed_upstream_host: Literal['127.0.0.1']
    path_prefixes: list[Literal['/api/', '/samples/']]
    sse_paths: list[Literal['/api/events']]


class Health(StrictModel):
    path: Literal['/api/health']
    timeout_seconds: int = Field(default=3, ge=1, le=10)


class License(StrictModel):
    name: str
    path: str
    source: str


class ExtensionManifest(StrictModel):
    schema_version: Literal[1]
    id: str = Field(pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$', max_length=64)
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(max_length=500)
    version: str = Field(pattern=r'^\d+\.\d+\.\d+(?:[-.][a-zA-Z0-9.]+)?$', max_length=64)
    publisher: str = Field(max_length=100)
    type: Literal['proxied_web']
    compatibility: Compatibility
    navigation: Navigation
    web: Web
    proxy: Proxy
    health: Health
    licenses: list[License] = Field(min_length=1, max_length=10)


def contained(root: Path, relative: str) -> Path:
    """Reject traversal, Windows paths, symlinks/junctions and absent files."""
    if not relative or '\\' in relative or ':' in relative:
        raise ValueError('invalid package path')
    parts = PurePosixPath(relative)
    if parts.is_absolute() or '..' in parts.parts or relative.startswith('/'):
        raise ValueError('invalid package path')
    target = root / relative
    if root.resolve() != root.absolute() or target.resolve() != target.absolute():
        raise ValueError('linked package path')
    target.resolve().relative_to(root.resolve())
    return target


def read_json(path: Path, limit: int = 131072):
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('missing or oversized metadata')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def registry(root: Path) -> dict:
    if not root.exists():
        return {'schema_version': 1, 'extensions': [], 'discovery_state': 'ok'}
    try:
        state_path = contained(root, 'active.json')
        if not state_path.exists():
            return {'schema_version': 1, 'extensions': [], 'discovery_state': 'ok'}
        state = read_json(state_path)
        if not isinstance(state, dict) or set(state) != {'schema_version', 'extensions'} or state['schema_version'] != 1:
            raise ValueError('invalid registry')
        active = state['extensions']
        if not isinstance(active, dict) or len(active) > 32:
            raise ValueError('invalid registry')
    except (ValueError, OSError):
        return {'schema_version': 1, 'extensions': [], 'discovery_state': 'broken_registry'}
    results = []
    for identifier, entry in active.items():
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', identifier) or len(identifier) > 64:
            continue
        item = {'id': identifier, 'name': identifier, 'enabled': False,
                'state': 'broken_package', 'message': '连接器结构无效，未加载。'}
        try:
            if not isinstance(entry, dict) or set(entry) != {'version', 'enabled'} or type(entry['enabled']) is not bool:
                raise ValueError('invalid activation')
            if not isinstance(entry['version'], str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-.][a-zA-Z0-9.]+)?', entry['version']):
                raise ValueError('invalid version')
            package = contained(root, f'packages/{identifier}/{entry["version"]}')
            manifest = ExtensionManifest.model_validate(read_json(contained(package, 'manifest.json')))
            if manifest.id != identifier or manifest.version != entry['version'] or manifest.web.base_path != f'/extensions/{identifier}/':
                raise ValueError('identity mismatch')
            index = contained(package, f'{manifest.web.root}/{manifest.web.index}')
            if not index.is_file():
                raise ValueError('missing frontend')
            for license in manifest.licenses:
                if not contained(package, license.path).is_file():
                    raise ValueError('missing license')
                read_json(contained(package, license.source))
            item.update(name=manifest.name, version=manifest.version,
                        enabled=entry['enabled'], navigation=manifest.navigation.model_dump(),
                        state='host_pending' if entry['enabled'] else 'disabled',
                        message='连接器已识别；安全会话与 Web 承载尚待接入。',
                        ui={'mode': 'proxied_web', 'launch_available': False,
                            'preferred_viewport': manifest.web.preferred_viewport})
        except (ValueError, OSError, TypeError, KeyError):
            pass
        results.append(item)
    return {'schema_version': 1, 'extensions': results, 'discovery_state': 'ok'}


router = APIRouter(prefix='/api/v1/admin/extensions', dependencies=[Depends(require_admin)])


@router.get('')
async def extensions(request: Request):
    data = registry(request.app.state.settings.extensions_root)
    for item in data['extensions']:
        await add_host_status(request, item)
    return data


@router.get('/{identifier}/status')
async def extension_status(identifier: str, request: Request):
    items = registry(request.app.state.settings.extensions_root)['extensions']
    for item in items:
        if item['id'] == identifier:
            await add_host_status(request, item)
            return item
    raise HTTPException(404, 'extension not installed')


async def add_host_status(request, item):
    host = getattr(request.app.state, 'extension_host', None)
    if host and item['id'] == 'anima-lora-studio' and item['enabled'] and item['state'] == 'host_pending':
        try:
            health = await host.health()
            item['state'] = health['state']
            item['message'] = health['message']
            item['ui']['launch_available'] = health['state'] == 'ready'
        except HTTPException:
            item['state'] = 'upstream_offline'
            item['message'] = '连接器上游配置或服务未就绪'
