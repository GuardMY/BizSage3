"""Isolate diagnosis sessions by temporary access token.

Revision ID: 20260714_03
Revises: 20260714_02
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_03"
down_revision = "20260714_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "diagnosis_sessions" not in inspector.get_table_names():
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("diagnosis_sessions")
    }
    if "owner_token_id" not in columns:
        with op.batch_alter_table("diagnosis_sessions") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "owner_token_id",
                    sa.String(),
                    nullable=True,
                )
            )
            batch_op.create_foreign_key(
                "fk_diagnosis_sessions_owner_token_id",
                "temporary_access_tokens",
                ["owner_token_id"],
                ["id"],
                ondelete="SET NULL",
            )

    inspector = sa.inspect(bind)
    indexes = {
        index["name"]
        for index in inspector.get_indexes("diagnosis_sessions")
    }
    if "ix_diagnosis_sessions_owner_token_id" not in indexes:
        op.create_index(
            "ix_diagnosis_sessions_owner_token_id",
            "diagnosis_sessions",
            ["owner_token_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "diagnosis_sessions" not in inspector.get_table_names():
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("diagnosis_sessions")
    }
    if "owner_token_id" not in columns:
        return

    indexes = {
        index["name"]
        for index in inspector.get_indexes("diagnosis_sessions")
    }
    if "ix_diagnosis_sessions_owner_token_id" in indexes:
        op.drop_index(
            "ix_diagnosis_sessions_owner_token_id",
            table_name="diagnosis_sessions",
        )
    with op.batch_alter_table("diagnosis_sessions") as batch_op:
        batch_op.drop_column("owner_token_id")
