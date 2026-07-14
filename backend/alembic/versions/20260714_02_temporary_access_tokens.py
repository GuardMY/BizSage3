"""Add temporary access tokens.

Revision ID: 20260714_02
Revises: 20260714_01
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_02"
down_revision = "20260714_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "temporary_access_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_temporary_access_tokens_token_hash",
        "temporary_access_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_temporary_access_tokens_expires_at",
        "temporary_access_tokens",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_temporary_access_tokens_expires_at",
        table_name="temporary_access_tokens",
    )
    op.drop_index(
        "ix_temporary_access_tokens_token_hash",
        table_name="temporary_access_tokens",
    )
    op.drop_table("temporary_access_tokens")
