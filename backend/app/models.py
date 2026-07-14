"""SQLAlchemy ORM models for BizSage3."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.utcnow()


class DiagnosisSession(Base):
    __tablename__ = "diagnosis_sessions"

    id = Column(String, primary_key=True, default=_new_id)
    owner_token_id = Column(
        String,
        ForeignKey("temporary_access_tokens.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = Column(String, nullable=False, default="新的运营诊断")
    status = Column(String, nullable=False, default="collecting")  # collecting|analyzing|completed|failed
    stage = Column(String, nullable=False, default="init")
    scene = Column(Text, default="{}")          # JSON: industry/stage/mode info
    metrics = Column(Text, default="[]")         # JSON: raw_facts list (repurposed from structured metrics)
    anomalies = Column(Text, default="[]")       # JSON: anomaly contexts
    score = Column(Integer, nullable=False, default=0)  # completeness score from LLM
    score_detail = Column(Text, default="{}")    # JSON: {score, summary, missing_aspects}
    asked_codes = Column(Text, default="[]")     # JSON
    waiting_for_input = Column(Boolean, nullable=False, default=False)
    force_diagnosis = Column(Boolean, nullable=False, default=False)
    limited_diagnosis = Column(Boolean, nullable=False, default=False)
    report_generating = Column(Boolean, nullable=False, default=False)
    report_error = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    messages = relationship("Message", back_populates="session", order_by="Message.sequence",
                            cascade="all, delete-orphan")
    reports = relationship(
        "Report",
        back_populates="session",
        order_by="Report.created_at.desc()",
        cascade="all, delete-orphan",
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=_new_id)
    session_id = Column(String, ForeignKey("diagnosis_sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)         # user | assistant
    content = Column(Text, nullable=False)
    sequence = Column(Integer, nullable=False)
    client_message_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    session = relationship("DiagnosisSession", back_populates="messages")

    __table_args__ = (
        UniqueConstraint("session_id", "client_message_id", name="uq_session_client_msg"),
        UniqueConstraint("session_id", "sequence", name="uq_session_sequence"),
    )


class Report(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=_new_id)
    session_id = Column(
        String,
        ForeignKey("diagnosis_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    markdown = Column(Text, nullable=False)
    diagnosis = Column(Text, nullable=False, default="{}")  # JSON
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    session = relationship("DiagnosisSession", back_populates="reports")


class TemporaryAccessToken(Base):
    """A revocable, expiring access token. Only its SHA-256 digest is stored."""

    __tablename__ = "temporary_access_tokens"

    id = Column(String, primary_key=True, default=_new_id)
    name = Column(String(80), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    token_prefix = Column(String(16), nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
