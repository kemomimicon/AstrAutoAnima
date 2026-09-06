from __future__ import annotations

import hashlib
from typing import Any

from .auth import AuthPrincipal
from .config import Settings
from .repositories import RepositoryError, file_revision, read_json_object
from .schemas import (
    PersonalStyleListResponse,
    PersonalStyleRecord,
    PersonalStyleWriteRequest,
)
from .storage import ResourceNotFound, mutate_json


def _require_owner(principal: AuthPrincipal) -> None:
    if principal.role == "legacy_lite":
        raise RepositoryError("共享用户令牌不能保存个人预设，请使用绑定 QQ 的个人令牌")


def _style_key(principal: AuthPrincipal, slot: int) -> str:
    return _style_key_for_subject(principal.subject, slot)


def _style_key_for_subject(subject: str, slot: int) -> str:
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:14]
    return f"__hub_personal_{digest}_{slot}"


def _empty_personal_styles() -> dict[str, Any]:
    return {"schema_version": "1.0", "users": {}}


def _validate_loras(settings: Settings, payload: PersonalStyleWriteRequest) -> None:
    if not settings.lora_catalog_path.is_file():
        raise RepositoryError("LoRA 目录尚未扫描，请先让管理员扫描并分类")
    catalog = read_json_object(settings.lora_catalog_path).get("entries", {})
    if not isinstance(catalog, dict):
        raise RepositoryError("LoRA catalog entries must be an object")
    seen: set[str] = set()
    for item in payload.loras:
        if item.path in seen:
            raise RepositoryError(f"同一个 LoRA 不能重复添加：{item.path}")
        seen.add(item.path)
        entry = catalog.get(item.path)
        if not isinstance(entry, dict) or not (
            entry.get("category") == "style"
            and bool(entry.get("enabled", True))
            and bool(entry.get("present", False))
        ):
            raise RepositoryError(f"LoRA 未被管理员设为可用画风：{item.path}")


def _records(settings: Settings, principal: AuthPrincipal) -> PersonalStyleListResponse:
    _require_owner(principal)
    if not settings.personal_styles_path.is_file():
        return PersonalStyleListResponse(items=[], revision="missing")
    data = read_json_object(settings.personal_styles_path)
    users = data.get("users", {})
    raw_slots = users.get(principal.subject, {}) if isinstance(users, dict) else {}
    items: list[PersonalStyleRecord] = []
    if isinstance(raw_slots, dict):
        for slot_text, raw in raw_slots.items():
            if not isinstance(raw, dict):
                continue
            try:
                slot = int(slot_text)
                items.append(
                    PersonalStyleRecord(
                        slot=slot,
                        name=str(raw.get("name", "")),
                        prompt=str(raw.get("prompt", "")),
                        loras=raw.get("loras", []),
                        style_key=_style_key(principal, slot),
                    )
                )
            except (TypeError, ValueError):
                continue
    items.sort(key=lambda item: item.slot)
    return PersonalStyleListResponse(
        items=items,
        revision=file_revision(settings.personal_styles_path, "personal_styles").revision
        or "missing",
    )


def list_personal_styles(
    settings: Settings, principal: AuthPrincipal
) -> PersonalStyleListResponse:
    return _records(settings, principal)


def resolve_personal_style_key(
    settings: Settings, principal: AuthPrincipal, slot: int
) -> str:
    records = _records(settings, principal)
    record = next((item for item in records.items if item.slot == slot), None)
    if record is None:
        raise ResourceNotFound(f"personal style slot is empty: {slot}")
    return record.style_key


def _sync_plugin_preset(
    settings: Settings,
    principal: AuthPrincipal,
    slot: int,
    payload: PersonalStyleWriteRequest | None,
) -> None:
    revision = file_revision(settings.preset_path, "presets").revision or "missing"
    style_key = _style_key(principal, slot)

    def initialize() -> dict[str, Any]:
        return {"version": 1, "styles": {}, "characters": {}}

    def mutate(data: dict[str, Any]) -> None:
        styles = data.setdefault("styles", {})
        data.setdefault("characters", {})
        if not isinstance(styles, dict):
            raise RepositoryError("presets styles must be an object")
        if payload is None:
            styles.pop(style_key, None)
            return
        styles[style_key] = {
            "loras": [
                {
                    "name": item.path,
                    "strength_model": item.strength,
                    "strength_clip": item.strength,
                }
                for item in payload.loras
            ],
            "prompt": payload.prompt.strip(" ,\n\t"),
            "match": [],
            "hidden": True,
            "owner_hash": style_key.split("_")[-2],
            "display_name": payload.name,
        }

    mutate_json(
        path=settings.preset_path,
        resource="presets",
        expected_revision=revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=f"{principal.role}:{principal.subject}",
        action="sync_personal_style" if payload else "remove_personal_style",
        target=style_key,
        mutate=mutate,
        initialize=initialize,
    )


def write_personal_style(
    settings: Settings,
    principal: AuthPrincipal,
    slot: int,
    payload: PersonalStyleWriteRequest,
    expected_revision: str,
) -> PersonalStyleListResponse:
    _require_owner(principal)
    if slot not in {1, 2, 3}:
        raise ResourceNotFound("personal style slot must be 1, 2 or 3")
    _validate_loras(settings, payload)

    def mutate(data: dict[str, Any]) -> None:
        users = data.setdefault("users", {})
        if not isinstance(users, dict):
            raise RepositoryError("personal style users must be an object")
        slots = users.setdefault(principal.subject, {})
        if not isinstance(slots, dict):
            raise RepositoryError("personal style slots must be an object")
        slots[str(slot)] = {
            "name": payload.name.strip(),
            "prompt": payload.prompt.strip(" ,\n\t"),
            "loras": [item.model_dump() for item in payload.loras],
        }

    mutate_json(
        path=settings.personal_styles_path,
        resource="personal_styles",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=f"{principal.role}:{principal.subject}",
        action="write",
        target=f"{principal.subject}:{slot}",
        mutate=mutate,
        initialize=_empty_personal_styles,
    )
    _sync_plugin_preset(settings, principal, slot, payload)
    return _records(settings, principal)


