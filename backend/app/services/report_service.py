"""Background diagnosis report generation with per-session concurrency control."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import async_session_factory
from app.domain.schemas import CompletenessEval
from app.models import DiagnosisSession
from app.repository import SessionRepository
from app.services.model_service import DiagnosisModel, create_model

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


class ReportTaskManager:
    """Own report tasks and persist their completion independently of requests."""

    def __init__(
        self,
        *,
        model_factory: Callable[[], DiagnosisModel] = create_model,
        session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    ):
        self._model_factory = model_factory
        self._session_factory = session_factory
        self._tasks: Dict[str, asyncio.Task[None]] = {}

    async def startup(self) -> None:
        async with self._session_factory() as db:
            repo = SessionRepository.for_system(db)
            await repo.reset_running_report_generations()
            await db.commit()

    def start(self, context: ReportContext) -> asyncio.Task[None]:
        active = self._tasks.get(context.session_id)
        if active and not active.done():
            raise RuntimeError("该会话已有诊断报告正在生成")

        task = asyncio.create_task(
            self._generate(context),
            name=f"report:{context.session_id}",
        )
        self._tasks[context.session_id] = task
        task.add_done_callback(
            lambda completed: self._remove(context.session_id, completed)
        )
        return task

    async def cancel(self, session_id: str) -> None:
        task = self._tasks.get(session_id)
        if not task or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _remove(self, session_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(session_id) is task:
            self._tasks.pop(session_id, None)

    async def _generate(self, context: ReportContext) -> None:
        try:
            model = self._model_factory()
            markdown = await model.generate_report(
                context.raw_facts,
                context.completeness,
                context.scene,
                messages=context.messages,
            )

            async with self._session_factory() as db:
                repo = SessionRepository.for_system(db)
                await repo.save_report(
                    context.session_id,
                    markdown,
                    diagnosis={
                        "scene": context.scene,
                        "raw_facts": context.raw_facts,
                        "completeness": context.completeness.model_dump(),
                    },
                )
                await repo.finish_report_generation(context.session_id)
                await db.commit()
            logger.info("Background report generated for session %s", context.session_id)
        except asyncio.CancelledError:
            await self._mark_failed(context.session_id, "报告生成任务已取消，请重新生成")
            raise
        except Exception:
            logger.exception(
                "Background report generation failed for session %s",
                context.session_id,
            )
            await self._mark_failed(context.session_id, "诊断报告生成失败，请稍后重试")

    async def _mark_failed(self, session_id: str, message: str) -> None:
        try:
            async with self._session_factory() as db:
                await SessionRepository.for_system(db).finish_report_generation(
                    session_id,
                    error=message,
                )
                await db.commit()
        except Exception:
            logger.exception(
                "Failed to persist report task failure for session %s",
                session_id,
            )


report_task_manager = ReportTaskManager()
