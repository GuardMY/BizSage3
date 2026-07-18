"""Authenticated APIs for administering and consuming platform knowledge."""

import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import Principal, get_current_principal, require_admin
from app.db import get_session as get_db_session
from app.knowledge_schemas import (
    KnowledgeCatalogSyncItemResponse,
    KnowledgeCatalogSyncRunResponse,
    KnowledgeDocumentResponse,
    KnowledgeIngestionJobResponse,
    KnowledgeRetrievalPolicyResponse,
    KnowledgeRetrievalPolicyUpdate,
    KnowledgeSearchResultResponse,
    KnowledgeVersionResponse,
    PublishVersionRequest,
    ReportEvidenceResponse,
)
from app.models import (
    DiagnosisSession,
    KnowledgeCatalogSyncRun,
    KnowledgeAuditEvent,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIngestionJob,
    Report,
    ReportEvidence,
)
from app.services.knowledge import (
    SOURCE_TYPES,
    content_type_for,
    extension_for,
    knowledge_retrieval_service,
    knowledge_storage,
    parse_document,
    parse_tags,
    safe_filename,
    sha256,
    storage_key_for,
    utcnow,
)
from app.services.industry_catalog import industry_catalog_sync_service
from app.services.knowledge_lifecycle import publish_version, revoke_version
from app.services.task_queue import task_queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


def _percent(value: float, *, maximum: float = 1.0) -> float:
    return round(max(0.0, min(value / maximum, 1.0)) * 100, 1)


def _naive(value: datetime | None) -> datetime:
    if value is None:
        return utcnow()
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _latest_job(version: KnowledgeDocumentVersion) -> KnowledgeIngestionJob | None:
    return (version.ingestion_jobs or [None])[0]


def _job_response(job: KnowledgeIngestionJob | None) -> KnowledgeIngestionJobResponse | None:
    if job is None:
        return None
    return KnowledgeIngestionJobResponse(
        id=job.id,
        state=job.state,
        parser=job.parser,
        error=job.error,
        retry_count=job.retry_count,
        indexed_at=job.indexed_at,
        created_at=job.created_at,
    )


