"""Add suggested_replies column to messages table.

Revision ID: 20260715_01
Revises: 20260714_01
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "20260715_01"
down_revision = "20260714_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "messages" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("messages")}
    if "suggested_replies" in columns:
        return
    op.add_column(
        "messages",
        sa.Column("suggested_replies", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "messages" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("messages")}
    if "suggested_replies" not in columns:
        return
    op.drop_column("messages", "suggested_replies")
