from __future__ import annotations

from typing import Any

from .character_catalog import clean_values, get_character
from .config import Settings
from .repositories import RepositoryError
from .schemas import CharacterDictionaryUpdateRequest, MutationResponse
from .storage import mutate_json, move_to_trash


def _initialize() -> dict[str, Any]:
    return {"schema_version": "1.0", "entries": {}}


def update_character(
    settings: Settings,
    tag: str,
    payload: CharacterDictionaryUpdateRequest,
    expected_revision: str,
    actor: str,
) -> MutationResponse:
    character = get_character(
        settings.character_dictionary_path,
        tag,
        edits_path=settings.character_dictionary_edits_path,
        include_disabled=True,
    )
    if character is None:
        raise RepositoryError(f"character not found: {tag}")
    changes = payload.model_dump(exclude_none=True)
    for field in ("aliases", "copyright", "gender", "appearance"):
        if field in changes:
            changes[field] = list(clean_values(changes[field]))

    def apply(data: dict[str, Any]) -> None:
        entries = data.setdefault("entries", {})
        if not isinstance(entries, dict):
            raise RepositoryError("character edits entries must be an object")
        current = entries.setdefault(tag, {})
        if not isinstance(current, dict):
            current = {}
            entries[tag] = current
        current.update(changes)

    _, revision, backup = mutate_json(
        path=settings.character_dictionary_edits_path,
        resource="character_dictionary",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="update",
        target=tag,
        mutate=apply,
        initialize=_initialize,
    )
    return MutationResponse(
        action="updated", resource=tag, revision=revision,
        backup=str(backup) if backup else None,
    )


def disable_character(
    settings: Settings,
    tag: str,
    expected_revision: str,
    actor: str,
) -> MutationResponse:
    character = get_character(
        settings.character_dictionary_path,
        tag,
        edits_path=settings.character_dictionary_edits_path,
        include_disabled=True,
    )
    if character is None:
        raise RepositoryError(f"character not found: {tag}")

    def apply(data: dict[str, Any]) -> None:
        entries = data.setdefault("entries", {})
        if not isinstance(entries, dict):
            raise RepositoryError("character edits entries must be an object")
        current = entries.setdefault(tag, {})
        if not isinstance(current, dict):
            current = {}
            entries[tag] = current
        current["disabled"] = True
        move_to_trash(settings.trash_dir, "character_dictionary", tag, character)

    _, revision, backup = mutate_json(
        path=settings.character_dictionary_edits_path,
        resource="character_dictionary",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="delete",
        target=tag,
        mutate=apply,
        initialize=_initialize,
    )
    return MutationResponse(
        action="deleted", resource=tag, revision=revision,
        backup=str(backup) if backup else None,
    )
