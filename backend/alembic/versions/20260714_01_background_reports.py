"""Support background generation and multiple reports per session.

Revision ID: 20260714_01
Revises:
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_01"
down_revision = "20260713_01"
branch_labels = None
depends_on = None


def _rebuild_reports(*, unique_session: bool) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "reports" not in inspector.get_table_names():
        return

    temp_table = "_reports_20260714"
    op.create_table(
        temp_table,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("diagnosis_sessions.id", ondelete="CASCADE"),
            nullable=False,
            unique=unique_session,
        ),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column(
            "diagnosis",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.execute(
        sa.text(
            f"INSERT INTO {temp_table} "
            "(id, session_id, markdown, diagnosis, created_at) "
            "SELECT id, session_id, markdown, diagnosis, created_at FROM reports"
        )
    )
    op.drop_table("reports")
    op.rename_table(temp_table, "reports")
    if not unique_session:
        op.create_index("ix_reports_session_id", "reports", ["session_id"])


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "diagnosis_sessions" in tables:
        columns = {
            column["name"]
            for column in inspector.get_columns("diagnosis_sessions")
        }
        if "report_generating" not in columns:
            op.add_column(
                "diagnosis_sessions",
                sa.Column(
                    "report_generating",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )
        if "report_error" not in columns:
            op.add_column(
                "diagnosis_sessions",
                sa.Column("report_error", sa.Text(), nullable=True),
            )

    if "reports" in tables:
        unique_constraints = inspector.get_unique_constraints("reports")
        has_unique_session = any(
            constraint.get("column_names") == ["session_id"]
            for constraint in unique_constraints
        )
        if has_unique_session:
            _rebuild_reports(unique_session=False)
        else:
            indexes = {index["name"] for index in inspector.get_indexes("reports")}
            if "ix_reports_session_id" not in indexes:
                op.create_index("ix_reports_session_id", "reports", ["session_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "reports" in tables:
        op.execute(
            sa.text(
                "DELETE FROM reports WHERE id NOT IN ("
                "SELECT id FROM ("
                "SELECT id, ROW_NUMBER() OVER ("
                "PARTITION BY session_id ORDER BY created_at DESC, id DESC"
                ") AS row_number FROM reports"
                ") ranked WHERE row_number = 1)"
            )
        )
        _rebuild_reports(unique_session=True)

    inspector = sa.inspect(bind)
    if "diagnosis_sessions" in inspector.get_table_names():
        columns = {
            column["name"]
            for column in inspector.get_columns("diagnosis_sessions")
        }
        if "report_error" in columns:
            op.drop_column("diagnosis_sessions", "report_error")
        if "report_generating" in columns:
            op.drop_column("diagnosis_sessions", "report_generating")
