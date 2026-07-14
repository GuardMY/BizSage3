"""Signed-cookie authentication and authorization dependencies."""

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session as get_db_session
from app.models import TemporaryAccessToken


@dataclass(frozen=True)
class Principal:
    role: Literal["admin", "user"]
    expires_at: datetime
    token_id: str | None = None


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _urlsafe_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _signing_key() -> bytes:
    if not settings.admin_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="服务端尚未配置 ADMIN_TOKEN",
        )
    return hashlib.sha256(
        f"bizsage-session:{settings.admin_token}".encode("utf-8")
    ).digest()


def create_session_cookie(principal: Principal) -> str:
    payload = {
        "role": principal.role,
        "exp": int(principal.expires_at.replace(tzinfo=timezone.utc).timestamp()),
    }
    if principal.token_id:
        payload["token_id"] = principal.token_id

    encoded = _urlsafe_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        _signing_key(), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded}.{_urlsafe_encode(signature)}"


def _decode_session_cookie(value: str) -> Principal | None:
    try:
        encoded, supplied_signature = value.split(".", 1)
        expected_signature = hmac.new(
            _signing_key(), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(
            expected_signature, _urlsafe_decode(supplied_signature)
        ):
            return None

        payload = json.loads(_urlsafe_decode(encoded))
        role = payload.get("role")
        expires_at = datetime.fromtimestamp(
            int(payload["exp"]), timezone.utc
        ).replace(tzinfo=None)
        token_id = payload.get("token_id")
        if role not in {"admin", "user"} or expires_at <= _utcnow():
            return None
        if role == "user" and not token_id:
            return None
        return Principal(role=role, expires_at=expires_at, token_id=token_id)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已失效，请重新登录",
        headers={"WWW-Authenticate": "Cookie"},
    )


async def get_current_principal(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> Principal:
    cookie = request.cookies.get(settings.auth_cookie_name)
    if not cookie:
        raise _unauthorized()

    principal = _decode_session_cookie(cookie)
    if principal is None:
        raise _unauthorized()

    if principal.role == "user":
        result = await db.execute(
            select(TemporaryAccessToken).where(
                TemporaryAccessToken.id == principal.token_id
            )
        )
        token = result.scalar_one_or_none()
        now = _utcnow()
        if token is None or token.revoked_at is not None or token.expires_at <= now:
            raise _unauthorized()

    return principal


async def require_admin(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    if principal.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return principal
