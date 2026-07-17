"""Shared transactional lifecycle changes for knowledge document versions."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    KnowledgeAuditEvent,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeVectorSyncJob,
)


def utcnow() -> datetime:
    return datetime.utcnow()


async def publish_version(
    db: AsyncSession,
    version: KnowledgeDocumentVersion,
    *,
    effective_from: datetime | None = None,
    actor_role: str = "system",
) -> list[KnowledgeVectorSyncJob]:
    """Publish one parsed version and supersede the document's prior current version."""
    effective_at = effective_from or utcnow()
    document = await db.get(KnowledgeDocument, version.document_id)
    if document is None:
        raise ValueError("Knowledge document no longer exists")

    prior_versions = list((await db.execute(
        select(KnowledgeDocumentVersion).where(
            KnowledgeDocumentVersion.document_id == version.document_id,
            KnowledgeDocumentVersion.status == "published",
            KnowledgeDocumentVersion.id != version.id,
        )
    )).scalars().all())
    for prior in prior_versions:
        prior.status = "superseded"
        prior.effective_to = effective_at

    version.status = "published"
    version.effective_from = effective_at
    version.effective_to = None
    document.current_version_id = version.id
    document.status = "published"

    sync_jobs = [
        KnowledgeVectorSyncJob(
            id=uuid.uuid4().hex,
            version_id=prior.id,
            operation="delete",
            state="queued",
        )
        for prior in prior_versions
    ]
    sync_jobs.append(KnowledgeVectorSyncJob(
        id=uuid.uuid4().hex,
        version_id=version.id,
        operation="activate",
        state="queued",
    ))
    db.add_all(sync_jobs)
    db.add(KnowledgeAuditEvent(
        event_type="version_published",
        document_id=version.document_id,
        version_id=version.id,
        actor_role=actor_role,
        detail={"superseded_version_ids": [item.id for item in prior_versions]},
    ))
    return sync_jobs


async def revoke_version(
    db: AsyncSession,
    version: KnowledgeDocumentVersion,
    *,
    actor_role: str = "system",
) -> KnowledgeVectorSyncJob | None:
    """Revoke a version and queue removal of its vectors."""
    if version.status == "revoked":
        return None
    document = await db.get(KnowledgeDocument, version.document_id)
    if document is None:
        raise ValueError("Knowledge document no longer exists")

    version.status = "revoked"
    version.effective_to = utcnow()
    if document.current_version_id == version.id:
        document.current_version_id = None
        document.status = "revoked"

    sync_job = KnowledgeVectorSyncJob(
        id=uuid.uuid4().hex,
        version_id=version.id,
        operation="delete",
        state="queued",
    )
    db.add(sync_job)
    db.add(KnowledgeAuditEvent(
        event_type="version_revoked",
        document_id=version.document_id,
        version_id=version.id,
        actor_role=actor_role,
        detail={},
    ))
    return sync_job
