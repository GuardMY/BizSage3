"""Transaction-boundary regressions for long-running API workflows."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api import _process_message
from app.api_schemas import MessageRequest
from app.models import Base, Message
from app.repository import SessionRepository


@pytest.mark.asyncio
async def test_chat_commits_user_message_before_workflow(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as db:
        repo = SessionRepository.for_system(db)
        session = await repo.create_session()
        await db.commit()
        session = await repo.get_session(session.id)

        async def fake_start(session_id, user_message, existing_messages):
            assert db.in_transaction() is False
            return {
                "stage": "await_input",
                "user_scene": {"industry": "电商"},
                "raw_facts": [user_message],
                "completeness": {"score": 20},
                "messages": [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": "请继续补充。"},
                ],
                "suggested_replies": [],
            }

        monkeypatch.setattr("app.api.workflow_manager.start", fake_start)
        request = MessageRequest(client_message_id="message-1", content="经营一家网店")
        events = [event async for event in _process_message(repo, session, request)]

        messages = list((await db.execute(
            select(Message).where(Message.session_id == session.id).order_by(Message.sequence)
        )).scalars().all())

    await engine.dispose()
    assert [message.role for message in messages] == ["user", "assistant"]
    assert events[-1]["event"] == "done"
