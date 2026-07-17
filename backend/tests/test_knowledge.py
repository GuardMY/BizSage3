"""Lifecycle tests for versioned knowledge ingestion and report citations."""

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import (
    Base,
    KnowledgeAuditEvent,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIngestionJob,
    ReportEvidence,
)
from app.repository import SessionRepository
from app.services.knowledge import (
    EvidenceContext,
    KnowledgeIngestionService,
    KnowledgeRetrievalService,
    evidence_from_state,
    evidence_to_state,
    persist_report_evidences,
    validate_report_citations,
)


class FakeStorage:
    def __init__(self, content: bytes):
        self.content = content

    async def get(self, storage_key: str) -> bytes:
        return self.content


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorIndex:
    def __init__(self):
        self.indexed: list[tuple[str, int]] = []

    async def upsert_chunks(self, chunks, vectors, version) -> None:
        assert len(chunks) == len(vectors)
        self.indexed.append((version.id, len(chunks)))


class EmptyVectorIndex:
    async def search(self, vector, scene, limit):
        return []


def test_evidence_state_is_json_checkpoint_safe():
    evidence = EvidenceContext(
        chunk_id="chunk", version_id="version", document_id="document",
        document_title="餐饮方法", source_type="methodology", version_no=1,
        quote="原文片段", locator={"line_start": 3}, query="外卖转化", rank=1,
        retrieved_at=datetime(2026, 7, 16, 10, 0, 0),
    )

    restored = evidence_from_state([evidence_to_state(evidence)])

    assert restored == [evidence]


@pytest.fixture
async def knowledge_db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_ingestion_creates_reviewable_chunks(knowledge_db_factory):
    async with knowledge_db_factory() as db:
        document = KnowledgeDocument(title="外卖转化方法", status="draft")
        db.add(document)
        await db.flush()
        version = KnowledgeDocumentVersion(
            document_id=document.id,
            version_no=1,
            original_filename="delivery.md",
            content_type="text/markdown",
            source_type="methodology",
            sha256="a" * 64,
            storage_key="documents/version/delivery.md",
            status="draft",
            industry_tags=["餐饮"],
            sub_industry_tags=[],
            business_mode_tags=["外卖"],
            operating_stage_tags=["增长"],
        )
        db.add(version)
        await db.flush()
        db.add(KnowledgeIngestionJob(version_id=version.id, state="queued"))
        await db.commit()
        version_id = version.id

    vectors = FakeVectorIndex()
    service = KnowledgeIngestionService(
        storage=FakeStorage("# 转化诊断\n\n菜单曝光下降时，先检查曝光到下单的漏斗。".encode()),
        vector_index=vectors,
        embedding_service=FakeEmbedder(),
        session_factory=knowledge_db_factory,
    )
    async with knowledge_db_factory() as db:
        job_id = (await db.execute(
            select(KnowledgeIngestionJob.id).where(KnowledgeIngestionJob.version_id == version_id)
        )).scalar_one()
    await service.run(job_id, worker_id="test-worker")

    async with knowledge_db_factory() as db:
        version = await db.get(KnowledgeDocumentVersion, version_id)
        chunks = list((await db.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.version_id == version_id)
        )).scalars().all())
        job = (await db.execute(
            select(KnowledgeIngestionJob).where(KnowledgeIngestionJob.version_id == version_id)
        )).scalar_one()

    assert version.status == "pending_review"
    assert job.state == "completed"
    assert job.worker_id == "test-worker"
    assert chunks and "曝光到下单" in chunks[0].content
    assert vectors.indexed == [(version_id, len(chunks))]


@pytest.mark.asyncio
async def test_retrieval_does_not_write_audit_event(knowledge_db_factory):
    service = KnowledgeRetrievalService(
        vector_index=EmptyVectorIndex(),
        embedding_service=FakeEmbedder(),
        session_factory=knowledge_db_factory,
    )
    service._ready = True

    assert await service.retrieve("机械制造业关键指标", {"industry": "机械制造业"}) == []

    async with knowledge_db_factory() as db:
        events = list((await db.execute(select(KnowledgeAuditEvent))).scalars().all())

    assert events == []


@pytest.mark.asyncio
async def test_report_citations_are_limited_to_authorized_candidates(knowledge_db_factory):
    async with knowledge_db_factory() as db:
        document = KnowledgeDocument(title="餐饮基准", status="published")
        db.add(document)
        await db.flush()
        version = KnowledgeDocumentVersion(
            document_id=document.id,
            version_no=1,
            original_filename="benchmark.txt",
            content_type="text/plain",
            source_type="benchmark_rule",
            sha256="b" * 64,
            storage_key="documents/version/benchmark.txt",
            status="published",
            effective_from=datetime.utcnow(),
            industry_tags=["餐饮"],
            sub_industry_tags=[],
            business_mode_tags=[],
            operating_stage_tags=[],
        )
        db.add(version)
        await db.flush()
        chunk = KnowledgeChunk(
            version_id=version.id,
            chunk_no=1,
            content="外卖转化异常应优先核对菜单曝光与下单漏斗。",
            locator={"line_start": 1, "line_end": 1},
        )
        db.add(chunk)
        session = await SessionRepository.for_system(db).create_session()
        report = await SessionRepository.for_system(db).save_report(session.id, "# 初始", {})
        await db.commit()

        candidate = EvidenceContext(
            chunk_id=chunk.id,
            version_id=version.id,
            document_id=document.id,
            document_title=document.title,
            source_type=version.source_type,
            version_no=version.version_no,
            quote=chunk.content,
            locator=chunk.locator,
            query="外卖转化",
            rank=1,
            retrieved_at=datetime.utcnow(),
        )
        markdown, selected = await validate_report_citations(
            db,
            "结论有来源。[证据 1] 伪造来源。[证据 9]",
            [candidate],
        )
        await persist_report_evidences(db, report_id=report.id, selected=selected)
        await db.commit()

        saved = list((await db.execute(
            select(ReportEvidence).where(ReportEvidence.report_id == report.id)
        )).scalars().all())

        version.status = "revoked"
        await db.flush()
        revoked_markdown, revoked_selected = await validate_report_citations(
            db,
            "撤回资料。[证据 1]",
            [candidate],
        )

    assert markdown == "结论有来源。[证据 1] 伪造来源。"
    assert len(saved) == 1
    assert revoked_markdown == "撤回资料。"
    assert revoked_selected == []
