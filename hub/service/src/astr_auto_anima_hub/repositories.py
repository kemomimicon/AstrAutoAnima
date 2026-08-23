from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from .schemas import (
    PresetListResponse,
    PresetSummary,
    PromptPage,
    PromptRecord,
    RevisionInfo,
)


SOURCE_NAME_TO_CODE = {
    "basic": "B",
    "generate": "G",
    "discord": "D",
    "codex": "C",
    "reverse": "R",
}
SAFETY_NAME_TO_CODE = {"normal": "N", "nsfw": "H", "sexual": "S"}


class RepositoryError(RuntimeError):
    pass


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as file:
            value = json.load(file)
    except OSError as exc:
        raise RepositoryError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RepositoryError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RepositoryError(f"JSON root must be an object: {path}")
    return value


def file_revision(path: Path, name: str) -> RevisionInfo:
    if not path.is_file():
        return RevisionInfo(name=name, exists=False)
    try:
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError as exc:
        raise RepositoryError(f"cannot inspect {path}: {exc}") from exc
    return RevisionInfo(
        name=name,
        exists=True,
        revision=f"{stat.st_mtime_ns:x}-{stat.st_size:x}-{digest}",
        modified_at=datetime.fromtimestamp(stat.st_mtime),
        size=stat.st_size,
    )


def _source_code(item: dict[str, Any]) -> str:
    value = str(item.get("source_code", "")).strip().upper()
    if value in {"B", "G", "D", "C", "R"}:
        return value
    return SOURCE_NAME_TO_CODE.get(
        str(item.get("source_group", "basic")).strip().casefold(), "B"
    )


def _safety_code(item: dict[str, Any]) -> str:
    value = str(item.get("safety_code", "")).strip().upper()
    if value in {"N", "H", "S"}:
        return value
    return SAFETY_NAME_TO_CODE.get(
        str(item.get("safety_level", "normal")).strip().casefold(), "N"
    )


def list_prompts(
    path: Path,
    *,
    source: str = "",
    safety: str = "",
    query: str = "",
    enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PromptPage:
    data = read_json_object(path)
    prompts = data.get("prompts")
    if not isinstance(prompts, list):
        raise RepositoryError("prompt pool must contain a prompts list")
    source_set = {part for part in source.upper().replace(",", "").replace("/", "")}
    safety_set = {part for part in safety.upper().replace(",", "").replace("/", "")}
    folded_query = query.strip().casefold()
    selected: list[PromptRecord] = []
    for raw in prompts:
        if not isinstance(raw, dict):
            continue
        item_source = _source_code(raw)
        item_safety = _safety_code(raw)
        item_enabled = bool(raw.get("enabled", True))
        if source_set and item_source not in source_set:
            continue
        if safety_set and item_safety not in safety_set:
            continue
        if enabled is not None and item_enabled is not enabled:
            continue
        if folded_query:
            haystack = "\n".join(
                [
                    str(raw.get("id", "")),
                    str(raw.get("name", "")),
                    str(raw.get("prompt", "")),
                    " ".join(str(value) for value in raw.get("categories", [])),
                ]
            ).casefold()
            if folded_query not in haystack:
                continue
        prompt_id = str(raw.get("id", "")).strip()
        prompt_text = str(raw.get("prompt", "")).strip()
        if not prompt_id or not prompt_text:
            continue
        try:
            weight = int(raw.get("weight", 1))
        except (TypeError, ValueError):
            weight = 1
        selected.append(
            PromptRecord(
                id=prompt_id,
                name=str(raw.get("name", "")),
                prompt=prompt_text,
                source_code=item_source,
                safety_code=item_safety,
                enabled=item_enabled,
                weight=weight,
                categories=[str(value) for value in raw.get("categories", [])],
            )
        )
    selected.sort(key=lambda item: item.id.casefold())
    total = len(selected)
    pages = max(1, math.ceil(total / page_size))
    start = (page - 1) * page_size
    revision = file_revision(path, "prompts").revision or "missing"
    return PromptPage(
        items=selected[start : start + page_size],
        page=page,
        page_size=page_size,
        total=total,
        pages=pages,
        revision=revision,
    )


def list_presets(path: Path) -> PresetListResponse:
    data = (
        read_json_object(path)
        if path.is_file()
        else {"version": 1, "styles": {}, "characters": {}}
    )
    styles = data.get("styles", {})
    characters = data.get("characters", {})
    if not isinstance(styles, dict) or not isinstance(characters, dict):
        raise RepositoryError("presets JSON must contain styles and characters objects")

    style_items: list[PresetSummary] = []
    for name, raw in styles.items():
        if not isinstance(raw, dict):
            continue
        loras = raw.get("loras", [])
        style_items.append(
            PresetSummary(
                name=str(name),
                kind="style",
                prompt=str(raw.get("prompt", "")),
                match=[str(value) for value in raw.get("match", [])],
                loras=[value for value in loras if isinstance(value, dict)],
            )
        )

    character_items: list[PresetSummary] = []
    for name, raw in characters.items():
        if not isinstance(raw, dict):
            continue
        lora = raw.get("lora")
        character_items.append(
            PresetSummary(
                name=str(name),
                kind="character",
                prompt=str(raw.get("prompt", "")),
                loras=[lora] if isinstance(lora, dict) else [],
                text_only=not isinstance(lora, dict),
            )
        )

    style_items.sort(key=lambda item: item.name.casefold())
    character_items.sort(key=lambda item: item.name.casefold())
    revision = file_revision(path, "presets").revision or "missing"
    return PresetListResponse(
        styles=style_items,
        characters=character_items,
        revision=revision,
    )
