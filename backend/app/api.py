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
from app.auth import Principal, get_current_principal
from app.domain.schemas import ResumeInput
from app.api_schemas import (
    SessionSummary,
    SessionDetail,
    MessageRequest,
    ReportResponse,
    ReportGenerationResponse,
)
from app.serializers import session_summary, session_detail, report_response
from app.repository import SessionRepository
from app.services.workflow import workflow_manager
from app.services.report_service import ReportContext, report_task_manager

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
async def list_sessions(
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
):
    """List accessible diagnosis sessions, newest first."""
    repo = SessionRepository.for_principal(db, principal)
    sessions = await repo.list_sessions()
    return [session_summary(s) for s in sessions]


WELCOME_MESSAGE = (
    "你好！我是 BizSage 运营诊断助手 📊\n\n"
    "我可以帮你：\n"
    "- 识别你的行业和业务场景\n"
    "- 基于运营数据做多维度诊断分析\n"
    "- 生成诊断报告和优化方案"
)

CONVERSATION_STARTER = "来聊聊你的业务吧——你目前在做什么行业？"



@router.post("/sessions", response_model=SessionDetail, status_code=201)
async def create_session(
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new diagnosis session with a welcome message."""
    repo = SessionRepository.for_principal(db, principal)
    session = await repo.create_session()

    # Add welcome assistant message so the user sees a greeting immediately
    await repo.add_assistant_message(session.id, WELCOME_MESSAGE)
    # Follow up with a conversation starter to kick off the diagnosis dialogue
    await repo.add_assistant_message(session.id, CONVERSATION_STARTER)

    await db.commit()
    # Re-fetch with eager loaded relationships
    session = await repo.get_session(session.id)
    return session_detail(session)


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
):
    """Get a session by ID with all details."""
    repo = SessionRepository.for_principal(db, principal)
    session = await repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session_detail(session)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
):
    """Delete a session and all its data."""
    repo = SessionRepository.for_principal(db, principal)
    session = await repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await report_task_manager.cancel(session_id)
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
    "greeting_guide": "自我介绍...",
    "conversation_turn": "分析并回复...",
    "chat_extract": "分析对话...",
    "agent_reply": "思考中...",
    "await_input": "等待您的回复",
    "generate_report": "生成诊断报告...",
}


@router.post("/sessions/{session_id}/messages")
async def chat_message(
    session_id: str,
    body: MessageRequest,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
):
    """Send a message and receive SSE stream of workflow events.

    This is the core conversational endpoint. It can:
    - Start a new workflow if this is the first message
    - Resume a paused workflow after user reply

    Report generation uses the dedicated background reports endpoint.
    """
    if body.action == "diagnose_with_current_data":
        raise HTTPException(
            status_code=400,
            detail="诊断报告已改为后台生成，请使用 POST /sessions/{id}/reports",
        )

    repo = SessionRepository.for_principal(db, principal)

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

    # 3. Determine: start new workflow or resume
    stage = session.stage or "init"
    has_scene = bool(session.scene) and session.scene != "{}"

    # New workflow if: stage is init/collecting and no scene identified yet
    is_new = stage in ("init", "collecting") and not has_scene

    try:
        if is_new:
            yield {"event": "stage", "data": json.dumps(
                {"stage": "scene_recognize", "label": STAGE_LABELS.get("scene_recognize", "识别行业场景...")},
                ensure_ascii=False
            )}
            # Pass existing DB messages so workflow state aligns with DB count
            existing = [
                {"role": m.role, "content": m.content}
                for m in (session.messages or [])
            ]
            result = await workflow_manager.start(session.id, body.content or "", existing)
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

            # Save to DB with suggested_replies from workflow state
            suggestions = result.get("suggested_replies", []) or []
            saved_msg = await repo.add_assistant_message(session.id, content, suggestions)

            # Emit suggested_replies SSE event if present
            if suggestions:
                yield {"event": "suggested_replies", "data": json.dumps(
                    {"message_id": saved_msg.id, "replies": suggestions},
                    ensure_ascii=False,
                )}

    # Check if report was generated
    final_report = result.get("final_report", "")
    if final_report:
        # Save report to DB
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
    # Re-fetch session to get latest DB state (messages were added during
    # this request and the in-memory ORM relationship is stale).
    fresh_session = await repo.get_session(session.id)
    if fresh_session:
        detail = session_detail(fresh_session)
    else:
        detail = session_detail(session)
    yield {"event": "state", "data": json.dumps(
        detail.model_dump(mode="json"), ensure_ascii=False
    )}

    # Done
    yield {"event": "done", "data": json.dumps({"session_id": session.id})}


# =============================================================================
# Reports
# =============================================================================

@router.post(
    "/sessions/{session_id}/reports",
    response_model=ReportGenerationResponse,
    status_code=202,
)
async def start_report_generation(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
):
    """Start one background report task from the current conversation snapshot."""
    repo = SessionRepository.for_principal(db, principal)
    session = await repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    context = ReportContext.from_session(session)
    acquired = await repo.try_start_report_generation(session_id)
    if not acquired:
        raise HTTPException(status_code=409, detail="该会话已有诊断报告正在生成")
    await db.commit()

    try:
        report_task_manager.start(context)
    except RuntimeError as exc:
        await repo.finish_report_generation(session_id, error=str(exc))
        await db.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return ReportGenerationResponse(session_id=session_id)


@router.get(
    "/sessions/{session_id}/reports",
    response_model=list[ReportResponse],
)
async def list_reports(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
):
    """List all reports for a session, newest first."""
    repo = SessionRepository.for_principal(db, principal)
    session = await repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    reports = await repo.list_reports(session_id)
    return [report_response(report) for report in reports]


@router.get(
    "/sessions/{session_id}/reports/{report_id}",
    response_model=ReportResponse,
)
async def get_report_by_id(
    session_id: str,
    report_id: str,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
):
    """Get one diagnosis report by ID."""
    report = await SessionRepository.for_principal(db, principal).get_report(
        session_id,
        report_id,
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report_response(report)


@router.get("/sessions/{session_id}/reports/{report_id}/download")
async def download_report_by_id(
    session_id: str,
    report_id: str,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
):
    """Download one report as Markdown."""
    from fastapi.responses import PlainTextResponse

    report = await SessionRepository.for_principal(db, principal).get_report(
        session_id,
        report_id,
    )
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return PlainTextResponse(
        content=report.markdown,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f"attachment; filename=diagnosis-report-{report.id[:8]}.md"
        },
    )

@router.get("/sessions/{session_id}/report", response_model=ReportResponse)
async def get_report(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
):
    """Get the latest diagnosis report for backward compatibility."""
    repo = SessionRepository.for_principal(db, principal)
    session = await repo.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    reports = await repo.list_reports(session_id)
    if not reports:
        raise HTTPException(status_code=404, detail="Report not yet generated")
    return report_response(reports[0])


@router.get("/sessions/{session_id}/report/download")
async def download_report(
    session_id: str,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
):
    """Download the latest report as Markdown for backward compatibility."""
    from fastapi.responses import PlainTextResponse

    repo = SessionRepository.for_principal(db, principal)
    reports = await repo.list_reports(session_id)
    if not reports:
        raise HTTPException(status_code=404, detail="Report not found")
    report = reports[0]

    return PlainTextResponse(
        content=report.markdown,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f"attachment; filename=diagnosis-report-{report.id[:8]}.md"
        },
    )


