"""Integration tests for administrator and temporary-token access control."""

import hashlib
from datetime import timedelta

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import get_current_principal
from app.auth_api import router as auth_router
from app.config import settings
from app.db import get_session as get_db_session
from app.models import Base, TemporaryAccessToken


@pytest.fixture
async def auth_test_app(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "test-admin-token-with-enough-entropy")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with factory() as session:
            yield session

    app = FastAPI()
    app.dependency_overrides[get_db_session] = override_session
    app.include_router(auth_router)

    @app.get("/protected", dependencies=[Depends(get_current_principal)])
    async def protected():
        return {"ok": True}

    yield app, factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_admin_can_create_a_hashed_temporary_token(auth_test_app):
    app, factory = auth_test_app
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        invalid = await client.post("/api/v1/auth/login", json={"token": "wrong"})
        assert invalid.status_code == 401

        login = await client.post(
            "/api/v1/auth/login",
            json={"token": settings.admin_token},
        )
        assert login.status_code == 200
        assert login.json()["role"] == "admin"
        assert "httponly" in login.headers["set-cookie"].lower()

        created = await client.post(
            "/api/v1/admin/tokens",
            json={"name": "演示访问", "expires_in_hours": 24},
        )
        assert created.status_code == 201
        raw_token = created.json()["token"]
        assert raw_token.startswith("bst_")

    async with factory() as db:
        stored = (await db.execute(select(TemporaryAccessToken))).scalar_one()
        assert stored.token_hash == hashlib.sha256(raw_token.encode()).hexdigest()
        assert raw_token not in stored.token_hash


@pytest.mark.asyncio
async def test_revoking_token_invalidates_an_existing_session(auth_test_app):
    app, _ = auth_test_app
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as admin:
        await admin.post("/api/v1/auth/login", json={"token": settings.admin_token})
        created = await admin.post(
            "/api/v1/admin/tokens",
            json={"name": "临时用户", "expires_in_hours": 1},
        )
        token_data = created.json()

        async with AsyncClient(transport=transport, base_url="http://test") as user:
            login = await user.post(
                "/api/v1/auth/login",
                json={"token": token_data["token"]},
            )
            assert login.status_code == 200
            assert login.json()["role"] == "user"
            assert (await user.get("/protected")).status_code == 200
            assert (await user.get("/api/v1/admin/tokens")).status_code == 403

            revoked = await admin.delete(
                f"/api/v1/admin/tokens/{token_data['id']}"
            )
            assert revoked.status_code == 204
            assert (await user.get("/protected")).status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_the_session_cookie(auth_test_app):
    app, _ = auth_test_app
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/v1/auth/login", json={"token": settings.admin_token})
        assert (await client.get("/protected")).status_code == 200
        assert (await client.post("/api/v1/auth/logout")).status_code == 204
        assert (await client.get("/protected")).status_code == 401


@pytest.mark.asyncio
async def test_expired_temporary_token_cannot_log_in(auth_test_app):
    app, factory = auth_test_app
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as admin:
        await admin.post("/api/v1/auth/login", json={"token": settings.admin_token})
        created = await admin.post(
            "/api/v1/admin/tokens",
            json={"name": "过期令牌", "expires_in_hours": 1},
        )

    async with factory() as db:
        token = await db.get(TemporaryAccessToken, created.json()["id"])
        token.expires_at = token.created_at - timedelta(seconds=1)
        await db.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as user:
        response = await user.post(
            "/api/v1/auth/login",
            json={"token": created.json()["token"]},
        )
        assert response.status_code == 401
