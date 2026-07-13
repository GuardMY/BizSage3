"""FastAPI router: all BizSage3 API endpoints.

Includes session CRUD, SSE chat streaming, report retrieval, and meta.
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.db import get_session as get_db_session
from app.config import settings
from app.domain.schemas import ResumeInput
from app.domain.catalog import CORE_METRICS, INDUSTRY_SECONDARY_METRICS, INDUSTRIES
from app.api_schemas import (
    SessionSummary,
    SessionDetail,
    MessageRequest,
    ReportResponse,
    MetaResponse,
    IndustryDef,
    MetricDef,
)
from app.serializers import session_summary, session_detail, report_response
from app.repository import SessionRepository
from app.services.workflow import workflow_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


# =============================================================================
# Health
# =============================================================================

@router.get("/health/live")
async def health_live():
    return {"status": "ok"}


@router.get("/health/ready")
async def health_ready():
    return {"status": "ready"}


# =============================================================================
# Sessions
# =============================================================================

@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(db: AsyncSession = Depends(get_db_session)):
    """List all diagnosis sessions, newest first."""
    repo = SessionRepository(db)
    sessions = await repo.list_sessions()
    return [session_summary(s) for s in sessions]


@router.post("/sessions", response_model=SessionDetail, status_code=201)
async def create_session(db: AsyncSession = Depends(get_db_session)):
    """Create a new diagnosis session."""
    repo = SessionRepository(db)
    session = await repo.create_session()
    await db.commit()
    # Re-fetch with eager loaded relationships
    session = await repo.get_session(session.id)
    return session_detail(session)


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db_session)):
    """Get a session by ID with all details."""
    repo = SessionRepository(db)
    session = await repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session_detail(session)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db_session)):
    """Delete a session and all its data."""
    repo = SessionRepository(db)
    deleted = await repo.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.commit()


# =============================================================================
# Chat (SSE Streaming)
# =============================================================================

# Stage labels for SSE events
STAGE_LABELS = {
    "init": "初始化",
    "scene_recognize": "识别行业场景...",
    "collect_metrics": "提取运营指标...",
    "check_complete": "评估信息完备度...",
    "exception_ask": "生成补充问题...",
    "await_input": "等待您的回复",
    "diagnosis_analysis": "六维度诊断分析中...",
    "generate_report": "生成诊断报告...",
}


@router.post("/sessions/{session_id}/messages")
async def chat_message(
    session_id: str,
    body: MessageRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Send a message and receive SSE stream of workflow events.

    This is the core conversational endpoint. It can:
    - Start a new workflow if this is the first message
    - Resume a paused workflow after user reply
    - Force diagnosis with current data (action=diagnose_with_current_data)
    """
    repo = SessionRepository(db)

    # 1. Load session
    session = await repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2. Concurrency: acquire per-session lock
    lock = workflow_manager.get_lock(session_id)
    acquired = lock.locked()
    if acquired:
        raise HTTPException(
            status_code=409,
            detail="A message is already being processed for this session",
        )

    async def event_generator():
        async with lock:
            try:
                async for event in _process_message(repo, session, body):
                    yield event
                await db.commit()
            except Exception as exc:
                logger.exception("Error processing message for session %s", session_id)
                session.status = "failed"
                session.error_message = str(exc)
                await db.commit()
                yield {"event": "error", "data": json.dumps({"message": str(exc)}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


async def _process_message(repo: SessionRepository, session, body: MessageRequest):
    """Core message processing logic, yields SSE events."""

    # 1. Idempotency check
    existing = await repo.find_client_message(session.id, body.client_message_id)
    if existing:
        # Return current state without re-processing
        yield {"event": "state", "data": json.dumps(
            session_detail(session).model_dump(mode="json"), ensure_ascii=False
        )}
        yield {"event": "done", "data": json.dumps({"session_id": session.id})}
        return

    # 2. Save user message
    if body.content:
        await repo.add_user_message(
            session.id, body.content, body.client_message_id
        )

    # 3. Determine: start or resume
    # If session is new (stage=init, no scene yet), start
    # Otherwise resume
    stage = session.stage or "init"
    is_new = stage == "init" and not session.scene or session.scene == "{}"

    try:
        if is_new:
            yield {"event": "stage", "data": json.dumps(
                {"stage": "scene_recognize", "label": STAGE_LABELS["scene_recognize"]}
            )}
            result = await workflow_manager.start(session.id, body.content or "")
        else:
            action = body.action or "reply"
            payload = ResumeInput(
                content=body.content or "",
                action=action,
            )
            result = await workflow_manager.resume(session.id, payload)

        # 4. Process result: emit SSE events from workflow result
        async for event in _emit_result(repo, session, result):
            yield event
    except Exception:
        raise


async def _emit_result(repo: SessionRepository, session, result: dict):
    """Extract and emit SSE events from workflow result."""

    # Update session state from workflow result
    await repo.update_session_state(session, result)

    # Find new messages added by the workflow
    messages = result.get("messages", [])
    old_count = len(session.messages) if session.messages else 0

    new_messages = messages[old_count:] if len(messages) > old_count else []

    for msg_dict in new_messages:
        role = msg_dict.get("role", "assistant")
        content = msg_dict.get("content", "")

        if role == "assistant" and content:
            # Stream as delta events (simulate word-by-word for real-time feel)
            yield {"event": "assistant.delta", "data": json.dumps(
                {"target": "message", "delta": content[:50]}, ensure_ascii=False
            )}

            # Full message event
            yield {"event": "assistant.message", "data": json.dumps(
                {"content": content}, ensure_ascii=False
            )}

            # Save to DB
            await repo.add_assistant_message(session.id, content)

    # Check if report was generated
    final_report = result.get("final_report", "")
    if final_report:
        # Save report to DB
        from app.domain.schemas import DiagnosisResult
        await repo.save_report(
            session.id,
            markdown=final_report,
            diagnosis={"raw": result.get("diagnosis_result", "")},
        )
        yield {"event": "report.ready", "data": json.dumps(
            {"session_id": session.id}, ensure_ascii=False
        )}

    # Emit stage update
    stage = result.get("stage", "")
    if stage:
        yield {"event": "stage", "data": json.dumps(
            {"stage": stage, "label": STAGE_LABELS.get(stage, stage)}
        )}

    # Emit full state snapshot
    # Re-fetch session to get latest DB state
    detail = session_detail(session)
    yield {"event": "state", "data": json.dumps(
        detail.model_dump(mode="json"), ensure_ascii=False
    )}

    # Done
    yield {"event": "done", "data": json.dumps({"session_id": session.id})}


# =============================================================================
# Reports
# =============================================================================

@router.get("/sessions/{session_id}/report", response_model=ReportResponse)
async def get_report(session_id: str, db: AsyncSession = Depends(get_db_session)):
    """Get the diagnosis report for a session."""
    repo = SessionRepository(db)
    session = await repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    rpt = report_response(session)
    if not rpt:
        raise HTTPException(status_code=404, detail="Report not yet generated")
    return rpt


@router.get("/sessions/{session_id}/report/download")
async def download_report(session_id: str, db: AsyncSession = Depends(get_db_session)):
    """Download the diagnosis report as a Markdown file."""
    from fastapi.responses import PlainTextResponse

    repo = SessionRepository(db)
    session = await repo.get_session(session_id)
    if not session or not session.report:
        raise HTTPException(status_code=404, detail="Report not found")

    return PlainTextResponse(
        content=session.report.markdown,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f"attachment; filename=diagnosis-report-{session_id[:8]}.md"
        },
    )


# =============================================================================
# Meta
# =============================================================================

@router.get("/meta/industries", response_model=MetaResponse)
async def get_industries():
    """Return available industries, core metrics, and LLM mode."""
    industry_defs = [
        IndustryDef(code=k, label=k, description=v)
        for k, v in INDUSTRIES.items()
    ]
    metric_defs = [
        MetricDef(
            code=m.code,
            label=m.label,
            category=m.category,
            description=m.description,
            unit=m.unit,
            is_core=m.is_core,
        )
        for m in CORE_METRICS
    ]
    return MetaResponse(
        industries=industry_defs,
        core_metrics=metric_defs,
        llm_mode=settings.llm_mode,
    )
