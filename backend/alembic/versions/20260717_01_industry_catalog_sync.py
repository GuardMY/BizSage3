"""Add repository-managed industry catalog synchronization.

Revision ID: 20260717_01
Revises: 20260716_03
Create Date: 2026-07-17
"""

from alembic import op
import sqlalchemy as sa


revision = "20260717_01"
down_revision = "20260716_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column("managed_source_key", sa.String(length=512), nullable=True),
    )
    op.create_index(
        "ix_knowledge_documents_managed_source_key",
        "knowledge_documents",
        ["managed_source_key"],
        unique=True,
    )

    op.create_table(
        "knowledge_catalog_sync_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("active_key", sa.String(length=64), nullable=True),
        sa.Column("source_keys", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("active_key", name="uq_knowledge_catalog_sync_runs_active_key"),
    )
    op.create_index(
        "ix_knowledge_catalog_sync_runs_state",
        "knowledge_catalog_sync_runs",
        ["state"],
    )

    op.create_table(
        "knowledge_catalog_sync_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("knowledge_catalog_sync_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_key", sa.String(length=512), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("document_id", sa.String(), nullable=True),
        sa.Column("version_id", sa.String(), nullable=True),
        sa.Column("ingestion_job_id", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "source_key",
            name="uq_knowledge_catalog_sync_item_source",
        ),
    )
    for column in (
        "run_id",
        "state",
        "document_id",
        "version_id",
        "ingestion_job_id",
    ):
        op.create_index(
            f"ix_knowledge_catalog_sync_items_{column}",
            "knowledge_catalog_sync_items",
            [column],
        )


def downgrade() -> None:
    op.drop_table("knowledge_catalog_sync_items")
    op.drop_table("knowledge_catalog_sync_runs")
    op.drop_index(
        "ix_knowledge_documents_managed_source_key",
        table_name="knowledge_documents",
    )
    op.drop_column("knowledge_documents", "managed_source_key")
