from __future__ import annotations

import json
import hashlib
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from .workflow_runtime import WorkflowError, build_prompt_text
    from .kp_dynamic_runtime import _safety_for_text
except ImportError:  # pragma: no cover - direct local tests
    from workflow_runtime import WorkflowError, build_prompt_text
    from kp_dynamic_runtime import _safety_for_text


VALID_SAFETY_LABELS = {"normal", "nsfw", "sexual"}
SOURCE_CODES = ("B", "G", "D", "C", "R", "K", "P")
MANAGEABLE_SOURCE_CODES = ("B", "G", "D", "C", "R", "P")
SAFETY_CODES = ("N", "H", "S")
DEFAULT_SOURCE_CODES = ("B", "G", "D", "P")
DEFAULT_SAFETY_CODES = ("N", "H")
SOURCE_NAME_TO_CODE = {
    "basic": "B",
    "generate": "G",
    "discord": "D",
    "codex": "C",
    "reverse": "R",
    "kprompt": "K",
    "liked": "P",
    "personal": "P",
}
SAFETY_NAME_TO_CODE = {"normal": "N", "nsfw": "H", "sexual": "S"}
CODE_TO_SAFETY_NAME = {value: key for key, value in SAFETY_NAME_TO_CODE.items()}
CUSTOM_GROUP_ID_PATTERN = re.compile(r"^[^\s@/+,]{1,64}$", flags=re.UNICODE)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("root is not an object")
    return data


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _merge_dict(base: Any, override: Any) -> Any:
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    result = dict(base)
    for key, value in override.items():
        result[key] = _merge_dict(result.get(key), value)
    return result


