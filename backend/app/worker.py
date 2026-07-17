"""ARQ worker entry points and durable-job reconciliation."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select, update

from app.config import settings
from app.db import async_session_factory, engine
from app.models import (
    KnowledgeIngestionJob,
    KnowledgeVectorSyncJob,
    ReportGenerationJob,
)
from app.services.knowledge import (
    knowledge_ingestion_service,
    knowledge_retrieval_service,
    knowledge_storage,
    knowledge_vector_index,
    knowledge_vector_sync_service,
)
from app.services.report_service import report_job_service


def _worker_id(role: str) -> str:
    return f"{role}:{socket.gethostname()}:{os.getpid()}"


async def report_worker_startup(ctx: dict) -> None:
    ctx["worker_id"] = _worker_id("report")
    await knowledge_retrieval_service.startup()


async def report_worker_shutdown(ctx: dict) -> None:
    await knowledge_retrieval_service.shutdown()
    await engine.dispose()


async def knowledge_worker_startup(ctx: dict) -> None:
    ctx["worker_id"] = _worker_id("knowledge")
    await knowledge_storage.startup()
    await knowledge_vector_index.startup()


async def knowledge_worker_shutdown(ctx: dict) -> None:
    await knowledge_vector_index.close()
    await engine.dispose()


async def run_report_job(ctx: dict, job_id: str) -> bool:
    return await report_job_service.run(job_id, worker_id=ctx["worker_id"])


async def run_knowledge_ingestion_job(ctx: dict, job_id: str) -> bool:
    return await knowledge_ingestion_service.run(job_id, worker_id=ctx["worker_id"])


async def run_knowledge_vector_sync_job(ctx: dict, job_id: str) -> bool:
    return await knowledge_vector_sync_service.run(job_id, worker_id=ctx["worker_id"])


async def reconcile_report_jobs(ctx: dict) -> None:
    cutoff = datetime.utcnow() - timedelta(seconds=settings.background_job_stale_seconds)
    async with async_session_factory() as db:
        await db.execute(
            update(ReportGenerationJob)
            .where(
                ReportGenerationJob.state == "running",
                ReportGenerationJob.started_at < cutoff,
            )
            .values(state="queued", worker_id=None, error="Worker lease expired")
        )
        job_ids = list((await db.execute(
            select(ReportGenerationJob.id).where(ReportGenerationJob.state == "queued")
        )).scalars().all())
        await db.commit()
    for job_id in job_ids:
        await ctx["redis"].enqueue_job(
            "run_report_job",
            job_id,
            _job_id=f"report:{job_id}",
            _queue_name=settings.report_queue_name,
        )


async def reconcile_knowledge_jobs(ctx: dict) -> None:
    cutoff = datetime.utcnow() - timedelta(seconds=settings.background_job_stale_seconds)
    async with async_session_factory() as db:
        await db.execute(
            update(KnowledgeIngestionJob)
            .where(
                KnowledgeIngestionJob.state == "running",
                KnowledgeIngestionJob.started_at < cutoff,
            )
            .values(state="queued", worker_id=None, error="Worker lease expired")
        )
        await db.execute(
            update(KnowledgeVectorSyncJob)
            .where(
                KnowledgeVectorSyncJob.state == "running",
                KnowledgeVectorSyncJob.started_at < cutoff,
            )
            .values(state="queued", worker_id=None, error="Worker lease expired")
        )
        ingestion_ids = list((await db.execute(
            select(KnowledgeIngestionJob.id).where(KnowledgeIngestionJob.state == "queued")
        )).scalars().all())
        sync_ids = list((await db.execute(
            select(KnowledgeVectorSyncJob.id).where(KnowledgeVectorSyncJob.state == "queued")
        )).scalars().all())
        await db.commit()
    for job_id in ingestion_ids:
        await ctx["redis"].enqueue_job(
            "run_knowledge_ingestion_job",
            job_id,
            _job_id=f"knowledge-ingestion:{job_id}",
            _queue_name=settings.knowledge_queue_name,
        )
    for job_id in sync_ids:
        await ctx["redis"].enqueue_job(
            "run_knowledge_vector_sync_job",
            job_id,
            _job_id=f"knowledge-vector-sync:{job_id}",
            _queue_name=settings.knowledge_queue_name,
        )


class ReportWorkerSettings:
    functions = [run_report_job]
    cron_jobs = [cron(reconcile_report_jobs, second={0, 30}, run_at_startup=True)]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = settings.report_queue_name
    max_jobs = settings.report_worker_concurrency
    max_tries = settings.background_job_max_attempts
    job_timeout = 1800
    keep_result = 0
    on_startup = report_worker_startup
    on_shutdown = report_worker_shutdown


class KnowledgeWorkerSettings:
    functions = [run_knowledge_ingestion_job, run_knowledge_vector_sync_job]
    cron_jobs = [cron(reconcile_knowledge_jobs, second={0, 30}, run_at_startup=True)]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = settings.knowledge_queue_name
    max_jobs = settings.knowledge_worker_concurrency
    max_tries = settings.background_job_max_attempts
    job_timeout = 1800
    keep_result = 0
    on_startup = knowledge_worker_startup
    on_shutdown = knowledge_worker_shutdown
