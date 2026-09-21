"""Owner-scoped ordered task presets, separate from the plugin preset file."""
from __future__ import annotations

import copy
import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .repositories import RepositoryError, file_revision, read_json_object
from .storage import ResourceNotFound, mutate_json
from .personal_styles import resolve_personal_style_key


class SuiteRow(BaseModel):
    character_kind: Literal['preset', 'favorite', 'text'] = 'preset'
    character: str = Field(min_length=1, max_length=1000)
    style_kind: Literal['global', 'personal'] = 'global'
    style: str = Field(min_length=1, max_length=200)

    @field_validator('character', 'style')
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value or '\x00' in value:
            raise ValueError('选项不能为空')
        return value


class SuiteWrite(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: Literal['personal', 'global'] = 'personal'
    rows: list[SuiteRow] = Field(min_length=1, max_length=20)

    @field_validator('name')
    @classmethod
    def name_nonblank(cls, value):
        if not value.strip():
            raise ValueError('请输入套组名称')
        return value.strip()


def _path(settings):
    return settings.hub_state_dir / 'task_suites.json'


def _visible(item, principal):
    return item.get('scope') == 'global' or item.get('owner') == principal.subject


def list_suites(settings, principal):
    path = _path(settings)
    data = read_json_object(path) if path.is_file() else {}
    return {'revision': file_revision(path, 'task_suites').revision or 'missing',
            'items': [dict(item, editable=(item.get('owner') == principal.subject or
                       (item.get('scope') == 'global' and principal.is_admin)))
                      for item in data.get('items', {}).values() if _visible(item, principal)]}


def resolve_rows(settings, principal, payload):
    """Validate references and freeze actual preset bodies at submission time."""
    presets = read_json_object(settings.preset_path)
    result = []
    for row in payload.rows:
        character = row.character
        character_snapshot = None
        if row.character_kind == 'preset':
            character_snapshot = presets.get('characters', {}).get(character)
            if not isinstance(character_snapshot, dict) or character_snapshot.get('hidden') or character_snapshot.get('disabled') or character_snapshot.get('enabled', True) is False:
                raise RepositoryError(f'全局角色预设不可用：{character}')
        elif row.character_kind == 'favorite':
            from .character_favorites import list_character_favorites
            favorites = list_character_favorites(settings, principal)
            favorite = next((f for f in favorites.items if f.tag == character), None)
            if favorite is None or not favorite.strong_prompt:
                raise RepositoryError(f'收藏角色已失效：{character}')
            character = favorite.strong_prompt
        key = row.style
        if row.style_kind == 'personal':
            if payload.scope == 'global':
                raise RepositoryError('全局套组不能引用管理员的私人画风')
            try:
                key = resolve_personal_style_key(settings, principal, int(key))
            except (ValueError, TypeError) as exc:
                raise RepositoryError('个人画风槽位无效') from exc
        elif key.startswith('__hub_') or key == '随机模式':
            raise RepositoryError('套组只允许明确的画风预设')
        style = presets.get('styles', {}).get(key)
        if not isinstance(style, dict) or style.get('disabled') or style.get('enabled', True) is False or (row.style_kind == 'global' and style.get('hidden')):
            raise RepositoryError(f'画风预设不可用：{row.style}')
        if payload.scope == 'global' and row.character_kind == 'favorite':
            raise RepositoryError('全局套组请使用全局角色或角色文本，不引用私人收藏')
        result.append({'character': character, 'style': key,
                       'character_snapshot': copy.deepcopy(character_snapshot),
                       'style_snapshot': copy.deepcopy(style),
                       'character_kind': row.character_kind})
    return result


def write_suite(settings, principal, payload, revision, identifier=None):
    if principal.role == 'legacy_lite':
        raise RepositoryError('请使用个人令牌保存套组')
    if payload.scope == 'global' and not principal.is_admin:
        raise RepositoryError('只有管理员可以保存全局套组')
    resolve_rows(settings, principal, payload)
    identifier = identifier or uuid.uuid4().hex
    def change(data):
        items = data.setdefault('items', {})
        old = items.get(identifier)
        if old and not (old.get('owner') == principal.subject or (old.get('scope') == 'global' and principal.is_admin)):
            raise ResourceNotFound('套组不存在或无权修改')
        items[identifier] = dict(payload.model_dump(), id=identifier, owner=principal.subject)
    _mutate(settings, principal, revision, identifier, change)
    return list_suites(settings, principal)


def delete_suite(settings, principal, identifier, revision):
    def change(data):
        item = data.get('items', {}).get(identifier)
        if not item or not (item.get('owner') == principal.subject or (item.get('scope') == 'global' and principal.is_admin)):
            raise ResourceNotFound('套组不存在或无权删除')
        del data['items'][identifier]
    _mutate(settings, principal, revision, identifier, change)
    return list_suites(settings, principal)


def _mutate(settings, principal, revision, identifier, change):
    mutate_json(path=_path(settings), resource='task_suites', expected_revision=revision,
                backup_root=settings.hub_state_dir / 'backups', audit_path=settings.hub_state_dir / 'task_suites.audit.jsonl',
                actor=principal.subject, action='write', target=identifier, mutate=change,
                initialize=lambda: {'items': {}})


def suite_snapshot(settings, principal, identifier):
    item = next((i for i in list_suites(settings, principal)['items'] if i['id'] == identifier), None)
    if item is None:
        raise ResourceNotFound('任务套组不存在或无权使用')
    return {'id': identifier, 'name': item['name'], 'rows': resolve_rows(settings, principal, SuiteWrite.model_validate(item))}
