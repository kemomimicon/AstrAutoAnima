from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .workflow_runtime import WorkflowError
except ImportError:  # pragma: no cover - direct execution for local tests
    from workflow_runtime import WorkflowError


@dataclass(frozen=True, slots=True)
class CharacterMatch:
    query: str
    tag: str
    copyright: tuple[str, ...]
    appearance: tuple[str, ...]
    prompt: str
    mode: str


_CACHE: dict[
    tuple[Path, Path | None],
    tuple[tuple[int, int], tuple[int, int] | None, dict[str, dict[str, Any]]],
] = {}


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return "".join(character for character in text if character.isalnum())


def _tags(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = ()
    found: list[str] = []
    for raw in values:
        tag = str(raw or "").strip(" ,\n\t")
        if tag and tag not in found:
            found.append(tag)
    return tuple(found)


def _entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("characters", payload.get("entries", []))
    if isinstance(raw, dict):
        return [
            {"tag": str(tag), **value}
            for tag, value in raw.items()
            if isinstance(value, dict)
        ]
    if isinstance(raw, list):
        return [value for value in raw if isinstance(value, dict)]
    raise WorkflowError("角色词典 characters/entries 必须是数组或对象。")


def _load_index(
    path: Path,
    edits_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    resolved = path.expanduser().resolve()
    try:
        stat = resolved.stat()
    except OSError as exc:
        raise WorkflowError(f"角色词典不存在：{resolved}") from exc
    resolved_edits = edits_path.expanduser().resolve() if edits_path else None
    edits_signature: tuple[int, int] | None = None
    if resolved_edits and resolved_edits.is_file():
        edit_stat = resolved_edits.stat()
        edits_signature = (edit_stat.st_mtime_ns, edit_stat.st_size)
    cached = _CACHE.get((resolved, resolved_edits))
    signature = (stat.st_mtime_ns, stat.st_size)
    if cached and cached[:2] == (signature, edits_signature):
        return cached[2]
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"无法读取角色词典：{exc}") from exc
    if not isinstance(payload, dict):
        raise WorkflowError("角色词典必须是 JSON 对象。")
    edits: dict[str, dict[str, Any]] = {}
    if resolved_edits and resolved_edits.is_file():
        try:
            edit_payload = json.loads(resolved_edits.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowError(f"无法读取角色词典管理覆盖层：{exc}") from exc
        raw_edits = edit_payload.get("entries", {}) if isinstance(edit_payload, dict) else {}
        if not isinstance(raw_edits, dict):
            raise WorkflowError("角色词典管理覆盖层 entries 必须是对象。")
        edits = {
            str(tag): value
            for tag, value in raw_edits.items()
            if isinstance(value, dict)
        }

    candidates: dict[str, list[dict[str, Any]]] = {}
    entries_by_tag: dict[str, dict[str, Any]] = {}
    for raw in _entries(payload):
        tag = str(raw.get("tag", raw.get("name", ""))).strip()
        if not tag:
            continue
        override = edits.get(tag, {})
        if bool(override.get("disabled", False)):
            continue
        effective = {**raw, **override}
        aliases = _tags(effective.get("aliases", effective.get("names", [])))
        copyright_tags = _tags(
            effective.get("copyright", effective.get("copyrights", []))
        )
        appearance = _tags(
            effective.get("appearance", effective.get("characteristics", []))
        )
        gender = _tags(effective.get("gender", []))
        entry = {
            "tag": tag,
            "base_tag": str(effective.get("base_tag", tag)).strip() or tag,
            "is_variant": bool(effective.get("is_variant", False)),
            "copyright": copyright_tags,
            "appearance": (*gender, *appearance),
            "post_count": int(effective.get("post_count", 0) or 0),
        }
        alias_keys = {
            _normalize(alias)
            for alias in (tag, tag.replace("_", " "), *aliases)
            if _normalize(alias)
        }
        entry["alias_keys"] = alias_keys
        entry["tag_keys"] = {
            _normalize(tag),
            _normalize(tag.replace("_", " ")),
        }
        entries_by_tag[tag] = entry
        for key in alias_keys:
            candidates.setdefault(key, []).append(entry)

    index: dict[str, dict[str, Any]] = {}
    for key, values in candidates.items():
        def preference(entry: dict[str, Any]) -> tuple[int, int, int, str]:
            base = entries_by_tag.get(str(entry["base_tag"]))
            shared_with_base = bool(
                entry["is_variant"]
                and base is not None
                and key in base["alias_keys"]
            )
            return (
                1 if shared_with_base else 0,
                0 if key in entry["tag_keys"] else 1,
                -int(entry["post_count"]),
                str(entry["tag"]),
            )

        index[key] = min(values, key=preference)
    _CACHE[(resolved, resolved_edits)] = (signature, edits_signature, index)
    return index


def resolve_character(
    path: Path,
    query: str,
    *,
    mode: str = "weak",
    edits_path: Path | None = None,
) -> CharacterMatch | None:
    normalized_query = _normalize(query)
    if not normalized_query:
        return None
    mode_aliases = {
        "weak": "weak",
        "弱": "weak",
        "弱模式": "weak",
        "strong": "strong",
        "强": "strong",
        "强模式": "strong",
        "off": "off",
        "关闭": "off",
        "原样": "off",
    }
    selected_mode = mode_aliases.get(str(mode or "weak").strip().casefold())
    if selected_mode is None:
        raise WorkflowError("角色标签模式只能是：弱、强、关闭。")
    if selected_mode == "off":
        return None

    entry = _load_index(path, edits_path).get(normalized_query)
    if entry is None:
        return None
    prompt_tags = [str(entry["tag"]), *entry["copyright"]]
    if selected_mode == "strong":
        prompt_tags.extend(entry["appearance"])
    deduplicated = list(dict.fromkeys(tag for tag in prompt_tags if tag))
    return CharacterMatch(
        query=str(query),
        tag=str(entry["tag"]),
        copyright=tuple(entry["copyright"]),
        appearance=tuple(entry["appearance"]),
        prompt=", ".join(deduplicated),
        mode=selected_mode,
    )
