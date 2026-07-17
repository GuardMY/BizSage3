"""LangGraph checkpoint backend selection without application side effects."""

from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings


@asynccontextmanager
async def _postgres_checkpoint_context(checkpoint_url: str):
    pool = AsyncConnectionPool(
        checkpoint_url,
        min_size=1,
        max_size=settings.checkpoint_pool_size,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "application_name": f"{settings.db_application_name}-checkpoints",
        },
        open=False,
        name=f"{settings.db_application_name}-checkpoints",
    )
    await pool.open()
    try:
        yield AsyncPostgresSaver(pool)
    finally:
        await pool.close()


def checkpoint_context(checkpoint_url: str):
    """Return the configured LangGraph checkpoint context manager."""
    if checkpoint_url.startswith("sqlite+aiosqlite:////"):
        db_path = "/" + checkpoint_url[len("sqlite+aiosqlite:////"):]
        return AsyncSqliteSaver.from_conn_string(db_path)
    if checkpoint_url.startswith("sqlite+aiosqlite:///"):
        db_path = checkpoint_url[len("sqlite+aiosqlite:///"):]
        return AsyncSqliteSaver.from_conn_string(db_path)
    if not checkpoint_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("CHECKPOINT_DB_URL must use PostgreSQL in production")
    return _postgres_checkpoint_context(checkpoint_url)
