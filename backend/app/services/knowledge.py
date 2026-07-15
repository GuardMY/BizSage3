"""Versioned industry knowledge ingestion, retrieval and evidence snapshots."""

import asyncio
import hashlib
import html
import io
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Iterable

import bleach
import markdown as markdown_renderer
from docx import Document
from minio import Minio
from openai import AsyncOpenAI
from qdrant_client import AsyncQdrantClient, models as qmodels
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.config import embedding_api_key, embedding_base_url, settings
from app.db import async_session_factory
from app.models import (
    KnowledgeAuditEvent,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIngestionJob,
    Report,
    ReportEvidence,
)

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".docx", ".md", ".markdown", ".txt"}
SOURCE_TYPES = {"methodology", "benchmark_rule", "case_sop"}
_MAX_CHUNK_CHARS = 1200
_CHUNK_OVERLAP_CHARS = 180


def utcnow() -> datetime:
    return datetime.utcnow()


def normalize_tag(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def parse_tags(value: str | Iterable[str] | None) -> list[str]:
    """Normalize free-entered tags while preserving a deterministic order."""
    raw_items = re.split(r"[,，\n]", value) if isinstance(value, str) else (value or [])
    tags: list[str] = []
    for raw in raw_items:
        tag = normalize_tag(str(raw))
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def extension_for(filename: str) -> str:
    return PurePosixPath(filename).suffix.lower()


def content_type_for(extension: str) -> str:
    return {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".txt": "text/plain",
    }[extension]


def safe_filename(filename: str) -> str:
    name = PurePosixPath(filename.replace("\\", "/")).name
    return name[:255] or "document"


@dataclass(frozen=True)
class ParsedBlock:
    text: str
    locator: dict[str, Any]


@dataclass(frozen=True)
class ParsedDocument:
    parser: str
    blocks: list[ParsedBlock]
    preview_html: str


@dataclass(frozen=True)
class EvidenceContext:
    """Authorized evidence given to a model or persisted with a report."""

    chunk_id: str
    version_id: str
    document_id: str
    document_title: str
    source_type: str
    version_no: int
    quote: str
    locator: dict[str, Any]
    query: str
    rank: int
    retrieved_at: datetime


def evidence_to_state(evidence: EvidenceContext) -> dict[str, Any]:
    """Convert evidence to JSON-only graph state for LangGraph checkpoints."""
    return {
        "chunk_id": evidence.chunk_id,
        "version_id": evidence.version_id,
        "document_id": evidence.document_id,
        "document_title": evidence.document_title,
        "source_type": evidence.source_type,
        "version_no": evidence.version_no,
        "quote": evidence.quote,
        "locator": evidence.locator,
        "query": evidence.query,
        "rank": evidence.rank,
        "retrieved_at": evidence.retrieved_at.isoformat(),
    }


def evidence_from_state(values: Iterable[EvidenceContext | dict[str, Any]]) -> list[EvidenceContext]:
    contexts: list[EvidenceContext] = []
    for value in values:
        if isinstance(value, EvidenceContext):
            contexts.append(value)
            continue
        try:
            retrieved_at = value.get("retrieved_at")
            contexts.append(EvidenceContext(
                chunk_id=str(value["chunk_id"]),
                version_id=str(value["version_id"]),
                document_id=str(value["document_id"]),
                document_title=str(value["document_title"]),
                source_type=str(value["source_type"]),
                version_no=int(value["version_no"]),
                quote=str(value["quote"]),
                locator=dict(value.get("locator") or {}),
                query=str(value["query"]),
                rank=int(value["rank"]),
                retrieved_at=datetime.fromisoformat(str(retrieved_at)),
            ))
        except (KeyError, TypeError, ValueError):
            logger.warning("Ignoring malformed evidence in graph state")
    return contexts


class KnowledgeStorage:
    """MinIO wrapper. Object access is always proxied through authorized APIs."""

    def __init__(self) -> None:
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )

    async def startup(self) -> None:
        await self._retry(self._ensure_bucket)

    async def _retry(self, operation, attempts: int = 15) -> None:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                await asyncio.to_thread(operation)
                return
            except Exception as exc:  # MinIO may start after FastAPI.
                last_error = exc
                await asyncio.sleep(min(0.5 * (attempt + 1), 3))
        raise RuntimeError("MinIO is unavailable") from last_error

    def _ensure_bucket(self) -> None:
        if not self._client.bucket_exists(settings.minio_bucket):
            self._client.make_bucket(settings.minio_bucket)

    async def put(self, storage_key: str, content: bytes, content_type: str) -> None:
        def operation() -> None:
            self._client.put_object(
                settings.minio_bucket,
                storage_key,
                io.BytesIO(content),
                len(content),
                content_type=content_type,
            )

        await asyncio.to_thread(operation)

    async def get(self, storage_key: str) -> bytes:
        def operation() -> bytes:
            response = self._client.get_object(settings.minio_bucket, storage_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(operation)


class EmbeddingService:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=embedding_api_key(),
            base_url=embedding_base_url(),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not embedding_api_key():
            raise RuntimeError("未配置 OPENAI_API_KEY 或 EMBEDDING_API_KEY")
        response = await self._client.embeddings.create(
            model=settings.embedding_model,
            input=texts,
            dimensions=settings.embedding_dimensions,
        )
        return [item.embedding for item in response.data]


class KnowledgeVectorIndex:
    def __init__(self) -> None:
        self._client = AsyncQdrantClient(url=settings.qdrant_url)

    async def startup(self) -> None:
        async def ensure_collection() -> None:
            collections = await self._client.get_collections()
            if not any(item.name == settings.qdrant_collection for item in collections.collections):
                await self._client.create_collection(
                    collection_name=settings.qdrant_collection,
                    vectors_config=qmodels.VectorParams(
                        size=settings.embedding_dimensions,
                        distance=qmodels.Distance.COSINE,
                    ),
                )

        last_error: Exception | None = None
        for attempt in range(15):
            try:
                await ensure_collection()
                return
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(min(0.5 * (attempt + 1), 3))
        raise RuntimeError("Qdrant is unavailable") from last_error

    async def close(self) -> None:
        await self._client.close()

    async def upsert_chunks(
        self,
        chunks: list[KnowledgeChunk],
        vectors: list[list[float]],
        version: KnowledgeDocumentVersion,
    ) -> None:
        points: list[qmodels.PointStruct] = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"bizsage:{chunk.id}"))
            chunk.embedding_ref = point_id
            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "chunk_id": chunk.id,
                        "version_id": version.id,
                        "status": version.status,
                        "industry_tags": version.industry_tags or [],
                        "sub_industry_tags": version.sub_industry_tags or [],
                        "business_mode_tags": version.business_mode_tags or [],
                        "operating_stage_tags": version.operating_stage_tags or [],
                        "source_type": version.source_type,
                    },
                )
            )
        if points:
            await self._client.upsert(
                collection_name=settings.qdrant_collection,
                points=points,
                wait=True,
            )

    async def activate_version(self, version_id: str) -> None:
        await self._client.set_payload(
            collection_name=settings.qdrant_collection,
            payload={"status": "published"},
            points=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(
                        key="version_id", match=qmodels.MatchValue(value=version_id)
                    )]
                )
            ),
            wait=True,
        )

    async def delete_version(self, version_id: str) -> None:
        await self._client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(
                        key="version_id", match=qmodels.MatchValue(value=version_id)
                    )]
                )
            ),
            wait=True,
        )

    async def search(
        self,
        vector: list[float],
        scene: dict[str, str],
        limit: int,
    ) -> list[tuple[str, float]]:
        filters = [
            qmodels.FieldCondition(
                key="status", match=qmodels.MatchValue(value="published")
            )
        ]
        metadata_fields = {
            "industry": "industry_tags",
            "sub_industry": "sub_industry_tags",
            "business_mode": "business_mode_tags",
            "operating_stage": "operating_stage_tags",
        }
        for scene_key, payload_key in metadata_fields.items():
            value = normalize_tag(scene.get(scene_key, ""))
            if value:
                filters.append(
                    qmodels.FieldCondition(
                        key=payload_key,
                        match=qmodels.MatchValue(value=value),
                    )
                )
        result = await self._client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            query_filter=qmodels.Filter(must=filters),
            limit=limit,
            with_payload=["chunk_id"],
            with_vectors=False,
        )
        return [
            (str(point.payload["chunk_id"]), float(point.score))
            for point in result.points
            if point.payload and point.payload.get("chunk_id")
        ]


