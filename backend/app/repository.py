"""Repository layer: async data access for sessions, messages, reports."""

import json
import uuid
from typing import Optional, List
from datetime import datetime

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DiagnosisSession, Message, Report


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.utcnow()


class SessionRepository:
    """Async data access for diagnosis sessions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---- Sessions ----

    async def list_sessions(self) -> List[DiagnosisSession]:
        """Return all sessions ordered by most recent first."""
        stmt = (
            select(DiagnosisSession)
            .order_by(DiagnosisSession.updated_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def create_session(self) -> DiagnosisSession:
        """Create a new empty diagnosis session."""
        session = DiagnosisSession(
            id=_new_id(),
            title="新的运营诊断",
            status="collecting",
            stage="init",
            waiting_for_input=True,
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def get_session(self, session_id: str) -> Optional[DiagnosisSession]:
        """Get a session by ID, including messages and report."""
        from sqlalchemy.orm import selectinload
        stmt = (
            select(DiagnosisSession)
            .where(DiagnosisSession.id == session_id)
            .options(
                selectinload(DiagnosisSession.messages),
                selectinload(DiagnosisSession.report),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session and its messages/report (cascade). Returns True if deleted."""
        session = await self.get_session(session_id)
        if not session:
            return False
        await self.db.delete(session)
        await self.db.flush()
        return True

    async def update_session_state(
        self,
        session: DiagnosisSession,
        workflow_state: dict,
    ) -> None:
        """Persist workflow state back to the session ORM object.

        Args:
            session: The ORM object (already tracked by the session).
            workflow_state: The dict returned by LangGraph workflow.
        """
        session.stage = workflow_state.get("stage", session.stage)
        session.scene = json.dumps(workflow_state.get("user_scene", {}), ensure_ascii=False)

        # Store raw_facts in the metrics column (repurposed)
        raw_facts = workflow_state.get("raw_facts", [])
        session.metrics = json.dumps(raw_facts, ensure_ascii=False)

        # Store completeness from LLM evaluation
        completeness = workflow_state.get("completeness", {})
        session.score = completeness.get("score", 0)
        session.score_detail = json.dumps({
            "score": completeness.get("score", 0),
            "summary": completeness.get("summary", ""),
            "missing_aspects": completeness.get("missing_aspects", []),
        }, ensure_ascii=False)
        session.updated_at = _utcnow()

        # Determine status from stage
        final_report = workflow_state.get("final_report", "")
        stage = workflow_state.get("stage", "")
        if final_report:
            session.status = "completed"
            session.waiting_for_input = False
        elif stage in ("agent_reply", "await_input", "chat_extract"):
            session.status = "collecting"
            session.waiting_for_input = True
        else:
            session.waiting_for_input = False

        await self.db.flush()

    # ---- Messages ----

    async def add_user_message(
        self,
        session_id: str,
        content: str,
        client_message_id: str,
    ) -> Message:
        """Add a user message to a session. Returns the created message."""
        # Check idempotency
        existing = await self.find_client_message(session_id, client_message_id)
        if existing:
            return existing

        # Get next sequence number
        max_seq = await self._max_sequence(session_id)
        seq = max_seq + 1

        msg = Message(
            id=_new_id(),
            session_id=session_id,
            role="user",
            content=content,
            sequence=seq,
            client_message_id=client_message_id,
        )
        self.db.add(msg)
        await self.db.flush()
        return msg

    async def add_assistant_message(
        self,
        session_id: str,
        content: str,
    ) -> Message:
        """Add an assistant message to a session."""
        max_seq = await self._max_sequence(session_id)
        seq = max_seq + 1

        msg = Message(
            id=_new_id(),
            session_id=session_id,
            role="assistant",
            content=content,
            sequence=seq,
        )
        self.db.add(msg)
        await self.db.flush()
        return msg

    async def find_client_message(
        self,
        session_id: str,
        client_message_id: str,
    ) -> Optional[Message]:
        """Check if a client message was already processed (idempotency)."""
        stmt = (
            select(Message)
            .where(
                Message.session_id == session_id,
                Message.client_message_id == client_message_id,
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def _max_sequence(self, session_id: str) -> int:
        """Get the highest sequence number for a session."""
        stmt = (
            select(func.max(Message.sequence))
            .where(Message.session_id == session_id)
        )
        result = await self.db.execute(stmt)
        val = result.scalar()
        return val if val is not None else 0

    # ---- Reports ----

    async def save_report(
        self,
        session_id: str,
        markdown: str,
        diagnosis: dict,
    ) -> Report:
        """Create or update the report for a session."""
        # Check if report already exists
        stmt = select(Report).where(Report.session_id == session_id)
        result = await self.db.execute(stmt)
        report = result.scalars().first()

        if report:
            report.markdown = markdown
            report.diagnosis = json.dumps(diagnosis, ensure_ascii=False)
            report.created_at = _utcnow()
        else:
            report = Report(
                id=_new_id(),
                session_id=session_id,
                markdown=markdown,
                diagnosis=json.dumps(diagnosis, ensure_ascii=False),
            )
            self.db.add(report)

        await self.db.flush()
        return report
