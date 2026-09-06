from __future__ import annotations

import json
import math
import unicodedata
from pathlib import Path
from typing import Any

from .repositories import file_revision
from .schemas import CharacterDictionaryItem, CharacterDictionaryResponse


_CACHE: dict[
    tuple[Path, Path | None],
    tuple[tuple[int, int], tuple[int, int] | None, tuple[dict[str, Any], ...]],
] = {}


def normalize_character_query(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return "".join(character for character in text if character.isalnum())


def clean_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = ()
    result: list[str] = []
    for item in raw:
        text = str(item or "").strip(" ,\t\r\n")
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _is_chinese(value: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in value)


def _signature(path: Path | None) -> tuple[int, int] | None:
    if path is None or not path.is_file():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def read_character_edits(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    raw = payload.get("entries", {}) if isinstance(payload, dict) else {}
    if not isinstance(raw, dict):
        raise ValueError("character dictionary edits entries must be an object")
    return {
        str(tag): value
        for tag, value in raw.items()
        if str(tag).strip() and isinstance(value, dict)
    }


def load_character_catalog(
    path: Path,
    edits_path: Path | None = None,
) -> tuple[dict[str, Any], ...]:
    resolved = path.expanduser().resolve()
    resolved_edits = edits_path.expanduser().resolve() if edits_path else None
    base_signature = _signature(resolved)
    if base_signature is None:
        raise FileNotFoundError(resolved)
    edits_signature = _signature(resolved_edits)
    cache_key = (resolved, resolved_edits)
    cached = _CACHE.get(cache_key)
    if cached and cached[:2] == (base_signature, edits_signature):
        return cached[2]
    payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    raw_entries = payload.get("characters", []) if isinstance(payload, dict) else []
    if not isinstance(raw_entries, list):
        raise ValueError("character dictionary characters must be a list")
    edits = read_character_edits(resolved_edits)
    entries: list[dict[str, Any]] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        tag = str(raw.get("tag", raw.get("name", ""))).strip()
        if not tag:
            continue
        override = edits.get(tag, {})
        effective = {**raw, **override}
        aliases = clean_values(effective.get("aliases", effective.get("names", ())))
        copyright_tags = clean_values(
            effective.get("copyright", effective.get("copyrights", ()))
        )
        gender = clean_values(effective.get("gender", ()))
        appearance = clean_values(
            effective.get("appearance", effective.get("characteristics", ()))
        )
        searchable = tuple(
            dict.fromkeys((tag, tag.replace("_", " "), *aliases, *copyright_tags))
        )
        weak = tuple(dict.fromkeys((tag, *copyright_tags)))
        strong = tuple(dict.fromkeys((*weak, *gender, *appearance)))
        entries.append(
            {
                "tag": tag,
                "base_tag": str(effective.get("base_tag", tag)).strip() or tag,
                "is_variant": bool(effective.get("is_variant", False)),
                "aliases": aliases,
                "chinese_names": tuple(value for value in aliases if _is_chinese(value)),
                "copyright": copyright_tags,
                "gender": gender,
                "appearance": appearance,
                "post_count": max(0, int(effective.get("post_count", 0) or 0)),
                "disabled": bool(override.get("disabled", False)),
                "overridden": bool(override),
                "searchable": searchable,
                "normalized": tuple(normalize_character_query(value) for value in searchable),
                "weak_prompt": ", ".join(weak),
                "strong_prompt": ", ".join(strong),
            }
        )
    entries.sort(key=lambda item: (-item["post_count"], item["tag"]))
    result = tuple(entries)
    _CACHE[cache_key] = (base_signature, edits_signature, result)
    return result


def get_character(
    path: Path,
    tag: str,
    *,
    edits_path: Path | None = None,
    include_disabled: bool = False,
) -> dict[str, Any] | None:
    requested = str(tag or "").strip()
    for entry in load_character_catalog(path, edits_path):
        if entry["tag"] == requested:
            if entry["disabled"] and not include_disabled:
                return None
            return entry
    return None


def search_character_dictionary(
    path: Path,
    *,
    query: str = "",
    limit: int = 20,
    page: int = 1,
    edits_path: Path | None = None,
    include_disabled: bool = False,
) -> CharacterDictionaryResponse:
    if not path.is_file():
        return CharacterDictionaryResponse(
            available=False, query=query, total=0, items=[],
            message="服务器尚未安装本地角色词典。", page=1,
            page_size=limit, pages=1, revision="missing",
        )
    try:
        entries = load_character_catalog(path, edits_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return CharacterDictionaryResponse(
            available=False, query=query, total=0, items=[],
            message=f"角色词典无法读取：{exc}", page=1,
            page_size=limit, pages=1, revision="missing",
        )

    needle = normalize_character_query(query)
    entries_by_tag = {entry["tag"]: entry for entry in entries}
    ranked: list[tuple[int, int, int, str, dict[str, Any]]] = []
    for entry in entries:
        if entry["disabled"] and not include_disabled:
            continue
        if not needle:
            rank = 4
        elif needle in entry["normalized"]:
            rank = 0
        elif any(value.startswith(needle) for value in entry["normalized"]):
            rank = 1
        elif any(needle in value for value in entry["normalized"]):
            rank = 2
        else:
            continue
        base = entries_by_tag.get(entry["base_tag"])
        shared_variant_alias = bool(
            entry["is_variant"] and base is not None
            and (not needle or needle in base["normalized"])
        )
        ranked.append((rank, 1 if shared_variant_alias else 0,
                       -entry["post_count"], entry["tag"], entry))
    ranked.sort(key=lambda item: item[:4])
    total = len(ranked)
    pages = max(1, math.ceil(total / limit))
    safe_page = min(max(1, page), pages)
    start = (safe_page - 1) * limit
    selected = [item[4] for item in ranked[start : start + limit]]
    revision_path = edits_path if edits_path and edits_path.is_file() else path
    revision = file_revision(revision_path, "character_dictionary").revision or "missing"
    return CharacterDictionaryResponse(
        available=True, query=query, total=total,
        items=[
            CharacterDictionaryItem(
                tag=item["tag"], chinese_names=list(item["chinese_names"]),
                aliases=list(item["aliases"]), copyright=list(item["copyright"]),
                gender=list(item["gender"]), appearance=list(item["appearance"]),
                post_count=item["post_count"], weak_prompt=item["weak_prompt"],
                strong_prompt=item["strong_prompt"], disabled=item["disabled"],
                overridden=item["overridden"],
            ) for item in selected
        ],
        page=safe_page, page_size=limit, pages=pages, revision=revision,
    )
