from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from .auth import AuthPrincipal
from .config import Settings
from .repositories import RepositoryError, file_revision, read_json_object
from .schemas import PromptLikeResponse
from .storage import RevisionConflict, mutate_json


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


def _kp_entry(path: Path, prompt_id: str) -> dict[str, Any]:
    data = read_json_object(path)
    for item in data.get("prompts", []):
        if isinstance(item, dict) and str(item.get("id", "")) == prompt_id:
            return item
    raise RepositoryError(f"prompt not found: {prompt_id}")


def _saved_id(principal: AuthPrincipal, prompt_id: str) -> str:
    owner = hashlib.sha256(principal.subject.encode("utf-8")).hexdigest()[:10]
    source = prompt_id.removeprefix("kp-")
    return f"liked-{owner}-{source}"[:180]


def promote_k_prompt(
    settings: Settings,
    prompt_id: str,
    principal: AuthPrincipal,
) -> PromptLikeResponse:
    if principal.role == "legacy_lite":
        raise RepositoryError("共享用户令牌无法保存点赞，请使用绑定 QQ 的个人令牌")
    source = _kp_entry(ensure_kp_pool(settings) if prompt_id.startswith("kp-") else settings.prompt_pool_path, prompt_id)
    if not source.get("enabled", True):
        raise RepositoryError("已停用的条目不能新增收藏")
    if source.get("liked_by") and source["liked_by"] != principal.subject:
        raise RepositoryError("无权收藏其他用户的个人条目")
    saved_id = _saved_id(principal, prompt_id)
    already_liked = False

    def mutate(data: dict[str, Any]) -> None:
        nonlocal already_liked
        prompts = data.get("prompts")
        if not isinstance(prompts, list):
            raise RepositoryError("prompt pool must contain a prompts list")
        if any(
            isinstance(item, dict) and str(item.get("id", "")) == saved_id
            for item in prompts
        ):
            already_liked = True
            return
        copied = dict(source)
        copied.update(
            {
                "id": saved_id,
                "name": f"P 收藏｜{source.get('name', prompt_id)}",
                "source_group": "liked",
                "source_code": "P",
                "categories": list(
                    dict.fromkeys(
                        [
                            "liked",
                            *[str(value) for value in source.get("categories", [])],
                        ]
                    )
                ),
                "liked_from": prompt_id,
                "liked_by": principal.subject,
            }
        )
        prompts.append(copied)

    for attempt in range(2):
        revision = file_revision(settings.prompt_pool_path, "prompts").revision
        if not revision:
            raise RepositoryError("main prompt pool does not exist")
        try:
            _, new_revision, _ = mutate_json(
                path=settings.prompt_pool_path,
                resource="prompts",
                expected_revision=revision,
                backup_root=settings.backup_dir,
                audit_path=settings.audit_log_path,
                actor=f"{principal.role}:{principal.subject}",
                action="like_k_prompt",
                target=prompt_id,
                mutate=mutate,
            )
            return PromptLikeResponse(
                action="already_liked" if already_liked else "liked",
                prompt_id=prompt_id,
                saved_prompt_id=saved_id,
                revision=new_revision,
            )
        except RevisionConflict:
            if attempt:
                raise
            already_liked = False
    raise RepositoryError("cannot save liked prompt")


def remove_prompt_favorite(settings: Settings, prompt_id: str, principal: AuthPrincipal):
    def apply(data):
        data["prompts"] = [row for row in data.get("prompts", [])
            if not (isinstance(row, dict) and row.get("liked_by") == principal.subject
                    and (row.get("id") == prompt_id or row.get("liked_from") == prompt_id))]
    mutate_json(path=settings.prompt_pool_path, resource="prompts",
        expected_revision=file_revision(settings.prompt_pool_path, "prompts").revision,
        backup_root=settings.backup_dir, audit_path=settings.audit_log_path,
        actor=f"{principal.role}:{principal.subject}", action="unfavorite", target=prompt_id, mutate=apply)
    return {"removed": True}
