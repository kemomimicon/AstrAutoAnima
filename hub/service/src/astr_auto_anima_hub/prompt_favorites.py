"""Small, per-user prompt collection independent of the managed catalog."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from .auth import AuthPrincipal
from .repositories import RepositoryError
from .schemas import PromptLikeResponse, PromptPage, PromptRecord


def normalize_text(value: str) -> str:
    # Preserve tag order and punctuation; only insignificant whitespace differs.
    return " ".join(value.strip().casefold().split())


def full_prompt(source: str, addition: str) -> str:
    # compose_random_body places the user's own text before the catalog entry.
    parts = [str(value).strip(" ,\n\t") for value in (addition, source)]
    return ", ".join(part for part in parts if part)


def favorite_id(owner: str, prompt: str) -> str:
    fingerprint = hashlib.sha256(normalize_text(prompt).encode("utf-8")).hexdigest()
    return f"liked-{hashlib.sha256(owner.encode()).hexdigest()[:10]}-{fingerprint[:24]}"


def source_safety_code(source: dict[str, Any], *, required: bool = False) -> str:
    """Catalogs historically default to N; image snapshots must be explicit."""
    code = str(source.get("safety_code", "")).strip().upper()
    level = str(source.get("safety_level", "")).strip().casefold()
    if code in {"N", "H", "S"}:
        return code
    mapped = {"normal": "N", "nsfw": "H", "sexual": "S"}.get(level)
    if mapped:
        return mapped
    if required or code or level:
        raise RepositoryError("图片缺少可信的原词条分级，无法收藏；请重新生成，不能默认为 N")
    return "N"


def owned_favorite_ids(path: Path, principal: AuthPrincipal) -> set[str]:
    if not path.is_file():
        return set()
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            return {str(row["id"]) for row in db.execute(
                "SELECT id FROM favorites WHERE owner=?", (principal.subject,))}
    except sqlite3.Error as exc:
        raise RepositoryError(f"个人收藏库不可用：{exc}") from exc


@contextmanager
def _connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("""CREATE TABLE IF NOT EXISTS favorites (
        id TEXT PRIMARY KEY,
        owner TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        source_id TEXT NOT NULL,
        source_prompt TEXT NOT NULL,
        addition TEXT NOT NULL,
        prompt TEXT NOT NULL,
        name TEXT NOT NULL,
        safety_code TEXT NOT NULL,
        created_at REAL NOT NULL,
        UNIQUE(owner, fingerprint)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS favorites_owner ON favorites(owner, created_at DESC)")
    try:
        with db:
            yield db
    finally:
        db.close()


def save_favorite(
    path: Path, principal: AuthPrincipal, source: dict[str, Any],
    *, addition: str = "",
) -> PromptLikeResponse:
    if principal.role == "legacy_lite":
        raise RepositoryError("共享用户令牌无法保存收藏，请使用绑定 QQ 的个人令牌")
    source_id = str(source.get("id", "")).strip()
    source_prompt = str(source.get("prompt", "")).strip()
    addition = str(addition).strip()
    if not source_id or not source_prompt:
        raise RepositoryError("收藏缺少可靠的原始词库编号或内容")
    if len(source_prompt) + len(addition) > 100_000:
        raise RepositoryError("收藏内容过长")
    prompt = full_prompt(source_prompt, addition)
    fingerprint = hashlib.sha256(normalize_text(prompt).encode("utf-8")).hexdigest()
    owner = principal.subject
    saved_id = favorite_id(owner, prompt)
    safety = source_safety_code(source)
    try:
        with _connect(path) as db:
            cursor = db.execute(
                """INSERT OR IGNORE INTO favorites
                (id,owner,fingerprint,source_id,source_prompt,addition,prompt,name,safety_code,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (saved_id, owner, fingerprint, source_id, source_prompt, addition,
                 prompt, str(source.get("name", source_id)), safety, time.time()),
            )
            row = db.execute(
                "SELECT id,safety_code FROM favorites WHERE owner=? AND fingerprint=?",
                (owner, fingerprint),
            ).fetchone()
            if row is None:
                raise RepositoryError("收藏未能写入")
            # Same text may be collected from differently classified entries.
            # Content dedup must never silently lower an existing classification.
            if "NHS".index(safety) > "NHS".index(str(row["safety_code"])):
                db.execute("UPDATE favorites SET safety_code=? WHERE owner=? AND id=?",
                           (safety, owner, row["id"]))
        return PromptLikeResponse(
            action="liked" if cursor.rowcount else "already_liked",
            prompt_id=source_id,
            saved_prompt_id=str(row["id"]),
            revision="favorites-v1",
        )
    except sqlite3.Error as exc:
        raise RepositoryError(f"个人收藏库不可用：{exc}") from exc


def delete_favorite(path: Path, principal: AuthPrincipal, identifier: str) -> dict[str, bool]:
    try:
        with _connect(path) as db:
            rows = db.execute(
                "SELECT id FROM favorites WHERE owner=? AND (id=? OR source_id=?)",
                (principal.subject, identifier, identifier),
            ).fetchall()
            if len(rows) > 1:
                raise RepositoryError("同一词库编号有多个附加内容，请在个人收藏中选择具体条目取消")
            removed = bool(rows)
            if removed:
                db.execute("DELETE FROM favorites WHERE owner=? AND id=?", (principal.subject, rows[0]["id"]))
        return {"removed": removed}
    except sqlite3.Error as exc:
        raise RepositoryError(f"个人收藏库不可用：{exc}") from exc


def list_favorites(
    path: Path, principal: AuthPrincipal, *, query: str = "", safety: str = "",
    page: int = 1, page_size: int = 20,
) -> PromptPage:
    if principal.role == "legacy_lite":
        raise RepositoryError("共享用户令牌无法查看个人收藏")
    clauses = ["owner=?"]
    values: list[Any] = [principal.subject]
    if safety:
        codes = [code for code in safety.upper() if code in "NHS"]
        if codes:
            clauses.append("safety_code IN (" + ",".join("?" for _ in codes) + ")")
            values.extend(codes)
    if query.strip():
        clauses.append("(id LIKE ? ESCAPE '\\' OR source_id LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\' OR prompt LIKE ? ESCAPE '\\')")
        escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        needle = f"%{escaped}%"
        values.extend([needle] * 4)
    where = " AND ".join(clauses)
    try:
        with _connect(path) as db:
            count = int(db.execute(f"SELECT COUNT(*) FROM favorites WHERE {where}", values).fetchone()[0])
            rows = db.execute(
                f"SELECT * FROM favorites WHERE {where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                [*values, page_size, (page - 1) * page_size],
            ).fetchall()
    except sqlite3.Error as exc:
        raise RepositoryError(f"个人收藏库不可用：{exc}") from exc
    return PromptPage(
        items=[PromptRecord(
            id=str(row["id"]), name=str(row["name"]), prompt=str(row["prompt"]),
            original_id=str(row["source_id"]), user_addition=str(row["addition"]),
            source_code="P", safety_code=str(row["safety_code"]),
            categories=["liked"],
        ) for row in rows],
        page=page, page_size=page_size, total=count,
        pages=max(1, (count + page_size - 1) // page_size),
        revision="favorites-v1",
    )
