"""Read Hub-owned source policy for QQ and all message-platform entry points."""
import json
from pathlib import Path

from .workflow_runtime import WorkflowError


def read_policies(data_dir: Path):
    path = data_dir / "hub_state/prompt_catalog.json"
    if not path.exists():
        return {}
    try:
        if path.is_symlink() or path.stat().st_size > 65536:
            raise ValueError("invalid path")
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = raw["sources"]
        if not isinstance(rows, list) or len(rows) > 8:
            raise ValueError("invalid rows")
        result = {}
        for row in rows:
            code = row["id"]
            levels = row["safety_codes"]
            if (code not in "BGDCRPKV" or len(code) != 1 or code in result
                    or not isinstance(levels, list) or not levels
                    or len(set(levels)) != len(levels)
                    or any(v not in ("N", "H", "S") for v in levels)
                    or row["default_safety"] not in levels
                    or any(type(row[k]) is not bool for k in ("enabled", "allow_group", "allow_private"))
                    or (code == "V" and len(levels) != 1)):
                raise ValueError("invalid source policy")
            result[code] = row
        return result
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise WorkflowError("词库来源配置损坏，已停止抽取，请管理员核对。") from exc


def apply_catalog_policy(data_dir: Path, selection: dict, *, private: bool):
    policies = read_policies(data_dir)
    result = dict(selection)
    sources = list(selection["source_codes"])
    levels = list(selection["safety_codes"])
    if sources == ["V"]:
        # Only this physical catalog adapter has legacy V/S compatibility.
        from .gufeng_catalog_runtime import gufeng_available
        if not gufeng_available(data_dir / "resources/gufeng/cards.sqlite3"):
            raise WorkflowError("独立通常词库尚未安装或不可用。")
        v_level = policies.get("V", {}).get("default_safety", "N")
        if not selection.get("explicit_safety") or levels == ["S"]:
            levels = [v_level]
    allowed = []
    for source in sources:
        policy = policies.get(source)
        if policy and (not policy["enabled"] or not policy["allow_private" if private else "allow_group"]):
            if selection.get("explicit_sources"):
                raise WorkflowError(f"来源 {source} 已停用或不允许当前会话。")
            continue
        allowed.append(source)
        if policy:
            if selection.get("explicit_safety") and any(s not in policy["safety_codes"] for s in levels):
                raise WorkflowError(f"来源 {source} 不允许当前内容级别，请刷新词库。")
            levels = [s for s in levels if s in policy["safety_codes"]]
    if not allowed or not levels:
        raise WorkflowError("当前词库策略下没有可抽取的来源/内容级别。")
    result.update(source_codes=allowed, safety_codes=levels)
    return result
