from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable


def _values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        result: list[str] = []
        for nested in value.values():
            result.extend(_values(nested))
        return list(dict.fromkeys(result))
    return []


_TRAILING_QUALIFIER = re.compile(r"\s*[（(][^()（）]*[）)]\s*$")


def _alias_variants(value: Any) -> list[str]:
    """Return source aliases plus progressively stripped trailing qualifiers."""
    variants: list[str] = []
    for raw in _values(value):
        current = raw
        while current:
            if current not in variants:
                variants.append(current)
            stripped = _TRAILING_QUALIFIER.sub("", current).strip()
            if not stripped or stripped == current:
                break
            current = stripped
    return variants


def _records(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as source:
        for number, line in enumerate(source, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{number} is not an object")
            yield value


def _alias_map(path: Path | None) -> dict[str, list[str]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("name map must be an object keyed by Danbooru tag")
    return {str(tag): _values(names) for tag, names in payload.items()}


def _translation_sqlite(path: Path | None) -> dict[str, list[str]]:
    if path is None:
        return {}
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT name, cn_name FROM tags "
            "WHERE category = 4 AND cn_name IS NOT NULL AND trim(cn_name) <> ''"
        )
        return {
            str(tag): _alias_variants(chinese_name)
            for tag, chinese_name in rows
            if str(tag or "").strip()
        }
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build AstrAutoAnima's offline character dictionary."
    )
    parser.add_argument("--characters-jsonl", required=True, type=Path)
    parser.add_argument(
        "--name-map",
        type=Path,
        help="Optional multilingual/Chinese map keyed by canonical character tag.",
    )
    parser.add_argument(
        "--translation-sqlite",
        type=Path,
        help=(
            "Optional Danbooru translation database with a tags table containing "
            "name, category and cn_name columns."
        ),
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    aliases = _alias_map(args.name_map)
    for tag, names in _translation_sqlite(args.translation_sqlite).items():
        aliases[tag] = list(dict.fromkeys([*aliases.get(tag, []), *names]))
    source_records = list(_records(args.characters_jsonl))
    records_by_id = {
        int(raw["id"]): raw
        for raw in source_records
        if isinstance(raw.get("id"), int)
    }
    characters: list[dict[str, Any]] = []
    for raw in source_records:
        tag = str(raw.get("name", raw.get("tag", ""))).strip()
        if not tag:
            continue
        relationships = raw.get("relationships", {})
        parent_ids = (
            relationships.get("parents", [])
            if isinstance(relationships, dict)
            else []
        )
        parent_records = [
            records_by_id[parent_id]
            for parent_id in parent_ids
            if isinstance(parent_id, int) and parent_id in records_by_id
        ]
        parent_records.sort(
            key=lambda item: -int(item.get("post_count", 0) or 0)
        )
        base_tag = (
            str(parent_records[0].get("name", parent_records[0].get("tag", ""))).strip()
            if parent_records
            else tag
        )
        record_aliases = list(
            dict.fromkeys(
                [tag.replace("_", " "), *_values(raw.get("aliases")), *aliases.get(tag, [])]
            )
        )
        characters.append(
            {
                "tag": tag,
                "base_tag": base_tag,
                "is_variant": bool(parent_records),
                "aliases": record_aliases,
                "copyright": _values(raw.get("copyright")),
                "gender": _values(raw.get("gender")),
                "appearance": _values(
                    raw.get("characteristics", raw.get("appearance"))
                ),
                "post_count": int(raw.get("post_count", 0) or 0),
            }
        )
    characters.sort(key=lambda item: (-item["post_count"], item["tag"]))
    output = {
        "schema_version": "1.1",
        "source": {
            "characters": str(args.characters_jsonl),
            "name_map": str(args.name_map or ""),
            "translation_sqlite": str(args.translation_sqlite or ""),
        },
        "characters": characters,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(characters)} characters to {args.output}")


if __name__ == "__main__":
    main()
