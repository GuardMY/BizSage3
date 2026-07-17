"""Durable reconciliation of repository-managed industry knowledge documents."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.db import async_session_factory
from app.models import (
    KnowledgeAuditEvent,
    KnowledgeCatalogSyncItem,
    KnowledgeCatalogSyncRun,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIngestionJob,
)
from app.services.knowledge import (
    KnowledgeStorage,
    knowledge_storage,
    sha256,
    storage_key_for,
    utcnow,
)
from app.services.knowledge_lifecycle import publish_version, revoke_version

logger = logging.getLogger(__name__)

CATALOG_ACTIVE_KEY = "industry_catalog"
TERMINAL_ITEM_STATES = {"published", "skipped", "failed", "revoked"}


@dataclass(frozen=True)
class CatalogFile:
    source_key: str
    filename: str
    content: bytes | None
    digest: str | None
    title: str | None
    industry: str | None
    sub_industry: str | None
    error: str | None = None


class IndustryCatalogSyncService:
    def __init__(
        self,
        *,
        catalog_dir: str | Path | None = None,
        storage: KnowledgeStorage | None = None,
        session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    ) -> None:
        self._catalog_dir = Path(catalog_dir or settings.industry_catalog_dir)
        self._storage = storage or knowledge_storage
        self._session_factory = session_factory

    async def request_run(
        self,
        trigger: str,
        *,
        source_keys: Iterable[str] | None = None,
    ) -> tuple[KnowledgeCatalogSyncRun, bool]:
        """Create one active run, or return the run another API replica created."""
        keys = sorted(set(source_keys or [])) or None
        async with self._session_factory() as db:
            active = (await db.execute(
                select(KnowledgeCatalogSyncRun).where(
                    KnowledgeCatalogSyncRun.active_key == CATALOG_ACTIVE_KEY
                )
            )).scalar_one_or_none()
            if active is not None:
                return active, False

            run = KnowledgeCatalogSyncRun(
                id=uuid.uuid4().hex,
                trigger=trigger,
                state="queued",
                active_key=CATALOG_ACTIVE_KEY,
                source_keys=keys,
            )
            db.add(run)
            try:
                await db.commit()
                return run, True
            except IntegrityError:
                await db.rollback()
                active = (await db.execute(
                    select(KnowledgeCatalogSyncRun).where(
                        KnowledgeCatalogSyncRun.active_key == CATALOG_ACTIVE_KEY
                    )
                )).scalar_one()
                return active, False

    async def request_failed_retry(
        self,
        run_id: str,
    ) -> tuple[KnowledgeCatalogSyncRun, bool]:
        async with self._session_factory() as db:
            keys = list((await db.execute(
                select(KnowledgeCatalogSyncItem.source_key).where(
                    KnowledgeCatalogSyncItem.run_id == run_id,
                    KnowledgeCatalogSyncItem.state == "failed",
                )
            )).scalars().all())
        if not keys:
            raise ValueError("当前同步批次没有失败项")
        return await self.request_run("retry", source_keys=keys)

    async def run(self, run_id: str, *, worker_id: str) -> list[str]:
        """Scan the catalog and create ordinary durable ingestion jobs."""
        run = await self._claim(run_id, worker_id)
        if run is None:
            return []

        try:
            files = self._scan(run.source_keys)
        except Exception as exc:
            logger.exception("Industry catalog scan failed: run_id=%s", run_id)
            await self._fail_run(run_id, str(exc)[:2000])
            return []

        job_ids: list[str] = []
        scan_has_errors = False
        for catalog_file in files:
            if catalog_file.error:
                scan_has_errors = True
                await self._record_file_error(run_id, catalog_file)
                continue
            try:
                job_id = await self._process_file(run_id, catalog_file)
                if job_id:
                    job_ids.append(job_id)
            except Exception as exc:
                scan_has_errors = True
                logger.exception(
                    "Industry catalog file processing failed: run_id=%s source=%s",
                    run_id,
                    catalog_file.source_key,
                )
                await self._record_file_error(run_id, catalog_file, str(exc)[:2000])

        if run.source_keys is None and not scan_has_errors:
            await self._revoke_deleted_files(
                run_id,
                {catalog_file.source_key for catalog_file in files},
            )

        async with self._session_factory() as db:
            current = await db.get(KnowledgeCatalogSyncRun, run_id)
            if current is not None and current.state == "scanning":
                current.state = "running"
                current.error = "部分文件扫描失败，已跳过自动撤回" if scan_has_errors else None
                await db.flush()
                await finalize_catalog_runs(db, {run_id})
                await db.commit()
        return list(dict.fromkeys(job_ids))

    async def _claim(
        self,
        run_id: str,
        worker_id: str,
    ) -> KnowledgeCatalogSyncRun | None:
        async with self._session_factory() as db:
            result = await db.execute(
                update(KnowledgeCatalogSyncRun)
                .where(
                    KnowledgeCatalogSyncRun.id == run_id,
                    KnowledgeCatalogSyncRun.state == "queued",
                )
                .values(
                    state="scanning",
                    worker_id=worker_id,
                    started_at=utcnow(),
                    finished_at=None,
                    error=None,
                )
                .returning(KnowledgeCatalogSyncRun.id)
            )
            if result.one_or_none() is None:
                await db.rollback()
                return None
            await db.commit()
            return await db.get(KnowledgeCatalogSyncRun, run_id)

    def _scan(self, source_keys: list[str] | None) -> list[CatalogFile]:
        root = self._catalog_dir.resolve()
        if not root.is_dir():
            raise RuntimeError(f"行业文档目录不存在或不可读：{root}")
        if not (root / "index.md").is_file():
            raise RuntimeError("行业文档目录缺少 index.md，拒绝执行同步和撤回")

        if source_keys is None:
            paths = sorted(
                path for path in root.glob("*.md")
                if path.name.casefold() != "index.md"
            )
        else:
            paths = []
            for source_key in source_keys:
                candidate = (root / source_key).resolve()
                try:
                    candidate.relative_to(root)
                except ValueError:
                    paths.append(root / f"__invalid__{len(paths)}.md")
                    continue
                paths.append(candidate)

        records: list[CatalogFile] = []
        requested_keys = source_keys or []
        for index, path in enumerate(paths):
            source_key = (
                requested_keys[index]
                if source_keys is not None
                else path.relative_to(root).as_posix()
            )
            if not path.is_file():
                records.append(CatalogFile(
                    source_key=source_key,
                    filename=Path(source_key).name,
                    content=None,
                    digest=None,
                    title=None,
                    industry=None,
                    sub_industry=None,
                    error="文件不存在或路径不合法",
                ))
                continue
            try:
                content = path.read_bytes()
                if not content:
                    raise ValueError("文件内容为空")
                if len(content) > settings.knowledge_upload_max_bytes:
                    raise ValueError("文件超过知识库单文件大小限制")
                metadata = self._frontmatter(content)
                title = self._required_text(metadata, "title")
                industry = self._required_text(metadata, "industry")
                sub_industry = self._required_text(metadata, "sub_industry")
                if metadata.get("source_type", "methodology") != "methodology":
                    raise ValueError("目录文档 source_type 必须为 methodology")
                if len(title) > 240:
                    raise ValueError("文档标题不能超过 240 个字符")
                records.append(CatalogFile(
                    source_key=source_key,
                    filename=path.name,
                    content=content,
                    digest=sha256(content),
                    title=title,
                    industry=industry,
                    sub_industry=sub_industry,
                ))
            except Exception as exc:
                records.append(CatalogFile(
                    source_key=source_key,
                    filename=path.name,
                    content=None,
                    digest=None,
                    title=None,
                    industry=None,
                    sub_industry=None,
                    error=str(exc)[:2000],
                ))
        return records

    @staticmethod
    def _frontmatter(content: bytes) -> dict[str, Any]:
        text = content.decode("utf-8-sig")
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            raise ValueError("缺少 Markdown frontmatter")
        try:
            end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
        except StopIteration as exc:
            raise ValueError("Markdown frontmatter 未闭合") from exc
        metadata = yaml.safe_load("\n".join(lines[1:end])) or {}
        if not isinstance(metadata, dict):
            raise ValueError("Markdown frontmatter 必须是对象")
        return metadata

    @staticmethod
    def _required_text(metadata: dict[str, Any], key: str) -> str:
        value = metadata.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Markdown frontmatter 缺少 {key}")
        return value.strip()

    async def _process_file(self, run_id: str, item: CatalogFile) -> str | None:
        assert item.content is not None
        assert item.digest and item.title and item.industry and item.sub_industry

        async with self._session_factory() as db:
            prior_item = (await db.execute(
                select(KnowledgeCatalogSyncItem).where(
                    KnowledgeCatalogSyncItem.run_id == run_id,
                    KnowledgeCatalogSyncItem.source_key == item.source_key,
                )
            )).scalar_one_or_none()
            if prior_item is not None and prior_item.state in TERMINAL_ITEM_STATES:
                return None
            if prior_item is not None and prior_item.ingestion_job_id:
                job = await db.get(KnowledgeIngestionJob, prior_item.ingestion_job_id)
                if job is not None and job.state in {"queued", "running"}:
                    return job.id if job.state == "queued" else None

            document = (await db.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.managed_source_key == item.source_key
                )
            )).scalar_one_or_none()
            latest = None
            latest_job = None
            current = None
            if document is not None:
                latest = (await db.execute(
                    select(KnowledgeDocumentVersion)
                    .where(KnowledgeDocumentVersion.document_id == document.id)
                    .order_by(KnowledgeDocumentVersion.version_no.desc())
                    .limit(1)
                )).scalar_one_or_none()
                if document.current_version_id:
                    current = await db.get(KnowledgeDocumentVersion, document.current_version_id)
                if latest is not None:
                    latest_job = (await db.execute(
                        select(KnowledgeIngestionJob)
                        .where(KnowledgeIngestionJob.version_id == latest.id)
                        .order_by(KnowledgeIngestionJob.created_at.desc())
                        .limit(1)
                    )).scalar_one_or_none()

            if current is not None and current.sha256 == item.digest and current.status == "published":
                await self._set_item(
                    db,
                    run_id,
                    item,
                    action="skip",
                    state="skipped",
                    document_id=document.id,
                    version_id=current.id,
                    finished=True,
                )
                await db.commit()
                return None

            if latest is not None and latest.sha256 == item.digest and latest.status != "revoked":
                if latest.status == "published":
                    document.current_version_id = latest.id
                    document.status = "published"
                    await self._set_item(
                        db,
                        run_id,
                        item,
                        action="skip",
                        state="skipped",
                        document_id=document.id,
                        version_id=latest.id,
                        finished=True,
                    )
                    await db.commit()
                    return None
                if latest.status == "pending_review":
                    await publish_version(db, latest, actor_role="system")
                    await self._set_item(
                        db,
                        run_id,
                        item,
                        action="update" if latest.version_no > 1 else "create",
                        state="published",
                        document_id=document.id,
                        version_id=latest.id,
                        finished=True,
                    )
                    await db.commit()
                    return None
                if latest_job is not None and latest_job.state in {"queued", "running", "failed"}:
                    if latest_job.state == "failed":
                        latest_job.state = "queued"
                        latest_job.error = None
                        latest_job.worker_id = None
                        latest_job.started_at = None
                        latest_job.finished_at = None
                        latest.status = "draft"
                    await self._set_item(
                        db,
                        run_id,
                        item,
                        action="update" if latest.version_no > 1 else "create",
                        state="running" if latest_job.state == "running" else "queued",
                        document_id=document.id,
                        version_id=latest.id,
                        ingestion_job_id=latest_job.id,
                    )
                    await db.commit()
                    return latest_job.id if latest_job.state == "queued" else None

        version_id = uuid.uuid4().hex
        storage_key = storage_key_for(version_id, item.filename)
        await self._storage.put(storage_key, item.content, "text/markdown")
        try:
            async with self._session_factory() as db:
                document = (await db.execute(
                    select(KnowledgeDocument)
                    .where(KnowledgeDocument.managed_source_key == item.source_key)
                    .with_for_update()
                )).scalar_one_or_none()
                is_new = document is None
                if document is None:
                    document = KnowledgeDocument(
                        id=uuid.uuid4().hex,
                        title=item.title,
                        managed_source_key=item.source_key,
                        status="draft",
                    )
                    db.add(document)
                    await db.flush()
                    version_no = 1
                else:
                    document.title = item.title
                    version_no = int((await db.execute(
                        select(func.max(KnowledgeDocumentVersion.version_no)).where(
                            KnowledgeDocumentVersion.document_id == document.id
                        )
                    )).scalar_one() or 0) + 1
                    if document.current_version_id is None:
                        document.status = "draft"

                version = KnowledgeDocumentVersion(
                    id=version_id,
                    document_id=document.id,
                    version_no=version_no,
                    original_filename=item.filename,
                    content_type="text/markdown",
                    source_type="methodology",
                    sha256=item.digest,
                    storage_key=storage_key,
                    status="draft",
                    industry_tags=[item.industry],
                    sub_industry_tags=[item.sub_industry],
                    business_mode_tags=[],
                    operating_stage_tags=[],
                )
                job = KnowledgeIngestionJob(
                    id=uuid.uuid4().hex,
                    version_id=version.id,
                    state="queued",
                )
                db.add_all([version, job])
                await self._set_item(
                    db,
                    run_id,
                    item,
                    action="create" if is_new else "update",
                    state="queued",
                    document_id=document.id,
                    version_id=version.id,
                    ingestion_job_id=job.id,
                )
                db.add(KnowledgeAuditEvent(
                    event_type="catalog_version_queued",
                    document_id=document.id,
                    version_id=version.id,
                    actor_role="system",
                    detail={"source_key": item.source_key, "sha256": item.digest},
                ))
                await db.commit()
                return job.id
        except Exception:
            try:
                await self._storage.delete(storage_key)
            except Exception:
                logger.exception("Failed to delete orphaned catalog object: %s", storage_key)
            raise

    async def _set_item(
        self,
        db: AsyncSession,
        run_id: str,
        source: CatalogFile,
        *,
        action: str,
        state: str,
        document_id: str | None = None,
        version_id: str | None = None,
        ingestion_job_id: str | None = None,
        error: str | None = None,
        finished: bool = False,
    ) -> KnowledgeCatalogSyncItem:
        item = (await db.execute(
            select(KnowledgeCatalogSyncItem).where(
                KnowledgeCatalogSyncItem.run_id == run_id,
                KnowledgeCatalogSyncItem.source_key == source.source_key,
            )
        )).scalar_one_or_none()
        if item is None:
            item = KnowledgeCatalogSyncItem(
                id=uuid.uuid4().hex,
                run_id=run_id,
                source_key=source.source_key,
                filename=source.filename,
                action=action,
                state=state,
            )
            db.add(item)
        item.filename = source.filename
        item.sha256 = source.digest
        item.action = action
        item.state = state
        item.document_id = document_id
        item.version_id = version_id
        item.ingestion_job_id = ingestion_job_id
        item.error = error
        item.started_at = item.started_at or (utcnow() if state == "running" else None)
        item.finished_at = utcnow() if finished else None
        return item

    async def _record_file_error(
        self,
        run_id: str,
        item: CatalogFile,
        error: str | None = None,
    ) -> None:
        async with self._session_factory() as db:
            await self._set_item(
                db,
                run_id,
                item,
                action="scan",
                state="failed",
                error=error or item.error or "文件处理失败",
                finished=True,
            )
            await db.commit()

    async def _revoke_deleted_files(self, run_id: str, seen_keys: set[str]) -> None:
        async with self._session_factory() as db:
            documents = list((await db.execute(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.managed_source_key.is_not(None)
                )
            )).scalars().all())
            for document in documents:
                source_key = document.managed_source_key
                if not source_key or source_key in seen_keys:
                    continue
                active_versions = list((await db.execute(
                    select(KnowledgeDocumentVersion)
                    .where(
                        KnowledgeDocumentVersion.document_id == document.id,
                        KnowledgeDocumentVersion.status.in_({
                            "draft", "parsing", "indexing", "pending_review", "published"
                        }),
                    )
                    .order_by(KnowledgeDocumentVersion.version_no.desc())
                )).scalars().all())
                if not active_versions:
                    continue
                for version in active_versions:
                    await revoke_version(db, version, actor_role="system")
                document.current_version_id = None
                document.status = "revoked"
                target = active_versions[0]
                source = CatalogFile(
                    source_key=source_key,
                    filename=target.original_filename,
                    content=None,
                    digest=target.sha256,
                    title=document.title,
                    industry=None,
                    sub_industry=None,
                )
                await self._set_item(
                    db,
                    run_id,
                    source,
                    action="revoke",
                    state="revoked",
                    document_id=document.id,
                    version_id=target.id,
                    finished=True,
                )
                db.add(KnowledgeAuditEvent(
                    event_type="catalog_source_removed",
                    document_id=document.id,
                    version_id=target.id,
                    actor_role="system",
                    detail={"source_key": source_key},
                ))
            await db.commit()

    async def _fail_run(self, run_id: str, error: str) -> None:
        async with self._session_factory() as db:
            run = await db.get(KnowledgeCatalogSyncRun, run_id)
            if run is None:
                return
            run.state = "failed"
            run.active_key = None
            run.error = error
            run.finished_at = utcnow()
            await db.commit()


async def mark_catalog_item_running(db: AsyncSession, ingestion_job_id: str) -> None:
    items = list((await db.execute(
        select(KnowledgeCatalogSyncItem).where(
            KnowledgeCatalogSyncItem.ingestion_job_id == ingestion_job_id,
            KnowledgeCatalogSyncItem.state == "queued",
        )
    )).scalars().all())
    for item in items:
        item.state = "running"
        item.started_at = item.started_at or utcnow()
        item.error = None


async def mark_catalog_item_finished(
    db: AsyncSession,
    ingestion_job_id: str,
    *,
    state: str,
    error: str | None = None,
    retrying: bool = False,
) -> None:
    items = list((await db.execute(
        select(KnowledgeCatalogSyncItem).where(
            KnowledgeCatalogSyncItem.ingestion_job_id == ingestion_job_id,
            KnowledgeCatalogSyncItem.state.in_({"queued", "running"}),
        )
    )).scalars().all())
    run_ids = {item.run_id for item in items}
    for item in items:
        item.state = "queued" if retrying else state
        item.error = error
        item.retry_count += 1 if error else 0
        item.finished_at = None if retrying else utcnow()
    await db.flush()
    await finalize_catalog_runs(db, run_ids)


async def finalize_catalog_runs(db: AsyncSession, run_ids: set[str]) -> None:
    for run_id in run_ids:
        run = await db.get(KnowledgeCatalogSyncRun, run_id)
        if run is None or run.state != "running":
            continue
        states = list((await db.execute(
            select(KnowledgeCatalogSyncItem.state).where(
                KnowledgeCatalogSyncItem.run_id == run_id
            )
        )).scalars().all())
        if any(state not in TERMINAL_ITEM_STATES for state in states):
            continue
        failed_count = sum(state == "failed" for state in states)
        run.state = (
            "failed" if states and failed_count == len(states)
            else "partial_failed" if failed_count
            else "completed"
        )
        run.active_key = None
        run.finished_at = utcnow()


industry_catalog_sync_service = IndustryCatalogSyncService()
