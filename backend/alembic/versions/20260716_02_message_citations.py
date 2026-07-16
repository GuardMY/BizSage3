"""Persist verified source cards for ordinary conversation messages.

Revision ID: 20260716_02
Revises: 20260716_01
Create Date: 2026-07-16
"""

from alembic import op
import sqlalchemy as sa


revision = "20260716_02"
down_revision = "20260716_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        op.add_column("messages", sa.Column("citations", sa.JSON(), nullable=True))
        return
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("messages"):
        return
    columns = {column["name"] for column in inspector.get_columns("messages")}
    if "citations" not in columns:
        op.add_column("messages", sa.Column("citations", sa.JSON(), nullable=True))


def downgrade() -> None:
    if op.get_context().as_sql:
        op.drop_column("messages", "citations")
        return
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("messages"):
        return
    columns = {column["name"] for column in inspector.get_columns("messages")}
    if "citations" in columns:
        op.drop_column("messages", "citations")
