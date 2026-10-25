"""Resolve catalog entries and save them to a separate personal collection."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .auth import AuthPrincipal
from .config import Settings
from .prompt_favorites import delete_favorite, save_favorite, source_safety_code
from .repositories import RepositoryError, read_json_object
from .schemas import PromptLikeResponse


def ensure_kp_pool(settings: Settings) -> Path:
    target = settings.kp_prompt_pool_path
    if target.is_file():
        return target
    bundled = settings.bundled_kp_prompt_pool_path
    if not bundled.is_file():
        raise RepositoryError(f"bundled KP prompt pool does not exist: {bundled}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.installing")
    try:
        shutil.copy2(bundled, temporary)
        temporary.replace(target)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise RepositoryError(f"cannot install KP prompt pool: {exc}") from exc
    return target


def _source_entry(path: Path, prompt_id: str) -> dict[str, Any]:
    data = read_json_object(path)
    for item in data.get("prompts", []):
        if isinstance(item, dict) and str(item.get("id", "")) == prompt_id:
            return item
    raise RepositoryError(f"prompt not found: {prompt_id}")


# Report resolution also reads the source catalog through this historical name.
_kp_entry = _source_entry


def promote_k_prompt(
    settings: Settings, prompt_id: str, principal: AuthPrincipal,
    *, addition: str = "", snapshot: dict[str, Any] | None = None,
) -> PromptLikeResponse:
    if snapshot is not None:
        if str(snapshot.get("id", "")) != prompt_id:
            raise RepositoryError("词库编号与任务快照不一致")
        source = {**snapshot, "safety_code": source_safety_code(snapshot, required=True)}
    else:
        source = _source_entry(
            ensure_kp_pool(settings) if prompt_id.startswith("kp-") else settings.prompt_pool_path,
            prompt_id,
        )
    if not source.get("enabled", True):
        raise RepositoryError("已停用的条目不能新增收藏")
    if source.get("liked_by") and source["liked_by"] != principal.subject:
        raise RepositoryError("无权收藏其他用户的个人条目")
    return save_favorite(settings.prompt_favorites_path, principal, source, addition=addition)


def remove_prompt_favorite(settings: Settings, prompt_id: str, principal: AuthPrincipal):
    return delete_favorite(settings.prompt_favorites_path, principal, prompt_id)
