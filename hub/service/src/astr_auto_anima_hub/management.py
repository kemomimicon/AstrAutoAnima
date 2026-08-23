from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from .config import Settings
from .repositories import RepositoryError, read_json_object
from .schemas import (
    MutationResponse,
    PresetWriteRequest,
    PromptCreateRequest,
    PromptImportRequest,
    PromptUpdateRequest,
)
from .storage import (
    DuplicateResource,
    ResourceNotFound,
    SAFETY_NAMES,
    SOURCE_NAMES,
    content_hash,
    clean_categories,
    move_to_trash,
    mutate_json,
    new_prompt_id,
    prompt_entry,
)


def _find_prompt(data: dict[str, Any], prompt_id: str) -> dict[str, Any]:
    prompts = data.get("prompts")
    if not isinstance(prompts, list):
        raise RepositoryError("prompt pool must contain a prompts list")
    folded = prompt_id.casefold()
    for item in prompts:
        if isinstance(item, dict) and str(item.get("id", "")).casefold() == folded:
            return item
    raise ResourceNotFound(f"prompt not found: {prompt_id}")


def _result(
    action: Literal["created", "updated", "deleted", "imported"],
    resource: str,
    revision: str,
    backup: Path | None,
    *,
    count: int = 1,
) -> MutationResponse:
    return MutationResponse(
        action=action,
        resource=resource,
        revision=revision,
        backup=str(backup) if backup else None,
        count=count,
    )


def create_prompt(
    settings: Settings,
    payload: PromptCreateRequest,
    expected_revision: str,
    actor: str,
) -> MutationResponse:
    entry = prompt_entry(payload.model_dump())

    def mutate(data: dict[str, Any]) -> None:
        prompts = data.get("prompts")
        if not isinstance(prompts, list):
            raise RepositoryError("prompt pool must contain a prompts list")
        prompts.append(entry)

    _, revision, backup = mutate_json(
        path=settings.prompt_pool_path,
        resource="prompts",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="create",
        target=entry["id"],
        mutate=mutate,
    )
    return _result("created", entry["id"], revision, backup)


def update_prompt(
    settings: Settings,
    prompt_id: str,
    payload: PromptUpdateRequest,
    expected_revision: str,
    actor: str,
) -> MutationResponse:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise RepositoryError("at least one prompt field must be supplied")

    def mutate(data: dict[str, Any]) -> None:
        entry = _find_prompt(data, prompt_id)
        if "prompt" in changes:
            text = str(changes["prompt"]).strip(" ,\n\t")
            if not text:
                raise RepositoryError("prompt must not be empty")
            entry["prompt"] = text
            entry["content_hash"] = content_hash(text)
        if "name" in changes:
            entry["name"] = str(changes["name"]).strip()
        if "source_code" in changes:
            source = str(changes["source_code"])
            entry["source_code"] = source
            entry["source_group"] = SOURCE_NAMES[source]
        if "safety_code" in changes:
            safety = str(changes["safety_code"])
            entry["safety_code"] = safety
            entry["safety_level"] = SAFETY_NAMES[safety]
        if "enabled" in changes:
            entry["enabled"] = bool(changes["enabled"])
        if "weight" in changes:
            entry["weight"] = int(changes["weight"])
        if "categories" in changes:
            entry["categories"] = clean_categories(changes["categories"])

    _, revision, backup = mutate_json(
        path=settings.prompt_pool_path,
        resource="prompts",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="update",
        target=prompt_id,
        mutate=mutate,
    )
    return _result("updated", prompt_id, revision, backup)


def delete_prompt(
    settings: Settings,
    prompt_id: str,
    expected_revision: str,
    actor: str,
) -> MutationResponse:
    def mutate(data: dict[str, Any]) -> None:
        entry = _find_prompt(data, prompt_id)
        move_to_trash(settings.trash_dir, "prompts", prompt_id, entry)
        prompts = data["prompts"]
        prompts.remove(entry)
        deleted_ids = {
            str(value).strip()
            for value in data.get("deleted_prompt_ids", [])
            if str(value).strip()
        }
        deleted_ids.add(str(entry["id"]))
        data["deleted_prompt_ids"] = sorted(deleted_ids)

    _, revision, backup = mutate_json(
        path=settings.prompt_pool_path,
        resource="prompts",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="delete",
        target=prompt_id,
        mutate=mutate,
    )
    return _result("deleted", prompt_id, revision, backup)