def _version_response(version: KnowledgeDocumentVersion) -> KnowledgeVersionResponse:
    return KnowledgeVersionResponse(
        id=version.id,
        document_id=version.document_id,
        version_no=version.version_no,
        original_filename=version.original_filename,
        content_type=version.content_type,
        source_type=version.source_type,
        sha256=version.sha256,
        status=version.status,
        effective_from=version.effective_from,
        effective_to=version.effective_to,
        industry_tags=version.industry_tags or [],
        sub_industry_tags=version.sub_industry_tags or [],
        business_mode_tags=version.business_mode_tags or [],
        operating_stage_tags=version.operating_stage_tags or [],
        chunk_count=len(version.chunks or []),
        latest_job=_job_response(_latest_job(version)),
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


def _document_response(document: KnowledgeDocument) -> KnowledgeDocumentResponse:
    return KnowledgeDocumentResponse(
        id=document.id,
        title=document.title,
        managed_source_key=document.managed_source_key,
        current_version_id=document.current_version_id,
        status=document.status,
        created_at=document.created_at,
        updated_at=document.updated_at,
        versions=[_version_response(version) for version in (document.versions or [])],
    )


def _catalog_sync_response(run: KnowledgeCatalogSyncRun) -> KnowledgeCatalogSyncRunResponse:
    items = list(run.items or [])
    counts = {
        state: sum(item.state == state for item in items)
        for state in ("queued", "running", "published", "skipped", "failed", "revoked")
    }
    completed = sum(counts[state] for state in ("published", "skipped", "failed", "revoked"))
    total = len(items)
    return KnowledgeCatalogSyncRunResponse(
        id=run.id,
        trigger=run.trigger,
        state=run.state,
        error=run.error,
        total_count=total,
        pending_count=counts["queued"],
        processing_count=counts["running"],
        published_count=counts["published"],
        skipped_count=counts["skipped"],
        failed_count=counts["failed"],
        revoked_count=counts["revoked"],
        progress_percent=100 if run.state == "completed" and total == 0 else round(completed * 100 / max(total, 1)),
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        items=[KnowledgeCatalogSyncItemResponse(
            id=item.id,
            source_key=item.source_key,
            filename=item.filename,
            sha256=item.sha256,
            action=item.action,
            state=item.state,
            document_id=item.document_id,
            version_id=item.version_id,
            error=item.error,
            retry_count=item.retry_count,
            started_at=item.started_at,
            finished_at=item.finished_at,
        ) for item in items],
    )


def _audit(
    db: AsyncSession,
    event_type: str,
    *,
    document_id: str | None,
    version_id: str | None,
    actor_role: str = "admin",
    detail: dict | None = None,
) -> None:
    db.add(KnowledgeAuditEvent(
        event_type=event_type,
        document_id=document_id,
        version_id=version_id,
        actor_role=actor_role,
        detail=detail or {},
    ))


async def _read_upload(file: UploadFile) -> tuple[str, bytes, str]:
    filename = safe_filename(file.filename or "")
    extension = extension_for(filename)
    if extension not in {".docx", ".md", ".markdown", ".txt"}:
        raise HTTPException(status_code=422, detail="仅支持 DOCX、Markdown 和 TXT 文件")
    from app.config import settings
    content = await file.read(settings.knowledge_upload_max_bytes + 1)
    if not content:
        raise HTTPException(status_code=422, detail="上传文件不能为空")
    if len(content) > settings.knowledge_upload_max_bytes:
        raise HTTPException(status_code=413, detail="单个原件不能超过 20 MB")
    return filename, content, content_type_for(extension)


def _validate_source_type(value: str) -> str:
    if value not in SOURCE_TYPES:
        raise HTTPException(status_code=422, detail="资料类型必须是 methodology、benchmark_rule 或 case_sop")
    return value


async def _prepare_version(
    *,
    document_id: str,
    version_no: int,
    file: UploadFile,
    source_type: str,
    industry_tags: str,
    sub_industry_tags: str,
    business_mode_tags: str,
    operating_stage_tags: str,
) -> KnowledgeDocumentVersion:
    source_type = _validate_source_type(source_type)
    filename, content, content_type = await _read_upload(file)
    version = KnowledgeDocumentVersion(
        id=uuid.uuid4().hex,
        document_id=document_id,
        version_no=version_no,
        original_filename=filename,
        content_type=content_type,
        source_type=source_type,
        sha256=sha256(content),
        storage_key="pending",
        status="draft",
        industry_tags=parse_tags(industry_tags),
        sub_industry_tags=parse_tags(sub_industry_tags),
        business_mode_tags=parse_tags(business_mode_tags),
        operating_stage_tags=parse_tags(operating_stage_tags),
    )
    version.storage_key = storage_key_for(version.id, filename)
    await knowledge_storage.put(version.storage_key, content, content_type)
    return version


async def _remove_orphaned_upload(storage_key: str) -> None:
    try:
        await knowledge_storage.delete(storage_key)
    except Exception:
        logger.exception("Failed to remove orphaned knowledge object: %s", storage_key)


async def _enqueue_ingestion(job_id: str) -> None:
    try:
        await task_queue.enqueue_ingestion(job_id)
    except Exception:
        # The durable queued row is reconciled by the worker.
        logger.exception("Failed to enqueue knowledge ingestion job: %s", job_id)


async def _enqueue_vector_sync_jobs(job_ids: list[str]) -> None:
    for job_id in job_ids:
        try:
            await task_queue.enqueue_vector_sync(job_id)
        except Exception:
            logger.exception("Failed to enqueue knowledge vector sync job: %s", job_id)


async def _enqueue_catalog_sync(run_id: str) -> None:
    try:
        await task_queue.enqueue_catalog_sync(run_id)
    except Exception:
        logger.exception("Failed to enqueue industry catalog sync: %s", run_id)


async def _load_document(db: AsyncSession, document_id: str) -> KnowledgeDocument | None:
    result = await db.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.id == document_id)
        .options(
            selectinload(KnowledgeDocument.versions).selectinload(KnowledgeDocumentVersion.chunks),
            selectinload(KnowledgeDocument.versions).selectinload(KnowledgeDocumentVersion.ingestion_jobs),
        )
    )
    return result.scalar_one_or_none()


async def _load_version(db: AsyncSession, version_id: str) -> KnowledgeDocumentVersion | None:
    result = await db.execute(
        select(KnowledgeDocumentVersion)
        .where(KnowledgeDocumentVersion.id == version_id)
        .options(
            selectinload(KnowledgeDocumentVersion.document),
            selectinload(KnowledgeDocumentVersion.chunks),
            selectinload(KnowledgeDocumentVersion.ingestion_jobs),
        )
    )
    return result.scalar_one_or_none()


