from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Any, Literal

from .config import Settings
from .repositories import RepositoryError, file_revision, read_json_object
from .schemas import (
    LiteUserCreateRequest,
    LiteUserIssueResponse,
    LiteUserListResponse,
    LiteUserSummary,
    LiteUserUpdateRequest,
    MutationResponse,
)
from .storage import (
    DuplicateResource,
    ResourceNotFound,
    move_to_trash,
    mutate_json,
)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _initialize() -> dict[str, Any]:
    return {"version": 1, "users": []}


def _users(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("users")
    if not isinstance(raw, list):
        raise RepositoryError("Lite user registry must contain a users list")
    return [item for item in raw if isinstance(item, dict)]


def _find(data: dict[str, Any], qq: str) -> dict[str, Any]:
    for item in _users(data):
        if str(item.get("qq", "")).strip() == qq:
            return item
    raise ResourceNotFound(f"Lite user not found: {qq}")


def _summary(item: dict[str, Any]) -> LiteUserSummary:
    return LiteUserSummary(
        id=str(item.get("id", "")),
        qq=str(item.get("qq", "")),
        label=str(item.get("label", "")),
        allow_group=bool(item.get("allow_group", True)),
        enabled=bool(item.get("enabled", True)),
        created_at=item.get("created_at"),
        updated_at=item.get("updated_at"),
    )


def _token() -> str:
    return f"aah_u_{secrets.token_urlsafe(32)}"


def list_lite_users(settings: Settings) -> LiteUserListResponse:
    path = settings.lite_users_path
    revision = file_revision(path, "lite_users").revision or "missing"
    if not path.is_file():
        return LiteUserListResponse(items=[], revision=revision)
    data = read_json_object(path)
    items = sorted((_summary(item) for item in _users(data)), key=lambda item: item.qq)
    return LiteUserListResponse(items=items, revision=revision)


def _issue_result(
    action: Literal["created", "rotated"],
    result: tuple[dict[str, Any], str],
    revision: str,
    backup: Any,
) -> LiteUserIssueResponse:
    item, token = result
    return LiteUserIssueResponse(
        action=action,
        user=_summary(item),
        token=token,
        revision=revision,
        backup=str(backup) if backup else None,
    )


def create_lite_user(
    settings: Settings,
    payload: LiteUserCreateRequest,
    expected_revision: str,
    actor: str,
) -> LiteUserIssueResponse:
    token = _token()
    timestamp = _now()

    def mutate(data: dict[str, Any]) -> tuple[dict[str, Any], str]:
        users = _users(data)
        if any(str(item.get("qq", "")).strip() == payload.qq for item in users):
            raise DuplicateResource(f"Lite user already exists: {payload.qq}")
        item = {
            "id": f"qq-{payload.qq}",
            "label": payload.label.strip() or f"QQ {payload.qq}",
            "qq": payload.qq,
            "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
            "allow_group": payload.allow_group,
            "enabled": True,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        data["version"] = 1
        data["users"].append(item)
        return item, token

    result, revision, backup = mutate_json(
        path=settings.lite_users_path,
        resource="lite_users",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="create",
        target=payload.qq,
        mutate=mutate,
        initialize=_initialize,
    )
    return _issue_result("created", result, revision, backup)


def update_lite_user(
    settings: Settings,
    qq: str,
    payload: LiteUserUpdateRequest,
    expected_revision: str,
    actor: str,
) -> MutationResponse:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise RepositoryError("at least one Lite user field must be supplied")

    def mutate(data: dict[str, Any]) -> None:
        item = _find(data, qq)
        if "label" in changes:
            item["label"] = str(changes["label"]).strip()
        if "allow_group" in changes:
            item["allow_group"] = bool(changes["allow_group"])
        if "enabled" in changes:
            item["enabled"] = bool(changes["enabled"])
        item["updated_at"] = _now()

    _, revision, backup = mutate_json(
        path=settings.lite_users_path,
        resource="lite_users",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="update",
        target=qq,
        mutate=mutate,
    )
    return MutationResponse(
        action="updated",
        resource=f"lite-user:{qq}",
        revision=revision,
        backup=str(backup) if backup else None,
    )


def rotate_lite_user_token(
    settings: Settings,
    qq: str,
    expected_revision: str,
    actor: str,
) -> LiteUserIssueResponse:
    token = _token()

    def mutate(data: dict[str, Any]) -> tuple[dict[str, Any], str]:
        item = _find(data, qq)
        item["token_sha256"] = hashlib.sha256(token.encode("utf-8")).hexdigest()
        item["enabled"] = True
        item["updated_at"] = _now()
        return item, token

    result, revision, backup = mutate_json(
        path=settings.lite_users_path,
        resource="lite_users",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="rotate-token",
        target=qq,
        mutate=mutate,
    )
    return _issue_result("rotated", result, revision, backup)


def delete_lite_user(
    settings: Settings,
    qq: str,
    expected_revision: str,
    actor: str,
) -> MutationResponse:
    def mutate(data: dict[str, Any]) -> None:
        item = _find(data, qq)
        move_to_trash(settings.trash_dir, "lite_users", qq, item)
        data["users"].remove(item)

    _, revision, backup = mutate_json(
        path=settings.lite_users_path,
        resource="lite_users",
        expected_revision=expected_revision,
        backup_root=settings.backup_dir,
        audit_path=settings.audit_log_path,
        actor=actor,
        action="delete",
        target=qq,
        mutate=mutate,
    )
    return MutationResponse(
        action="deleted",
        resource=f"lite-user:{qq}",
        revision=revision,
        backup=str(backup) if backup else None,
    )
