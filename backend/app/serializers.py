"""Serializers: convert SQLAlchemy ORM objects to Pydantic API schemas."""

import json
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.models import DiagnosisSession, Message, Report
from app.api_schemas import (
    SessionSummary,
    SessionDetail,
    MessageSchema,
    ScoreDetailSchema,
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
        created_at=msg.created_at,
    )


def score_detail(session: DiagnosisSession) -> ScoreDetailSchema:
    """Extract score detail from session JSON fields."""
    sd = _parse_json(session.score_detail, {})
    return ScoreDetailSchema(
        score=session.score,
        core_complete=sd.get("core_complete", False),
        core_provided_count=sd.get("core_provided_count", 0),
        secondary_coverage=sd.get("secondary_coverage", 0.0),
        anomaly_complete=sd.get("anomaly_complete", True),
        missing_core=sd.get("missing_core", []),
        missing_secondary=sd.get("missing_secondary", []),
        unresolved_anomalies=sd.get("unresolved_anomalies", []),
        can_limited_diagnose=sd.get("can_limited_diagnose", False),
        passed=sd.get("passed", False),
    )


def session_detail(session: DiagnosisSession) -> SessionDetail:
    """ORM -> SessionDetail (full)."""
    msgs = [message_schema(m) for m in (session.messages or [])]
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
        metrics=_parse_json(session.metrics, {}),
        score_detail=score_detail(session),
        waiting_for_input=session.waiting_for_input or False,
        error_message=session.error_message,
        messages=msgs,
        has_report=session.report is not None,
    )


def report_response(session: DiagnosisSession) -> Optional[ReportResponse]:
    """ORM -> ReportResponse, or None if no report."""
    if not session.report:
        return None
    return ReportResponse(
        session_id=session.id,
        markdown=session.report.markdown,
        diagnosis=_parse_json(session.report.diagnosis, {}),
        created_at=session.report.created_at,
    )
