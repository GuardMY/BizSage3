"""SQLAlchemy async engine and session factory."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.config import settings


def _engine_options(database_url: str) -> dict[str, Any]:
    options: dict[str, Any] = {
        "echo": False,
        "pool_pre_ping": True,
    }
    if database_url.startswith("postgresql"):
        options.update({
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout_seconds,
            "pool_recycle": settings.db_pool_recycle_seconds,
            "connect_args": {
                "server_settings": {
                    "application_name": settings.db_application_name,
                    "statement_timeout": str(settings.db_statement_timeout_ms),
                    "idle_in_transaction_session_timeout": str(
                        settings.db_idle_transaction_timeout_ms
                    ),
                }
            },
        })
    return options


engine = create_async_engine(settings.database_url, **_engine_options(settings.database_url))

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    """FastAPI dependency that yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
