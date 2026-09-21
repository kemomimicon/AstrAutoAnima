"""Final-stage tag ordering and reverse identity filtering, without a GPU."""
from __future__ import annotations
import json
import re
from functools import lru_cache
from pathlib import Path

EMOTICONS = {":d", ";d", ":)", ";)", ":p", ";p", ":o", ":3", "xd", ">_<", "^_^", ":(", ";("}
SPECIAL = re.compile(r"\b(?:animal ears|fox ears|cat ears|wolf ears|rabbit ears|dog ears|ears? fluff|tail|tails|horns?|antlers?|wings?|halo|halos|fins?|scales|tentacles?|furry|kemonomimi)\b", re.I)
APPEARANCE = re.compile(r"\b(?:hair|eyes?|skin|twintails?|ponytails?|braids?|bangs|ahoge|mole|freckles|height|short stature|small build|large breasts|small breasts|flat chest)\b", re.I)


def key(tag: str) -> str:
    return " ".join(str(tag).replace("_", " ").lower().split()).strip()


@lru_cache(maxsize=4)
def _vocabulary(path: str, mtime: int, size: int):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    entries = data.get("characters", data.get("entries", []))
    if isinstance(entries, dict):
        entries = [{"tag": tag, **value} for tag, value in entries.items() if isinstance(value, dict)]
    characters, copyrights = set(), set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for field in ("tag", "base_tag"):
            if entry.get(field):
                characters.add(key(entry[field]))
        raw = entry.get("copyright", [])
        if isinstance(raw, str):
            raw = raw.split(",")
        copyrights.update(key(value) for value in raw if value)
    return characters, copyrights


def vocabulary(path: Path | None):
    if not path or not path.is_file():
        return set(), set()
    stat = path.stat()
    return _vocabulary(str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def category(tag: str, characters=(), copyrights=()) -> str:
    value = key(tag)
    # Emoticons must precede prefix/weight parsing; ':d' is a literal Danbooru tag.
    if value in EMOTICONS:
        return "action"
    if value in characters or value.startswith("character:"):
        return "character"
    if value in copyrights or value.startswith("copyright:"):
        return "copyright"
    if value.startswith(("artist:", "@")):
        return "artist"
    if re.fullmatch(r"\d+\s*(?:girls?|boys?|people|others?)|solo|multiple girls|multiple boys", value):
        return "count"
    if re.fullmatch(r"(?:masterpiece|best quality|high quality|normal quality|low quality|worst quality|highres|absurdres|safe|sensitive|explicit|questionable|rating[: ].+|year \d{4}|score .+)", value):
        return "meta"
    if SPECIAL.search(value):
        return "special_features"
    if APPEARANCE.search(value) and not re.search(r"\b(?:looking|closed|open|wink|blush|smile|contact)\b", value):
        return "appearance"
    return "other"


def compile_prompt(text: str, dictionary: Path | None = None, *, strip_identity: bool = False) -> str:
    characters, copyrights = vocabulary(dictionary)
    buckets = {name: [] for name in ("meta", "count", "character", "copyright", "artist", "general")}
    seen = set()
    for raw in str(text).replace("，", ",").split(","):
        tag = raw.strip()
        normalized = key(tag)
        if not normalized or normalized in seen:
            continue
        kind = category(tag, characters, copyrights)
        if strip_identity and kind in {"character", "copyright", "appearance", "special_features"}:
            continue
        seen.add(normalized)
        buckets[kind if kind in buckets else "general"].append(tag)
    return ", ".join(tag for tags in buckets.values() for tag in tags)
