"""Integration tests for administrator and temporary-token access control."""

import hashlib
from datetime import timedelta

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import get_current_principal
from app.api import router as api_router
from app.auth_api import router as auth_router
from app.config import settings
from app.db import get_session as get_db_session
from app.models import Base, DiagnosisSession, Report, TemporaryAccessToken


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
    app.include_router(
        api_router,
        dependencies=[Depends(get_current_principal)],
    )

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
async def test_token_must_be_revoked_before_deletion(auth_test_app):
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
            assert (
                await user.post(
                    f"/api/v1/admin/tokens/{token_data['id']}/revoke"
                )
            ).status_code == 403
            assert (
                await user.delete(f"/api/v1/admin/tokens/{token_data['id']}")
            ).status_code == 403

            not_revoked = await admin.delete(
                f"/api/v1/admin/tokens/{token_data['id']}"
            )
            assert not_revoked.status_code == 409

            revoked = await admin.post(
                f"/api/v1/admin/tokens/{token_data['id']}/revoke"
            )
            assert revoked.status_code == 204
            assert (await user.get("/protected")).status_code == 401

            listed = await admin.get("/api/v1/admin/tokens")
            assert listed.status_code == 200
            assert listed.json()[0]["status"] == "revoked"

            deleted = await admin.delete(
                f"/api/v1/admin/tokens/{token_data['id']}"
            )
            assert deleted.status_code == 204
            assert (await admin.get("/api/v1/admin/tokens")).json() == []
            assert (
                await admin.delete(f"/api/v1/admin/tokens/{token_data['id']}")
            ).status_code == 404


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


@pytest.mark.asyncio
async def test_sessions_are_isolated_by_temporary_token(
    auth_test_app,
    monkeypatch,
):
    app, factory = auth_test_app
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as admin:
        await admin.post(
            "/api/v1/auth/login",
            json={"token": settings.admin_token},
        )
        token_a = (
            await admin.post(
                "/api/v1/admin/tokens",
                json={"name": "用户 A", "expires_in_hours": 24},
            )
        ).json()
        token_b = (
            await admin.post(
                "/api/v1/admin/tokens",
                json={"name": "用户 B", "expires_in_hours": 24},
            )
        ).json()
        admin_session = (await admin.post("/api/v1/sessions")).json()

    async with AsyncClient(transport=transport, base_url="http://test") as user_a:
        await user_a.post(
            "/api/v1/auth/login",
            json={"token": token_a["token"]},
        )
        session_a = (await user_a.post("/api/v1/sessions")).json()

    async with AsyncClient(transport=transport, base_url="http://test") as user_b:
        await user_b.post(
            "/api/v1/auth/login",
            json={"token": token_b["token"]},
        )
        session_b = (await user_b.post("/api/v1/sessions")).json()

    async with factory() as db:
        stored_admin = await db.get(DiagnosisSession, admin_session["id"])
        stored_a = await db.get(DiagnosisSession, session_a["id"])
        stored_b = await db.get(DiagnosisSession, session_b["id"])
        assert stored_admin.owner_token_id is None
        assert stored_a.owner_token_id == token_a["id"]
        assert stored_b.owner_token_id == token_b["id"]

        report_a = Report(
            id="report-a",
            session_id=session_a["id"],
            markdown="# A 的报告",
            diagnosis="{}",
        )
        db.add(report_a)
        await db.commit()

    async with AsyncClient(transport=transport, base_url="http://test") as user_a:
        await user_a.post(
            "/api/v1/auth/login",
            json={"token": token_a["token"]},
        )
        listed = (await user_a.get("/api/v1/sessions")).json()
        assert {session["id"] for session in listed} == {session_a["id"]}
        assert (
            await user_a.get(
                f"/api/v1/sessions/{session_a['id']}/reports/report-a"
            )
        ).status_code == 200

    cancelled = []

    async def record_cancel(session_id: str) -> None:
        cancelled.append(session_id)

    monkeypatch.setattr("app.api.report_task_manager.cancel", record_cancel)

    async with AsyncClient(transport=transport, base_url="http://test") as user_b:
        await user_b.post(
            "/api/v1/auth/login",
            json={"token": token_b["token"]},
        )
        listed = (await user_b.get("/api/v1/sessions")).json()
        assert {session["id"] for session in listed} == {session_b["id"]}

        inaccessible_requests = [
            await user_b.get(f"/api/v1/sessions/{session_a['id']}"),
            await user_b.delete(f"/api/v1/sessions/{session_a['id']}"),
            await user_b.post(
                f"/api/v1/sessions/{session_a['id']}/messages",
                json={
                    "client_message_id": "cross-token-message",
                    "content": "不应写入",
                },
            ),
            await user_b.post(
                f"/api/v1/sessions/{session_a['id']}/reports"
            ),
            await user_b.get(
                f"/api/v1/sessions/{session_a['id']}/reports"
            ),
            await user_b.get(
                f"/api/v1/sessions/{session_a['id']}/reports/report-a"
            ),
            await user_b.get(
                f"/api/v1/sessions/{session_a['id']}/reports/report-a/download"
            ),
            await user_b.get(
                f"/api/v1/sessions/{session_a['id']}/report"
            ),
            await user_b.get(
                f"/api/v1/sessions/{session_a['id']}/report/download"
            ),
        ]
        assert {response.status_code for response in inaccessible_requests} == {404}
        assert cancelled == []

    async with AsyncClient(transport=transport, base_url="http://test") as admin:
        await admin.post(
            "/api/v1/auth/login",
            json={"token": settings.admin_token},
        )
        listed = (await admin.get("/api/v1/sessions")).json()
        assert {session["id"] for session in listed} == {
            admin_session["id"],
            session_a["id"],
            session_b["id"],
        }
        assert (
            await admin.get(
                f"/api/v1/sessions/{session_a['id']}/reports/report-a"
            )
        ).status_code == 200

        assert (
            await admin.post(
                f"/api/v1/admin/tokens/{token_a['id']}/revoke"
            )
        ).status_code == 204
        assert (
            await admin.delete(
                f"/api/v1/admin/tokens/{token_a['id']}"
            )
        ).status_code == 204

    async with factory() as db:
        stored_a = await db.get(DiagnosisSession, session_a["id"])
        assert stored_a.owner_token_id is None

    async with AsyncClient(transport=transport, base_url="http://test") as user_b:
        await user_b.post(
            "/api/v1/auth/login",
            json={"token": token_b["token"]},
        )
        assert (
            await user_b.get(f"/api/v1/sessions/{session_a['id']}")
        ).status_code == 404
