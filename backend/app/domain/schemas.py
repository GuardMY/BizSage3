"""Domain Pydantic models for structured data in the LangGraph workflow."""

from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field


class Scene(BaseModel):
    """Scene recognition output (node_scene_recognize)."""
    industry: str = Field(default="", description="行业: 电商|本地生活|新媒体内容|ToB企业服务|线下零售|教育")
    sub_industry: str = Field(default="", description="子行业或品类")
    business_mode: str = Field(default="", description="业务模式，如外卖、到店、订阅")
    operating_stage: str = Field(default="", description="经营阶段，如起步、增长、成熟")


class MetricValue(BaseModel):
    """A single collected metric with value and metadata."""
    code: str = Field(description="Metric code, e.g. 'traffic', 'conversion_rate'")
    label: str = Field(default="", description="Human-readable label")
    raw_text: str = Field(default="", description="Original user-provided text")
    status: str = Field(default="provided", description="provided | unavailable")
    numeric_value: Optional[float] = Field(default=None, description="Parsed numeric value")
    range_min: Optional[float] = Field(default=None, description="Range estimate minimum")
    range_max: Optional[float] = Field(default=None, description="Range estimate maximum")
    unit: Optional[str] = Field(default=None, description="Unit: 次|%|元|人|单 等")
    period: Optional[str] = Field(default=None, description="Time period: 日|周|月|季度|年")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="LLM extraction confidence")


class AnomalyContext(BaseModel):
    """Context about a detected anomaly that may need follow-up."""
    code: str = Field(description="Anomaly identifier code")
    metric_code: str = Field(default="", description="Related metric code")
    description: str = Field(default="", description="Anomaly description")
    severity: str = Field(default="risk", description="risk | critical")
    resolved: bool = Field(default=False, description="Whether follow-up resolved it")
    question_asked: str = Field(default="", description="Question asked to user about this anomaly")


class CompletenessEval(BaseModel):
    """LLM evaluation of how complete the collected operational info is."""
    score: int = Field(default=0, ge=0, le=100, description="完备度分数 0-100")
    summary: str = Field(default="", description="一句话概括已有信息")
    missing_aspects: List[str] = Field(default_factory=list, description="还缺什么方面")
    next_question: str = Field(default="", description="建议追问的问题")


class ChatExtractOutput(BaseModel):
    """Combined output of chat_extract: new facts + completeness evaluation."""
    new_facts: List[str] = Field(default_factory=list, description="新提取的运营事实")
    completeness: CompletenessEval = Field(default_factory=CompletenessEval, description="信息完备度评估")


class ExtractionResult(BaseModel):
    """Output of the extraction (scene + facts + anomalies) from conversation."""
    scene: Scene = Field(default_factory=Scene)
    raw_facts: List[str] = Field(default_factory=list, description="散装运营事实列表")
    metrics: Dict[str, MetricValue] = Field(default_factory=dict)  # retained for backward compat
    anomalies: Dict[str, AnomalyContext] = Field(default_factory=dict)


class DiagnosisDimension(BaseModel):
    """Single diagnosis dimension result."""
    name: str = Field(description="维度名称")
    severity: str = Field(description="优势|正常|风险|严重问题")
    findings: str = Field(default="", description="诊断发现")
    root_cause: str = Field(default="", description="根因分析")
    recommendation: str = Field(default="", description="优化建议")


class DiagnosisResult(BaseModel):
    """Complete multi-dimension diagnosis output (node_diagnosis_analysis)."""
    dimensions: List[DiagnosisDimension] = Field(default_factory=list)
    overall_health_score: int = Field(default=0, ge=0, le=100, description="综合健康度评分")
    summary: str = Field(default="", description="核心结论概述")
    key_risks: List[str] = Field(default_factory=list, description="关键风险列表")
    key_strengths: List[str] = Field(default_factory=list, description="核心优势列表")


class AgentReplyOutput(BaseModel):
    """Structured output of agent_reply: the reply text plus quick-reply suggestions.

    Deprecated: kept for backward-compat reference. Use ConversationTurnOutput instead.
    """
    reply: str = Field(description="对话回复文本")
    suggested_replies: List[str] = Field(
        default_factory=list,
        description="预测用户可能回复的选项（3-10个）",
    )


class ConversationCitation(BaseModel):
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


class ConversationTurnOutput(BaseModel):
    """Merged output of chat_extract + agent_reply in a single LLM call.

    One call handles: fact extraction, completeness evaluation, reply generation,
    and quick-reply suggestions.
    """
    new_facts: List[str] = Field(default_factory=list, description="新提取的运营事实")
    completeness: CompletenessEval = Field(default_factory=CompletenessEval, description="信息完备度评估")
    reply: str = Field(description="对话回复文本")
    suggested_replies: List[str] = Field(
        default_factory=list,
        description="预测用户可能回复的选项（3-10个）",
    )
    citations: List[ConversationCitation] = Field(default_factory=list)
    tool_invocations: List[ToolInvocationSummary] = Field(default_factory=list)
    # Retained only in LangGraph state. API persistence uses the verified
    # citations above, so unreferenced search results are never displayed.
    tool_evidence: List[ConversationCitation] = Field(default_factory=list, exclude=True)


class ResumeInput(BaseModel):
    """Payload sent to LangGraph when resuming after interrupt()."""
    content: str = Field(description="User's reply text")
    action: str = Field(default="reply", description="reply | diagnose_with_current_data")
