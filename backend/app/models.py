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
    JSON,
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
    suggested_replies = Column(JSON, nullable=True)  # LLM-generated quick-reply suggestions
    citations = Column(JSON, nullable=True)  # verified conversation source cards
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
    evidences = relationship(
        "ReportEvidence",
        back_populates="report",
        order_by="ReportEvidence.evidence_no",
        cascade="all, delete-orphan",
    )


class KnowledgeDocument(Base):
    """A platform-wide logical industry knowledge document."""

    __tablename__ = "knowledge_documents"

    id = Column(String, primary_key=True, default=_new_id)
    title = Column(String(240), nullable=False)
    current_version_id = Column(String, nullable=True, index=True)
    status = Column(String(32), nullable=False, default="draft", index=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    versions = relationship(
        "KnowledgeDocumentVersion",
        back_populates="document",
        order_by="KnowledgeDocumentVersion.version_no.desc()",
        cascade="all, delete-orphan",
        foreign_keys="KnowledgeDocumentVersion.document_id",
    )


class KnowledgeDocumentVersion(Base):
    """Immutable uploaded original plus its lifecycle and retrieval metadata."""

    __tablename__ = "knowledge_document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_knowledge_document_version_no"),
    )

    id = Column(String, primary_key=True, default=_new_id)
    document_id = Column(
        String,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_no = Column(Integer, nullable=False)
    original_filename = Column(String(255), nullable=False)
    content_type = Column(String(128), nullable=False)
    source_type = Column(String(48), nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    storage_key = Column(String(512), nullable=False, unique=True)
    status = Column(String(32), nullable=False, default="draft", index=True)
    effective_from = Column(DateTime, nullable=True, index=True)
    effective_to = Column(DateTime, nullable=True, index=True)
    industry_tags = Column(JSON, nullable=False, default=list)
    sub_industry_tags = Column(JSON, nullable=False, default=list)
    business_mode_tags = Column(JSON, nullable=False, default=list)
    operating_stage_tags = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    document = relationship(
        "KnowledgeDocument",
        back_populates="versions",
        foreign_keys=[document_id],
    )
    chunks = relationship(
        "KnowledgeChunk",
        back_populates="version",
        order_by="KnowledgeChunk.chunk_no",
        cascade="all, delete-orphan",
    )
    ingestion_jobs = relationship(
        "KnowledgeIngestionJob",
        back_populates="version",
        order_by="KnowledgeIngestionJob.created_at.desc()",
        cascade="all, delete-orphan",
    )


class KnowledgeChunk(Base):
    """A retrievable source fragment with a stable source locator."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "chunk_no", name="uq_knowledge_chunk_no"),
    )

    id = Column(String, primary_key=True, default=_new_id)
    version_id = Column(
        String,
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_no = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    locator = Column(JSON, nullable=False, default=dict)
    page_no = Column(Integer, nullable=True)
    embedding_ref = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)

    version = relationship("KnowledgeDocumentVersion", back_populates="chunks")


class KnowledgeIngestionJob(Base):
    """Durable state for parsing, chunking and vector indexing work."""

    __tablename__ = "knowledge_ingestion_jobs"

    id = Column(String, primary_key=True, default=_new_id)
    version_id = Column(
        String,
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    state = Column(String(32), nullable=False, default="queued", index=True)
    parser = Column(String(64), nullable=True)
    error = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    indexed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)

    version = relationship("KnowledgeDocumentVersion", back_populates="ingestion_jobs")


class ReportEvidence(Base):
    """Immutable evidence snapshot selected for one generated report."""

    __tablename__ = "report_evidences"
    __table_args__ = (
        UniqueConstraint("report_id", "evidence_no", name="uq_report_evidence_no"),
    )

    id = Column(String, primary_key=True, default=_new_id)
    report_id = Column(
        String,
        ForeignKey("reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id = Column(
        String,
        ForeignKey("knowledge_document_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    chunk_id = Column(
        String,
        ForeignKey("knowledge_chunks.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evidence_no = Column(Integer, nullable=False)
    quote = Column(Text, nullable=False)
    locator = Column(JSON, nullable=False, default=dict)
    query = Column(Text, nullable=False)
    rank = Column(Integer, nullable=False)
    retrieved_at = Column(DateTime, nullable=False, default=_utcnow)

    report = relationship("Report", back_populates="evidences")
    version = relationship("KnowledgeDocumentVersion")
    chunk = relationship("KnowledgeChunk")


class KnowledgeAuditEvent(Base):
    """Append-only administrator and system audit event for the knowledge base."""

    __tablename__ = "knowledge_audit_events"

    id = Column(String, primary_key=True, default=_new_id)
    event_type = Column(String(64), nullable=False, index=True)
    document_id = Column(String, nullable=True, index=True)
    version_id = Column(String, nullable=True, index=True)
    actor_role = Column(String(32), nullable=False, default="system")
    detail = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=_utcnow)


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
