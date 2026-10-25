"""Explicit, offline migration of legacy P records out of the main catalog.

The caller must stop Hub and AstrBot before removal; this module does not run
automatically during normal requests. It never deletes its one-time JSON backup.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any

from .auth import AuthPrincipal
from .prompt_favorites import normalize_text, save_favorite
from .repositories import RepositoryError


def _legacy_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = data.get("prompts")
    if not isinstance(rows, list):
        raise RepositoryError("主词库缺少 prompts 列表")
    legacy = [row for row in rows if isinstance(row, dict)
              and str(row.get("source_code", "")).upper() == "P"]
    for row in legacy:
        if not str(row.get("liked_by", "")).strip() or not str(row.get("prompt", "")).strip():
            raise RepositoryError("存在没有归属用户或内容的旧 P 条目，必须人工处理")
    return legacy


def migrate_legacy_favorites(
    pool_path: Path, database_path: Path, *, apply: bool = False,
    remove_embedded: bool = False,
) -> dict[str, Any]:
    if remove_embedded and not apply:
        raise RepositoryError("清除主词库旧 P 条目须先指定 apply")
    if pool_path.is_symlink() or not pool_path.is_file() or pool_path.resolve() != pool_path:
        raise RepositoryError("主词库路径异常")
    if database_path.exists() and (database_path.is_symlink() or not database_path.is_file()):
        raise RepositoryError("收藏数据库路径异常")
    before = pool_path.read_bytes()
    data = json.loads(before.decode("utf-8-sig"))
    legacy = _legacy_rows(data)
    result: dict[str, Any] = {"legacy_rows": len(legacy), "owners": len({r["liked_by"] for r in legacy}),
                              "imported": 0, "duplicates": 0, "removed": 0, "backup": ""}
    if not apply or not legacy:
        return result
    for row in legacy:
        owner = str(row["liked_by"])
        source = dict(row)
        source["id"] = str(row.get("liked_from") or row.get("id") or "")
        source["name"] = str(row.get("name", ""))
        response = save_favorite(
            database_path, AuthPrincipal(role="user", subject=owner), source,
        )
        result["imported" if response.action == "liked" else "duplicates"] += 1
    # Readback of every full-text fingerprint is required before touching JSON.
    with closing(sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)) as db:
        for row in legacy:
            fingerprint = hashlib.sha256(normalize_text(str(row["prompt"])).encode("utf-8")).hexdigest()
            found = db.execute("SELECT 1 FROM favorites WHERE owner=? AND fingerprint=?",
                               (str(row["liked_by"]), fingerprint)).fetchone()
            if found is None:
                raise RepositoryError("旧收藏校验失败，主词库未修改")
    if not remove_embedded:
        return result
    if pool_path.read_bytes() != before:
        raise RepositoryError("导入期间主词库被修改，未清除旧条目")
    backup = pool_path.with_name(pool_path.name + ".before-favorites-migration.json")
    if backup.exists():
        raise RepositoryError(f"回滚备份已存在，拒绝覆盖：{backup}")
    shutil.copy2(pool_path, backup)
    if backup.read_bytes() != before:
        raise RepositoryError("回滚备份校验失败，未清除旧条目")
    updated = dict(data)
    updated["prompts"] = [row for row in data["prompts"] if not (
        isinstance(row, dict) and str(row.get("source_code", "")).upper() == "P"
    )]
    encoded = (json.dumps(updated, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=".favorites-migration-", suffix=".json", dir=pool_path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if pool_path.read_bytes() != before:
            raise RepositoryError("写入期间主词库被修改，未清除旧条目")
        os.replace(temp_name, pool_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    result["removed"] = len(legacy)
    result["backup"] = str(backup)
    return result


def main(argv=None) -> int:
    """Offline helper distributed with the Hub; preview is the default."""
    import argparse
    import stat
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pool', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--remove-embedded', action='store_true')
    parser.add_argument('--confirm-services-stopped', action='store_true',
                        help='操作人确认已停止写入该词库的 Hub/AstrBot；不是自动进程检查')
    args = parser.parse_args(argv)
    for path in (args.pool, args.database):
        if not path.is_absolute() or '..' in path.parts or path.resolve() != path:
            parser.error('必须使用不含链接的规范绝对路径')
        for part in (path, *path.parents):
            if part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & 0x400):
                parser.error('路径不能包含符号链接或 junction')
        if path.exists() and not stat.S_ISREG(path.lstat().st_mode):
            parser.error('目标必须是普通文件')
    if args.pool == args.database:
        parser.error('主词库和收藏数据库不能是同一个文件')
    if args.apply and not args.confirm_services_stopped:
        parser.error('先停止词库写入，再添加 --confirm-services-stopped；工具不会停止服务')
    result = migrate_legacy_favorites(args.pool, args.database, apply=args.apply,
                                     remove_embedded=args.remove_embedded)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print('已完成指定迁移；不含图片操作。' if args.apply else '仅预览；未修改词库或创建收藏数据库。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
