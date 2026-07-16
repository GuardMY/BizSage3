"""Serializers: convert SQLAlchemy ORM objects to Pydantic API schemas."""

import json
from typing import Optional, List, Any

from app.models import DiagnosisSession, Message, Report
from app.api_schemas import (
    SessionSummary,
    SessionDetail,
    MessageSchema,
    CompletenessSchema,
    ReportResponse,
)


def _parse_json(text: str, default: Any = None) -> Any:
    """Safely parse a JSON column value."""
    if default is None:
        default = {}
    try:
        return json.loads(text) if text else default
    except (json.JSONDecodeError, TypeError):
        return default


def session_summary(session: DiagnosisSession) -> SessionSummary:
    """ORM -> SessionSummary."""
    return SessionSummary(
        id=session.id,
        title=session.title,
        status=session.status,
        stage=session.stage,
        score=session.score,
        limited_diagnosis=session.limited_diagnosis,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def message_schema(msg: Message) -> MessageSchema:
    """ORM -> MessageSchema."""
    return MessageSchema(
        id=msg.id,
        role=msg.role,
        content=msg.content,
        sequence=msg.sequence,
        suggested_replies=msg.suggested_replies,
        citations=msg.citations,
        created_at=msg.created_at,
    )


def completeness(session: DiagnosisSession) -> CompletenessSchema:
    """Extract completeness info from session JSON fields.

    The score_detail column now stores completeness data (score, summary, missing_aspects).
    """
    sd = _parse_json(session.score_detail, {})
    return CompletenessSchema(
        score=session.score or sd.get("score", 0),
        summary=sd.get("summary", ""),
        missing_aspects=sd.get("missing_aspects", []),
    )


def session_detail(session: DiagnosisSession) -> SessionDetail:
    """ORM -> SessionDetail (full)."""
    msgs = [message_schema(m) for m in (session.messages or [])]
    facts = _parse_json(session.metrics, [])
    if isinstance(facts, dict):
        # Legacy data: metrics dict → convert keys to fact strings
        facts = [f"{k}: {v}" for k, v in facts.items()] if facts else []
    return SessionDetail(
        id=session.id,
        title=session.title,
        status=session.status,
        stage=session.stage,
        score=session.score,
        limited_diagnosis=session.limited_diagnosis or False,
        created_at=session.created_at,
        updated_at=session.updated_at,
        scene=_parse_json(session.scene, {}),
        raw_facts=facts if isinstance(facts, list) else [],
        completeness=completeness(session),
        waiting_for_input=session.waiting_for_input or False,
        error_message=session.error_message,
        messages=msgs,
        has_report=bool(session.reports),
        report_count=len(session.reports),
        report_generating=session.report_generating or False,
        report_error=session.report_error,
    )


def report_response(report: Report) -> ReportResponse:
    """ORM Report -> ReportResponse."""
    return ReportResponse(
        id=report.id,
        session_id=report.session_id,
        markdown=report.markdown,
        diagnosis=_parse_json(report.diagnosis, {}),
        created_at=report.created_at,
    )
