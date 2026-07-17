"""Create the core diagnosis tables on an empty database.

Revision ID: 20260713_01
Revises:
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa


revision = "20260713_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diagnosis_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("scene", sa.Text(), nullable=True),
        sa.Column("metrics", sa.Text(), nullable=True),
        sa.Column("anomalies", sa.Text(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score_detail", sa.Text(), nullable=True),
        sa.Column("asked_codes", sa.Text(), nullable=True),
        sa.Column("waiting_for_input", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("force_diagnosis", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("limited_diagnosis", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("report_generating", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("report_error", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("diagnosis_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("client_message_id", sa.String(), nullable=True),
        sa.Column("suggested_replies", sa.JSON(), nullable=True),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_id", "client_message_id", name="uq_session_client_msg"),
        sa.UniqueConstraint("session_id", "sequence", name="uq_session_sequence"),
    )
    op.create_table(
        "reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("diagnosis_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("diagnosis", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_reports_session_id", "reports", ["session_id"])


def downgrade() -> None:
    op.drop_table("reports")
    op.drop_table("messages")
    op.drop_table("diagnosis_sessions")
