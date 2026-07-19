"""Durable diagnosis report jobs executed by ARQ workers."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.db import async_session_factory
from app.domain.schemas import CompletenessEval
from app.models import DiagnosisSession, ReportGenerationJob
from app.observability import trace_agent, trace_turn
from app.repository import SessionRepository
from app.services.model_service import DiagnosisModel, create_model
from app.services.knowledge import (
    knowledge_retrieval_service,
    persist_report_evidences,
    validate_report_citations,
)

logger = logging.getLogger(__name__)


def _parse_json(value: str, default):
    try:
        return json.loads(value) if value else default
    except (json.JSONDecodeError, TypeError):
        return default


@dataclass(frozen=True)
class ReportContext:
    """Immutable conversation snapshot captured when generation is requested."""

    session_id: str
    raw_facts: List[str]
    completeness: CompletenessEval
    scene: Dict[str, str]
    messages: List[Dict[str, str]]

    @classmethod
    def from_session(cls, session: DiagnosisSession) -> "ReportContext":
        score_detail = _parse_json(session.score_detail, {})
        raw_facts = _parse_json(session.metrics, [])
        if isinstance(raw_facts, dict):
            raw_facts = [f"{key}: {value}" for key, value in raw_facts.items()]
        if not isinstance(raw_facts, list):
            raw_facts = []
        return cls(
            session_id=session.id,
            raw_facts=raw_facts,
            completeness=CompletenessEval(
                score=session.score or score_detail.get("score", 0),
                summary=score_detail.get("summary", ""),
                missing_aspects=score_detail.get("missing_aspects", []),
                next_question=score_detail.get("next_question", ""),
            ),
            scene=_parse_json(session.scene, {}),
            messages=[
                {"role": message.role, "content": message.content}
                for message in (session.messages or [])
            ],
        )

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "raw_facts": self.raw_facts,
            "completeness": self.completeness.model_dump(),
            "scene": self.scene,
            "messages": self.messages,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "ReportContext":
        return cls(
            session_id=str(value["session_id"]),
            raw_facts=list(value.get("raw_facts") or []),
            completeness=CompletenessEval(**(value.get("completeness") or {})),
            scene=dict(value.get("scene") or {}),
            messages=list(value.get("messages") or []),
        )


class ReportJobService:
    """Claim and execute report jobs with PostgreSQL-backed idempotency."""

    def __init__(
        self,
        *,
        model_factory: Callable[[], DiagnosisModel] = create_model,
        session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
        max_attempts: int = settings.background_job_max_attempts,
    ) -> None:
        self._model_factory = model_factory
        self._session_factory = session_factory
        self._max_attempts = max_attempts

    async def run(self, job_id: str, *, worker_id: str) -> bool:
        claimed = await self._claim(job_id, worker_id)
        if claimed is None:
            return False
        context, attempt_count = claimed
        return await self._run_claimed(
            job_id,
            worker_id=worker_id,
            context=context,
            attempt_count=attempt_count,
        )

    @trace_turn(
        name="Background report turn",
        node_key="conversation.background_report_turn",
        session_id=lambda _self, _job_id, *, context, **_kwargs: context.session_id,
    )
    @trace_agent(name="Background report generation", node_key="conversation.background_report")
    async def _run_claimed(
        self,
        job_id: str,
        *,
        worker_id: str,
        context: ReportContext,
        attempt_count: int,
    ) -> bool:
        try:
            model = self._model_factory()
            query = "\n".join([
                context.scene.get("industry", ""),
                *context.raw_facts,
                *[
                    message["content"]
                    for message in context.messages[-8:]
                    if message.get("role") == "user"
                ],
            ])
            evidence = await knowledge_retrieval_service.retrieve(
                query,
                context.scene,
                limit=5,
            )
            markdown = await model.generate_report(
                context.raw_facts,
                context.completeness,
                context.scene,
                messages=context.messages,
                evidence=evidence,
            )

            async with self._session_factory() as db:
                job = await db.get(ReportGenerationJob, job_id)
                if job is None or job.state != "running" or job.worker_id != worker_id:
                    return False
                repo = SessionRepository.for_system(db)
                markdown, selected = await validate_report_citations(db, markdown, evidence)
                report = await repo.save_report(
                    context.session_id,
                    markdown,
                    diagnosis={
                        "scene": context.scene,
                        "raw_facts": context.raw_facts,
                        "completeness": context.completeness.model_dump(),
                    },
                )
                await persist_report_evidences(
                    db,
                    report_id=report.id,
                    selected=selected,
                )
                await repo.finish_report_generation(context.session_id)
                job.state = "completed"
                job.error = None
                job.finished_at = datetime.utcnow()
                await db.commit()
            logger.info("Report job completed: job_id=%s session_id=%s", job_id, context.session_id)
            return True
        except asyncio.CancelledError:
            await self._record_failure(job_id, context.session_id, attempt_count, worker_id, "报告生成任务被中断")
            raise
        except Exception as exc:
            logger.exception("Report job failed: %s", job_id)
            await self._record_failure(
                job_id,
                context.session_id,
                attempt_count,
                worker_id,
                str(exc)[:2000],
            )
            raise

    async def _claim(
        self,
        job_id: str,
        worker_id: str,
    ) -> tuple[ReportContext, int] | None:
        now = datetime.utcnow()
        async with self._session_factory() as db:
            result = await db.execute(
                update(ReportGenerationJob)
                .where(
                    ReportGenerationJob.id == job_id,
                    ReportGenerationJob.state == "queued",
                )
                .values(
                    state="running",
                    worker_id=worker_id,
                    started_at=now,
                    finished_at=None,
                    error=None,
                    attempt_count=ReportGenerationJob.attempt_count + 1,
                )
                .returning(
                    ReportGenerationJob.context_snapshot,
                    ReportGenerationJob.attempt_count,
                )
            )
            row = result.one_or_none()
            await db.commit()
        if row is None:
            return None
        return ReportContext.from_dict(row.context_snapshot), int(row.attempt_count)

    async def _record_failure(
        self,
        job_id: str,
        session_id: str,
        attempt_count: int,
        worker_id: str,
        error: str,
    ) -> None:
        retrying = attempt_count < self._max_attempts
        async with self._session_factory() as db:
            job = await db.get(ReportGenerationJob, job_id)
            if job is None or job.state != "running" or job.worker_id != worker_id:
                return
            job.state = "queued" if retrying else "failed"
            job.error = error
            job.worker_id = None
            job.finished_at = None if retrying else datetime.utcnow()
            if not retrying:
                await SessionRepository.for_system(db).finish_report_generation(
                    session_id,
                    error="诊断报告生成失败，请稍后重试",
                )
            await db.commit()


report_job_service = ReportJobService()