@router.get(
    "/admin/knowledge/search",
    response_model=list[KnowledgeSearchResultResponse],
    dependencies=[Depends(require_admin)],
)
async def search_knowledge(
    query: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    normalized_query = query.strip()
    if not normalized_query:
        raise HTTPException(status_code=422, detail="检索内容不能为空")
    try:
        evidence = await knowledge_retrieval_service.retrieve(
            normalized_query,
            {},
            limit=limit,
            raise_on_error=True,
        )
    except Exception as exc:
        logger.exception("Admin knowledge search failed")
        raise HTTPException(status_code=503, detail="知识库检索暂时不可用") from exc

    return [KnowledgeSearchResultResponse(
        chunk_id=item.chunk_id,
        document_id=item.document_id,
        version_id=item.version_id,
        document_title=item.document_title,
        source_type=item.source_type,
        version_no=item.version_no,
        quote=item.quote,
        locator=item.locator,
        rank=item.rank,
        semantic_score_percent=_percent(item.semantic_score),
        keyword_match_percent=_percent(item.keyword_score),
        source_weight_percent=round(item.source_weight * 100, 1),
        combined_score_percent=_percent(item.combined_score, maximum=1.25),
    ) for item in evidence]


@router.get(
    "/admin/knowledge/retrieval-policy",
    response_model=KnowledgeRetrievalPolicyResponse,
    dependencies=[Depends(require_admin)],
)
async def get_knowledge_retrieval_policy():
    return KnowledgeRetrievalPolicyResponse(
        strategy=await knowledge_retrieval_service.get_global_strategy(),
    )


@router.put(
    "/admin/knowledge/retrieval-policy",
    response_model=KnowledgeRetrievalPolicyResponse,
    dependencies=[Depends(require_admin)],
)
async def update_knowledge_retrieval_policy(body: KnowledgeRetrievalPolicyUpdate):
    return KnowledgeRetrievalPolicyResponse(
        strategy=await knowledge_retrieval_service.set_global_strategy(body.strategy),
    )


@router.get(
    "/admin/knowledge/documents",
    response_model=list[KnowledgeDocumentResponse],
    dependencies=[Depends(require_admin)],
)
async def list_knowledge_documents(db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(
        select(KnowledgeDocument)
        .order_by(KnowledgeDocument.updated_at.desc())
        .options(
            selectinload(KnowledgeDocument.versions).selectinload(KnowledgeDocumentVersion.chunks),
            selectinload(KnowledgeDocument.versions).selectinload(KnowledgeDocumentVersion.ingestion_jobs),
        )
    )
    return [_document_response(document) for document in result.scalars().all()]


async def _load_catalog_sync_run(
    db: AsyncSession,
    run_id: str,
) -> KnowledgeCatalogSyncRun | None:
    return (await db.execute(
        select(KnowledgeCatalogSyncRun)
        .where(KnowledgeCatalogSyncRun.id == run_id)
        .options(selectinload(KnowledgeCatalogSyncRun.items))
    )).scalar_one_or_none()


@router.get(
    "/admin/knowledge/industry-sync/latest",
    response_model=KnowledgeCatalogSyncRunResponse | None,
    dependencies=[Depends(require_admin)],
)
async def get_latest_industry_sync(db: AsyncSession = Depends(get_db_session)):
    run = (await db.execute(
        select(KnowledgeCatalogSyncRun)
        .order_by(KnowledgeCatalogSyncRun.created_at.desc())
        .limit(1)
        .options(selectinload(KnowledgeCatalogSyncRun.items))
    )).scalar_one_or_none()
    return _catalog_sync_response(run) if run is not None else None


@router.post(
    "/admin/knowledge/industry-sync",
    response_model=KnowledgeCatalogSyncRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
async def start_industry_sync(db: AsyncSession = Depends(get_db_session)):
    run, created = await industry_catalog_sync_service.request_run("manual")
    if created:
        await _enqueue_catalog_sync(run.id)
    loaded = await _load_catalog_sync_run(db, run.id)
    return _catalog_sync_response(loaded or run)


@router.post(
    "/admin/knowledge/industry-sync/{run_id}/retry-failed",
    response_model=KnowledgeCatalogSyncRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
async def retry_failed_industry_sync(
    run_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    if await _load_catalog_sync_run(db, run_id) is None:
        raise HTTPException(status_code=404, detail="同步批次不存在")
    try:
        run, created = await industry_catalog_sync_service.request_failed_retry(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if created:
        await _enqueue_catalog_sync(run.id)
    loaded = await _load_catalog_sync_run(db, run.id)
    return _catalog_sync_response(loaded or run)


@router.post(
    "/admin/knowledge/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_knowledge_document(
    title: Annotated[str, Form(min_length=1, max_length=240)],
    source_type: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    industry_tags: Annotated[str, Form()] = "",
    sub_industry_tags: Annotated[str, Form()] = "",
    business_mode_tags: Annotated[str, Form()] = "",
    operating_stage_tags: Annotated[str, Form()] = "",
    db: AsyncSession = Depends(get_db_session),
):
    clean_title = title.strip()
    if not clean_title:
        raise HTTPException(status_code=422, detail="资料标题不能为空")
    document = KnowledgeDocument(id=uuid.uuid4().hex, title=clean_title, status="draft")
    version = await _prepare_version(
        document_id=document.id,
        version_no=1,
        file=file,
        source_type=source_type,
        industry_tags=industry_tags,
        sub_industry_tags=sub_industry_tags,
        business_mode_tags=business_mode_tags,
        operating_stage_tags=operating_stage_tags,
    )
    job = KnowledgeIngestionJob(id=uuid.uuid4().hex, version_id=version.id, state="queued")
    try:
        db.add_all([document, version, job])
        _audit(db, "document_uploaded", document_id=document.id, version_id=version.id, detail={"filename": version.original_filename})
        await db.commit()
    except Exception:
        await db.rollback()
        await _remove_orphaned_upload(version.storage_key)
        raise
    loaded = await _load_document(db, document.id)
    await _enqueue_ingestion(job.id)
    return _document_response(loaded or document)


@router.post(
    "/admin/knowledge/documents/{document_id}/versions",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
async def create_knowledge_document_version(
    document_id: str,
    source_type: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    industry_tags: Annotated[str, Form()] = "",
    sub_industry_tags: Annotated[str, Form()] = "",
    business_mode_tags: Annotated[str, Form()] = "",
    operating_stage_tags: Annotated[str, Form()] = "",
    db: AsyncSession = Depends(get_db_session),
):
    document = await _load_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="资料不存在")
    if document.managed_source_key:
        raise HTTPException(status_code=409, detail="目录托管资料只能通过行业文档同步更新")
    await db.rollback()
    version = await _prepare_version(
        document_id=document_id,
        version_no=0,
        file=file,
        source_type=source_type,
        industry_tags=industry_tags,
        sub_industry_tags=sub_industry_tags,
        business_mode_tags=business_mode_tags,
        operating_stage_tags=operating_stage_tags,
    )
    job = KnowledgeIngestionJob(id=uuid.uuid4().hex, version_id=version.id, state="queued")
    try:
        locked_document = (await db.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.id == document_id)
            .with_for_update()
        )).scalar_one_or_none()
        if locked_document is None:
            raise HTTPException(status_code=404, detail="资料不存在")
        version.version_no = int((await db.execute(
            select(func.max(KnowledgeDocumentVersion.version_no)).where(
                KnowledgeDocumentVersion.document_id == document_id
            )
        )).scalar_one() or 0) + 1
        db.add_all([version, job])
        _audit(db, "version_uploaded", document_id=document_id, version_id=version.id, detail={"version_no": version.version_no})
        await db.commit()
    except Exception:
        await db.rollback()
        await _remove_orphaned_upload(version.storage_key)
        raise
    loaded = await _load_document(db, document_id)
    await _enqueue_ingestion(job.id)
    return _document_response(loaded or locked_document)


@router.post(
    "/admin/knowledge/versions/{version_id}/retry",
    response_model=KnowledgeVersionResponse,
    dependencies=[Depends(require_admin)],
)
async def retry_knowledge_ingestion(
    version_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    version = await _load_version(db, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="资料版本不存在")
    if version.document.managed_source_key:
        raise HTTPException(status_code=409, detail="目录托管资料请通过同步批次重试")
    if version.status not in {"draft", "parsing"}:
        raise HTTPException(status_code=409, detail="只有草稿或解析失败的版本可以重试")
    job = _latest_job(version)
    if job is None:
        job = KnowledgeIngestionJob(version_id=version.id, state="queued")
        db.add(job)
    else:
        if job.state == "running":
            raise HTTPException(status_code=409, detail="知识入库任务正在执行")
        job.state = "queued"
        job.error = None
        job.worker_id = None
        job.started_at = None
        job.finished_at = None
    _audit(db, "ingestion_retried", document_id=version.document_id, version_id=version.id)
    await db.commit()
    await _enqueue_ingestion(job.id)
    refreshed = await _load_version(db, version.id)
    return _version_response(refreshed or version)


@router.post(
    "/admin/knowledge/versions/{version_id}/publish",
    response_model=KnowledgeVersionResponse,
    dependencies=[Depends(require_admin)],
)
async def publish_knowledge_version(
    version_id: str,
    body: PublishVersionRequest,
    db: AsyncSession = Depends(get_db_session),
):
    version = await _load_version(db, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="资料版本不存在")
    if version.document.managed_source_key:
        raise HTTPException(status_code=409, detail="目录托管资料由系统自动发布")
    if version.status != "pending_review":
        raise HTTPException(status_code=409, detail="只有完成解析、等待审核的版本可以发布")
    sync_jobs = await publish_version(
        db,
        version,
        effective_from=_naive(body.effective_from),
        actor_role="admin",
    )
    await db.commit()
    await _enqueue_vector_sync_jobs([job.id for job in sync_jobs])
    refreshed = await _load_version(db, version.id)
    return _version_response(refreshed or version)


@router.post(
    "/admin/knowledge/versions/{version_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
async def revoke_knowledge_version(
    version_id: str,
    db: AsyncSession = Depends(get_db_session),
):
    version = await _load_version(db, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="资料版本不存在")
    if version.document.managed_source_key:
        raise HTTPException(status_code=409, detail="目录托管资料请通过删除源文件后同步撤回")
    sync_job = await revoke_version(db, version, actor_role="admin")
    if sync_job is None:
        return None
    await db.commit()
    await _enqueue_vector_sync_jobs([sync_job.id])
    return None


async def _public_version_access(
    db: AsyncSession,
    version_id: str,
    principal: Principal,
) -> KnowledgeDocumentVersion:
    version = await _load_version(db, version_id)
    if version is None or version.status == "revoked":
        raise HTTPException(status_code=404, detail="资料不存在或已撤回")
    if principal.role != "admin" and version.status not in {"published", "superseded"}:
        raise HTTPException(status_code=403, detail="当前版本尚未发布")
    return version


@router.get("/knowledge/documents/{document_id}/versions/{version_id}/preview")
async def preview_knowledge_original(
    document_id: str,
    version_id: str,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
):
    version = await _public_version_access(db, version_id, principal)
    if version.document_id != document_id:
        raise HTTPException(status_code=404, detail="资料版本不存在")
    await db.commit()
    content = await knowledge_storage.get(version.storage_key)
    parsed = parse_document(version.original_filename, content)
    _audit(db, "original_previewed", document_id=document_id, version_id=version.id, actor_role=principal.role)
    await db.commit()
    return HTMLResponse(parsed.preview_html)


@router.get("/knowledge/documents/{document_id}/versions/{version_id}/original")
async def download_knowledge_original(
    document_id: str,
    version_id: str,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
):
    version = await _public_version_access(db, version_id, principal)
    if version.document_id != document_id:
        raise HTTPException(status_code=404, detail="资料版本不存在")
    await db.commit()
    content = await knowledge_storage.get(version.storage_key)
    _audit(db, "original_downloaded", document_id=document_id, version_id=version.id, actor_role=principal.role)
    await db.commit()
    encoded_name = quote(safe_filename(version.original_filename))
    return StreamingResponse(
        io.BytesIO(content),
        media_type=version.content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@router.get("/reports/{report_id}/evidences", response_model=list[ReportEvidenceResponse])
async def get_report_evidences(
    report_id: str,
    principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
):
    report_stmt = select(Report).join(DiagnosisSession).where(Report.id == report_id)
    if principal.role == "user":
        report_stmt = report_stmt.where(DiagnosisSession.owner_token_id == principal.token_id)
    report = (await db.execute(report_stmt)).scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    evidences = list((await db.execute(
        select(ReportEvidence)
        .where(ReportEvidence.report_id == report_id)
        .options(selectinload(ReportEvidence.version).selectinload(KnowledgeDocumentVersion.document))
        .order_by(ReportEvidence.evidence_no)
    )).scalars().all())
    response: list[ReportEvidenceResponse] = []
    for evidence in evidences:
        version = evidence.version
        # A revoked source intentionally has no title, quote, locator or status leaked.
        if version.status == "revoked":
            continue
        response.append(ReportEvidenceResponse(
            evidence_no=evidence.evidence_no,
            document_id=version.document.id,
            version_id=version.id,
            document_title=version.document.title,
            source_type=version.source_type,
            version_no=version.version_no,
            effective_from=version.effective_from,
            status=version.status,
            quote=evidence.quote,
            locator=evidence.locator or {},
            retrieved_at=evidence.retrieved_at,
        ))
    return response
