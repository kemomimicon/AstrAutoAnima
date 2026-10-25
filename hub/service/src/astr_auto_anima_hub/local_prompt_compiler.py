"""Deterministic tag ordering shared by local direct and Chinese generation.

This mirrors the bridge's stable meta/count/identity/artist/general ordering.
It deliberately leaves user-specified visual tags intact rather than asking an
LLM to rewrite the complete preset-expanded prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

from .character_catalog import load_character_catalog


_COUNT = re.compile(
    r"\d+\s*(?:girls?|boys?|wom[ae]n|m[ae]n|people|others?)|solo|multiple (?:girls|boys|women|men)"
)
_META = re.compile(
    r"(?:masterpiece|best quality|high quality|normal quality|low quality|"
    r"worst quality|highres|absurdres|safe|sensitive|explicit|questionable|"
    r"rating[: ].+|year \d{4}|score .+)"
)


def _key(value: str) -> str:
    return " ".join(value.replace("_", " ").casefold().split())


def order_tags(text: str, dictionary: Path | None = None) -> str:
    characters: set[str] = set()
    copyrights: set[str] = set()
    if dictionary is not None and dictionary.is_file():
        try:
            for item in load_character_catalog(dictionary):
                characters.add(_key(str(item["tag"])))
                copyrights.update(_key(str(value)) for value in item.get("copyright", ()))
        except (OSError, ValueError):
            pass
    buckets = {name: [] for name in ("meta", "count", "character", "copyright", "artist", "general")}
    seen: set[str] = set()
    for raw in text.replace("，", ",").split(","):
        tag = raw.strip()
        normalized = _key(tag)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if _META.fullmatch(normalized):
            bucket = "meta"
        elif _COUNT.fullmatch(normalized):
            bucket = "count"
        elif normalized in characters or normalized.startswith("character:"):
            bucket = "character"
        elif normalized in copyrights or normalized.startswith("copyright:"):
            bucket = "copyright"
        elif normalized.startswith(("artist:", "@")):
            bucket = "artist"
        else:
            bucket = "general"
        buckets[bucket].append(tag)
    return ", ".join(tag for group in buckets.values() for tag in group)