def _merge_prompt_pools(
    persistent: dict[str, Any], bundled: dict[str, Any]
) -> dict[str, Any]:
    replacement_sources = {
        str(code).strip().upper()
        for code in bundled.get("replace_source_codes_on_upgrade", [])
        if str(code).strip().upper() in SOURCE_CODES
    }
    deleted_ids = {
        str(item).strip()
        for item in persistent.get("deleted_prompt_ids", [])
        if str(item).strip()
    }
    bundled_by_id = {
        str(item.get("id")): item
        for item in bundled.get("prompts", [])
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    replacement_ids = {
        prompt_id
        for prompt_id, item in bundled_by_id.items()
        if str(item.get("source_code", "")).strip().upper() in replacement_sources
    }
    # A replacement catalog may reuse an old ID for different content. Its build
    # step already applies content-based administrator deletions, so stale ID
    # tombstones must not hide the newly assigned record.
    deleted_ids.difference_update(replacement_ids)
    retired = bundled.get("retired_managed_prompt_fingerprints", {})
    merged_prompts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for existing in persistent.get("prompts", []):
        if not isinstance(existing, dict):
            continue
        prompt_id = str(existing.get("id", "")).strip()
        if not prompt_id or prompt_id in seen_ids or prompt_id in deleted_ids:
            continue
        # Only retire known, unmodified old defaults. Custom entries and edits survive.
        fingerprint = hashlib.sha256(json.dumps(existing, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if fingerprint in retired.get(prompt_id, []):
            continue
        bundled_item = bundled_by_id.get(prompt_id)
        existing_source = str(existing.get("source_code", "")).strip().upper()
        if existing_source not in SOURCE_CODES:
            existing_source = SOURCE_NAME_TO_CODE.get(
                str(existing.get("source_group", "basic")).strip().casefold(), "B"
            )
        catalog_prefix = {
            "B": "good-",
            "G": "generate-",
            "D": "discord-",
            "C": "codex-",
            "R": "reverse-",
            "K": "kp-",
            "P": "liked-",
        }.get(existing_source, "")
        is_replaced_catalog_item = (
            existing_source in replacement_sources
            and bool(catalog_prefix)
            and prompt_id.casefold().startswith(catalog_prefix)
        )
        if existing_source == "K" and bool(existing.get("runtime_generated")):
            # Runtime-composed K records are persisted so Hub/App can like the
            # exact prompt. They are history, not bundled catalog records, and
            # therefore must survive a managed K catalog upgrade.
            is_replaced_catalog_item = False
        if is_replaced_catalog_item:
            if bundled_item is None:
                continue
            item = dict(bundled_item)
        elif bundled_item is not None:
            # Preserve user edits, but fill all new 0.2.6 routing metadata.
            item = dict(bundled_item)
            item.update(existing)
            for key in (
                "source_group",
                "source_code",
                "safety_level",
                "safety_code",
                "safety_matches",
            ):
                if key not in existing and key in bundled_item:
                    item[key] = bundled_item[key]
        else:
            item = dict(existing)
        merged_prompts.append(item)
        seen_ids.add(prompt_id)

    for bundled_item in bundled.get("prompts", []):
        if not isinstance(bundled_item, dict):
            continue
        prompt_id = str(bundled_item.get("id", "")).strip()
        if prompt_id and prompt_id not in seen_ids and prompt_id not in deleted_ids:
            merged_prompts.append(dict(bundled_item))
            seen_ids.add(prompt_id)

    result = dict(bundled)
    for key, value in persistent.items():
        if key in {"prompts", "schema_version", "catalog_revision", "release_version"}:
            continue
        if key in {"quality_presets", "category_aliases", "controllers"}:
            result[key] = _merge_dict(result.get(key, {}), value)
        elif key not in result:
            result[key] = value
    result["prompts"] = merged_prompts
    result["deleted_prompt_ids"] = sorted(deleted_ids)
    return result


def ensure_prompt_pool(path: Path, bundled_path: Path) -> Path:
    """Install or non-destructively migrate the persistent prompt pool."""

    if not bundled_path.is_file():
        raise WorkflowError(f"插件内置提示词池不存在：{bundled_path}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            shutil.copy2(bundled_path, path)
            return path

        persistent = _read_json(path)
        bundled = _read_json(bundled_path)
        current_revision = int(persistent.get("catalog_revision", 0) or 0)
        bundled_revision = int(bundled.get("catalog_revision", 0) or 0)
        if bundled_revision <= current_revision:
            return path

        backup = path.with_name(f"{path.stem}.pre-0.2.6.json")
        if not backup.exists():
            shutil.copy2(path, backup)
        revision_backup = path.with_name(f"{path.stem}.pre-catalog-{bundled_revision}-{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json")
        with path.open('rb') as source, revision_backup.open('xb') as target:
            shutil.copyfileobj(source, target)
        _write_json_atomic(path, _merge_prompt_pools(persistent, bundled))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"无法初始化或升级随机提示词池：{exc}") from exc
    return path


def load_prompt_pool(path: Path) -> dict[str, Any]:
    try:
        data = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"无法读取随机提示词池：{exc}") from exc
    if not isinstance(data.get("prompts"), list):
        raise WorkflowError("随机提示词池必须包含 prompts 列表。")

    identifiers: set[str] = set()
    for index, item in enumerate(data["prompts"], start=1):
        if not isinstance(item, dict):
            raise WorkflowError(f"随机提示词第 {index} 项不是对象。")
        prompt_id = str(item.get("id", "")).strip()
        prompt = str(item.get("prompt", "")).strip()
        safety = str(item.get("safety_level", "normal")).strip().lower()
        if not prompt_id or prompt_id in identifiers:
            raise WorkflowError(f"随机提示词第 {index} 项 ID 缺失或重复。")
        if not prompt:
            raise WorkflowError(f"随机提示词 {prompt_id} 内容为空。")
        if safety not in VALID_SAFETY_LABELS:
            raise WorkflowError(
                f"随机提示词 {prompt_id} 的 safety_level 必须是 normal/nsfw/sexual。"
            )
        groups = item.get("custom_groups", [])
        if isinstance(groups, str):
            groups = [groups]
        if not isinstance(groups, list):
            raise WorkflowError(
                f"随机提示词 {prompt_id} 的 custom_groups 必须是数组。"
            )
        for group in groups:
            validate_custom_group_id(str(group))
        identifiers.add(prompt_id)
    return data


def validate_custom_group_id(value: str) -> str:
    group_id = str(value or "").strip().casefold()
    if not CUSTOM_GROUP_ID_PATTERN.fullmatch(group_id):
        raise WorkflowError(
            "自定义分组 ID 长度须为 1-64，且不能包含空格或 @ / + ,。"
        )
    return group_id


def prompt_entry_custom_groups(item: dict[str, Any]) -> list[str]:
    raw = item.get("custom_groups", [])
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for value in raw:
        try:
            group_id = validate_custom_group_id(str(value))
        except WorkflowError:
            continue
        if group_id not in result:
            result.append(group_id)
    return result


def decode_custom_group_token(token: str) -> list[str] | None:
    candidate = str(token or "").strip()
    if not candidate.startswith("@") or len(candidate) == 1:
        return None
    raw_groups = [part for part in re.split(r"[+,]", candidate[1:]) if part]
    if not raw_groups:
        return None
    try:
        return list(dict.fromkeys(validate_custom_group_id(part) for part in raw_groups))
    except WorkflowError:
        return None


def parse_group_selector(body: str) -> tuple[str, dict[str, Any]]:
    """Consume a leading `C/H`-style selector and apply safe defaults."""

    stripped = str(body or "").strip()
    tokens: list[str] = []
    rest = stripped
    parts: list[str] = []
    custom_groups: list[str] = []
    while rest:
        match = re.match(r"^(\S+)(?:\s+(.*))?$", rest, flags=re.S)
        first = match.group(1) if match else ""
        candidate = first.upper()
        candidate_parts = [part for part in re.split(r"[/+,]", candidate) if part]
        valid_codes = set(SOURCE_CODES + SAFETY_CODES)
        is_code_token = (
            first == candidate
            and bool(candidate_parts)
            and all(len(part) == 1 and part in valid_codes for part in candidate_parts)
        )
        alias_code = SOURCE_NAME_TO_CODE.get(first.casefold()) or SAFETY_NAME_TO_CODE.get(
            first.casefold()
        )
        custom = decode_custom_group_token(first)
        if is_code_token and not parts:
            tokens.append(candidate)
            parts = candidate_parts
        elif alias_code:
            if parts:
                break
            tokens.append(alias_code)
            parts = [alias_code]
        elif custom is not None and not custom_groups:
            tokens.append("@" + "+".join(custom))
            custom_groups = custom
        else:
            break
        rest = (match.group(2) or "").strip() if match else ""

    requested_sources = [code for code in parts if code in SOURCE_CODES]
    requested_safety = [code for code in parts if code in SAFETY_CODES]
    sources = requested_sources or list(DEFAULT_SOURCE_CODES)
    safety = requested_safety or list(DEFAULT_SAFETY_CODES)
    return rest, {
        "token": " ".join(tokens),
        "source_codes": sources,
        "safety_codes": safety,
        "custom_groups": custom_groups,
        "explicit_sources": bool(requested_sources),
        "explicit_safety": bool(requested_safety),
        "protected_fallback": False,
    }


def decode_group_code_token(token: str) -> tuple[list[str], list[str]] | None:
    candidate = str(token or "").strip().upper()
    if not candidate:
        return None
    parts = [part for part in re.split(r"[/+,]", candidate) if part]
    valid = set(SOURCE_CODES + SAFETY_CODES)
    if not parts or any(len(part) != 1 or part not in valid for part in parts):
        return None
    sources = list(dict.fromkeys(part for part in parts if part in SOURCE_CODES))
    safety = list(dict.fromkeys(part for part in parts if part in SAFETY_CODES))
    return sources, safety


def require_source_safety_selector(token: str) -> tuple[str, str]:
    decoded = decode_group_code_token(token)
    if decoded is None or len(decoded[0]) != 1 or len(decoded[1]) != 1:
        raise WorkflowError("分组必须同时且各指定一个来源组和级别组，例如 B/N、D/H、C/S。")
    return decoded[0][0], decoded[1][0]


def parse_protected_characters(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        raw_items = [str(item) for item in value]
    else:
        raw_items = re.split(r"[,，;；\n\r]+", str(value or ""))
    return {item.strip().casefold() for item in raw_items if item.strip()}


def apply_protected_character_policy(
    selection: dict[str, Any], character_name: str, protected_characters: Any
) -> dict[str, Any]:
    result = dict(selection)
    protected = parse_protected_characters(protected_characters)
    if (
        character_name.strip().casefold() in protected
        and "S" in result.get("safety_codes", [])
    ):
        result["safety_codes"] = list(DEFAULT_SAFETY_CODES)
        result["protected_fallback"] = True
    return result


def describe_selection(selection: dict[str, Any]) -> str:
    sources = ",".join(selection.get("source_codes", DEFAULT_SOURCE_CODES))
    safety = ",".join(selection.get("safety_codes", DEFAULT_SAFETY_CODES))
    custom = "+".join(selection.get("custom_groups", []))
    return f"{sources}/{safety}" + (f" @{custom}" if custom else "")


def _entry_source_code(item: dict[str, Any]) -> str:
    code = str(item.get("source_code", "")).strip().upper()
    if code in SOURCE_CODES:
        return code
    return SOURCE_NAME_TO_CODE.get(
        str(item.get("source_group", "basic")).strip().casefold(), "B"
    )


def _entry_safety_code(item: dict[str, Any]) -> str:
    code = str(item.get("safety_code", "")).strip().upper()
    if code in SAFETY_CODES:
        return code
    return SAFETY_NAME_TO_CODE.get(
        str(item.get("safety_level", "normal")).strip().casefold(), "N"
    )


def _matched_categories(pool: dict[str, Any], user_prompt: str) -> list[str]:
    folded = str(user_prompt or "").casefold()
    if not folded:
        return []
    matched: list[str] = []
    aliases = pool.get("category_aliases", {})
    if not isinstance(aliases, dict):
        return matched
    for category, needles in aliases.items():
        if not isinstance(needles, list):
            continue
        if any(str(needle).casefold() in folded for needle in needles if str(needle)):
            matched.append(str(category))
    return matched


def _weighted_choice(items: list[dict[str, Any]]) -> dict[str, Any]:
    weighted: list[tuple[dict[str, Any], int]] = []
    total = 0
    for item in items:
        try:
            weight = max(0, int(item.get("weight", 1)))
        except (TypeError, ValueError):
            weight = 1
        if weight <= 0:
            continue
        total += weight
        weighted.append((item, total))
    if not weighted or total <= 0:
        raise WorkflowError("随机提示词池没有权重大于 0 的可用条目。")
    ticket = secrets.randbelow(total) + 1
    for item, ceiling in weighted:
        if ticket <= ceiling:
            return item
    return weighted[-1][0]


def select_random_prompt(
    pool: dict[str, Any],
    user_prompt: str = "",
    *,
    source_codes: list[str] | tuple[str, ...] = DEFAULT_SOURCE_CODES,
    safety_codes: list[str] | tuple[str, ...] = DEFAULT_SAFETY_CODES,
    custom_groups: list[str] | tuple[str, ...] = (),
) -> tuple[dict[str, Any], list[str], bool]:
    source_set = {str(code).upper() for code in source_codes}
    safety_set = {str(code).upper() for code in safety_codes}
    required_groups = {
        validate_custom_group_id(str(group)) for group in custom_groups
    }
    eligible = [
        item
        for item in pool.get("prompts", [])
        if isinstance(item, dict)
        and bool(item.get("enabled", True))
        and _entry_source_code(item) in source_set
        and _entry_safety_code(item) in safety_set
        and not (_entry_source_code(item) == "K" and _entry_safety_code(item) == "N" and _safety_for_text(str(item.get("prompt", ""))) != "N")
        and required_groups.issubset(set(prompt_entry_custom_groups(item)))
    ]
    if not eligible:
        sources = ",".join(sorted(source_set)) or "无"
        safety = ",".join(sorted(safety_set)) or "无"
        custom = "+".join(sorted(required_groups))
        custom_text = f" @{custom}" if custom else ""
        raise WorkflowError(f"所选范围 {sources}/{safety}{custom_text} 暂无可用提示词。")

    matched = _matched_categories(pool, user_prompt)
    candidates = eligible
    used_match = False
    if matched:
        matched_set = set(matched)
        filtered = [
            item
            for item in eligible
            if matched_set.intersection(
                str(category) for category in item.get("categories", [])
            )
        ]
        if filtered:
            candidates = filtered
            used_match = True
    return _weighted_choice(candidates), matched, used_match


def select_random_prompts(
    pool: dict[str, Any],
    count: int,
    user_prompt: str = "",
    *,
    source_codes: list[str] | tuple[str, ...] = DEFAULT_SOURCE_CODES,
    safety_codes: list[str] | tuple[str, ...] = DEFAULT_SAFETY_CODES,
    custom_groups: list[str] | tuple[str, ...] = (),
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Select distinct records without replacement for multi-draw generation."""

    requested = max(1, int(count))
    selected: list[dict[str, Any]] = []
    excluded_ids: set[str] = set()
    matched_categories: list[str] = []
    used_match = False
    working = dict(pool)
    for _ in range(requested):
        working["prompts"] = [
            item
            for item in pool.get("prompts", [])
            if str(item.get("id", "")) not in excluded_ids
        ]
        item, matched, used = select_random_prompt(
            working,
            user_prompt,
            source_codes=source_codes,
            safety_codes=safety_codes,
            custom_groups=custom_groups,
        )
        selected.append(item)
        excluded_ids.add(str(item.get("id", "")))
        matched_categories = matched
        used_match = used_match or used
    return selected, matched_categories, used_match


def quality_prompt(pool: dict[str, Any], preset_name: str = "general") -> str:
    presets = pool.get("quality_presets", {})
    preset = presets.get(preset_name) if isinstance(presets, dict) else None
    if not isinstance(preset, dict) or not bool(preset.get("enabled", True)):
        return ""
    return str(preset.get("prompt", "")).strip(" ,\n\t")


def compose_random_body(user_prompt: str, item: dict[str, Any]) -> str:
    return build_prompt_text("", user_prompt, str(item.get("prompt", "")))


def prompt_pool_stats(pool: dict[str, Any]) -> dict[str, Any]:
    prompts = [item for item in pool.get("prompts", []) if isinstance(item, dict)]
    enabled = [item for item in prompts if bool(item.get("enabled", True))]
    labels = {label: 0 for label in sorted(VALID_SAFETY_LABELS)}
    sources = {code: 0 for code in SOURCE_CODES}
    safety_codes = {code: 0 for code in SAFETY_CODES}
    custom_groups: dict[str, int] = {}
    for item in prompts:
        label = str(item.get("safety_level", "normal")).lower()
        labels[label] = labels.get(label, 0) + 1
        sources[_entry_source_code(item)] += 1
        safety_codes[_entry_safety_code(item)] += 1
        for group in prompt_entry_custom_groups(item):
            custom_groups[group] = custom_groups.get(group, 0) + 1
    return {
        "total": len(prompts),
        "enabled": len(enabled),
        "disabled": len(prompts) - len(enabled),
        "labels": labels,
        "sources": sources,
        "safety_codes": safety_codes,
        "custom_groups": dict(sorted(custom_groups.items())),
    }


def prompt_entry_source_code(item: dict[str, Any]) -> str:
    """Public wrapper used by the management UI."""

    return _entry_source_code(item)


def prompt_entry_safety_code(item: dict[str, Any]) -> str:
    """Public wrapper used by the management UI."""

    return _entry_safety_code(item)


def filter_prompt_entries(
    pool: dict[str, Any],
    *,
    source_codes: list[str] | tuple[str, ...] = SOURCE_CODES,
    safety_codes: list[str] | tuple[str, ...] = SAFETY_CODES,
    custom_groups: list[str] | tuple[str, ...] = (),
    keyword: str = "",
    include_disabled: bool = True,
) -> list[dict[str, Any]]:
    source_set = {str(code).upper() for code in source_codes}
    safety_set = {str(code).upper() for code in safety_codes}
    required_groups = {
        validate_custom_group_id(str(group)) for group in custom_groups
    }
    folded_keyword = str(keyword or "").strip().casefold()
    result: list[dict[str, Any]] = []
    for item in pool.get("prompts", []):
        if not isinstance(item, dict):
            continue
        if not include_disabled and not bool(item.get("enabled", True)):
            continue
        if _entry_source_code(item) not in source_set:
            continue
        if _entry_safety_code(item) not in safety_set:
            continue
        if not required_groups.issubset(set(prompt_entry_custom_groups(item))):
            continue
        if folded_keyword:
            searchable = "\n".join(
                (
                    str(item.get("id", "")),
                    str(item.get("name", "")),
                    str(item.get("prompt", "")),
                    " ".join(str(value) for value in item.get("categories", [])),
                )
            ).casefold()
            if folded_keyword not in searchable:
                continue
        result.append(item)
    return result


def get_prompt_entry(pool: dict[str, Any], prompt_id: str) -> dict[str, Any]:
    wanted = str(prompt_id or "").strip().casefold()
    for item in pool.get("prompts", []):
        if isinstance(item, dict) and str(item.get("id", "")).casefold() == wanted:
            return item
    raise WorkflowError(f"找不到提示词条目：{prompt_id}")


def _prompt_content_hash(prompt: str) -> str:
    normalized = re.sub(r"\s+", " ", str(prompt).strip()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _source_group_name(code: str) -> str:
    return next(
        (name for name, value in SOURCE_NAME_TO_CODE.items() if value == code),
        "basic",
    )


def _validate_management_codes(source_code: str, safety_code: str) -> tuple[str, str]:
    source = str(source_code).strip().upper()
    safety = str(safety_code).strip().upper()
    if source not in MANAGEABLE_SOURCE_CODES:
        raise WorkflowError(f"来源组必须是 {'/'.join(MANAGEABLE_SOURCE_CODES)}。")
    if safety not in SAFETY_CODES:
        raise WorkflowError(f"级别组必须是 {'/'.join(SAFETY_CODES)}。")
    return source, safety


def _backup_pool(path: Path) -> Path:
    backup_dir = path.parent / "prompt_pool_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = backup_dir / f"{path.stem}_{stamp}.json"
    shutil.copy2(path, backup)
    return backup


def save_prompt_pool(path: Path, pool: dict[str, Any], *, make_backup: bool = True) -> Path | None:
    load_prompt_pool(path)
    backup = _backup_pool(path) if make_backup else None
    _write_json_atomic(path, pool)
    load_prompt_pool(path)
    return backup


def add_prompt_entry(
    path: Path,
    *,
    prompt: str,
    source_code: str,
    safety_code: str,
    name: str = "",
) -> tuple[dict[str, Any], Path | None]:
    text = str(prompt or "").strip(" ,\n\t")
    if not text:
        raise WorkflowError("提示词内容不能为空。")
    source, safety = _validate_management_codes(source_code, safety_code)
    pool = load_prompt_pool(path)
    prompt_id = (
        f"custom-{datetime.now().strftime('%Y%m%d-%H%M%S')}-"
        f"{secrets.token_hex(3)}"
    )
    entry = {
        "id": prompt_id,
        "name": str(name or "").strip() or f"自定义提示词 {prompt_id}",
        "enabled": True,
        "weight": 1,
        "prompt": text,
        "prompt_position": "suffix",
        "categories": [],
        "safety_level": CODE_TO_SAFETY_NAME[safety],
        "safety_code": safety,
        "source_group": _source_group_name(source),
        "source_code": source,
        "content_hash": _prompt_content_hash(text),
        "source": {"source_collection": "AstrBot self-service"},
    }
    pool["prompts"].append(entry)
    return entry, save_prompt_pool(path, pool)


def update_prompt_entry(
    path: Path,
    prompt_id: str,
    *,
    prompt: str | None = None,
    source_code: str | None = None,
    safety_code: str | None = None,
    enabled: bool | None = None,
) -> tuple[dict[str, Any], Path | None]:
    pool = load_prompt_pool(path)
    entry = get_prompt_entry(pool, prompt_id)
    source = source_code or _entry_source_code(entry)
    safety = safety_code or _entry_safety_code(entry)
    source, safety = _validate_management_codes(source, safety)
    if prompt is not None:
        text = str(prompt).strip(" ,\n\t")
        if not text:
            raise WorkflowError("提示词内容不能为空。")
        entry["prompt"] = text
        entry["content_hash"] = _prompt_content_hash(text)
    entry["source_code"] = source
    entry["source_group"] = _source_group_name(source)
    entry["safety_code"] = safety
    entry["safety_level"] = CODE_TO_SAFETY_NAME[safety]
    if enabled is not None:
        entry["enabled"] = bool(enabled)
    return entry, save_prompt_pool(path, pool)


def delete_prompt_entry(
    path: Path,
    trash_path: Path,
    prompt_id: str,
    *,
    actor: str = "",
) -> tuple[dict[str, Any], Path | None]:
    pool = load_prompt_pool(path)
    entry = get_prompt_entry(pool, prompt_id)
    pool["prompts"] = [item for item in pool["prompts"] if item is not entry]
    deleted_ids = {
        str(value).strip()
        for value in pool.get("deleted_prompt_ids", [])
        if str(value).strip()
    }
    deleted_ids.add(str(entry["id"]))
    pool["deleted_prompt_ids"] = sorted(deleted_ids)
    backup = save_prompt_pool(path, pool)

    trash_path.parent.mkdir(parents=True, exist_ok=True)
    if trash_path.is_file():
        trash = _read_json(trash_path)
    else:
        trash = {"version": 1, "deleted": []}
    deleted = trash.setdefault("deleted", [])
    deleted.append(
        {
            "deleted_at": datetime.now().isoformat(timespec="seconds"),
            "actor": str(actor),
            "entry": entry,
        }
    )
    _write_json_atomic(trash_path, trash)
    return entry, backup


def import_prompt_entries(
    path: Path,
    import_path: Path,
) -> tuple[int, int, Path | None]:
    if not import_path.is_file():
        raise WorkflowError(f"导入文件不存在：{import_path}")
    try:
        with import_path.open("r", encoding="utf-8-sig") as file:
            incoming = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"无法读取导入 JSON：{exc}") from exc
    if isinstance(incoming, dict):
        records = incoming.get("prompts")
    elif isinstance(incoming, list):
        records = incoming
    else:
        records = None
    if not isinstance(records, list):
        raise WorkflowError("导入 JSON 必须是数组，或包含 prompts 数组的对象。")

    pool = load_prompt_pool(path)
    existing_ids = {str(item.get("id", "")) for item in pool["prompts"]}
    added = 0
    skipped = 0
    for raw in records:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        prompt = str(raw.get("prompt", "")).strip(" ,\n\t")
        if not prompt:
            skipped += 1
            continue
        source, safety = _validate_management_codes(
            str(raw.get("source_code", "B")),
            str(raw.get("safety_code", "N")),
        )
        prompt_id = str(raw.get("id", "")).strip()
        if not prompt_id or prompt_id in existing_ids:
            prompt_id = (
                f"import-{datetime.now().strftime('%Y%m%d-%H%M%S')}-"
                f"{secrets.token_hex(4)}"
            )
        entry = dict(raw)
        entry.update(
            {
                "id": prompt_id,
                "name": str(raw.get("name", "")).strip() or f"导入提示词 {prompt_id}",
                "enabled": bool(raw.get("enabled", True)),
                "weight": max(1, int(raw.get("weight", 1) or 1)),
                "prompt": prompt,
                "prompt_position": "suffix",
                "safety_level": CODE_TO_SAFETY_NAME[safety],
                "safety_code": safety,
                "source_group": _source_group_name(source),
                "source_code": source,
                "content_hash": _prompt_content_hash(prompt),
            }
        )
        pool["prompts"].append(entry)
        existing_ids.add(prompt_id)
        added += 1
    if not added:
        return 0, skipped, None
    return added, skipped, save_prompt_pool(path, pool)


def export_prompt_entries(
    target: Path,
    entries: list[dict[str, Any]],
    *,
    selector: str = "",
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "selector": selector,
        "count": len(entries),
        "prompts": entries,
    }
    _write_json_atomic(target, payload)
    return target