def delete_personal_style(
    settings: Settings,
    principal: AuthPrincipal,
    slot: int,
    expected_revision: str,
) -> PersonalStyleListResponse:
    _require_owner(principal)
    if slot not in {1, 2, 3}:
        raise ResourceNotFound("personal style slot must be 1, 2 or 3")

    def mutate(data: dict[str, Any]) -> None:
        users = data.get("users", {})
        slots = users.get(principal.subject, {}) if isinstance(users, dict) else {}
        if not isinstance(slots, dict) or str(slot) not in slots:
            raise ResourceNotFound(f"personal style slot is empty: {slot}")
        del slots[str(slot)]
        if not slots:
            users.pop(principal.subject, None)

    mutate_json(
        path=settings.personal_styles_path,
        resource="personal_styles",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=f"{principal.role}:{principal.subject}",
        action="delete",
        target=f"{principal.subject}:{slot}",
        mutate=mutate,
    )
    _sync_plugin_preset(settings, principal, slot, None)
    return _records(settings, principal)


def prune_missing_personal_style_loras(
    settings: Settings,
    *,
    actor: str,
) -> dict[str, int]:
    """Drop unavailable LoRAs after a catalog scan and free empty user slots."""

    if not settings.personal_styles_path.is_file():
        return {"removed_loras": 0, "removed_slots": 0, "updated_slots": 0}
    catalog = read_json_object(settings.lora_catalog_path).get("entries", {})
    if not isinstance(catalog, dict):
        raise RepositoryError("LoRA catalog entries must be an object")
    available = {
        str(path)
        for path, raw in catalog.items()
        if isinstance(raw, dict)
        and raw.get("category") == "style"
        and bool(raw.get("enabled", True))
        and bool(raw.get("present", False))
    }
    counts = {"removed_loras": 0, "removed_slots": 0, "updated_slots": 0}
    current = (
        file_revision(settings.personal_styles_path, "personal_styles").revision
        or "missing"
    )

    def mutate(data: dict[str, Any]) -> None:
        users = data.get("users", {})
        if not isinstance(users, dict):
            raise RepositoryError("personal style users must be an object")
        for subject, raw_slots in list(users.items()):
            if not isinstance(raw_slots, dict):
                users.pop(subject, None)
                continue
            for slot, raw in list(raw_slots.items()):
                if not isinstance(raw, dict):
                    raw_slots.pop(slot, None)
                    counts["removed_slots"] += 1
                    continue
                loras = raw.get("loras", [])
                if not isinstance(loras, list):
                    loras = []
                kept = [
                    item
                    for item in loras
                    if isinstance(item, dict) and str(item.get("path", "")) in available
                ]
                counts["removed_loras"] += len(loras) - len(kept)
                if not kept:
                    raw_slots.pop(slot, None)
                    counts["removed_slots"] += 1
                elif len(kept) != len(loras):
                    raw["loras"] = kept
                    counts["updated_slots"] += 1
            if not raw_slots:
                users.pop(subject, None)

    mutate_json(
        path=settings.personal_styles_path,
        resource="personal_styles",
        expected_revision=current,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="prune_missing_loras",
        target=str(settings.lora_root),
        mutate=mutate,
        initialize=_empty_personal_styles,
    )

    personal = read_json_object(settings.personal_styles_path)
    users = personal.get("users", {})
    preset_revision = file_revision(settings.preset_path, "presets").revision or "missing"

    def initialize_presets() -> dict[str, Any]:
        return {"version": 1, "styles": {}, "characters": {}}

    def sync(data: dict[str, Any]) -> None:
        styles = data.setdefault("styles", {})
        data.setdefault("characters", {})
        if not isinstance(styles, dict):
            raise RepositoryError("presets styles must be an object")
        for key in list(styles):
            raw = styles.get(key)
            if key.startswith("__hub_personal_") and isinstance(raw, dict):
                styles.pop(key, None)
        if not isinstance(users, dict):
            return
        for subject, raw_slots in users.items():
            if not isinstance(raw_slots, dict):
                continue
            for slot_text, raw in raw_slots.items():
                if not isinstance(raw, dict):
                    continue
                try:
                    slot = int(slot_text)
                except ValueError:
                    continue
                style_key = _style_key_for_subject(str(subject), slot)
                loras = raw.get("loras", [])
                styles[style_key] = {
                    "loras": [
                        {
                            "name": str(item.get("path", "")),
                            "strength_model": float(item.get("strength", 1.0)),
                            "strength_clip": float(item.get("strength", 1.0)),
                        }
                        for item in loras
                        if isinstance(item, dict) and item.get("path")
                    ],
                    "prompt": str(raw.get("prompt", "")).strip(" ,\n\t"),
                    "match": [],
                    "hidden": True,
                    "owner_hash": style_key.split("_")[-2],
                    "display_name": str(raw.get("name", "")),
                }

    mutate_json(
        path=settings.preset_path,
        resource="presets",
        expected_revision=preset_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="sync_pruned_personal_styles",
        target=str(settings.personal_styles_path),
        mutate=sync,
        initialize=initialize_presets,
    )
    return counts
