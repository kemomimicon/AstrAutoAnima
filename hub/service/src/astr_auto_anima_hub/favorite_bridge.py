"""Publish non-secret favorite reader configuration to the local bot plugin."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from .config import Settings


def publish_favorite_bridge(settings: Settings) -> Path:
    # Settings remain authoritative. Do not copy tokens or favorite contents,
    # invent an account, or re-import legacy collections.
    qq = settings.legacy_lite_qq.strip()
    if not settings.lite_token or re.fullmatch(r"[1-9][0-9]{4,14}", qq) is None:
        qq = ""
    document = {
        "schema": "aaa-favorite-reader-v1",
        "legacy_qq": qq,
        "users_path": str(settings.lite_users_path.resolve()),
        "favorites_path": str(settings.prompt_favorites_path.resolve()),
    }
    path = settings.hub_state_dir / "favorite_reader.json"
    if path.is_symlink():
        raise ValueError("favorite reader configuration must not be a symlink")
    raw = (json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == raw:
        return path
    fd, temporary = tempfile.mkstemp(prefix=".favorite_reader_", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path
