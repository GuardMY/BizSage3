"""Repository-managed industry catalog synchronization regressions."""

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.knowledge_api import _catalog_sync_response
from app.models import (
    Base,
    KnowledgeCatalogSyncItem,
    KnowledgeCatalogSyncRun,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
)
from app.services.industry_catalog import IndustryCatalogSyncService
from app.services.knowledge import KnowledgeIngestionService


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, storage_key: str, content: bytes, content_type: str) -> None:
        self.objects[storage_key] = content

    async def get(self, storage_key: str) -> bytes:
        return self.objects[storage_key]

    async def delete(self, storage_key: str) -> None:
        self.objects.pop(storage_key, None)


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorIndex:
    def __init__(self) -> None:
        self.indexed: list[str] = []

    async def upsert_chunks(self, chunks, vectors, version) -> None:
        self.indexed.append(version.id)

    async def delete_version(self, version_id: str) -> None:
        pass


def _write_document(path: Path, title: str, industry: str, sub_industry: str) -> None:
    path.write_text(
        f'''---
title: "{title}"
industry: "{industry}"
sub_industry: "{sub_industry}"
source_type: "methodology"
---

# {title}

## 上游

原材料、设备和专业服务。

## 运营

需求、采购、交付、结算和复盘。
''',
        encoding="utf-8",
    )


def test_repository_catalog_contains_100_valid_managed_documents():
    catalog_dir = Path(__file__).parents[2] / "docs" / "industry"
    service = IndustryCatalogSyncService(catalog_dir=catalog_dir, storage=MemoryStorage())

    files = service._scan(None)

    assert len(files) == 100
    assert all(file.error is None for file in files)
    assert all(file.filename != "index.md" for file in files)
    assert len({file.source_key for file in files}) == 100


@pytest.fixture
async def catalog_db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_catalog_sync_is_idempotent_and_revokes_deleted_files(
    tmp_path,
    catalog_db_factory,
):
    catalog_dir = tmp_path / "industry"
    catalog_dir.mkdir()
    (catalog_dir / "index.md").write_text("# 目录\n", encoding="utf-8")
    _write_document(catalog_dir / "01-01.md", "种植业知识库", "农林牧渔", "种植业")
    _write_document(catalog_dir / "02-01.md", "食品制造知识库", "食品饮料", "食品制造")

    storage = MemoryStorage()
    sync_service = IndustryCatalogSyncService(
        catalog_dir=catalog_dir,
        storage=storage,
        session_factory=catalog_db_factory,
    )
    ingestion_service = KnowledgeIngestionService(
        storage=storage,
        vector_index=FakeVectorIndex(),
        embedding_service=FakeEmbedder(),
        session_factory=catalog_db_factory,
    )

    first_run, created = await sync_service.request_run("startup")
    duplicate, duplicate_created = await sync_service.request_run("startup")
    assert created is True
    assert duplicate_created is False
    assert duplicate.id == first_run.id

    job_ids = await sync_service.run(first_run.id, worker_id="catalog-worker")
    assert len(job_ids) == 2
    for job_id in job_ids:
        assert await ingestion_service.run(job_id, worker_id="ingestion-worker") is True

    async with catalog_db_factory() as db:
        run = await db.get(KnowledgeCatalogSyncRun, first_run.id)
        documents = list((await db.execute(
            select(KnowledgeDocument).order_by(KnowledgeDocument.managed_source_key)
        )).scalars().all())
        versions = list((await db.execute(
            select(KnowledgeDocumentVersion).order_by(KnowledgeDocumentVersion.original_filename)
        )).scalars().all())
        items = list((await db.execute(
            select(KnowledgeCatalogSyncItem).where(
                KnowledgeCatalogSyncItem.run_id == first_run.id
            )
        )).scalars().all())

    assert run.state == "completed"
    assert run.active_key is None
    assert [document.managed_source_key for document in documents] == ["01-01.md", "02-01.md"]
    assert all(document.status == "published" for document in documents)
    assert all(version.status == "published" for version in versions)
    assert {item.state for item in items} == {"published"}

    second_run, created = await sync_service.request_run("manual")
    assert created is True
    assert await sync_service.run(second_run.id, worker_id="catalog-worker") == []
    async with catalog_db_factory() as db:
        second_items = list((await db.execute(
            select(KnowledgeCatalogSyncItem).where(
                KnowledgeCatalogSyncItem.run_id == second_run.id
            )
        )).scalars().all())
        second_state = (await db.get(KnowledgeCatalogSyncRun, second_run.id)).state
    assert second_state == "completed"
    assert {item.state for item in second_items} == {"skipped"}

    (catalog_dir / "02-01.md").unlink()
    third_run, _ = await sync_service.request_run("manual")
    assert await sync_service.run(third_run.id, worker_id="catalog-worker") == []
    async with catalog_db_factory() as db:
        removed = (await db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.managed_source_key == "02-01.md"
            )
        )).scalar_one()
        revoke_item = (await db.execute(
            select(KnowledgeCatalogSyncItem).where(
                KnowledgeCatalogSyncItem.run_id == third_run.id,
                KnowledgeCatalogSyncItem.source_key == "02-01.md",
            )
        )).scalar_one()
    assert removed.status == "revoked"
    assert removed.current_version_id is None
    assert revoke_item.state == "revoked"


