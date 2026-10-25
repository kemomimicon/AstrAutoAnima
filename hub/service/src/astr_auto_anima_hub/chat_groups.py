"""Authenticated management for the shared, optional chat-group policy store.

Only explicit writes create the database. Reading capabilities does not scan an
adapter, open a network port, or change the Hub's startup execution mode.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth import require_admin, require_reader


router = APIRouter()


class GroupWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    key: str = Field(min_length=1, max_length=240)
    # The shared key format reserves other platforms, but only the QQ bridge is
    # verified for this release. Never expose an unenforced TG/DC policy switch.
    platform: Literal["qq"] = "qq"
    bot_id: str = Field(min_length=1, max_length=80)
    group_id: str = Field(min_length=1, max_length=120)
    name: str = Field(default="", max_length=120)
    enabled: bool = True
    level_system_enabled: bool = False
    safety_mode: bool | None = None
    daily_limit: int = Field(default=20, ge=1, le=100000)
    cooldown_seconds: int = Field(default=60, ge=0, le=86400)


class UserWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    group_key: str = Field(min_length=1, max_length=240)
    qq: str = Field(min_length=1, max_length=120)
    grade: int = Field(ge=0, le=4)
    primary_group: str = Field(default="", max_length=240)


class EnabledWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


def group_store(settings):
    from .group_policy_runtime import GroupStore
    return GroupStore(settings.plugin_data_dir / "hub_state" / "group_management.sqlite3")


def _available(settings):
    if settings.execution_mode == "local":
        raise HTTPException(409, "本机执行模式不启用群聊权限；切换为完整远程服务模式后使用")


def _operate(settings, operation):
    from .group_policy_runtime import GroupPolicyError
    try:
        return operation(group_store(settings))
    except GroupPolicyError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/api/v1/capabilities", dependencies=[Depends(require_reader)])
def capabilities(request: Request):
    local = request.app.state.settings.execution_mode == "local"
    return {"execution_mode": "local" if local else "remote",
            "chat_group_platforms": [] if local else ["qq"], "features": {
        "chat_groups": not local, "platform_switchboard": not local,
        "local_generation": local, "qq_command_composer": True,
        "bilingual_tag_suggestions": True, "connection_guidance": True,
    }}


@router.get("/api/v1/admin/chat-groups", dependencies=[Depends(require_admin)])
def read_chat_groups(request: Request):
    settings = request.app.state.settings
    if settings.execution_mode == "local":
        return {"available": False, "enabled": False, "revision": "unavailable", "groups": [], "users": []}
    return {"available": True, **_operate(settings, lambda store: store.read())}


@router.put("/api/v1/admin/chat-groups/config", dependencies=[Depends(require_admin)])
def set_chat_groups(payload: EnabledWrite, request: Request):
    settings = request.app.state.settings
    _available(settings)
    _operate(settings, lambda store: store.set_enabled(payload.enabled))
    return read_chat_groups(request)


@router.put("/api/v1/admin/chat-groups/groups/{key}", dependencies=[Depends(require_admin)])
def write_chat_group(key: str, payload: GroupWrite, request: Request):
    settings = request.app.state.settings
    _available(settings)
    if key != payload.key or key != f"{payload.platform}:{payload.bot_id}:{payload.group_id}":
        raise HTTPException(422, "群标识与平台/账号/群号不一致")
    _operate(settings, lambda store: store.upsert_group(payload.model_dump()))
    return read_chat_groups(request)


@router.put("/api/v1/admin/chat-groups/users", dependencies=[Depends(require_admin)])
def write_chat_group_user(payload: UserWrite, request: Request):
    settings = request.app.state.settings
    _available(settings)
    if not payload.group_key.startswith("qq:") or (payload.primary_group and not payload.primary_group.startswith("qq:")):
        raise HTTPException(422, "本次群聊管理仅支持 QQ；TG/DC 群权限尚未启用")
    _operate(settings, lambda store: store.upsert_user(payload.model_dump()))
    return read_chat_groups(request)


@router.delete("/api/v1/admin/chat-groups/users", dependencies=[Depends(require_admin)])
def delete_chat_group_user(group_key: str, qq: str, request: Request, confirmed: bool = False):
    settings = request.app.state.settings
    _available(settings)
    if not confirmed:
        raise HTTPException(422, "删除群成员配置需要二次确认；不会删除令牌和历史任务")
    _operate(settings, lambda store: store.delete_user(group_key, qq))
    return read_chat_groups(request)
