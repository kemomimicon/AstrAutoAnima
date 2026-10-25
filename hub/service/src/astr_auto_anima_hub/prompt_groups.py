from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .config import Settings
from .repositories import file_revision, read_json_object
from .storage import RepositoryError, mutate_json


GROUP_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class PromptGroup(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    allow_private: bool = False
    allow_group: bool = True
    enabled: bool = True
    safety_codes: list[str] = Field(default_factory=lambda: ["N", "H", "S"], min_length=1, max_length=3)

    @field_validator("safety_codes")
    @classmethod
    def valid_levels(cls, value):
        if len(set(value)) != len(value) or any(v not in ("N", "H", "S") for v in value):
            raise ValueError("invalid content levels")
        return value

    @field_validator("id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        value = value.strip().casefold()
        if not GROUP_ID.fullmatch(value):
            raise ValueError("group id must use lower-case letters, digits, _ or -")
        return value


class PromptGroupsWrite(BaseModel):
    groups: list[PromptGroup] = Field(max_length=128)


def groups_path(settings: Settings) -> Path:
    return settings.plugin_data_dir / "hub_state" / "prompt_groups.json"


def read_groups(settings: Settings) -> dict:
    path = groups_path(settings)
    if not path.exists():
        return {"groups": [], "revision": "missing"}
    data = read_json_object(path)
    groups = data.get("groups", [])
    if not isinstance(groups, list):
        raise RepositoryError("prompt group registry is invalid")
    try:
        validated = [PromptGroup.model_validate(group).model_dump() for group in groups]
        if len({group['id'] for group in validated}) != len(validated):
            raise ValueError('duplicate group id')
    except ValueError as exc:
        raise RepositoryError('prompt group registry is invalid') from exc
    return {"groups": validated, "revision": file_revision(path, "prompt_groups").revision}


def validate_selected_groups(settings: Settings, selected: list[str], *, private=False,
                             for_generation=False, safety=None) -> list[str]:
    from .prompt_group_ids import normalize_group_ids
    try:
        groups = normalize_group_ids(selected)
    except ValueError as exc:
        raise RepositoryError(str(exc)) from exc
    if not groups:
        return []
    registry = {group['id']: group for group in read_groups(settings)['groups']}
    for ident in groups:
        if ident not in registry:
            raise RepositoryError(f'自定义分组 @{ident} 尚未登记或已移除，请刷新分组')
        if private and not registry[ident]['allow_private']:
            raise RepositoryError(f'自定义分组 @{ident} 不允许私聊抽取')
        if for_generation:
            row = registry[ident]
            if not row["enabled"] or (not private and not row["allow_group"]):
                raise RepositoryError(f'自定义分组 @{ident} 已停用或不允许群聊')
            if safety and safety not in row["safety_codes"]:
                raise RepositoryError(f'自定义分组 @{ident} 不允许所选内容级别')
    return groups


def write_groups(settings: Settings, payload: PromptGroupsWrite, revision: str, actor: str) -> dict:
    ids = [group.id for group in payload.groups]
    if len(set(ids)) != len(ids):
        raise RepositoryError("duplicate group id")

    def update(data: dict) -> None:
        data["groups"] = [group.model_dump() for group in payload.groups]

    _, new_revision, _ = mutate_json(
        path=groups_path(settings), resource="prompt_groups", expected_revision=revision,
        backup_root=settings.backup_dir, audit_path=settings.audit_log_path,
        actor=actor, action="replace", target="registry", mutate=update,
        initialize=lambda: {"groups": []},
    )
    return {"groups": [group.model_dump() for group in payload.groups], "revision": new_revision}
