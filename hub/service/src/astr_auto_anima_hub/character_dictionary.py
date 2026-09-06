from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from .schemas import CharacterDictionaryItem, CharacterDictionaryResponse


_CACHE: dict[Path, tuple[int, int, tuple[dict[str, Any], ...]]] = {}


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return "".join(character for character in text if character.isalnum())


def _values(value: Any) -> tuple[str, ...]:
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


def _load(path: Path) -> tuple[dict[str, Any], ...]:
    resolved = path.expanduser().resolve()
    stat = resolved.stat()
    signature = (stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(resolved)
    if cached and cached[:2] == signature:
        return cached[2]
    payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    raw_entries = payload.get("characters", []) if isinstance(payload, dict) else []
    if not isinstance(raw_entries, list):
        raise ValueError("character dictionary characters must be a list")
    entries: list[dict[str, Any]] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        tag = str(raw.get("tag", raw.get("name", ""))).strip()
        if not tag:
            continue
        aliases = _values(raw.get("aliases", raw.get("names", ())))
        copyright_tags = _values(raw.get("copyright", raw.get("copyrights", ())))
        gender = _values(raw.get("gender", ()))
        appearance = _values(raw.get("appearance", raw.get("characteristics", ())))
        searchable = tuple(
            dict.fromkeys((tag, tag.replace("_", " "), *aliases, *copyright_tags))
        )
        weak = tuple(dict.fromkeys((tag, *copyright_tags)))
        strong = tuple(dict.fromkeys((*weak, *gender, *appearance)))
        entries.append(
            {
                "tag": tag,
                "base_tag": str(raw.get("base_tag", tag)).strip() or tag,
                "is_variant": bool(raw.get("is_variant", False)),
                "aliases": aliases,
                "chinese_names": tuple(value for value in aliases if _is_chinese(value)),
                "copyright": copyright_tags,
                "gender": gender,
                "appearance": appearance,
                "post_count": max(0, int(raw.get("post_count", 0) or 0)),
                "searchable": searchable,
                "normalized": tuple(_normalize(value) for value in searchable),
                "weak_prompt": ", ".join(weak),
                "strong_prompt": ", ".join(strong),
            }
        )
    entries.sort(key=lambda item: (-item["post_count"], item["tag"]))
    result = tuple(entries)
    _CACHE[resolved] = (*signature, result)
    return result


def search_character_dictionary(
    path: Path,
    *,
    query: str = "",
    limit: int = 20,
) -> CharacterDictionaryResponse:
    if not path.is_file():
        return CharacterDictionaryResponse(
            available=False,
            query=query,
            total=0,
            items=[],
            message="服务器尚未安装本地角色词典。",
        )
    try:
        entries = _load(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return CharacterDictionaryResponse(
            available=False,
            query=query,
            total=0,
            items=[],
            message=f"角色词典无法读取：{exc}",
        )

    needle = _normalize(query)
    entries_by_tag = {entry["tag"]: entry for entry in entries}
    ranked: list[tuple[int, int, int, str, dict[str, Any]]] = []
    for entry in entries:
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
            entry["is_variant"]
            and base is not None
            and (not needle or needle in base["normalized"])
        )
        ranked.append(
            (
                rank,
                1 if shared_variant_alias else 0,
                -entry["post_count"],
                entry["tag"],
                entry,
            )
        )
    ranked.sort(key=lambda item: item[:4])
    selected = [item[4] for item in ranked[:limit]]
    return CharacterDictionaryResponse(
        available=True,
        query=query,
        total=len(ranked),
        items=[
            CharacterDictionaryItem(
                tag=item["tag"],
                chinese_names=list(item["chinese_names"]),
                aliases=list(item["aliases"]),
                copyright=list(item["copyright"]),
                gender=list(item["gender"]),
                appearance=list(item["appearance"]),
                post_count=item["post_count"],
                weak_prompt=item["weak_prompt"],
                strong_prompt=item["strong_prompt"],
            )
            for item in selected
        ],
    )
