"""Shared, stdlib-only group policy and atomic admission store.

The Hub ships an identical copy.  Missing database means the optional module is
off; a present but unreadable database never silently disables enforcement.
Limits count accepted tasks (a five-draw is one task), with UTC calendar days.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


class GroupPolicyError(RuntimeError):
    pass


def group_key(platform: str, bot_id: str, group_id: str) -> str:
    platform, bot_id, group_id = str(platform), str(bot_id), str(group_id)
    if platform not in {"qq", "telegram", "discord"}:
        raise GroupPolicyError("群平台无效")
    if not re.fullmatch(r"[^:\s/\\]{1,100}", bot_id):
        raise GroupPolicyError("机器人实例标识无效")
    if not re.fullmatch(r"-?[0-9]{1,24}", group_id):
        raise GroupPolicyError("群号无效")
    return f"{platform}:{bot_id}:{group_id}"


def canonical_group(value: str) -> str:
    parts = str(value).split(":")
    if len(parts) != 3:
        raise GroupPolicyError("群标识必须包含平台、机器人和群号")
    return group_key(*parts)


def _user_id(value) -> str:
    value = str(value)
    if not re.fullmatch(r"[0-9]{1,24}", value):
        raise GroupPolicyError("用户 ID 无效")
    return value


def _boolean(value, field):
    if not isinstance(value, bool):
        raise GroupPolicyError(f"{field} 必须为布尔值")
    return value


def _integer(value, field, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise GroupPolicyError(f"{field} 必须在 {minimum}–{maximum} 之间")
    return value


def normalize_group(value):
    if not isinstance(value, dict):
        raise GroupPolicyError("群配置无效")
    key = value.get("key") or group_key(value.get("platform", "qq"), value.get("bot_id", ""), value.get("group_id", ""))
    key = canonical_group(key)
    platform, bot_id, gid = key.split(":")
    for field, expected in (("platform", platform), ("bot_id", bot_id), ("group_id", gid)):
        if field in value and str(value[field]) != expected:
            raise GroupPolicyError("群标识与配置不一致")
    name = str(value.get("name", gid)).strip() or gid
    if not name or len(name) > 100:
        raise GroupPolicyError("群名称长度必须为 1–100")
    return dict(key=key, platform=platform, bot_id=bot_id, group_id=gid, name=name,
                enabled=_boolean(value.get("enabled", True), "群启用"),
                level_system_enabled=_boolean(value.get("level_system_enabled", False), "等级系统"),
                safety_mode=(None if value.get("safety_mode") is None else _boolean(value["safety_mode"], "群安全模式")),
                daily_limit=_integer(value.get("daily_limit", 20), "每日任务上限", 1, 100000),
                cooldown_seconds=_integer(value.get("cooldown_seconds", 60), "冷却秒数", 0, 86400))


def normalize_user(value):
    if not isinstance(value, dict):
        raise GroupPolicyError("用户配置无效")
    key = canonical_group(value.get("group_key", ""))
    primary = canonical_group(value.get("primary_group", "") or key)
    if primary.rsplit(":", 1)[0] != key.rsplit(":", 1)[0]:
        raise GroupPolicyError("主要跑图群必须属于同一平台和机器人")
    uid = _user_id(value.get("user_id", value.get("qq", "")))
    return dict(group_key=key, user_id=uid, qq=uid,
                grade=_integer(value.get("grade", 1), "用户等级", 0, 4),
                primary_group=primary)


class GroupStore:
    def __init__(self, path):
        self.path = Path(path)

    def _safe_path(self):
        if not self.path.is_absolute() or self.path.resolve() != self.path:
            raise GroupPolicyError("群管理数据路径无效")
        if self.path.exists() and not self.path.is_file():
            raise GroupPolicyError("群管理数据不是普通文件")

    def _connect(self, *, create=False):
        self._safe_path()
        new_database = not self.path.exists()
        if not self.path.exists():
            if not create:
                return None
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._safe_path()
        try:
            db = sqlite3.connect(self.path if create else self.path.as_uri() + "?mode=rw", uri=not create, timeout=10)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            if create and new_database:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS metadata(id INTEGER PRIMARY KEY CHECK(id=1), schema_version INTEGER NOT NULL, enabled INTEGER NOT NULL, revision INTEGER NOT NULL);
                    INSERT OR IGNORE INTO metadata VALUES(1,1,0,0);
                    CREATE TABLE IF NOT EXISTS groups(key TEXT PRIMARY KEY, body TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS users(group_key TEXT NOT NULL REFERENCES groups(key), user_id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(group_key,user_id));
                    CREATE TABLE IF NOT EXISTS admissions(request_id TEXT PRIMARY KEY, group_key TEXT NOT NULL, user_id TEXT NOT NULL, accepted_at REAL NOT NULL, day TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS admissions_user_day ON admissions(group_key,user_id,day);
                """)
            row = db.execute("SELECT * FROM metadata WHERE id=1").fetchone()
            if not row or row["schema_version"] != 1 or row["enabled"] not in (0, 1):
                raise GroupPolicyError("群管理数据库版本或设置无效")
            return db
        except Exception as exc:
            if "db" in locals():
                db.close()
            raise GroupPolicyError("群管理数据库不可用；为防止绕过权限已拒绝任务") from exc

    @staticmethod
    def _read(db):
        meta = db.execute("SELECT * FROM metadata WHERE id=1").fetchone()
        groups = [normalize_group(json.loads(row[0])) for row in db.execute("SELECT body FROM groups ORDER BY key")]
        users = [normalize_user(json.loads(row[0])) for row in db.execute("SELECT body FROM users ORDER BY group_key,user_id")]
        return {"enabled": bool(meta["enabled"]), "revision": meta["revision"], "groups": groups, "users": users, "day_timezone": "UTC"}

    def read(self):
        db = self._connect()
        if db is None:
            return {"enabled": False, "revision": 0, "groups": [], "users": [], "day_timezone": "UTC"}
        try:
            return self._read(db)
        except Exception as exc:
            raise GroupPolicyError("群管理配置读取失败；已拒绝任务") from exc
        finally:
            db.close()

    def is_enabled(self):
        """Constant-size configuration check; no member scan on image review."""
        db = self._connect()
        if db is None:
            return False
        try:
            return bool(db.execute("SELECT enabled FROM metadata WHERE id=1").fetchone()[0])
        finally:
            db.close()

    def _mutate(self, operation):
        db = self._connect(create=True)
        try:
            db.execute("BEGIN IMMEDIATE")
            operation(db)
            db.execute("UPDATE metadata SET revision=revision+1 WHERE id=1")
            result = self._read(db)
            db.commit()
            return result
        except Exception as exc:
            db.rollback()
            if isinstance(exc, GroupPolicyError):
                raise
            raise GroupPolicyError("群管理修改未保存") from exc
        finally:
            db.close()

    @staticmethod
    def _save_group(db, value):
        value = normalize_group(value)
        db.execute("INSERT INTO groups(key,body) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET body=excluded.body", (value["key"], json.dumps(value, ensure_ascii=False)))

    @staticmethod
    def _save_user(db, value):
        value = normalize_user(value)
        for key in (value["group_key"], value["primary_group"]):
            if not db.execute("SELECT 1 FROM groups WHERE key=?", (key,)).fetchone():
                raise GroupPolicyError("用户归属的群尚未配置")
        db.execute("INSERT INTO users(group_key,user_id,body) VALUES(?,?,?) ON CONFLICT(group_key,user_id) DO UPDATE SET body=excluded.body", (value["group_key"], value["user_id"], json.dumps(value, ensure_ascii=False)))

    def set_enabled(self, enabled):
        enabled = _boolean(enabled, "群管理启用")
        return self._mutate(lambda db: db.execute("UPDATE metadata SET enabled=? WHERE id=1", (int(enabled),)))

    def upsert_group(self, value):
        value = normalize_group(value)
        return self._mutate(lambda db: self._save_group(db, value))

    def patch_group(self, key, changes):
        key = canonical_group(key)
        if not isinstance(changes, dict) or set(changes) - {"name", "enabled", "level_system_enabled", "safety_mode", "daily_limit", "cooldown_seconds"}:
            raise GroupPolicyError("群配置修改字段无效")
        def update(db):
            row = db.execute("SELECT body FROM groups WHERE key=?", (key,)).fetchone()
            if not row:
                raise GroupPolicyError("群尚未接入")
            self._save_group(db, {**json.loads(row[0]), **changes})
        return self._mutate(update)

    def upsert_user(self, value):
        value = normalize_user(value)
        return self._mutate(lambda db: self._save_user(db, value))

    def set_user_grade(self, key, uid, grade):
        key, uid = canonical_group(key), _user_id(uid)
        grade = _integer(grade, "用户等级", 0, 4)
        def update(db):
            row = db.execute("SELECT body FROM users WHERE group_key=? AND user_id=?", (key, uid)).fetchone()
            if row:
                user = normalize_user(json.loads(row[0]))
            else:
                memberships = [normalize_user(json.loads(r[0])) for r in db.execute("SELECT body FROM users WHERE user_id=?", (uid,))]
                primary = {u["primary_group"] for u in memberships if u["group_key"].rsplit(":", 1)[0] == key.rsplit(":", 1)[0]}
                user = dict(group_key=key, user_id=uid, primary_group=next(iter(primary)) if len(primary) == 1 else key)
            self._save_user(db, {**user, "grade": grade})
        return self._mutate(update)

    def delete_user(self, group_id, user_id):
        key, uid = canonical_group(group_id), _user_id(user_id)
        return self._mutate(lambda db: db.execute("DELETE FROM users WHERE group_key=? AND user_id=?", (key, uid)))

    def write_config(self, enabled, groups, users, expected_revision=None):
        enabled = _boolean(enabled, "群管理启用")
        groups, users = [normalize_group(g) for g in groups], [normalize_user(u) for u in users]
        if len({g["key"] for g in groups}) != len(groups) or len({(u["group_key"], u["user_id"]) for u in users}) != len(users):
            raise GroupPolicyError("群或用户配置重复")
        def update(db):
            revision = db.execute("SELECT revision FROM metadata WHERE id=1").fetchone()[0]
            if expected_revision is not None and expected_revision != revision:
                raise GroupPolicyError("群配置已变更，请重新读取；建议按单项保存")
            db.execute("DELETE FROM users")
            db.execute("DELETE FROM groups")
            for g in groups:
                self._save_group(db, g)
            for u in users:
                self._save_user(db, u)
            db.execute("UPDATE metadata SET enabled=? WHERE id=1", (int(enabled),))
        return self._mutate(update)

    @staticmethod
    def _decision(db, key, uid, admin, scope=""):
        meta = db.execute("SELECT enabled FROM metadata WHERE id=1").fetchone()
        result = dict(enabled=False, allowed=True, silent=False, reason="", grade=3, safety_mode=None, group_key=key)
        if not meta[0]:
            return result
        if not key:
            if not scope and not admin:
                result.update(enabled=True, allowed=False, reason="私聊任务缺少平台及机器人身份")
                return result
            memberships = [normalize_user(json.loads(row[0])) for row in db.execute("SELECT body FROM users WHERE user_id=?", (uid,))]
            memberships = [u for u in memberships if u["group_key"].rsplit(":", 1)[0] == scope]
            primary = {u["primary_group"] for u in memberships}
            if len(primary) == 1:
                key = next(iter(primary))
                if key.rsplit(":", 1)[0] != scope:
                    raise GroupPolicyError("主要跑图群不属于当前平台或机器人")
                result["group_key"] = key
            elif admin:
                return result
            else:
                result.update(enabled=True, allowed=False, reason="请先由管理员设置唯一的主要跑图群")
                return result
        row = db.execute("SELECT body FROM groups WHERE key=?", (key,)).fetchone()
        if row is None:
            if not admin:
                result.update(enabled=True, allowed=False, silent=bool(key), reason="该群尚未接入群聊管理")
            return result
        group = normalize_group(json.loads(row[0]))
        if not group["enabled"]:
            if not admin:
                result.update(enabled=True, allowed=False, silent=bool(key), reason="本群生图功能已停用")
            return result
        userrow = db.execute("SELECT body FROM users WHERE group_key=? AND user_id=?", (key, uid)).fetchone()
        user = normalize_user(json.loads(userrow[0])) if userrow else None
        level = user["grade"] if user else 0
        if not group["level_system_enabled"]:
            level = 4 if level == 4 else 3
        if admin:
            level = 4
        result.update(enabled=True, grade=level, safety_mode=group["safety_mode"],
                      allowed=bool(level), silent=not bool(level),
                      reason="本群未授予生图权限" if not level else "",
                      level_system_enabled=group["level_system_enabled"], daily_limit=group["daily_limit"],
                      cooldown_seconds=group["cooldown_seconds"], primary_group=user["primary_group"] if user else key)
        return result

    def check(self, group_id, user_id, admin=False, request_id="", consume=False, scope=""):
        db = self._connect()
        if db is None:
            return dict(enabled=False, allowed=True, silent=False, reason="", grade=3, safety_mode=None, group_key=group_id, request_id=request_id)
        try:
            db.execute("BEGIN IMMEDIATE" if consume else "BEGIN")
            if not db.execute("SELECT enabled FROM metadata WHERE id=1").fetchone()[0]:
                return dict(enabled=False, allowed=True, silent=False, reason="", grade=3, safety_mode=None, group_key=group_id, request_id=request_id)
            key = canonical_group(group_id) if group_id else ""
            uid = "__admin__" if admin and not user_id else _user_id(user_id)
            if consume and (not isinstance(request_id, str) or not 1 <= len(request_id) <= 240):
                raise GroupPolicyError("任务幂等标识无效")
            result = self._decision(db, key, uid, bool(admin), scope=scope)
            key = result["group_key"]
            result["request_id"] = request_id
            if not result["enabled"] or not result["allowed"]:
                return result
            now = time.time()
            day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
            if request_id:
                previous = db.execute("SELECT group_key,user_id FROM admissions WHERE request_id=?", (request_id,)).fetchone()
                if previous:
                    if (previous[0], previous[1]) != (key, uid):
                        raise GroupPolicyError("任务幂等标识与群或用户不一致")
                    result["already_reserved"] = True
                    return result
            if result["grade"] <= 2:
                count = db.execute("SELECT COUNT(*) FROM admissions WHERE group_key=? AND user_id=? AND day=?", (key, uid, day)).fetchone()[0]
                if count >= result["daily_limit"]:
                    result.update(allowed=False, reason="本群今日生图次数已用完")
                if result["grade"] == 1:
                    latest = db.execute("SELECT MAX(accepted_at) FROM admissions WHERE group_key=? AND user_id=?", (key, uid)).fetchone()[0]
                    remaining = int(max(0, (latest or 0) + result["cooldown_seconds"] - now) + 0.999)
                    if remaining:
                        result.update(allowed=False, reason=f"本群生图冷却中，请等待 {remaining} 秒", retry_after=remaining)
            if consume and result["allowed"] and uid != "__admin__":
                db.execute("INSERT INTO admissions VALUES(?,?,?,?,?)", (request_id, key, uid, now, day))
                # Durable dedup outlives every bridge ticket; old quota rows are
                # bounded and contain no images/prompts or authorization state.
                db.execute("DELETE FROM admissions WHERE accepted_at<?", (now - 35 * 86400,))
                db.commit()
            return result
        except Exception as exc:
            if isinstance(exc, GroupPolicyError):
                raise
            raise GroupPolicyError("群权限检查失败；已拒绝任务") from exc
        finally:
            db.close()

    def policy(self, group_id, qq, is_admin=False, *, scope=""):
        return self.check(group_id, qq, admin=is_admin, scope=scope)

    def reserve(self, group_id, qq, request_id, is_admin=False, *, scope=""):
        return self.check(group_id, qq, admin=is_admin, request_id=request_id, consume=True, scope=scope)


GroupPolicyStore = GroupStore
