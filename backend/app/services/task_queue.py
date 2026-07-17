"""ARQ producer used by API processes to enqueue durable background jobs."""

from __future__ import annotations

from arq.connections import ArqRedis, RedisSettings, create_pool

from app.config import settings


class TaskQueue:
    def __init__(self, redis_url: str = settings.redis_url) -> None:
        self._settings = RedisSettings.from_dsn(redis_url)
        self._redis: ArqRedis | None = None

    async def startup(self) -> None:
        if self._redis is None:
            self._redis = await create_pool(self._settings)
        await self._redis.ping()

    async def shutdown(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def enqueue_report(self, job_id: str) -> None:
        redis = await self._pool()
        await redis.enqueue_job(
            "run_report_job",
            job_id,
            _job_id=f"report:{job_id}",
            _queue_name=settings.report_queue_name,
        )

    async def enqueue_ingestion(self, job_id: str) -> None:
        redis = await self._pool()
        await redis.enqueue_job(
            "run_knowledge_ingestion_job",
            job_id,
            _job_id=f"knowledge-ingestion:{job_id}",
            _queue_name=settings.knowledge_queue_name,
        )

    async def enqueue_vector_sync(self, job_id: str) -> None:
        redis = await self._pool()
        await redis.enqueue_job(
            "run_knowledge_vector_sync_job",
            job_id,
            _job_id=f"knowledge-vector-sync:{job_id}",
            _queue_name=settings.knowledge_queue_name,
        )

    async def ping(self) -> bool:
        if self._redis is None:
            return False
        return bool(await self._redis.ping())

    async def _pool(self) -> ArqRedis:
        if self._redis is None:
            await self.startup()
        assert self._redis is not None
        return self._redis


task_queue = TaskQueue()
