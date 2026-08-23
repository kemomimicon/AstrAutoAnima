from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Literal
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .lite_users import LiteUserRegistryError, authenticate_lite_user


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    role: Literal["admin", "legacy_lite", "user"]
    subject: str
    label: str = ""
    qq: str = ""
    allow_group: bool = True

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def chat_username(self) -> str:
        return f"hub_{self.role}_{self.subject}"[:100]


SYSTEM_ADMIN = AuthPrincipal(role="admin", subject="system")


def _matches(configured: str, supplied: str) -> bool:
    return bool(configured) and secrets.compare_digest(configured, supplied)


async def require_admin(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
) -> AuthPrincipal:
    """Validate the workstation administrator token in constant time."""

    configured = request.app.state.settings.admin_token
    supplied = credentials.credentials if credentials else ""
    if not _matches(configured, supplied):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing administrator token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthPrincipal(role="admin", subject="administrator", label="管理员")


async def require_reader(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
) -> AuthPrincipal:
    """Allow the read-only Lite token or the administrator token."""

    settings = request.app.state.settings
    supplied = credentials.credentials if credentials else ""
    if _matches(settings.admin_token, supplied):
        return AuthPrincipal(role="admin", subject="administrator", label="管理员")
    if _matches(settings.lite_token, supplied):
        if settings.legacy_lite_qq:
            return AuthPrincipal(
                role="user",
                subject="legacy-owner",
                label="令牌所有者",
                qq=settings.legacy_lite_qq,
                allow_group=True,
            )
        return AuthPrincipal(role="legacy_lite", subject="shared", label="共享用户端")
    try:
        user = authenticate_lite_user(settings.lite_users_path, supplied)
    except LiteUserRegistryError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if user is not None:
        return AuthPrincipal(
            role="user",
            subject=user.id,
            label=user.label,
            qq=user.qq,
            allow_group=user.allow_group,
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing client token",
        headers={"WWW-Authenticate": "Bearer"},
    )
