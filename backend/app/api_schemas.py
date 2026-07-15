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


class CompletenessSchema(BaseModel):
    """LLM-evaluated information completeness."""
    score: int = 0
    summary: str = ""                       # one-line summary of collected info
    missing_aspects: List[str] = Field(default_factory=list)  # what's still missing


class MessageSchema(BaseModel):
    """A single chat message."""
    id: str
    role: str  # user | assistant
    content: str
    sequence: int
    suggested_replies: Optional[List[str]] = None  # quick-reply suggestions (assistant only)
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionDetail(SessionSummary):
    """Full session info including messages and facts."""
    scene: Dict[str, str] = Field(default_factory=dict)
    raw_facts: List[str] = Field(default_factory=list)          # collected operational facts
    completeness: CompletenessSchema = Field(default_factory=CompletenessSchema)
    waiting_for_input: bool = False
    error_message: Optional[str] = None
    messages: List[MessageSchema] = Field(default_factory=list)
    has_report: bool = False
    report_count: int = 0
    report_generating: bool = False
    report_error: Optional[str] = None


# =============================================================================
# Message Schemas
# =============================================================================

class MessageRequest(BaseModel):
    """Request body for sending a message (SSE chat endpoint)."""
    client_message_id: str = Field(description="UUID for idempotency")
    content: str = Field(default="", description="User's reply text")
    action: str = Field(default="reply", description="reply (legacy report actions are rejected)")


# =============================================================================
# Report Schemas
# =============================================================================

class ReportResponse(BaseModel):
    """Diagnosis report response."""
    id: str
    session_id: str
    markdown: str
    diagnosis: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ReportGenerationResponse(BaseModel):
    """Accepted background report generation request."""
    session_id: str
    status: str = "generating"


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