def import_prompts(
    settings: Settings,
    payload: PromptImportRequest,
    expected_revision: str,
    actor: str,
) -> MutationResponse:
    count = len(payload.prompts)

    def mutate(data: dict[str, Any]) -> None:
        prompts = data.get("prompts")
        if not isinstance(prompts, list):
            raise RepositoryError("prompt pool must contain a prompts list")
        for item in payload.prompts:
            prompts.append(prompt_entry(item.model_dump(), prompt_id=new_prompt_id("import")))

    _, revision, backup = mutate_json(
        path=settings.prompt_pool_path,
        resource="prompts",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="import",
        target=f"{count} prompts",
        mutate=mutate,
    )
    return _result("imported", "prompts", revision, backup, count=count)


def export_prompts(
    path: Path,
    *,
    source: str = "",
    safety: str = "",
    query: str = "",
) -> dict[str, Any]:
    data = read_json_object(path)
    prompts = data.get("prompts")
    if not isinstance(prompts, list):
        raise RepositoryError("prompt pool must contain a prompts list")
    sources = set(source.upper().replace(",", "").replace("/", ""))
    safety_codes = set(safety.upper().replace(",", "").replace("/", ""))
    needle = query.strip().casefold()
    selected = []
    for item in prompts:
        if not isinstance(item, dict):
            continue
        if sources and str(item.get("source_code", "B")).upper() not in sources:
            continue
        if safety_codes and str(item.get("safety_code", "N")).upper() not in safety_codes:
            continue
        if needle:
            haystack = "\n".join(
                str(item.get(key, "")) for key in ("id", "name", "prompt")
            ).casefold()
            if needle not in haystack:
                continue
        selected.append(item)
    return {
        "schema_version": 2,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "filters": {"source": source, "safety": safety, "query": query},
        "count": len(selected),
        "prompts": selected,
    }


def _preset_key(kind: str) -> str:
    if kind == "style":
        return "styles"
    if kind == "character":
        return "characters"
    raise ResourceNotFound(f"unsupported preset kind: {kind}")


def _preset_value(kind: str, payload: PresetWriteRequest) -> dict[str, Any]:
    prompt = payload.prompt.strip(" ,\n\t")
    loras = [item.model_dump() for item in payload.loras]
    if kind == "style":
        if not loras:
            raise RepositoryError("a style preset requires at least one LoRA")
        return {
            "loras": loras,
            "prompt": prompt,
            "match": clean_categories(payload.match),
        }
    if kind == "character":
        if len(loras) > 1:
            raise RepositoryError("a character preset supports at most one LoRA")
        if not loras and not prompt:
            raise RepositoryError("a text-only character requires a prompt")
        return {"lora": loras[0] if loras else None, "prompt": prompt}
    raise ResourceNotFound(f"unsupported preset kind: {kind}")


def write_preset(
    settings: Settings,
    kind: str,
    payload: PresetWriteRequest,
    expected_revision: str,
    actor: str,
    *,
    previous_name: str | None = None,
) -> MutationResponse:
    key = _preset_key(kind)
    value = _preset_value(kind, payload)
    action: Literal["created", "updated"] = "created" if previous_name is None else "updated"

    def initialize() -> dict[str, Any]:
        return {"version": 1, "styles": {}, "characters": {}}

    def mutate(data: dict[str, Any]) -> None:
        data.setdefault("version", 1)
        data.setdefault("styles", {})
        data.setdefault("characters", {})
        collection = data.get(key)
        if not isinstance(collection, dict):
            raise RepositoryError(f"presets {key} must be an object")
        name = payload.name.strip()
        if previous_name is None:
            if name in collection:
                raise DuplicateResource(f"preset already exists: {name}")
        else:
            if previous_name not in collection:
                raise ResourceNotFound(f"preset not found: {previous_name}")
            if name != previous_name and name in collection:
                raise DuplicateResource(f"preset already exists: {name}")
            del collection[previous_name]
        collection[name] = value

    _, revision, backup = mutate_json(
        path=settings.preset_path,
        resource="presets",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="create" if action == "created" else "update",
        target=payload.name.strip(),
        mutate=mutate,
        initialize=initialize,
    )
    return _result(action, f"{kind}:{payload.name.strip()}", revision, backup)


def delete_preset(
    settings: Settings,
    kind: str,
    name: str,
    expected_revision: str,
    actor: str,
) -> MutationResponse:
    key = _preset_key(kind)

    def mutate(data: dict[str, Any]) -> None:
        collection = data.get(key)
        if not isinstance(collection, dict) or name not in collection:
            raise ResourceNotFound(f"preset not found: {name}")
        value = collection[name]
        move_to_trash(settings.trash_dir, "presets", f"{kind}_{name}", value)
        del collection[name]

    _, revision, backup = mutate_json(
        path=settings.preset_path,
        resource="presets",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="delete",
        target=f"{kind}:{name}",
        mutate=mutate,
    )
    return _result("deleted", f"{kind}:{name}", revision, backup)
