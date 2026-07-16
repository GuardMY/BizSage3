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
    op.add_column("messages", sa.Column("citations", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "citations")
