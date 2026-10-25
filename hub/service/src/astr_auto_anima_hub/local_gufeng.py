"""Local, read-only GuFeng v0.4 catalog adapter (Python standard library only).

Schema, provenance mapping and identity-tag cleaning follow the separately
delivered ComfyUI-GuFengPromptCards v0.4.0 ``catalog.py`` / ``node.py``. No code
from that node is imported; neither its installation nor any API is needed.
The catalog and its adjacent catalog_manifest.json retain their own source
attribution and licensing. This adapter does not redistribute that dataset.

Only ``full`` cards with origin=cn are selected, using their primary rendition.
The sorted ID list is cached in memory per file revision; no main-pool JSON,
SQLite index, or other on-disk cache is created. Each call owns its connection
so callers may run it in asyncio.to_thread. The manifest hash is provenance,
not a claim that the whole catalog is rehashed on each draw.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterator


class GufengError(ValueError):
    """The configured offline catalog cannot provide a valid card."""


_IDENTITY_TAG = re.compile(
    r"^(?:\d+\s*(?:girls?|boys?|women|men)|multiple\s+(?:girls?|boys?|women|men)|"
    r"(?:male|female)(?:\s+focus)?|(?:man|woman|boy|girl)|"
    r"loli|shota|bishounen|bishoujo|mature\s+(?:male|female)|"
    r"solo(?:\s+focus)?|\d+\s*others?|multiple\s+others)$", re.IGNORECASE,
)
_GENDER_WORD = re.compile(
    r"(?<![a-z])(?:girls?|boys?|woman|man|women|men|males?|females?)(?![a-z])",
    re.IGNORECASE,
)
_BAD_META_TAGS = {
    "chuunibyou demo koi ga shitai!", "medusa (rider) (fate)",
    "air (visual novel)", "palette (object)", "painting (action)",
    "earth (planet)", "a (phrase)", "poem", "poetic illustration",
    "classical poetry illustration",
}
_REQUIRED_COLUMNS = {
    "full": {
        "id", "origin", "tradition", "culture", "lang", "title", "author",
        "scene_zh", "tags_json", "grounded_quotes_json", "provider", "rank",
        "prompt_version",
    },
    "source": {
        "id", "poem_id", "origin", "source_text", "source_sha256",
        "source_start", "source_end",
    },
    "provenance": {"poem_id", "source_name", "source_url", "license"},
}
_CACHE_LOCK = threading.RLock()


@dataclass(frozen=True)
class _CatalogFiles:
    path: str
    database_stat: tuple[int, int, int]
    manifest_stat: tuple[int, int, int]


@dataclass(frozen=True)
class _CatalogInfo:
    version: str
    declared_sha256: str | None


def _files(path: Path | None) -> _CatalogFiles:
    if path is None:
        raise GufengError("未配置本机国风古韵离线词库")
    resolved = Path(path).expanduser().resolve(strict=True)
    manifest = resolved.with_name("catalog_manifest.json")
    if not resolved.is_file() or not manifest.is_file():
        raise GufengError("国风古韵词库不完整：需要 SQLite 和同目录 catalog_manifest.json")
    database_stat, manifest_stat = resolved.stat(), manifest.stat()
    if manifest_stat.st_size > 1024 * 1024:
        raise GufengError("国风古韵词库清单过大")
    return _CatalogFiles(
        str(resolved),
        (database_stat.st_size, database_stat.st_mtime_ns, database_stat.st_ctime_ns),
        (manifest_stat.st_size, manifest_stat.st_mtime_ns, manifest_stat.st_ctime_ns),
    )


@contextmanager
def _connect(files: _CatalogFiles) -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(Path(files.path).as_uri() + "?mode=ro", uri=True, timeout=3)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        yield db
    finally:
        db.close()


@lru_cache(maxsize=4)
def _inspect_catalog(files: _CatalogFiles) -> _CatalogInfo:
    manifest = json.loads(Path(files.path).with_name("catalog_manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise GufengError("国风古韵词库清单格式无效")
    version = manifest.get("version")
    if not isinstance(version, str) or not version.strip() or len(version) > 100:
        raise GufengError("国风古韵词库清单缺少有效版本")
    declared_hash = manifest.get("catalog_sha256")
    if declared_hash is not None and (
        not isinstance(declared_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", declared_hash)
    ):
        raise GufengError("国风古韵词库清单哈希格式无效")
    with _connect(files) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name, required in _REQUIRED_COLUMNS.items():
            if name not in tables:
                raise GufengError("国风古韵词库表结构不兼容")
            columns = {row["name"]: row for row in db.execute(f'PRAGMA table_info("{name}")')}
            primary = "poem_id" if name == "provenance" else "id"
            primary_columns = [column for column, info in columns.items() if info["pk"]]
            if not required.issubset(columns) or primary_columns != [primary]:
                raise GufengError("国风古韵词库字段或主键不兼容")
        if db.execute("SELECT 1 FROM full WHERE origin='cn' LIMIT 1").fetchone() is None:
            raise GufengError("国风古韵通常模式中没有中华候选卡片")
    return _CatalogInfo(version.strip(), declared_hash.lower() if declared_hash else None)


@lru_cache(maxsize=2)
def _candidate_ids(files: _CatalogFiles) -> tuple[str, ...]:
    # Scan only on the first draw after installation/replacement. Sorting the
    # compact IDs in Python avoids reading large rows through the id index.
    with _connect(files) as db:
        ids = [row[0] for row in db.execute("SELECT id FROM full WHERE origin='cn'")]
    if not ids or any(not isinstance(value, str) or not value for value in ids):
        raise GufengError("国风古韵中华候选卡片 ID 无效")
    return tuple(sorted(ids))


def _clean_tags(raw: object) -> list[str]:
    values = raw.split(",") if isinstance(raw, str) else raw
    if not isinstance(values, list):
        raise GufengError("国风古韵卡片英文标签格式无效")
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        # Split embedded commas too, so a combined identity/scene tag cannot
        # bypass cleaning. Preserve general figure/person tags when supplied.
        for part in value.split(","):
            tag = " ".join(part.strip().split())
            key = tag.casefold().replace("_", " ")
            identity_key = re.sub(r":\s*[+-]?\d+(?:\.\d+)?$", "", key.strip("()[]{} ")).strip()
            if (not tag or not tag.isascii() or not re.search(r"[a-z]", key)
                    or _IDENTITY_TAG.fullmatch(identity_key) or _GENDER_WORD.search(key)
                    or key in _BAD_META_TAGS or "(visual novel)" in key
                    or "(fate)" in key or key in seen):
                continue
            seen.add(key)
            cleaned.append(tag)
    if not cleaned:
        raise GufengError("抽到的国风古韵卡片没有可用英文视觉标签")
    return cleaned


def gufeng_available(path: Path | None) -> bool:
    """Check configuration/schema and candidate existence without loading IDs."""
    try:
        files = _files(path)
        with _CACHE_LOCK:
            _inspect_catalog(files)
        return True
    except (OSError, ValueError, TypeError, RuntimeError, sqlite3.Error):
        return False


def draw_gufeng(path: Path, seed: int) -> dict:
    """Draw one reproducible Chinese/full card, without writing or networking."""
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise GufengError("国风古韵抽卡种子必须是整数")
    try:
        files = _files(path)
        with _CACHE_LOCK:
            info = _inspect_catalog(files)
            ids = _candidate_ids(files)
        catalog_id = ids[random.Random(seed).randrange(len(ids))]
        with _connect(files) as db:
            card = db.execute("SELECT * FROM full WHERE id=? AND origin='cn'", (catalog_id,)).fetchone()
            source = db.execute("SELECT * FROM source WHERE id=?", (catalog_id,)).fetchone()
            if card is None or source is None or source["origin"] != "cn":
                raise GufengError("国风古韵卡片来源索引不完整")
            attribution = db.execute(
                "SELECT source_name,source_url,license FROM provenance WHERE poem_id=?",
                (source["poem_id"],),
            ).fetchone()
            if attribution is None or any(
                not isinstance(attribution[key], str) or not attribution[key].strip()
                for key in ("source_name", "source_url", "license")
            ):
                raise GufengError("国风古韵卡片来源署名或许可记录不完整")
        tags = _clean_tags(json.loads(card["tags_json"]))
        quotes = json.loads(card["grounded_quotes_json"])
        if (not isinstance(quotes, list) or not quotes
                or any(not isinstance(quote, str) or not quote
                       or quote not in source["source_text"] for quote in quotes)):
            raise GufengError("国风古韵卡片原文引文无效")
        scene = card["scene_zh"]
        if not isinstance(scene, str) or not scene.strip():
            raise GufengError("国风古韵卡片场景为空")
        provenance = {
            "catalog_id": catalog_id, "card_id": catalog_id,
            "catalog_version": info.version, "catalog_sha256": info.declared_sha256,
            "mode": "full", "origin": card["origin"], "culture": card["culture"],
            "tradition": card["tradition"], "lang": card["lang"],
            "title": card["title"], "author": card["author"],
            "poem_id": source["poem_id"], "source_text": source["source_text"],
            "source_sha256": source["source_sha256"],
            "source_start": source["source_start"], "source_end": source["source_end"],
            "grounded_quotes": quotes,
            "source_name": attribution["source_name"],
            "source_url": attribution["source_url"],
            "source_license": attribution["license"],
            "provider": card["provider"], "prompt_version": card["prompt_version"],
            "rank": card["rank"], "variant_index": 0, "quality": "mechanical_candidate",
        }
        template_id = "V:" + catalog_id
        if len(template_id) > 300 or not re.fullmatch(r"[A-Za-z0-9_.:-]+", catalog_id):
            # Template IDs also appear in single-segment HTTP routes. Preserve
            # arbitrary source IDs in provenance, not as raw URL path syntax.
            template_id = "V:sha256:" + hashlib.sha256(catalog_id.encode("utf-8")).hexdigest()
        return {
            "template_id": template_id, "prompt": ", ".join(tags),
            "scene_zh": scene.strip(), "provenance": provenance, "selection_seed": seed,
        }
    except GufengError:
        raise
    except (OSError, ValueError, TypeError, RuntimeError, sqlite3.Error) as exc:
        # Keep filesystem details, SQL errors and raw data out of client errors.
        raise GufengError("本机国风古韵词库无法读取或卡片数据无效，请检查离线词库安装") from exc