def parse_document(filename: str, content: bytes) -> ParsedDocument:
    extension = extension_for(filename)
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError("仅支持 DOCX、Markdown 和 TXT 文件")
    if extension == ".docx":
        return _parse_docx(content)
    return _parse_text(content, extension)


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文本文件必须使用 UTF-8 或 GB18030 编码")


def _parse_text(content: bytes, extension: str) -> ParsedDocument:
    raw = _decode_text(content).replace("\r\n", "\n").replace("\r", "\n")
    heading_path: list[str] = []
    blocks: list[ParsedBlock] = []
    paragraph: list[str] = []
    start_line = 1

    def flush(end_line: int) -> None:
        nonlocal paragraph, start_line
        text = "\n".join(paragraph).strip()
        if text:
            blocks.append(ParsedBlock(
                text=text,
                locator={
                    "heading_path": list(heading_path),
                    "line_start": start_line,
                    "line_end": end_line,
                },
            ))
        paragraph = []

    for line_no, line in enumerate(raw.split("\n"), start=1):
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line) if extension != ".txt" else None
        if heading:
            flush(line_no - 1)
            level = len(heading.group(1))
            title = heading.group(2).strip()
            heading_path[:] = heading_path[: level - 1]
            heading_path.append(title)
            start_line = line_no + 1
        elif line.strip():
            if not paragraph:
                start_line = line_no
            paragraph.append(line.strip())
        else:
            flush(line_no - 1)
            start_line = line_no + 1
    flush(len(raw.split("\n")))
    if not blocks and raw.strip():
        blocks = [ParsedBlock(raw.strip(), {"line_start": 1, "line_end": raw.count("\n") + 1})]

    if extension == ".txt":
        preview_html = f"<pre>{html.escape(raw)}</pre>"
    else:
        rendered = markdown_renderer.markdown(raw, extensions=["extra", "sane_lists"])
        preview_html = bleach.clean(
            rendered,
            tags=["p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "strong", "em", "code", "pre", "blockquote", "table", "thead", "tbody", "tr", "th", "td", "a", "br"],
            attributes={"a": ["href", "title"]},
            protocols=["http", "https", "mailto"],
            strip=True,
        )
    return ParsedDocument(parser="markdown" if extension != ".txt" else "text", blocks=blocks, preview_html=preview_html)


def _parse_docx(content: bytes) -> ParsedDocument:
    try:
        document = Document(io.BytesIO(content))
    except Exception as exc:
        raise ValueError("无法读取 DOCX 文件") from exc

    heading_path: list[str] = []
    blocks: list[ParsedBlock] = []
    preview: list[str] = []
    for index, paragraph in enumerate(document.paragraphs, start=1):
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = (getattr(paragraph.style, "name", "") or "").lower()
        match = re.search(r"(?:heading|标题)\s*(\d+)", style_name)
        if match:
            level = int(match.group(1))
            heading_path[:] = heading_path[: level - 1]
            heading_path.append(text)
            preview.append(f"<h{min(level, 6)}>{html.escape(text)}</h{min(level, 6)}>")
            continue
        blocks.append(ParsedBlock(
            text=text,
            locator={"heading_path": list(heading_path), "paragraph_start": index, "paragraph_end": index},
        ))
        preview.append(f"<p>{html.escape(text)}</p>")

    for table_index, table in enumerate(document.tables, start=1):
        rows = [" | ".join(cell.text.strip() for cell in row.cells).strip() for row in table.rows]
        table_text = "\n".join(row for row in rows if row)
        if table_text:
            blocks.append(ParsedBlock(
                text=table_text,
                locator={"heading_path": list(heading_path), "table_no": table_index},
            ))
            preview.append(f"<pre>{html.escape(table_text)}</pre>")
    if not blocks:
        raise ValueError("DOCX 中没有可解析的正文内容")
    return ParsedDocument(parser="docx", blocks=blocks, preview_html="\n".join(preview))


def chunk_blocks(blocks: list[ParsedBlock]) -> list[tuple[str, dict[str, Any]]]:
    """Keep source locations while packing paragraphs into bounded chunks."""
    chunks: list[tuple[str, dict[str, Any]]] = []
    buffer: list[str] = []
    first_locator: dict[str, Any] | None = None
    last_locator: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal buffer, first_locator, last_locator
        text = "\n\n".join(buffer).strip()
        if text and first_locator is not None:
            locator = dict(first_locator)
            if last_locator:
                for key in ("line_end", "paragraph_end"):
                    if key in last_locator:
                        locator[key] = last_locator[key]
            chunks.append((text, locator))
        overlap = text[-_CHUNK_OVERLAP_CHARS:].strip() if text else ""
        buffer = [overlap] if overlap else []
        first_locator = last_locator

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        while len(text) > _MAX_CHUNK_CHARS:
            segment, text = text[:_MAX_CHUNK_CHARS], text[_MAX_CHUNK_CHARS - _CHUNK_OVERLAP_CHARS:]
            if buffer:
                flush()
            chunks.append((segment, dict(block.locator)))
        projected = len("\n\n".join(buffer + [text]))
        if buffer and projected > _MAX_CHUNK_CHARS:
            flush()
        if not buffer:
            first_locator = dict(block.locator)
        buffer.append(text)
        last_locator = dict(block.locator)
    flush()
    return chunks


def _metadata_matches(version: KnowledgeDocumentVersion, scene: dict[str, str]) -> bool:
    for key, tags in (
        ("industry", version.industry_tags),
        ("sub_industry", version.sub_industry_tags),
        ("business_mode", version.business_mode_tags),
        ("operating_stage", version.operating_stage_tags),
    ):
        expected = normalize_tag(scene.get(key, ""))
        if expected and expected not in (tags or []):
            return False
    return True


class KnowledgeRetrievalService:
    """Retrieval always validates relational version state after Qdrant recall."""

    def __init__(
        self,
        *,
        vector_index: KnowledgeVectorIndex | None = None,
        embedder: EmbeddingService | None = None,
        session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    ) -> None:
        self._vector_index = vector_index or KnowledgeVectorIndex()
        self._embedding_service = embedding_service or EmbeddingService()
        self._session_factory = session_factory
        self._ready = False

    async def startup(self) -> None:
        await self._vector_index.startup()
        self._ready = True

    async def shutdown(self) -> None:
        await self._vector_index.close()
        self._ready = False

    async def retrieve(
        self,
        query: str,
        scene: dict[str, str],
        *,
        limit: int = 5,
    ) -> list[EvidenceContext]:
        if not self._ready or not query.strip():
            return []
        try:
            vector = (await self._embedding_service.embed([query]))[0]
            recalled = await self._vector_index.search(vector, scene, max(limit * 4, 12))
        except Exception:
            logger.exception("Knowledge retrieval failed")
            return []
        if not recalled:
            await self._audit_retrieval(query, scene, [])
            return []

        chunk_ids = [chunk_id for chunk_id, _ in recalled]
        now = utcnow()
        async with self._session_factory() as db:
            stmt = (
                select(KnowledgeChunk)
                .join(KnowledgeDocumentVersion)
                .join(KnowledgeDocument)
                .where(
                    KnowledgeChunk.id.in_(chunk_ids),
                    KnowledgeDocumentVersion.status == "published",
                    KnowledgeDocumentVersion.effective_from <= now,
                    (KnowledgeDocumentVersion.effective_to.is_(None) | (KnowledgeDocumentVersion.effective_to > now)),
                )
                .options(selectinload(KnowledgeChunk.version).selectinload(KnowledgeDocumentVersion.document))
            )
            db_chunks = {chunk.id: chunk for chunk in (await db.execute(stmt)).scalars().all()}

        query_terms = {term for term in re.findall(r"[\w\u4e00-\u9fff]+", query.casefold()) if len(term) > 1}
        ranked: list[tuple[float, EvidenceContext]] = []
        source_weight = {"methodology": 0.10, "benchmark_rule": 0.08, "case_sop": 0.05}
        for rank, (chunk_id, semantic_score) in enumerate(recalled, start=1):
            chunk = db_chunks.get(chunk_id)
            if not chunk or not _metadata_matches(chunk.version, scene):
                continue
            text_terms = set(re.findall(r"[\w\u4e00-\u9fff]+", chunk.content.casefold()))
            keyword_score = len(query_terms & text_terms) / max(len(query_terms), 1)
            score = semantic_score + keyword_score * 0.15 + source_weight.get(chunk.version.source_type, 0)
            ranked.append((score, EvidenceContext(
                chunk_id=chunk.id,
                version_id=chunk.version.id,
                document_id=chunk.version.document.id,
                document_title=chunk.version.document.title,
                source_type=chunk.version.source_type,
                version_no=chunk.version.version_no,
                quote=chunk.content,
                locator=chunk.locator or {},
                query=query,
                rank=rank,
                retrieved_at=now,
            )))
        ranked.sort(key=lambda item: item[0], reverse=True)
        selected = [item[1] for item in ranked[:limit]]
        await self._audit_retrieval(query, scene, selected)
        return selected

    async def _audit_retrieval(
        self,
        query: str,
        scene: dict[str, str],
        evidence: list[EvidenceContext],
    ) -> None:
        try:
            async with self._session_factory() as db:
                db.add(KnowledgeAuditEvent(
                    event_type="knowledge_retrieved",
                    actor_role="system",
                    detail={
                        "query": query[:2000],
                        "scene": scene,
                        "version_ids": [item.version_id for item in evidence],
                        "chunk_ids": [item.chunk_id for item in evidence],
                    },
                ))
                await db.commit()
        except Exception:
            logger.exception("Failed to write knowledge retrieval audit event")


_CITATION_PATTERN = re.compile(r"\[证据\s*(\d+)\]")


async def validate_report_citations(
    db: AsyncSession,
    markdown: str,
    candidates: list[EvidenceContext],
) -> tuple[str, list[tuple[int, EvidenceContext]]]:
    """Keep only citations backed by this retrieval and a non-revoked source.

    The model sees no storage URLs or raw identifiers. This server-side check is
    the boundary that prevents it from creating arbitrary source references.
    """
    candidate_by_no = {index: evidence for index, evidence in enumerate(candidates, start=1)}
    requested = {int(match.group(1)) for match in _CITATION_PATTERN.finditer(markdown)}
    if not requested:
        return markdown, []
    selected = {number: candidate_by_no[number] for number in requested if number in candidate_by_no}
    if selected:
        valid_rows = (await db.execute(
            select(KnowledgeChunk.id, KnowledgeChunk.version_id)
            .join(KnowledgeDocumentVersion)
            .where(
                KnowledgeChunk.id.in_([evidence.chunk_id for evidence in selected.values()]),
                KnowledgeDocumentVersion.status != "revoked",
            )
        )).all()
        valid_pairs = {(row[0], row[1]) for row in valid_rows}
        selected = {
            number: evidence
            for number, evidence in selected.items()
            if (evidence.chunk_id, evidence.version_id) in valid_pairs
        }

    valid_numbers = set(selected)
    sanitized = _CITATION_PATTERN.sub(
        lambda match: match.group(0) if int(match.group(1)) in valid_numbers else "",
        markdown,
    )
    return sanitized, sorted(selected.items())


async def persist_report_evidences(
    db: AsyncSession,
    *,
    report_id: str,
    selected: list[tuple[int, EvidenceContext]],
) -> None:
    for evidence_no, evidence in selected:
        db.add(ReportEvidence(
            report_id=report_id,
            version_id=evidence.version_id,
            chunk_id=evidence.chunk_id,
            evidence_no=evidence_no,
            quote=evidence.quote,
            locator=evidence.locator,
            query=evidence.query,
            rank=evidence.rank,
            retrieved_at=evidence.retrieved_at,
        ))
        db.add(KnowledgeAuditEvent(
            event_type="report_evidence_persisted",
            document_id=evidence.document_id,
            version_id=evidence.version_id,
            actor_role="system",
            detail={"report_id": report_id, "chunk_id": evidence.chunk_id, "evidence_no": evidence_no},
        ))
    await db.flush()


class KnowledgeIngestionManager:
    """Runs durable ingestion jobs; queued work resumes after service restart."""

    def __init__(
        self,
        *,
        storage: KnowledgeStorage | None = None,
        vector_index: KnowledgeVectorIndex | None = None,
        embedding_service: EmbeddingService | None = None,
        session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    ) -> None:
        self._storage = storage or knowledge_storage
        self._vector_index = vector_index or knowledge_vector_index
        self._embedding_service = embedder or embedding_service
        self._session_factory = session_factory
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def startup(self) -> None:
        async with self._session_factory() as db:
            await db.execute(
                update(KnowledgeIngestionJob)
                .where(KnowledgeIngestionJob.state == "running")
                .values(state="queued", error="服务重启后等待重试")
            )
            queued = list((await db.execute(
                select(KnowledgeIngestionJob.version_id).where(KnowledgeIngestionJob.state == "queued")
            )).scalars().all())
            await db.commit()
        for version_id in queued:
            self.start(version_id)

    def start(self, version_id: str) -> None:
        task = self._tasks.get(version_id)
        if task and not task.done():
            return
        task = asyncio.create_task(self._ingest(version_id), name=f"knowledge-ingest:{version_id}")
        self._tasks[version_id] = task
        task.add_done_callback(lambda completed: self._tasks.pop(version_id, None))

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _ingest(self, version_id: str) -> None:
        try:
            async with self._session_factory() as db:
                version = await db.get(KnowledgeDocumentVersion, version_id)
                if version is None or version.status == "revoked":
                    return
                job = await _latest_job(db, version_id)
                if job is None:
                    return
                job.state = "running"
                job.error = None
                version.status = "parsing"
                await db.commit()

            content = await self._storage.get(version.storage_key)
            parsed = parse_document(version.original_filename, content)
            chunk_data = chunk_blocks(parsed.blocks)
            if not chunk_data:
                raise ValueError("未提取到可索引的正文内容")

            async with self._session_factory() as db:
                version = await db.get(KnowledgeDocumentVersion, version_id)
                job = await _latest_job(db, version_id)
                if version is None or job is None or version.status == "revoked":
                    return
                await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.version_id == version_id))
                chunks = [
                    KnowledgeChunk(
                        version_id=version_id,
                        chunk_no=index,
                        content=text,
                        locator=locator,
                    )
                    for index, (text, locator) in enumerate(chunk_data, start=1)
                ]
                db.add_all(chunks)
                await db.flush()
                vectors = await self._embedding_service.embed([chunk.content for chunk in chunks])
                if len(vectors) != len(chunks):
                    raise RuntimeError("嵌入服务返回的向量数量不正确")
                version.status = "pending_review"
                await self._vector_index.upsert_chunks(chunks, vectors, version)
                job.state = "completed"
                job.parser = parsed.parser
                job.indexed_at = utcnow()
                db.add(KnowledgeAuditEvent(
                    event_type="ingestion_completed",
                    document_id=version.document_id,
                    version_id=version.id,
                    actor_role="system",
                    detail={"parser": parsed.parser, "chunk_count": len(chunks)},
                ))
                await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Knowledge ingestion failed for version %s", version_id)
            async with self._session_factory() as db:
                version = await db.get(KnowledgeDocumentVersion, version_id)
                job = await _latest_job(db, version_id)
                if version is not None:
                    version.status = "draft"
                if job is not None:
                    job.state = "failed"
                    job.error = str(exc)[:2000]
                    job.retry_count += 1
                if version is not None:
                    db.add(KnowledgeAuditEvent(
                        event_type="ingestion_failed",
                        document_id=version.document_id,
                        version_id=version.id,
                        actor_role="system",
                        detail={"error": str(exc)[:500]},
                    ))
                await db.commit()


async def _latest_job(db: AsyncSession, version_id: str) -> KnowledgeIngestionJob | None:
    return (await db.execute(
        select(KnowledgeIngestionJob)
        .where(KnowledgeIngestionJob.version_id == version_id)
        .order_by(KnowledgeIngestionJob.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()


def storage_key_for(version_id: str, filename: str) -> str:
    return f"documents/{version_id}/{safe_filename(filename)}"


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


knowledge_storage = KnowledgeStorage()
knowledge_vector_index = KnowledgeVectorIndex()
embedding_service = EmbeddingService()
knowledge_retrieval_service = KnowledgeRetrievalService(
    vector_index=knowledge_vector_index,
    embedding_service=embedding_service,
)
knowledge_ingestion_manager = KnowledgeIngestionManager(
    storage=knowledge_storage,
    vector_index=knowledge_vector_index,
    embedder=embedding_service,
)
