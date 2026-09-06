from __future__ import annotations

from datetime import datetime
from typing import Any

from .auth import AuthPrincipal
from .character_catalog import get_character
from .config import Settings
from .repositories import RepositoryError, file_revision, read_json_object
from .schemas import (
    CharacterFavoriteListResponse,
    CharacterFavoriteRecord,
    CharacterFavoriteWriteRequest,
)
from .storage import mutate_json


def _owner(principal: AuthPrincipal) -> str:
    return f"{principal.role}:{principal.subject}"


def _initialize() -> dict[str, Any]:
    return {"schema_version": "1.0", "users": {}}


def list_character_favorites(
    settings: Settings,
    principal: AuthPrincipal,
) -> CharacterFavoriteListResponse:
    path = settings.character_favorites_path
    data = read_json_object(path) if path.is_file() else _initialize()
    users = data.get("users", {})
    raw_items = users.get(_owner(principal), []) if isinstance(users, dict) else []
    items: list[CharacterFavoriteRecord] = []
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict):
            continue
        tag = str(raw.get("tag", "")).strip()
        character = get_character(
            settings.character_dictionary_path,
            tag,
            edits_path=settings.character_dictionary_edits_path,
        )
        if character is None:
            continue
        name = str(raw.get("name", "")).strip()
        if not name:
            chinese = character.get("chinese_names", ())
            name = str(chinese[0]) if chinese else tag
        mode = "strong" if raw.get("mode") == "strong" else "weak"
        items.append(
            CharacterFavoriteRecord(
                tag=tag, name=name, mode=mode,
                weak_prompt=str(character["weak_prompt"]),
                strong_prompt=str(character["strong_prompt"]),
            )
        )
    items.sort(key=lambda item: (item.name.casefold(), item.tag))
    return CharacterFavoriteListResponse(
        items=items,
        revision=file_revision(path, "character_favorites").revision or "missing",
    )


def write_character_favorite(
    settings: Settings,
    principal: AuthPrincipal,
    tag: str,
    payload: CharacterFavoriteWriteRequest,
    expected_revision: str,
) -> CharacterFavoriteListResponse:
    character = get_character(
        settings.character_dictionary_path,
        tag,
        edits_path=settings.character_dictionary_edits_path,
    )
    if character is None:
        raise RepositoryError(f"character is unavailable: {tag}")
    chinese = character.get("chinese_names", ())
    default_name = str(chinese[0]) if chinese else tag

    def apply(data: dict[str, Any]) -> None:
        users = data.setdefault("users", {})
        if not isinstance(users, dict):
            raise RepositoryError("character favorites users must be an object")
        items = users.setdefault(_owner(principal), [])
        if not isinstance(items, list):
            items = []
            users[_owner(principal)] = items
        entry = next(
            (item for item in items if isinstance(item, dict) and item.get("tag") == tag),
            None,
        )
        value = {
            "tag": tag,
            "name": payload.name.strip() or default_name,
            "mode": payload.mode,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if entry is None:
            items.append(value)
        else:
            entry.clear()
            entry.update(value)

    mutate_json(
        path=settings.character_favorites_path,
        resource="character_favorites",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=f"user:{_owner(principal)}",
        action="write",
        target=tag,
        mutate=apply,
        initialize=_initialize,
    )
    return list_character_favorites(settings, principal)


def delete_character_favorite(
    settings: Settings,
    principal: AuthPrincipal,
    tag: str,
    expected_revision: str,
) -> CharacterFavoriteListResponse:
    def apply(data: dict[str, Any]) -> None:
        users = data.get("users", {})
        items = users.get(_owner(principal), []) if isinstance(users, dict) else []
        before = len(items) if isinstance(items, list) else 0
        if isinstance(items, list):
            users[_owner(principal)] = [
                item for item in items
                if not isinstance(item, dict) or item.get("tag") != tag
            ]
        if before == len(users.get(_owner(principal), [])):
            raise RepositoryError(f"favorite not found: {tag}")

    mutate_json(
        path=settings.character_favorites_path,
        resource="character_favorites",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=f"user:{_owner(principal)}",
        action="delete",
        target=tag,
        mutate=apply,
        initialize=_initialize,
    )
    return list_character_favorites(settings, principal)
