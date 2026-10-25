"""AAA admission switches for AstrBot's existing message-platform adapters.

This never configures or starts an AstrBot adapter and never reads its token.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .config import Settings
from .repositories import RepositoryError, file_revision, read_json_object
from .storage import mutate_json


DEFAULTS = {"qq": True, "telegram": False, "discord": False}
ADAPTER_TYPES = {"qq": {"aiocqhttp"}, "telegram": {"telegram"}, "discord": {"discord"}}


class PlatformSwitches(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    qq: bool = True
    telegram: bool = False
    discord: bool = False


def board_path(settings: Settings) -> Path:
    return settings.plugin_data_dir / "hub_state" / "platform_switchboard.json"


def _adapter_states(settings: Settings) -> dict[str, str]:
    """Report configuration, never online status or secrets."""
    result = {key: "unknown" for key in DEFAULTS}
    # In the normal deployment plugin_data_dir is AstrBot/data/plugin_data/<plugin>.
    path = settings.plugin_data_dir.parent.parent / "cmd_config.json"
    try:
        if path.is_symlink() or not path.is_file():
            return result
        config = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = config.get("platform", [])
        if not isinstance(rows, list):
            return result
        for key, names in ADAPTER_TYPES.items():
            matches = [row for row in rows if isinstance(row, dict)
                       and str(row.get("type", "")).casefold() in names]
            result[key] = ("configured_enabled" if any(row.get("enable") is True for row in matches)
                           else "configured_disabled" if matches else "not_configured")
    except (OSError, ValueError, TypeError):
        return result
    return result


def read_board(settings: Settings) -> dict:
    path = board_path(settings)
    if not path.exists():
        switches = dict(DEFAULTS)
        revision = "missing"
    else:
        data = read_json_object(path)
        raw = data.get("accept_new")
        if not isinstance(raw, dict) or set(raw) != set(DEFAULTS) or any(type(v) is not bool for v in raw.values()):
            raise RepositoryError("platform switchboard is invalid")
        switches = dict(raw)
        revision = file_revision(path, "platform_switchboard").revision
    return {"accept_new": switches, "revision": revision,
            "adapter_configuration": _adapter_states(settings),
            "note": "仅控制 AAA 是否接收新生图任务；账号、令牌和在线状态在 AstrBot 机器人面板管理。"}


def write_board(settings: Settings, payload: PlatformSwitches, revision: str, actor: str) -> dict:
    switches = payload.model_dump()

    def update(data: dict) -> None:
        data["accept_new"] = switches

    _, _, _ = mutate_json(
        path=board_path(settings), resource="platform_switchboard", expected_revision=revision,
        backup_root=settings.backup_dir, audit_path=settings.audit_log_path,
        actor=actor, action="replace", target="platforms", mutate=update,
        initialize=lambda: {"accept_new": dict(DEFAULTS)},
    )
    return read_board(settings)
