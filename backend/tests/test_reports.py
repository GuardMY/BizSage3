"""Tests for background report generation and report history."""

from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import start_report_generation
from app.models import Base
from app.repository import SessionRepository
from app.services.report_service import ReportContext, ReportTaskManager


@pytest.fixture
async def report_db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_report_generation_slot_is_atomic(report_db_factory):
    async with report_db_factory() as db:
        repo = SessionRepository(db)
        session = await repo.create_session()
        await db.commit()

        assert await repo.try_start_report_generation(session.id) is True
        await db.commit()
        assert await repo.try_start_report_generation(session.id) is False

        await repo.finish_report_generation(session.id, error="生成失败")
        await db.commit()
        assert await repo.try_start_report_generation(session.id) is True


@pytest.mark.asyncio
async def test_reports_are_appended_and_listed_newest_first(report_db_factory):
    async with report_db_factory() as db:
        repo = SessionRepository(db)
        session = await repo.create_session()
        first = await repo.save_report(session.id, "# 第一版", {})
        first.created_at = datetime(2026, 7, 14, 10, 0, 0)
        second = await repo.save_report(session.id, "# 第二版", {})
        second.created_at = datetime(2026, 7, 14, 11, 0, 0)
        await db.commit()

        reports = await repo.list_reports(session.id)

    assert [report.markdown for report in reports] == ["# 第二版", "# 第一版"]


@pytest.mark.asyncio
async def test_background_task_persists_a_new_report(
    report_db_factory,
    mock_model,
):
    async with report_db_factory() as db:
        repo = SessionRepository(db)
        session = await repo.create_session()
        session.scene = '{"industry": "电商"}'
        session.metrics = '["本月访客两万人"]'
        session.score = 40
        session.score_detail = '{"score": 40, "summary": "已有访客信息"}'
        await repo.add_user_message(session.id, "本月访客两万人", "context-message")
        await db.commit()

        session = await repo.get_session(session.id)
        context = ReportContext.from_session(session)
        assert await repo.try_start_report_generation(session.id) is True
        await db.commit()

    manager = ReportTaskManager(
        model_factory=lambda: mock_model,
        session_factory=report_db_factory,
    )
    await manager.start(context)

    async with report_db_factory() as db:
        repo = SessionRepository(db)
        session = await repo.get_session(context.session_id)
        reports = await repo.list_reports(context.session_id)

    assert session.report_generating is False
    assert session.report_error is None
    assert len(reports) == 1
    assert "本月访客两万人" in reports[0].markdown


@pytest.mark.asyncio
async def test_start_report_api_rejects_a_second_running_task(
    report_db_factory,
    monkeypatch,
):
    async with report_db_factory() as db:
        repo = SessionRepository(db)
        session = await repo.create_session()
        await db.commit()
        monkeypatch.setattr(
            "app.api.report_task_manager.start",
            lambda context: None,
        )

        accepted = await start_report_generation(session.id, db)
        assert accepted.status == "generating"

        with pytest.raises(HTTPException) as exc_info:
            await start_report_generation(session.id, db)

    assert exc_info.value.status_code == 409
    assert "正在生成" in exc_info.value.detail
