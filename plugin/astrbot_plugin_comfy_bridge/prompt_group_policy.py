"""On-demand prompt group policy lookup; no polling or background sync."""
from __future__ import annotations

import json
from pathlib import Path


def private_group_denial(registry: Path, selected: list[str]) -> str | None:
    return group_denial(registry, selected, private=True)


def group_denial(registry: Path, selected: list[str], *, private=False, safety=()) -> str | None:
    if not selected:
        return None
    try:
        data = json.loads(registry.read_text(encoding="utf-8-sig"))
        groups = data.get("groups", [])
        if not isinstance(groups, list):
            raise ValueError("groups must be a list")
        allowed = {
            str(item.get("id", "")).casefold(): item
            for item in groups if isinstance(item, dict)
        }
    except (OSError, ValueError, TypeError):
        return "无法读取自定义分组权限；本次抽取已拒绝。"
    for group in selected:
        name = str(group).casefold()
        if name not in allowed:
            return f"自定义分组 @{name} 尚未登记，本次抽取已拒绝。"
        row = allowed[name]
        if (row.get("enabled", True) is not True
                or row.get("allow_private" if private else "allow_group", not private) is not True):
            return f"自定义分组 @{name} 已停用或不允许当前会话抽取。"
        levels = row.get("safety_codes", ["N", "H", "S"])
        if not isinstance(levels, list) or any(s not in levels for s in safety):
            return f"自定义分组 @{name} 不允许所选内容级别。"
    return None
