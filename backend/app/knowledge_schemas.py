"""API and service schemas for the platform industry knowledge base."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


KnowledgeSourceType = Literal["methodology", "benchmark_rule", "case_sop"]


class PublishVersionRequest(BaseModel):
    effective_from: datetime | None = None


class KnowledgeIngestionJobResponse(BaseModel):
    id: str
    state: str
    parser: str | None = None
    error: str | None = None
    retry_count: int
    indexed_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeVersionResponse(BaseModel):
    id: str
    document_id: str
    version_no: int
    original_filename: str
    content_type: str
    source_type: KnowledgeSourceType
    sha256: str
    status: str
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    industry_tags: list[str] = Field(default_factory=list)
    sub_industry_tags: list[str] = Field(default_factory=list)
    business_mode_tags: list[str] = Field(default_factory=list)
    operating_stage_tags: list[str] = Field(default_factory=list)
    chunk_count: int = 0
    latest_job: KnowledgeIngestionJobResponse | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentResponse(BaseModel):
    id: str
    title: str
    current_version_id: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    versions: list[KnowledgeVersionResponse] = Field(default_factory=list)


class ReportEvidenceResponse(BaseModel):
    evidence_no: int
    document_id: str
    version_id: str
    document_title: str
    source_type: KnowledgeSourceType
    version_no: int
    effective_from: datetime | None = None
    status: str
    quote: str
    locator: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime
