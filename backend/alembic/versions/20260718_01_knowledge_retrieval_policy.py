"""Add the global knowledge retrieval policy setting.

Revision ID: 20260718_01
Revises: 20260717_01
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260718_01"
down_revision = "20260717_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_retrieval_configuration",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("knowledge_retrieval_configuration")
