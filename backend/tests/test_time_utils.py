"""Regression tests for the application's UTC-to-China-time contract."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api_schemas import MessageSchema, SessionDetail, SessionSummary
from app.auth_schemas import TemporaryTokenResponse
from app.domain.schemas import ConversationCitation
from app.knowledge_schemas import (
    KnowledgeCatalogSyncItemResponse,
    KnowledgeCatalogSyncRunResponse,
    KnowledgeIngestionJobResponse,
    KnowledgeVersionResponse,
    ReportEvidenceResponse,
)
from app.time_utils import serialize_shanghai, to_shanghai


UTC_INSTANT = datetime(2026, 7, 19, 1, 2, 3)
SHANGHAI_INSTANT = "2026-07-19T09:02:03+08:00"


def test_naive_persisted_timestamp_is_interpreted_as_utc():
    assert to_shanghai(UTC_INSTANT).isoformat() == SHANGHAI_INSTANT
    assert serialize_shanghai(UTC_INSTANT) == SHANGHAI_INSTANT


def test_aware_timestamp_preserves_its_actual_instant():
    aware_utc = UTC_INSTANT.replace(tzinfo=timezone.utc)
    assert serialize_shanghai(aware_utc) == SHANGHAI_INSTANT


def test_api_response_models_emit_china_standard_time_for_all_datetime_fields():
    citation = ConversationCitation(
        citation_id="citation-1",
        source_type="web",
        title="Source",
        published_at=UTC_INSTANT,
    )
    session = SessionDetail(
        id="session-1",
        title="Session",
        status="collecting",
        stage="init",
        score=0,
        created_at=UTC_INSTANT,
        updated_at=UTC_INSTANT,
        messages=[MessageSchema(
            id="message-1",
            role="assistant",
            content="Hello",
            sequence=1,
            citations=[citation],
            created_at=UTC_INSTANT,
        )],
    )
    token = TemporaryTokenResponse(
        id="token-1",
        name="Token",
        token_prefix="bst_123",
        created_at=UTC_INSTANT,
        expires_at=UTC_INSTANT,
        last_used_at=UTC_INSTANT,
        revoked_at=UTC_INSTANT,
        status="active",
    )
    ingestion = KnowledgeIngestionJobResponse(
        id="job-1",
        state="completed",
        retry_count=0,
        indexed_at=UTC_INSTANT,
        created_at=UTC_INSTANT,
    )
    version = KnowledgeVersionResponse(
        id="version-1",
        document_id="document-1",
        version_no=1,
        original_filename="source.md",
        content_type="text/markdown",
        source_type="methodology",
        sha256="a" * 64,
        status="published",
        effective_from=UTC_INSTANT,
        effective_to=UTC_INSTANT,
        latest_job=ingestion,
        created_at=UTC_INSTANT,
        updated_at=UTC_INSTANT,
    )
    catalog = KnowledgeCatalogSyncRunResponse(
        id="run-1",
        trigger="manual",
        state="completed",
        total_count=1,
        pending_count=0,
        processing_count=0,
        published_count=1,
        skipped_count=0,
        failed_count=0,
        revoked_count=0,
        progress_percent=100,
        started_at=UTC_INSTANT,
        finished_at=UTC_INSTANT,
        created_at=UTC_INSTANT,
        updated_at=UTC_INSTANT,
        items=[KnowledgeCatalogSyncItemResponse(
            id="item-1",
            source_key="source",
            filename="source.md",
            action="create",
            state="published",
            retry_count=0,
            started_at=UTC_INSTANT,
            finished_at=UTC_INSTANT,
        )],
    )
    evidence = ReportEvidenceResponse(
        evidence_no=1,
        document_id="document-1",
        version_id="version-1",
        document_title="Source",
        source_type="methodology",
        version_no=1,
        effective_from=UTC_INSTANT,
        status="published",
        quote="Quote",
        retrieved_at=UTC_INSTANT,
    )

    assert session.model_dump(mode="json")["messages"][0]["citations"][0]["published_at"] == SHANGHAI_INSTANT
    assert token.model_dump(mode="json")["revoked_at"] == SHANGHAI_INSTANT
    assert version.model_dump(mode="json")["latest_job"]["indexed_at"] == SHANGHAI_INSTANT
    assert catalog.model_dump(mode="json")["items"][0]["finished_at"] == SHANGHAI_INSTANT
    assert evidence.model_dump(mode="json")["retrieved_at"] == SHANGHAI_INSTANT


@pytest.mark.asyncio
async def test_fastapi_response_serialization_uses_china_standard_time():
    app = FastAPI()
    session = SessionSummary(
        id="session-1",
        title="Session",
        status="collecting",
        stage="init",
        score=0,
        created_at=UTC_INSTANT,
        updated_at=UTC_INSTANT,
    )

    @app.get("/session", response_model=SessionSummary)
    async def get_session():
        return session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/session")

    assert response.json()["created_at"] == SHANGHAI_INSTANT
