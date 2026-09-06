from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .repositories import RepositoryError, file_revision, read_json_object


SOURCE_NAMES = {
    "B": "basic",
    "G": "generate",
    "D": "discord",
    "C": "codex",
    "R": "reverse",
    "P": "liked",
}
SAFETY_NAMES = {"N": "normal", "H": "nsfw", "S": "sexual"}


class RevisionConflict(RepositoryError):
    def __init__(self, current_revision: str) -> None:
        super().__init__("resource changed since it was loaded")
        self.current_revision = current_revision


class ResourceNotFound(RepositoryError):
    pass


class DuplicateResource(RepositoryError):
    pass


_write_lock = threading.RLock()


def content_hash(prompt: str) -> str:
    normalized = " ".join(prompt.strip().casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def clean_categories(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw).strip()
        folded = value.casefold()
        if value and folded not in seen:
            result.append(value[:100])
            seen.add(folded)
    return result


def new_prompt_id(prefix: str = "hub") -> str:
    return (
        f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-"
        f"{secrets.token_hex(3)}"
    )


def prompt_entry(payload: dict[str, Any], *, prompt_id: str | None = None) -> dict[str, Any]:
    prompt = str(payload.get("prompt", "")).strip(" ,\n\t")
    if not prompt:
        raise RepositoryError("prompt must not be empty")
    source = str(payload.get("source_code", "B")).upper()
    safety = str(payload.get("safety_code", "N")).upper()
    if source not in SOURCE_NAMES or safety not in SAFETY_NAMES:
        raise RepositoryError("invalid source or safety code")
    identifier = prompt_id or new_prompt_id()
    return {
        "id": identifier,
        "name": str(payload.get("name", "")).strip() or f"Hub 提示词 {identifier}",
        "enabled": bool(payload.get("enabled", True)),
        "weight": int(payload.get("weight", 1)),
        "prompt": prompt,
        "prompt_position": "suffix",
        "categories": clean_categories(payload.get("categories", [])),
        "safety_level": SAFETY_NAMES[safety],
        "safety_matches": [],
        "duplicate_of": None,
        "content_hash": content_hash(prompt),
        "source": {"source_collection": "AstrAutoAnima Hub"},
        "source_group": SOURCE_NAMES[source],
        "source_code": source,
        "safety_code": safety,
    }


def _recalculate_prompt_metadata(pool: dict[str, Any]) -> None:
    prompts = [item for item in pool.get("prompts", []) if isinstance(item, dict)]
    source_counts = {code: 0 for code in SOURCE_NAMES}
    safety_counts = {code: 0 for code in SAFETY_NAMES}
    enabled_source_counts = {code: 0 for code in SOURCE_NAMES}
    enabled_safety_counts = {code: 0 for code in SAFETY_NAMES}
    enabled_total = 0
    for item in prompts:
        source = str(item.get("source_code", "B")).upper()
        safety = str(item.get("safety_code", "N")).upper()
        enabled = bool(item.get("enabled", True))
        if source in source_counts:
            source_counts[source] += 1
            if enabled:
                enabled_source_counts[source] += 1
        if safety in safety_counts:
            safety_counts[safety] += 1
            if enabled:
                enabled_safety_counts[safety] += 1
        if enabled:
            enabled_total += 1
    pool["stats"] = {
        "raw_total": len(prompts),
        "enabled_total": enabled_total,
        "disabled_total": len(prompts) - enabled_total,
        "source_counts": source_counts,
        "enabled_source_counts": enabled_source_counts,
        "safety_counts": safety_counts,
        "enabled_safety_counts": enabled_safety_counts,
    }
    revision = pool.get("catalog_revision", 0)
    try:
        pool["catalog_revision"] = int(revision) + 1
    except (TypeError, ValueError):
        pool["catalog_revision"] = int(datetime.now().strftime("%Y%m%d%H%M%S"))
    pool["generated_on"] = datetime.now().date().isoformat()


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise RepositoryError(f"cannot write {path}: {exc}") from exc


def _backup(path: Path, backup_root: Path, resource: str) -> Path | None:
    if not path.is_file():
        return None
    target_dir = backup_root / resource
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = target_dir / f"{path.stem}_{stamp}.json"
    try:
        shutil.copy2(path, target)
    except OSError as exc:
        raise RepositoryError(f"cannot back up {path}: {exc}") from exc
    return target


def _append_audit(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        **record,
    }
    try:
        with path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
    except OSError as exc:
        raise RepositoryError(f"cannot append audit log: {exc}") from exc


def mutate_json(
    *,
    path: Path,
    resource: str,
    expected_revision: str,
    backup_root: Path,
    audit_path: Path,
    actor: str,
    action: str,
    target: str,
    mutate: Callable[[dict[str, Any]], Any],
    initialize: Callable[[], dict[str, Any]] | None = None,
) -> tuple[Any, str, Path | None]:
    if not expected_revision:
        raise RepositoryError("If-Match revision is required")
    with _write_lock:
        current = file_revision(path, resource).revision or "missing"
        if expected_revision != current:
            raise RevisionConflict(current)
        if path.is_file():
            data = read_json_object(path)
        elif initialize is not None:
            data = initialize()
        else:
            raise ResourceNotFound(f"resource does not exist: {path}")
        result = mutate(data)
        if resource == "prompts":
            _recalculate_prompt_metadata(data)
        backup = _backup(path, backup_root, resource)
        # AstrBot's QQ-side manager is a separate process and does not share
        # this lock. Recheck immediately before replacement so a concurrent QQ
        # write is rejected instead of being silently overwritten.
        latest = file_revision(path, resource).revision or "missing"
        if latest != current:
            raise RevisionConflict(latest)
        _write_json_atomic(path, data)
        new_revision = file_revision(path, resource).revision or "missing"
        try:
            _append_audit(
                audit_path,
                {
                    "actor": actor,
                    "action": action,
                    "resource": resource,
                    "target": target,
                    "before_revision": current,
                    "after_revision": new_revision,
                    "backup": str(backup) if backup else None,
                },
            )
        except RepositoryError:
            # The primary data has already been committed. Never roll it back by
            # overwriting a potentially newer file; report the audit failure.
            raise
        return result, new_revision, backup


def move_to_trash(trash_root: Path, resource: str, identifier: str, data: Any) -> Path:
    target_dir = trash_root / resource
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_identifier = "".join(
        value if value.isalnum() or value in {"-", "_"} else "_"
        for value in identifier
    )[:120]
    target = target_dir / (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_identifier}.json"
    )
    _write_json_atomic(target, {"deleted": data})
    return target
