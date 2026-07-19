"""Domain Pydantic models for structured data in the LangGraph workflow."""

from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

from app.response_models import ShanghaiTimeResponseModel


class Scene(BaseModel):
    """Scene recognition output (node_scene_recognize)."""
    industry: str = Field(default="", description="自由文本行业名称")
    sub_industry: str = Field(default="", description="子行业或品类")
    business_mode: str = Field(default="", description="业务模式，如外卖、到店、订阅")
    operating_stage: str = Field(default="", description="经营阶段，如起步、增长、成熟")


class ConversationDecision(BaseModel):
    """LLM routing decision for one user message. The reply is user-visible."""

    decision: Literal[
        "continue_diagnosis",
        "clarify_scene",
        "general_reply",
        "redirect_to_diagnosis",
        "handoff_unavailable",
    ] = "clarify_scene"
    scene_action: Literal["keep", "set", "replace", "clear"] = "keep"
    scene: Scene = Field(default_factory=Scene, description="本轮确认或候选的业务场景")
    reply: str = Field(default="", description="直接展示给用户的自然语言回复")
    suggested_replies: List[str] = Field(default_factory=list, description="用户可选的简短回复")
    reason: str = Field(default="", exclude=True, description="仅供日志与调试使用的简短决策理由")


class CompletenessEval(BaseModel):
    """LLM evaluation of how complete the collected operational info is."""
    score: int = Field(default=0, ge=0, le=100, description="完备度分数 0-100")
    summary: str = Field(default="", description="一句话概括已有信息")
    missing_aspects: List[str] = Field(default_factory=list, description="还缺什么方面")
    next_question: str = Field(default="", description="建议追问的问题")


class ConversationCitation(ShanghaiTimeResponseModel):
    """A verified source that may be displayed beneath an assistant message."""

    citation_id: str
    source_type: Literal["knowledge", "web"]
    title: str
    url: Optional[str] = None
    quote: str = ""
    locator: Dict[str, Any] = Field(default_factory=dict)
    provider: Optional[str] = None
    published_at: Optional[datetime] = None


class ToolInvocationSummary(BaseModel):
    """Safe, JSON-only summary of one read-only tool invocation."""

    tool_name: str
    provider: Optional[str] = None
    status: Literal["success", "unavailable", "error", "limited"]
    latency_ms: int = 0
    result_count: int = 0
    error_type: Optional[str] = None


class ConversationTurnOutput(ConversationDecision):
    """Merged output of chat_extract + agent_reply in a single LLM call.

    One call handles: fact extraction, completeness evaluation, reply generation,
    and quick-reply suggestions.
    """
    new_facts: List[str] = Field(default_factory=list, description="新提取的运营事实")
    completeness: CompletenessEval = Field(default_factory=CompletenessEval, description="信息完备度评估")
    citations: List[ConversationCitation] = Field(default_factory=list)
    tool_invocations: List[ToolInvocationSummary] = Field(default_factory=list)
    # Retained only in LangGraph state. API persistence uses the verified
    # citations above, so unreferenced search results are never displayed.
    tool_evidence: List[ConversationCitation] = Field(default_factory=list, exclude=True)


class ResumeInput(BaseModel):
    """Payload sent to LangGraph when resuming after interrupt()."""
    content: str = Field(description="User's reply text")
    action: str = Field(default="reply", description="reply | diagnose_with_current_data")
