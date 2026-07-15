"""Add versioned industry knowledge and immutable report evidence snapshots.

Revision ID: 20260716_01
Revises: 20260715_01
Create Date: 2026-07-16
"""

from alembic import op
import sqlalchemy as sa


revision = "20260716_01"
down_revision = "20260715_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("current_version_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_knowledge_documents_current_version_id", "knowledge_documents", ["current_version_id"])
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"])

    op.create_table(
        "knowledge_document_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=48), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("effective_from", sa.DateTime(), nullable=True),
        sa.Column("effective_to", sa.DateTime(), nullable=True),
        sa.Column("industry_tags", sa.JSON(), nullable=False),
        sa.Column("sub_industry_tags", sa.JSON(), nullable=False),
        sa.Column("business_mode_tags", sa.JSON(), nullable=False),
        sa.Column("operating_stage_tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("document_id", "version_no", name="uq_knowledge_document_version_no"),
        sa.UniqueConstraint("storage_key", name="uq_knowledge_document_versions_storage_key"),
    )
    for column in ("document_id", "sha256", "status", "effective_from", "effective_to"):
        op.create_index(f"ix_knowledge_document_versions_{column}", "knowledge_document_versions", [column])

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("version_id", sa.String(), sa.ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_no", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("embedding_ref", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("version_id", "chunk_no", name="uq_knowledge_chunk_no"),
    )
    op.create_index("ix_knowledge_chunks_version_id", "knowledge_chunks", ["version_id"])

    op.create_table(
        "knowledge_ingestion_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("version_id", sa.String(), sa.ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("parser", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_knowledge_ingestion_jobs_version_id", "knowledge_ingestion_jobs", ["version_id"])
    op.create_index("ix_knowledge_ingestion_jobs_state", "knowledge_ingestion_jobs", ["state"])

    op.create_table(
        "report_evidences",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("report_id", sa.String(), sa.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.String(), sa.ForeignKey("knowledge_document_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("chunk_id", sa.String(), sa.ForeignKey("knowledge_chunks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("evidence_no", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("report_id", "evidence_no", name="uq_report_evidence_no"),
    )
    for column in ("report_id", "version_id", "chunk_id"):
        op.create_index(f"ix_report_evidences_{column}", "report_evidences", [column])

    op.create_table(
        "knowledge_audit_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(), nullable=True),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=False, server_default="system"),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("event_type", "document_id", "version_id"):
        op.create_index(f"ix_knowledge_audit_events_{column}", "knowledge_audit_events", [column])


def downgrade() -> None:
    op.drop_table("knowledge_audit_events")
    op.drop_table("report_evidences")
    op.drop_table("knowledge_ingestion_jobs")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_document_versions")
    op.drop_table("knowledge_documents")
