"""Small, instance-local catalog. Contains policy, never prompts or credentials.

The main JSON is indexed only when its stat changes. Favorites are queried for
the authenticated owner only. No timer, background scan or remote catalog.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from contextlib import closing
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

from .prompt_groups import read_groups
from .repositories import RepositoryError, _source_code, _safety_code, read_json_object
from .storage import mutate_json

SOURCES = ("B", "G", "D", "C", "R", "P", "K", "V")
LEVELS = ("N", "H", "S")


class SourcePolicy(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    allow_group: bool = True
    allow_private: bool = True
    safety_codes: list[str] = Field(default_factory=lambda: list(LEVELS), min_length=1, max_length=3)
    default_safety: str = "N"

    @field_validator("id")
    @classmethod
    def source(cls, value):
        if value not in SOURCES:
            raise ValueError("未知来源适配器；自建分类请使用自定义分组")
        return value

    @field_validator("safety_codes")
    @classmethod
    def levels(cls, value):
        if len(set(value)) != len(value) or any(v not in LEVELS for v in value):
            raise ValueError("内容级别必须是 N/H/S，且不能重复")
        return value

    @model_validator(mode="after")
    def default_in_levels(self):
        if self.default_safety not in self.safety_codes:
            raise ValueError("默认级别必须在允许级别中")
        if self.id == "V" and len(self.safety_codes) != 1:
            raise ValueError("独立通常库必须指定一个内容级别")
        return self


class CatalogWrite(BaseModel):
    sources: list[SourcePolicy] = Field(max_length=8)

    @model_validator(mode="after")
    def unique(self):
        if len({r.id for r in self.sources}) != len(self.sources):
            raise ValueError("来源 ID 重复")
        return self


def config_path(settings):
    return settings.hub_state_dir / "prompt_catalog.json"


def config(settings):
    path = config_path(settings)
    if not path.exists():
        return {"sources": [], "revision": "missing"}
    if path.is_symlink() or path.stat().st_size > 64 * 1024:
        raise RepositoryError("词库配置路径或大小异常")
    with path.open("rb") as stream:
        raw = stream.read()
        info = os.fstat(stream.fileno())
    try:
        value = CatalogWrite.model_validate_json(raw)
    except ValueError as exc:
        raise RepositoryError("词库配置损坏，请管理员核对") from exc
    revision = f"{info.st_mtime_ns:x}-{len(raw):x}-{hashlib.sha256(raw).hexdigest()[:16]}"
    return {**value.model_dump(), "revision": revision}


def source_policy(settings, code):
    configured = {r["id"]: r for r in config(settings)["sources"]}
    default = dict(id=code, name="个人收藏" if code == "P" else f"来源 {code}")
    if code == "V":
        default.update(name="国风古韵", safety_codes=["N"])
    return SourcePolicy.model_validate(configured.get(code, default)).model_dump()


def write_catalog(settings, payload, revision, actor):
    path = config_path(settings)
    _, _, _ = mutate_json(
        path=path, resource="prompt_catalog", expected_revision=revision,
        backup_root=settings.backup_dir, audit_path=settings.audit_log_path,
        actor=actor, action="replace", target="sources",
        mutate=lambda data: data.update(payload.model_dump()),
        initialize=lambda: {"sources": []},
    )
    return config(settings)


def _stamp(path):
    try:
        s = path.stat()
        return str(path.resolve()), s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns
    except FileNotFoundError:
        return str(path.absolute()), 0, 0, 0, 0


@lru_cache(maxsize=8)
def _pool_index(stamp):
    path = Path(stamp[0])
    if not stamp[1]:
        return {}
    raw = read_json_object(path)
    rows = raw.get("prompts")
    if not isinstance(rows, list):
        raise RepositoryError("词库缺少 prompts 列表")
    result = defaultdict(set)
    for row in rows:
        if not isinstance(row, dict) or not row.get("prompt") or row.get("enabled") is False:
            continue
        code = _source_code(row)
        # Personal entries are exposed exclusively through owner-scoped SQLite.
        if code != "P":
            result[code].add(_safety_code(row))
    return {k: sorted(v) for k, v in result.items()}


def catalog(settings, principal):
    from .local_gufeng import gufeng_available
    local = settings.execution_mode == "local"
    available = {} if local else dict(_pool_index(_stamp(settings.prompt_pool_path)))
    if principal.role != "legacy_lite" and settings.prompt_favorites_path.is_file():
        try:
            with closing(sqlite3.connect(settings.prompt_favorites_path.as_uri() + "?mode=ro", uri=True)) as db:
                levels = [r[0] for r in db.execute(
                    "SELECT DISTINCT safety_code FROM favorites WHERE owner=?", (principal.subject,))]
            if levels:
                available["P"] = levels
        except sqlite3.Error as exc:
            raise RepositoryError("无法读取个人收藏目录") from exc
    if not local:
        kp = settings.kp_prompt_pool_path
        if not kp.is_file():
            kp = settings.bundled_kp_prompt_pool_path
        if kp.is_file():
            available["K"] = ["N", "S"]
    v_path = (settings.local_gufeng_catalog_path if local else
              settings.plugin_data_dir / "resources/gufeng/cards.sqlite3")
    if (not local or principal.is_admin) and gufeng_available(v_path):
        available["V"] = source_policy(settings, "V")["safety_codes"]
    policies = config(settings)
    rows = []
    for code in SOURCES:
        policy = source_policy(settings, code)
        levels = [s for s in LEVELS if s in available.get(code, []) and s in policy["safety_codes"]]
        if not levels or not policy["enabled"]:
            continue
        rows.append({**policy, "safety_codes": levels,
                     "default_safety": policy["default_safety"] if policy["default_safety"] in levels else levels[0],
                     "modes": ["random"] if code == "V" else ([] if local else ["random", "chaos"]),
                     "standalone": code in {"K", "V"},
                     "editable": code in {"B", "G", "D", "C", "R"},
                     "browseable": code not in {"V"},
                     "supports_custom_groups": code not in {"K", "V", "P"}})
    groups = read_groups(settings)["groups"]
    value = {"schema_version": 1, "execution_mode": settings.execution_mode,
             "sources": rows, "groups": groups,
             "levels": [{"id": "N", "name": "健康"}, {"id": "H", "name": "敏感"},
                        {"id": "S", "name": "成人（仅私聊）"}]}
    if principal.is_admin:
        # G is a supported empty destination for first import, not a promise of bundled data.
        edit_codes = {"G"} | {c for c in available if c in {"B", "G", "D", "C", "R"}}
        value["editable_sources"] = [source_policy(settings, c) for c in SOURCES if c in edit_codes]
        value["configuration"] = policies
    value["revision"] = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return value


def validate_request(settings, payload, target_kind):
    """Apply server policy to old and new clients before scheduling any work."""
    if payload.kind not in {"random", "chaos"}:
        return payload
    codes = {c for c in payload.pool_filter.upper() if c in SOURCES}
    if "V" in codes and codes != {"V"}:
        raise RepositoryError("独立通常词库不能与其他来源混合，请单独选择")
    requested = {c for c in payload.pool_filter.upper() if c in LEVELS}
    level = next(iter(requested)) if len(requested) == 1 else payload.safety_code
    # An omitted legacy source selection must not bypass disabled adapters.
    if not codes:
        codes = {"B", "G", "D", "P"}
        permitted = [c for c in SOURCES if c in codes and source_policy(settings, c)["enabled"]
                     and source_policy(settings, c)["allow_" + target_kind]
                     and level in source_policy(settings, c)["safety_codes"]]
        if not permitted:
            raise RepositoryError("当前来源策略下没有可用词库，请刷新选择")
        return payload.model_copy(update={"pool_filter": ",".join(permitted) + "/" + level})
    for code in codes:
        row = source_policy(settings, code)
        if not row["enabled"] or not row["allow_" + target_kind]:
            raise RepositoryError(f'{row["name"]} 已停用或不允许此投递目标，请刷新词库')
        if code == "V":
            # V is the installed GuFeng adapter, not an arbitrary user group named v.
            actual = row["default_safety"]
            if requested not in (set(), {actual}, {"S"}):
                raise RepositoryError(f'{row["name"]} 当前内容级别为 {actual}')
            payload = payload.model_copy(update={"pool_filter": "V/" + actual, "safety_code": actual})
        elif level not in row["safety_codes"]:
            raise RepositoryError(f'{row["name"]} 不允许所选内容级别，请刷新词库')
    return payload
