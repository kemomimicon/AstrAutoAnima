from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path


_QQ_PATTERN = re.compile(r"^[1-9][0-9]{4,14}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class LiteUserRegistryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LiteUser:
    id: str
    label: str
    qq: str
    token_sha256: str
    allow_group: bool = True


def hash_lite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_lite_users(path: Path) -> list[LiteUser]:
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiteUserRegistryError(f"invalid Lite user registry: {exc}") from exc
    raw_users = payload.get("users", []) if isinstance(payload, dict) else []
    if not isinstance(raw_users, list):
        raise LiteUserRegistryError("Lite user registry must contain a users list")

    users: list[LiteUser] = []
    seen_ids: set[str] = set()
    seen_qq: set[str] = set()
    seen_hashes: set[str] = set()
    for raw in raw_users:
        if not isinstance(raw, dict) or not bool(raw.get("enabled", True)):
            continue
        user_id = str(raw.get("id", "")).strip()
        label = str(raw.get("label", "")).strip()
        qq = str(raw.get("qq", "")).strip()
        token_sha256 = str(raw.get("token_sha256", "")).strip().lower()
        if not _ID_PATTERN.fullmatch(user_id):
            raise LiteUserRegistryError(f"invalid Lite user id: {user_id!r}")
        if not label or len(label) > 120:
            raise LiteUserRegistryError(f"invalid Lite user label: {user_id}")
        if not _QQ_PATTERN.fullmatch(qq):
            raise LiteUserRegistryError(f"invalid QQ number for Lite user: {user_id}")
        if not _SHA256_PATTERN.fullmatch(token_sha256):
            raise LiteUserRegistryError(f"invalid token hash for Lite user: {user_id}")
        if user_id in seen_ids or qq in seen_qq or token_sha256 in seen_hashes:
            raise LiteUserRegistryError("duplicate Lite user id, QQ number, or token hash")
        seen_ids.add(user_id)
        seen_qq.add(qq)
        seen_hashes.add(token_sha256)
        users.append(
            LiteUser(
                id=user_id,
                label=label,
                qq=qq,
                token_sha256=token_sha256,
                allow_group=bool(raw.get("allow_group", True)),
            )
        )
    return users


def authenticate_lite_user(path: Path, supplied_token: str) -> LiteUser | None:
    if not supplied_token:
        return None
    supplied_hash = hash_lite_token(supplied_token)
    match: LiteUser | None = None
    for user in load_lite_users(path):
        if secrets.compare_digest(user.token_sha256, supplied_hash):
            match = user
    return match
