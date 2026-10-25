"""Read a QQ user's separate prompt favorites without modifying the main pool."""

from __future__ import annotations

import json
import re
import math
import time
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

def _hub_favorite_owner(plugin_data: Path, event: Any) -> str | None:
    """Only a server-written, session-bound capability may identify a Hub owner.

    A webchat display name (including hub_user_*) is NOT an authenticated QQ.
    None denotes a native platform event, which still uses QQ registration.
    """
    platform = str(getattr(event, "get_platform_name", lambda: "")()).casefold()
    origin = str(getattr(event, "unified_msg_origin", "") or "").split(":", 1)[0].casefold()
    if platform != "webchat" and origin != "webchat":
        return None
    from .workflow_runtime import WorkflowError
    sender = str(event.get_sender_id())
    match = re.search(r"(?:^|_)aaa_safe_([a-f0-9]{32})$", sender)
    if not match:
        raise WorkflowError("个人库缺少 Hub 身份凭据，请更新 Hub 后重新提交")
    path = plugin_data / "safety" / "tickets" / f"{match[1]}.json"
    try:
        if path.resolve() != path or not path.is_file() or path.stat().st_size > 8192:
            raise ValueError("ticket path")
        ticket = json.loads(path.read_text(encoding="utf-8"))
        expires = float(ticket.get("expires", 0))
        owner, root = ticket.get("favorites_owner"), ticket.get("root")
        if (not math.isfinite(expires) or expires <= time.time()
                or not isinstance(root, str) or re.fullmatch(r"[a-f0-9]{32}", root) is None
                or not isinstance(owner, str) or not owner.strip() or len(owner) > 200
                or ticket.get("favorites_scope") != "prompt-favorites:read"):
            raise ValueError("invalid capability")
        session = str(event.get_session_id())
        if session not in {f"hub_job_{root}", f"webchat!{sender}!hub_job_{root}"}:
            raise ValueError("session mismatch")
        return owner
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise WorkflowError("个人库身份凭据无效、过期或不属于本次任务，请重新提交") from exc


def _reader_config(plugin_data: Path) -> tuple[Path, Path, str]:
    state = plugin_data / "hub_state"
    bridge = state / "favorite_reader.json"
    if bridge.is_symlink():
        raise ValueError("个人收藏读取配置不能是链接")
    if not bridge.exists():
        return state / "lite_users.json", state / "prompt_favorites.sqlite3", ""
    if not bridge.is_file() or bridge.stat().st_size > 8192:
        raise ValueError("个人收藏读取配置异常")
    payload = json.loads(bridge.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("schema") != "aaa-favorite-reader-v1":
        raise ValueError("个人收藏读取配置版本异常")
    values = [payload.get(key) for key in ("users_path", "favorites_path", "legacy_qq")]
    if not all(isinstance(value, str) for value in values):
        raise ValueError("个人收藏读取配置缺少字段")
    registry, database, legacy_qq = Path(values[0]), Path(values[1]), values[2]
    if not registry.is_absolute() or not database.is_absolute():
        raise ValueError("个人收藏读取路径必须为绝对路径")
    if legacy_qq and re.fullmatch(r"[1-9][0-9]{4,14}", legacy_qq) is None:
        raise ValueError("个人收藏旧账号绑定异常")
    return registry, database, legacy_qq


def personal_prompts(
    plugin_data: Path, qq: str, legacy_rows: list[dict[str, Any]] | None = None,
    *, event: Any = None,
) -> list[dict[str, Any]]:
    trusted_owner = _hub_favorite_owner(plugin_data, event) if event is not None else None
    qq = str(qq).strip()
    if trusted_owner is None and re.fullmatch(r"[1-9][0-9]{4,14}", qq) is None:
        return []
    registry, database, legacy_qq = _reader_config(plugin_data)
    if trusted_owner is not None:
        # This is the exact authenticated App principal, NOT the delivery
        # target's QQ, safety-admin QQ, or a username supplied by the caller.
        owner = trusted_owner
    else:
        payload = json.loads(registry.read_text(encoding="utf-8-sig")) if registry.exists() else {"users": []}
        if not isinstance(payload, dict) or not isinstance(payload.get("users"), list):
            raise ValueError("个人收藏用户注册表异常")
        # An explicit registered account takes precedence. Disabled/ambiguous
        # bindings never fall back to the legacy owner.
        matches = [user for user in payload["users"] if isinstance(user, dict)
                   and str(user.get("qq", "")).strip() == qq]
        if matches:
            if len(matches) != 1 or not matches[0].get("enabled", True):
                return []
            owner = str(matches[0].get("id", "")).strip()
        else:
            owner = "legacy-owner" if legacy_qq == qq else ""
    if not owner:
        return []
    rows = []
    if database.is_file():
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            rows = db.execute(
                "SELECT id,prompt,name,safety_code FROM favorites WHERE owner=? ORDER BY created_at DESC",
                (owner,),
            ).fetchall()
    result = [{"id": ident, "prompt": prompt, "name": name, "source_code": "P",
             "source_group": "liked", "safety_code": safety,
             "safety_level": {"N": "normal", "H": "nsfw", "S": "sexual"}.get(safety, "normal"),
             "enabled": True, "categories": ["liked"]}
            for ident, prompt, name, safety in rows]
    seen = {" ".join(str(row["prompt"]).casefold().split()) for row in result}
    for row in legacy_rows or []:
        if str(row.get("liked_by", "")) != owner or not row.get("enabled", True):
            continue
        prompt = str(row.get("prompt", ""))
        normalized = " ".join(prompt.casefold().split())
        if normalized and normalized not in seen:
            result.append(dict(row))
            seen.add(normalized)
    return result