@pytest.mark.asyncio
async def test_catalog_sync_response_paginates_items_and_keeps_full_run_counts(
    catalog_db_factory,
):
    async with catalog_db_factory() as db:
        run = KnowledgeCatalogSyncRun(id="run-1", trigger="manual", state="running")
        db.add(run)
        db.add_all([
            KnowledgeCatalogSyncItem(
                id=f"item-{number}",
                run_id=run.id,
                source_key=f"{number:02}.md",
                filename=f"{number:02}.md",
                action="create",
                state=state,
            )
            for number, state in enumerate(
                ("queued", "running", "published", "skipped", "failed"),
                start=1,
            )
        ])
        await db.commit()

        response = await _catalog_sync_response(db, run, page=2, page_size=2)

    assert response.total_count == 5
    assert response.pending_count == 1
    assert response.processing_count == 1
    assert response.published_count == 1
    assert response.skipped_count == 1
    assert response.failed_count == 1
    assert response.progress_percent == 60
    assert [item.source_key for item in response.items] == ["03.md", "04.md"]


@pytest.mark.asyncio
async def test_catalog_scan_failure_never_revokes_documents(tmp_path, catalog_db_factory):
    catalog_dir = tmp_path / "industry"
    catalog_dir.mkdir()
    storage = MemoryStorage()
    service = IndustryCatalogSyncService(
        catalog_dir=catalog_dir,
        storage=storage,
        session_factory=catalog_db_factory,
    )
    async with catalog_db_factory() as db:
        document = KnowledgeDocument(
            title="种植业知识库",
            managed_source_key="01-01.md",
            status="published",
        )
        db.add(document)
        await db.flush()
        version = KnowledgeDocumentVersion(
            document_id=document.id,
            version_no=1,
            original_filename="01-01.md",
            content_type="text/markdown",
            source_type="methodology",
            sha256="a" * 64,
            storage_key="documents/version/01-01.md",
            status="published",
            industry_tags=["农林牧渔"],
            sub_industry_tags=["种植业"],
            business_mode_tags=[],
            operating_stage_tags=[],
        )
        db.add(version)
        await db.flush()
        document.current_version_id = version.id
        await db.commit()

    run, _ = await service.request_run("manual")
    assert await service.run(run.id, worker_id="catalog-worker") == []

    async with catalog_db_factory() as db:
        saved_run = await db.get(KnowledgeCatalogSyncRun, run.id)
        document = (await db.execute(select(KnowledgeDocument))).scalar_one()
        version = (await db.execute(select(KnowledgeDocumentVersion))).scalar_one()

    assert saved_run.state == "failed"
    assert "index.md" in saved_run.error
    assert document.status == "published"
    assert version.status == "published"


@pytest.mark.asyncio
async def test_failed_file_retry_creates_a_scoped_sync_run(tmp_path, catalog_db_factory):
    catalog_dir = tmp_path / "industry"
    catalog_dir.mkdir()
    (catalog_dir / "index.md").write_text("# 目录\n", encoding="utf-8")
    source = catalog_dir / "01-01.md"
    source.write_text("# 缺少 frontmatter\n", encoding="utf-8")
    service = IndustryCatalogSyncService(
        catalog_dir=catalog_dir,
        storage=MemoryStorage(),
        session_factory=catalog_db_factory,
    )

    failed_run, _ = await service.request_run("manual")
    assert await service.run(failed_run.id, worker_id="catalog-worker") == []
    _write_document(source, "种植业知识库", "农林牧渔", "种植业")

    retry_run, created = await service.request_failed_retry(failed_run.id)

    assert created is True
    assert retry_run.trigger == "retry"
    assert retry_run.source_keys == ["01-01.md"]
    assert len(await service.run(retry_run.id, worker_id="catalog-worker")) == 1
