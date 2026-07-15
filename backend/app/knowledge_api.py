"""Authenticated APIs for administering and consuming platform knowledge."""

import asyncio
import io
import logging
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import Principal, get_current_principal, require_admin
from app.db import get_session as get_db_session
from app.knowledge_schemas import (
    KnowledgeDocumentResponse,
    KnowledgeIngestionJobResponse,
    KnowledgeVersionResponse,
    PublishVersionRequest,
    ReportEvidenceResponse,
)
from app.models import (
    DiagnosisSession,
    KnowledgeAuditEvent,
    KnowledgeChunk,
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
    knowledge_ingestion_manager,
    knowledge_storage,
    knowledge_vector_index,
    parse_document,
    parse_tags,
    safe_filename,
    sha256,
    storage_key_for,
    utcnow,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


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
        current_version_id=document.current_version_id,
        status=document.status,
        created_at=document.created_at,
        updated_at=document.updated_at,
        versions=[_version_response(version) for version in (document.versions or [])],
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


async def _create_version(
    db: AsyncSession,
    *,
    document: KnowledgeDocument,
    file: UploadFile,
    source_type: str,
    industry_tags: str,
    sub_industry_tags: str,
    business_mode_tags: str,
    operating_stage_tags: str,
) -> KnowledgeDocumentVersion:
    source_type = _validate_source_type(source_type)
    filename, content, content_type = await _read_upload(file)
    next_version = max((item.version_no for item in (document.versions or [])), default=0) + 1
    version = KnowledgeDocumentVersion(
        document_id=document.id,
        version_no=next_version,
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
    db.add(version)
    await db.flush()
    version.storage_key = storage_key_for(version.id, filename)
    await knowledge_storage.put(version.storage_key, content, content_type)
    job = KnowledgeIngestionJob(version_id=version.id, state="queued")
    db.add(job)
    return version


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
    document = KnowledgeDocument(title=clean_title, status="draft")
    db.add(document)
    await db.flush()
    version = await _create_version(
        db,
        document=document,
        file=file,
        source_type=source_type,
        industry_tags=industry_tags,
        sub_industry_tags=sub_industry_tags,
        business_mode_tags=business_mode_tags,
        operating_stage_tags=operating_stage_tags,
    )
    _audit(db, "document_uploaded", document_id=document.id, version_id=version.id, detail={"filename": version.original_filename})
    await db.commit()
    loaded = await _load_document(db, document.id)
    knowledge_ingestion_manager.start(version.id)
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
    version = await _create_version(
        db,
        document=document,
        file=file,
        source_type=source_type,
        industry_tags=industry_tags,
        sub_industry_tags=sub_industry_tags,
        business_mode_tags=business_mode_tags,
        operating_stage_tags=operating_stage_tags,
    )
    _audit(db, "version_uploaded", document_id=document.id, version_id=version.id, detail={"version_no": version.version_no})
    await db.commit()
    loaded = await _load_document(db, document.id)
    knowledge_ingestion_manager.start(version.id)
    return _document_response(loaded or document)


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
    if version.status not in {"draft", "parsing"}:
        raise HTTPException(status_code=409, detail="只有草稿或解析失败的版本可以重试")
    job = _latest_job(version)
    if job is None:
        job = KnowledgeIngestionJob(version_id=version.id, state="queued")
        db.add(job)
    else:
        job.state = "queued"
        job.error = None
    _audit(db, "ingestion_retried", document_id=version.document_id, version_id=version.id)
    await db.commit()
    knowledge_ingestion_manager.start(version.id)
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
    if version.status != "pending_review":
        raise HTTPException(status_code=409, detail="只有完成解析、等待审核的版本可以发布")
    effective_from = _naive(body.effective_from)
    prior_versions = list((await db.execute(
        select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.document_id == version.document_id,
            KnowledgeDocumentVersion.status == "published",
            KnowledgeDocumentVersion.id != version.id,
        )
    )).scalars().all())
    for prior in prior_versions:
        prior.status = "superseded"
        prior.effective_to = effective_from
    version.status = "published"
    version.effective_from = effective_from
    version.effective_to = None
    version.document.current_version_id = version.id
    version.document.status = "published"
    _audit(
        db,
        "version_published",
        document_id=version.document_id,
        version_id=version.id,
        detail={"superseded_version_ids": [item.id for item in prior_versions]},
    )
    await db.commit()
    try:
        for prior in prior_versions:
            await knowledge_vector_index.delete_version(prior.id)
        await knowledge_vector_index.activate_version(version.id)
    except Exception:
        logger.exception("Qdrant sync failed after publishing %s", version.id)
        async with db.begin():
            _audit(db, "vector_sync_failed", document_id=version.document_id, version_id=version.id)
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
    if version.status == "revoked":
        return None
    version.status = "revoked"
    version.effective_to = utcnow()
    if version.document.current_version_id == version.id:
        version.document.current_version_id = None
        version.document.status = "revoked"
    _audit(db, "version_revoked", document_id=version.document_id, version_id=version.id)
    await db.commit()
    try:
        await knowledge_vector_index.delete_version(version.id)
    except Exception:
        logger.exception("Qdrant cleanup failed after revoking %s", version.id)
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
