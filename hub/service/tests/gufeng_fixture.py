"""Synthetic GuFeng catalog for tests; never touches a real user catalog."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def open_fixture_db(path: Path) -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


def insert_gufeng_card(db, card_id, origin, tags):
    db.execute("INSERT INTO full VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        card_id, origin, "tang", "中华" if origin == "cn" else "日本", "zh-Hant",
        "测试诗", "作者", "雾中远山与明月。", json.dumps(tags), json.dumps(["明月"]),
        "fixture", 4, "fixture-v1",
    ))
    db.execute("INSERT INTO source VALUES (?,?,?,?,?,?,?)", (
        card_id, card_id + ":poem", origin, "山中明月。", "b" * 64, 0, 5,
    ))
    db.execute("INSERT INTO provenance VALUES (?,?,?,?)", (
        card_id + ":poem", "fixture source", "https://example.test/poem", "MIT",
    ))


def create_gufeng_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_name("catalog_manifest.json").write_text(
        json.dumps({"version": "0.4.0", "catalog_sha256": "a" * 64}), encoding="utf-8",
    )
    with open_fixture_db(path) as db:
        db.executescript("""
            CREATE TABLE full (
                id TEXT PRIMARY KEY, origin TEXT NOT NULL, tradition TEXT,
                culture TEXT, lang TEXT, title TEXT, author TEXT, scene_zh TEXT,
                tags_json TEXT, grounded_quotes_json TEXT, provider TEXT,
                rank INTEGER, prompt_version TEXT);
            CREATE TABLE source (
                id TEXT PRIMARY KEY, poem_id TEXT, origin TEXT, source_text TEXT,
                source_sha256 TEXT, source_start INTEGER, source_end INTEGER);
            CREATE TABLE provenance (
                poem_id TEXT PRIMARY KEY, source_name TEXT, source_url TEXT, license TEXT);
        """)
        insert_gufeng_card(db, "painter-v5:cn-tang-a:s0001", "cn", ["mountain", "mist"])
        insert_gufeng_card(db, "painter-v5:cn-song-b:s0002", "cn", ["lake", "moonlight"])
        insert_gufeng_card(db, "painter-v5:jp-c:s0001", "jp", ["foreign pool tag"])
