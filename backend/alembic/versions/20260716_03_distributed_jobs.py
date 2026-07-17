"""Add durable distributed background jobs.

Revision ID: 20260716_03
Revises: 20260716_02
Create Date: 2026-07-16
"""

from alembic import op
import sqlalchemy as sa


revision = "20260716_03"
down_revision = "20260716_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_generation_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("diagnosis_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("context_snapshot", sa.JSON(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_report_generation_jobs_session_id", "report_generation_jobs", ["session_id"])
    op.create_index("ix_report_generation_jobs_state", "report_generation_jobs", ["state"])
    op.create_index(
        "uq_report_generation_jobs_active_session",
        "report_generation_jobs",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('queued', 'running')"),
        sqlite_where=sa.text("state IN ('queued', 'running')"),
    )

    for column_name, column in (
        ("worker_id", sa.Column("worker_id", sa.String(length=128), nullable=True)),
        ("started_at", sa.Column("started_at", sa.DateTime(), nullable=True)),
        ("finished_at", sa.Column("finished_at", sa.DateTime(), nullable=True)),
    ):
        op.add_column("knowledge_ingestion_jobs", column)

    op.create_table(
        "knowledge_vector_sync_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_knowledge_vector_sync_jobs_version_id",
        "knowledge_vector_sync_jobs",
        ["version_id"],
    )
    op.create_index(
        "ix_knowledge_vector_sync_jobs_state",
        "knowledge_vector_sync_jobs",
        ["state"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_vector_sync_jobs")
    for column_name in ("finished_at", "started_at", "worker_id"):
        op.drop_column("knowledge_ingestion_jobs", column_name)
    op.drop_table("report_generation_jobs")
