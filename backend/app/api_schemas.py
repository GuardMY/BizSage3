"""Pydantic request/response schemas for the BizSage3 API."""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


# =============================================================================
# Session Schemas
# =============================================================================

class SessionSummary(BaseModel):
    """Lightweight session info for list views."""
    id: str
    title: str
    status: str  # collecting | analyzing | completed | failed
    stage: str
    score: int
    limited_diagnosis: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MetricValueSchema(BaseModel):
    """A single collected metric value."""
    code: str
    label: str = ""
    raw_text: str = ""
    status: str = "provided"  # provided | unavailable
    numeric_value: Optional[float] = None
    range_min: Optional[float] = None
    range_max: Optional[float] = None
    unit: Optional[str] = None
    period: Optional[str] = None
    confidence: float = 1.0


class ScoreDetailSchema(BaseModel):
    """Completeness score breakdown."""
    score: int = 0
    core_complete: bool = False
    core_provided_count: int = 0
    secondary_coverage: float = 0.0
    anomaly_complete: bool = True
    missing_core: List[str] = Field(default_factory=list)
    missing_secondary: List[str] = Field(default_factory=list)
    unresolved_anomalies: List[str] = Field(default_factory=list)
    can_limited_diagnose: bool = False
    passed: bool = False


class MessageSchema(BaseModel):
    """A single chat message."""
    id: str
    role: str  # user | assistant
    content: str
    sequence: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionDetail(SessionSummary):
    """Full session info including messages and metrics."""
    scene: Dict[str, str] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    score_detail: ScoreDetailSchema = Field(default_factory=ScoreDetailSchema)
    waiting_for_input: bool = False
    error_message: Optional[str] = None
    messages: List[MessageSchema] = Field(default_factory=list)
    has_report: bool = False


# =============================================================================
# Message Schemas
# =============================================================================

class MessageRequest(BaseModel):
    """Request body for sending a message (SSE chat endpoint)."""
    client_message_id: str = Field(description="UUID for idempotency")
    content: str = Field(default="", description="User's reply text (empty = force diagnose)")
    action: str = Field(default="reply", description="reply | diagnose_with_current_data")


# =============================================================================
# Report Schemas
# =============================================================================

class ReportResponse(BaseModel):
    """Diagnosis report response."""
    session_id: str
    markdown: str
    diagnosis: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


# =============================================================================
# Meta Schemas
# =============================================================================

class IndustryDef(BaseModel):
    """Industry definition for the meta endpoint."""
    code: str
    label: str
    description: str


class MetricDef(BaseModel):
    """Metric definition for the meta endpoint."""
    code: str
    label: str
    category: str
    description: str
    unit: str = ""
    is_core: bool = False


class MetaResponse(BaseModel):
    """Response for the /meta/industries endpoint."""
    industries: List[IndustryDef]
    core_metrics: List[MetricDef]
    llm_mode: str


# =============================================================================
# SSE Event Types (for documentation)
# =============================================================================

class SSEStageEvent(BaseModel):
    """Emitted when the workflow stage changes."""
    stage: str
    label: str


class SSEErrorEvent(BaseModel):
    """Emitted on error."""
    message: str
