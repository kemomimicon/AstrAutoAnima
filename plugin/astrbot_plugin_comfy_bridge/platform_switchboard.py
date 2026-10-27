"""Read the Hub-managed admission switches only when a new generation starts."""
from __future__ import annotations

import json
import re
from pathlib import Path


# Both QQ adapters already have generation/reply handlers. Keep their admission
# under the existing QQ switch without reinterpreting official IDs as QQ numbers.
DEFAULTS = {"aiocqhttp": True, "qq_official": True, "telegram": False, "discord": False, "webchat": True}
KEYS = {"aiocqhttp": "qq", "qq_official": "qq", "telegram": "telegram", "discord": "discord"}


def admission_denial(data_root: Path, platform_name: str) -> str | None:
    platform = str(platform_name).casefold()
    if platform == "webchat":
        return None  # Hub's authenticated API jobs have their own admission path.
    if platform not in DEFAULTS:
        return f"{platform or '未知'} 平台尚未接入 AAA 生图。"
    path = data_root / "hub_state" / "platform_switchboard.json"
    if path.is_symlink():
        return "平台切换板配置路径异常；已拒绝新生图任务。"
    if not path.exists():
        allowed = DEFAULTS[platform]
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            switches = data.get("accept_new")
            if not isinstance(switches, dict) or set(switches) != {"qq", "telegram", "discord"}:
                raise ValueError("invalid switches")
            if any(type(value) is not bool for value in switches.values()):
                raise ValueError("invalid switch values")
            allowed = switches[KEYS[platform]]
        except (OSError, ValueError, TypeError, KeyError):
            return "无法核实平台切换板配置；已拒绝新生图任务。"
    if not allowed:
        return f"{platform} 平台的 AAA 生图接单已关闭；已排队任务不受影响。"
    return None


def admit_event(data_root: Path, event) -> str | None:
    if getattr(event, "_aaa_platform_admitted", False) is True:
        return None
    platform = getattr(event, "get_platform_name", lambda: "")()
    denial = admission_denial(data_root, platform)
    if denial is None:
        setattr(event, "_aaa_platform_admitted", True)
    return denial


def safety_subject(platform_name: str, sender_id: str) -> str:
    """Keep platform credits independent; never reinterpret a Discord/TG ID as QQ."""
    platform = str(platform_name).casefold()
    sender = str(sender_id)
    if platform in {"telegram", "discord"}:
        if not re.fullmatch(r"[0-9]{1,24}", sender):
            raise ValueError("invalid platform user id")
        return f"{platform}:{sender}"
    return sender


def valid_credit_subject(subject: str) -> bool:
    return bool(re.fullmatch(r"(?:[1-9][0-9]{4,14}|(?:telegram|discord):[0-9]{1,24})", subject))
