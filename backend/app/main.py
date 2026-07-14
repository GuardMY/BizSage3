"""FastAPI application factory with lifespan management."""

import logging
from contextlib import asynccontextmanager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import engine
from app.models import Base
from app.api import router as api_router
from app.services.workflow import workflow_manager
from app.services.report_service import report_task_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create tables, configure SQLite, init workflow. Shutdown: cleanup."""
    # Enable WAL mode and create all tables
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.run_sync(Base.metadata.create_all)

    # Start the workflow manager (initializes checkpointer + graph)
    await workflow_manager.startup()
    await report_task_manager.startup()

    yield

    # Cleanup
    await report_task_manager.shutdown()
    await workflow_manager.shutdown()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="BizSage3",
        description="AI-powered industry operations diagnosis agent",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins.split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(api_router)

    # Health checks (at root level for simplicity)
    @app.get("/health/live")
    async def health_live():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def health_ready():
        async with engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")
        return {"status": "ready"}

    return app


app = create_app()
