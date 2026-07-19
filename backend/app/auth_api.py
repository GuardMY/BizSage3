"""Authentication and administrator token-management endpoints."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, create_session_cookie, get_current_principal, require_admin
from app.auth_schemas import (
    AuthSession,
    CreatedTemporaryTokenResponse,
    CreateTemporaryTokenRequest,
    LoginRequest,
    TemporaryTokenResponse,
)
from app.config import settings
from app.db import get_session as get_db_session
from app.models import DiagnosisSession, TemporaryAccessToken
from app.response_models import PaginatedResponse


router = APIRouter(prefix="/api/v1")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_status(token: TemporaryAccessToken) -> str:
    if token.revoked_at is not None:
        return "revoked"
    if token.expires_at <= _utcnow():
        return "expired"
    return "active"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc)


def _serialize_token(
    token: TemporaryAccessToken,
    *,
    raw_token: str | None = None,
) -> TemporaryTokenResponse | CreatedTemporaryTokenResponse:
    values = {
        "id": token.id,
        "name": token.name,
        "token_prefix": token.token_prefix,
        "created_at": _as_utc(token.created_at),
        "expires_at": _as_utc(token.expires_at),
        "last_used_at": _as_utc(token.last_used_at) if token.last_used_at else None,
        "revoked_at": _as_utc(token.revoked_at) if token.revoked_at else None,
        "status": _token_status(token),
    }
    if raw_token is not None:
        return CreatedTemporaryTokenResponse(**values, token=raw_token)
    return TemporaryTokenResponse(**values)


def _set_session_cookie(response: Response, principal: Principal) -> None:
    max_age = max(0, int((principal.expires_at - _utcnow()).total_seconds()))
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=create_session_cookie(principal),
        max_age=max_age,
        expires=_as_utc(principal.expires_at),
        path="/",
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
    )


@router.post("/auth/login", response_model=AuthSession)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
):
    if not settings.admin_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="服务端尚未配置 ADMIN_TOKEN",
        )

    submitted = body.token.strip()
    now = _utcnow()
    session_limit = now + timedelta(hours=settings.auth_session_hours)

    if hmac.compare_digest(submitted, settings.admin_token):
        principal = Principal(role="admin", expires_at=session_limit)
    else:
        result = await db.execute(
            select(TemporaryAccessToken).where(
                TemporaryAccessToken.token_hash == _token_hash(submitted)
            )
        )
        temporary_token = result.scalar_one_or_none()
        if (
            temporary_token is None
            or temporary_token.revoked_at is not None
            or temporary_token.expires_at <= now
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="访问令牌无效或已过期",
            )

        temporary_token.last_used_at = now
        await db.commit()
        principal = Principal(
            role="user",
            expires_at=min(temporary_token.expires_at, session_limit),
            token_id=temporary_token.id,
        )

    _set_session_cookie(response, principal)
    return AuthSession(role=principal.role, expires_at=_as_utc(principal.expires_at))


@router.post("/auth/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.get("/auth/me", response_model=AuthSession)
async def current_session(
    principal: Principal = Depends(get_current_principal),
):
    return AuthSession(role=principal.role, expires_at=_as_utc(principal.expires_at))


@router.get(
    "/admin/tokens",
    response_model=PaginatedResponse[TemporaryTokenResponse],
    dependencies=[Depends(require_admin)],
)
async def list_temporary_tokens(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    db: AsyncSession = Depends(get_db_session),
):
    total = await db.scalar(select(func.count()).select_from(TemporaryAccessToken))
    result = await db.execute(
        select(TemporaryAccessToken)
        .order_by(TemporaryAccessToken.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return PaginatedResponse(
        items=[_serialize_token(token) for token in result.scalars().all()],
        page=page,
        page_size=page_size,
        total=total or 0,
    )


@router.post(
    "/admin/tokens",
    response_model=CreatedTemporaryTokenResponse,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
async def create_temporary_token(
    body: CreateTemporaryTokenRequest,
    db: AsyncSession = Depends(get_db_session),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="令牌名称不能为空")

    raw_token = f"bst_{secrets.token_urlsafe(32)}"
    now = _utcnow()
    token = TemporaryAccessToken(
        name=name,
        token_hash=_token_hash(raw_token),
        token_prefix=raw_token[:12],
        created_at=now,
        expires_at=now + timedelta(hours=body.expires_in_hours),
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return _serialize_token(token, raw_token=raw_token)


@router.post(
    "/admin/tokens/{token_id}/revoke",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
async def revoke_temporary_token(
    token_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    token = await db.get(TemporaryAccessToken, token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="临时令牌不存在")
    if token.revoked_at is None:
        token.revoked_at = _utcnow()
        await db.commit()


@router.delete(
    "/admin/tokens/{token_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
async def delete_temporary_token(
    token_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    token = await db.get(TemporaryAccessToken, token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="临时令牌不存在")
    if token.revoked_at is None:
        raise HTTPException(status_code=409, detail="请先撤销临时令牌后再删除")
    await db.execute(
        update(DiagnosisSession)
        .where(DiagnosisSession.owner_token_id == token_id)
        .values(owner_token_id=None)
    )
    await db.delete(token)
    await db.commit()
