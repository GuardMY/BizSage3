"""Request and response schemas for access control."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.response_models import ShanghaiTimeResponseModel


class LoginRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)


class AuthSession(ShanghaiTimeResponseModel):
    role: Literal["admin", "user"]
    expires_at: datetime


class CreateTemporaryTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    expires_in_hours: int = Field(default=24, ge=1, le=24 * 30)


class TemporaryTokenResponse(ShanghaiTimeResponseModel):
    id: str
    name: str
    token_prefix: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    status: Literal["active", "expired", "revoked"]


class CreatedTemporaryTokenResponse(TemporaryTokenResponse):
    token: str
