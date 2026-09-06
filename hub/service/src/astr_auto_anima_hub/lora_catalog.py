from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .repositories import RepositoryError, file_revision, read_json_object
from .schemas import (
    LoraCatalogItem,
    LoraCatalogResponse,
    LoraCatalogUpdateRequest,
    MutationResponse,
)
from .storage import ResourceNotFound, mutate_json


def _empty_catalog() -> dict[str, Any]:
    return {"schema_version": "1.0", "entries": {}}


def _scan_files(root: Path) -> dict[str, dict[str, Any]]:
    if not root.is_dir():
        raise RepositoryError(f"LoRA directory does not exist: {root}")
    found: dict[str, dict[str, Any]] = {}
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            name for name in directories if not (current_path / name).is_symlink()
        ]
        for filename in filenames:
            if not filename.casefold().endswith(".safetensors"):
                continue
            path = current_path / filename
            if path.is_symlink() or not path.is_file():
                continue
            try:
                stat = path.stat()
                relative = path.relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            found[relative] = {
                "path": relative,
                "size_bytes": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
            }
    return found


def _items(data: dict[str, Any], *, only_styles: bool = False) -> list[LoraCatalogItem]:
    entries = data.get("entries", {})
    if not isinstance(entries, dict):
        raise RepositoryError("LoRA catalog entries must be an object")
    items: list[LoraCatalogItem] = []
    for relative, raw in entries.items():
        if not isinstance(raw, dict):
            continue
        payload = {"path": str(relative), **raw}
        try:
            item = LoraCatalogItem.model_validate(payload)
        except ValueError:
            continue
        if only_styles and not (
            item.category == "style" and item.enabled and item.present
        ):
            continue
        items.append(item)
    items.sort(key=lambda item: (item.display_name.casefold(), item.path.casefold()))
    return items


def scan_loras(settings: Settings, actor: str) -> LoraCatalogResponse:
    files = _scan_files(settings.lora_root)
    current = file_revision(settings.lora_catalog_path, "loras").revision or "missing"

    def mutate(data: dict[str, Any]) -> None:
        entries = data.setdefault("entries", {})
        if not isinstance(entries, dict):
            raise RepositoryError("LoRA catalog entries must be an object")
        for relative, raw in list(entries.items()):
            if isinstance(raw, dict):
                raw["present"] = relative in files
        for relative, scanned in files.items():
            existing = entries.get(relative)
            if not isinstance(existing, dict):
                existing = {
                    "display_name": Path(relative).stem,
                    "category": "unclassified",
                    "recommended_prompt": "",
                    "enabled": True,
                }
                entries[relative] = existing
            existing.update(scanned)
            existing["present"] = True
        data["schema_version"] = "1.0"
        data["scanned_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    _, revision, _ = mutate_json(
        path=settings.lora_catalog_path,
        resource="loras",
        expected_revision=current,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="scan",
        target=str(settings.lora_root),
        mutate=mutate,
        initialize=_empty_catalog,
    )
    data = read_json_object(settings.lora_catalog_path)
    from .personal_styles import prune_missing_personal_style_loras

    prune_missing_personal_style_loras(settings, actor=actor)
    return LoraCatalogResponse(
        items=_items(data),
        revision=revision,
        scanned_at=datetime.fromisoformat(str(data["scanned_at"])),
    )


def list_style_loras(settings: Settings) -> LoraCatalogResponse:
    if not settings.lora_catalog_path.is_file():
        return LoraCatalogResponse(
            items=[], revision="missing", scanned_at=datetime.now().astimezone()
        )
    data = read_json_object(settings.lora_catalog_path)
    scanned_at = data.get("scanned_at")
    try:
        timestamp = datetime.fromisoformat(str(scanned_at))
    except ValueError:
        timestamp = datetime.fromtimestamp(settings.lora_catalog_path.stat().st_mtime).astimezone()
    return LoraCatalogResponse(
        items=_items(data, only_styles=True),
        revision=file_revision(settings.lora_catalog_path, "loras").revision or "missing",
        scanned_at=timestamp,
    )


def update_lora(
    settings: Settings,
    relative_path: str,
    payload: LoraCatalogUpdateRequest,
    expected_revision: str,
    actor: str,
) -> MutationResponse:
    normalized = Path(relative_path.replace("\\", "/")).as_posix().lstrip("/")
    if not normalized or normalized.startswith("../") or "/../" in normalized:
        raise ResourceNotFound("invalid LoRA path")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise RepositoryError("at least one LoRA field must be supplied")

    def mutate(data: dict[str, Any]) -> None:
        entries = data.get("entries", {})
        entry = entries.get(normalized) if isinstance(entries, dict) else None
        if not isinstance(entry, dict):
            raise ResourceNotFound(f"LoRA not found: {normalized}")
        entry.update(changes)

    _, revision, backup = mutate_json(
        path=settings.lora_catalog_path,
        resource="loras",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="update",
        target=normalized,
        mutate=mutate,
    )
    return MutationResponse(
        action="updated",
        resource=normalized,
        revision=revision,
        backup=str(backup) if backup else None,
    )
