"""LangGraph conversational workflow for operations diagnosis.

Graph (after merging chat_extract + agent_reply → conversation_turn):

    START → scene_recognize
                ↓ (no industry)
           greeting_guide → await_input → back to scene_recognize
                ↓ (has industry)
           conversation_turn (facts + completeness + reply + suggestions)
                ↓                              ↑
           await_input (interrupt) ────────────┘  (main loop)

           Force diagnose → generate_report → END

Each conversation turn is a SINGLE LLM call (was 2 before the merge).
Uses LangGraph's interrupt() for human-in-the-loop pauses.
"""

import asyncio
import logging
from typing import Any, Optional, Dict, List, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import interrupt, Command

from app.config import settings
from app.domain.schemas import ResumeInput, CompletenessEval, ConversationTurnOutput
from app.services.knowledge import (
    evidence_from_state,
    evidence_to_state,
    knowledge_retrieval_service,
)
from app.services.model_service import DiagnosisModel, create_model

logger = logging.getLogger(__name__)


# =============================================================================
# State Definition
# =============================================================================

class AgentState(TypedDict, total=False):
    """State shared across all workflow nodes."""
    messages: List[Dict[str, Any]]
    user_scene: Dict[str, str]
    scene_decision: Dict[str, Any]
    raw_facts: List[str]
    completeness: Dict[str, Any]        # serialized CompletenessEval
    diagnosis_result: str
    final_report: str
    stage: str
    pending_question: str
    suggested_replies: List[str]        # LLM-generated quick-reply options
    conversation_evidence: List[Dict[str, Any]]
    tool_invocations: List[Dict[str, Any]]
    report_evidence: List[Dict[str, Any]]
    force_diagnosis: bool
    error_message: str


def make_initial_state(user_message: str, existing_messages: list = None) -> dict:
    """Create a fresh state dict for a new session.

    Args:
        user_message: The latest user message to append.
        existing_messages: List of {"role": ..., "content": ...} dicts already in
            the DB session (e.g. welcome + conversation starter). They are
            prepended so the workflow state tracks the full message history.
    """
    messages = list(existing_messages) if existing_messages else []
    messages.append({"role": "user", "content": user_message})
    return {
        "messages": messages,
        "user_scene": {},
        "scene_decision": {},
        "raw_facts": [],
        "completeness": {},
        "diagnosis_result": "",
        "final_report": "",
        "stage": "init",
        "pending_question": "",
        "suggested_replies": [],
        "conversation_evidence": [],
        "tool_invocations": [],
        "report_evidence": [],
        "force_diagnosis": False,
        "error_message": "",
    }


# =============================================================================
# Node Implementations
# =============================================================================

_SCENE_FIELDS = ("industry", "sub_industry", "business_mode", "operating_stage")


def _apply_scene_action(
    current_scene: Dict[str, str],
    action: str,
    candidate_scene: Dict[str, str],
) -> Dict[str, str]:
    """Apply an LLM scene update without accepting partial or invalid switches."""
    current = {
        field: str(current_scene.get(field) or "")
        for field in _SCENE_FIELDS
        if current_scene.get(field)
    }
    candidate = {
        field: str(candidate_scene.get(field) or "")
        for field in _SCENE_FIELDS
        if candidate_scene.get(field)
    }
    if action == "clear":
        return {}
    if action == "replace":
        return candidate if candidate.get("industry") else current
    if action == "set":
        return {**current, **candidate}
    return current

def _make_scene_recognize(model: DiagnosisModel):
    """Node 1: Scene recognition — identify industry, stage.

    On the first run, looks at the initial user message.
    On retry (after greeting_guide), looks at the full conversation to
    extract the industry from accumulated context.
    """

    async def node_scene_recognize(state: dict) -> dict:
        """节点1：场景识别 —— 识别用户所在的行业、商业模式、阶段和诊断目标。"""
        logger.info("Node: scene_recognize")
        messages = state.get("messages", [])
        if not messages:
            return {"stage": "scene_recognize"}

        # Build a combined context from the conversation for better recognition
        user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
        # Use the full user dialogue as context (last 5 messages max)
        context = "\n".join(user_msgs[-5:])

        decision = await model.recognize_scene(context)
        user_scene = _apply_scene_action(
            state.get("user_scene", {}),
            decision.scene_action,
            decision.scene.model_dump(),
        )
        if decision.decision == "continue_diagnosis" and not user_scene.get("industry"):
            decision = decision.model_copy(update={
                "decision": "clarify_scene",
                "scene_action": "keep",
                "reply": decision.reply or "为了更好地帮你诊断，你目前主要经营什么业务？",
            })
        logger.info(
            "Scene decision: decision=%s action=%s industry=%s reason=%s",
            decision.decision,
            decision.scene_action,
            user_scene.get("industry", ""),
            decision.reason,
        )
        return {
            "user_scene": user_scene,
            "scene_decision": decision.model_dump(),
            "stage": "scene_recognize",
        }

    return node_scene_recognize


def _make_greeting_guide(model: DiagnosisModel):
    """Node: Greeting guide — when no industry was identified."""

    async def node_greeting_guide(state: dict) -> dict:
        """节点2：引导问候 —— 当未识别到行业时，生成自我介绍和引导性问题。"""
        logger.info("Node: greeting_guide")
        messages = state.get("messages", [])

        decision = state.get("scene_decision", {})
        guide_text = str(decision.get("reply") or "")
        if not guide_text:
            user_msgs = [m for m in messages if m.get("role") == "user"]
            last_user = user_msgs[-1]["content"] if user_msgs else "你好"
            guide_text = await model.greeting_guide(last_user)

        messages = list(messages)
        messages.append({"role": "assistant", "content": guide_text})

        return {
            "messages": messages,
            "pending_question": guide_text,
            "suggested_replies": decision.get("suggested_replies", []),
            "stage": "greeting_guide",
        }

    return node_greeting_guide


def _make_conversation_turn(model: DiagnosisModel):
    """Node: Single-call conversation turn — merged chat_extract + agent_reply.

    One LLM call handles:
      1. Extract new operational facts
      2. Evaluate information completeness
      3. Generate the conversational reply
      4. Generate quick-reply suggestions
    """

    async def node_conversation_turn(state: dict) -> dict:
        """节点3：对话回合 —— 单次 LLM 调用完成事实提取、完备度评估、回复生成、快捷回答。"""
        logger.info("Node: conversation_turn")
        messages = state.get("messages", [])
        existing_facts = state.get("raw_facts", [])
        scene = state.get("user_scene", {})
        result: ConversationTurnOutput = await model.conversation_turn(
            messages, existing_facts, scene,
        )

        collects_diagnosis = result.decision == "continue_diagnosis"
        scene_action = result.scene_action
        if not collects_diagnosis and scene_action in {"set", "replace"}:
            scene_action = "keep"
        updated_scene = _apply_scene_action(
            scene,
            scene_action,
            result.scene.model_dump(),
        )

        # A confirmed business switch starts a distinct diagnosis context.
        all_facts = [] if scene_action == "replace" else list(existing_facts)
        if collects_diagnosis:
            for f in result.new_facts:
                if f not in all_facts:
                    all_facts.append(f)

        # Append assistant reply to messages
        messages_out = list(messages)
        reply = result.reply or ""
        if reply:
            messages_out.append({
                "role": "assistant",
                "content": reply,
                "citations": [citation.model_dump() for citation in result.citations],
            })

        return {
            "messages": messages_out,
            "user_scene": updated_scene,
            "scene_decision": result.model_dump(),
            "raw_facts": all_facts,
            "completeness": (
                result.completeness.model_dump()
                if collects_diagnosis
                else state.get("completeness", {})
            ),
            "pending_question": reply,
            "suggested_replies": result.suggested_replies or [],
            "conversation_evidence": (
                [citation.model_dump() for citation in result.tool_evidence]
                if collects_diagnosis else []
            ),
            "tool_invocations": (
                [invocation.model_dump() for invocation in result.tool_invocations]
                if collects_diagnosis else []
            ),
            "stage": "conversation_turn",
        }

    return node_conversation_turn


def _make_await_input():
    """Interrupt node: pause workflow and wait for user reply.

    On first invocation: interrupt() suspends the graph, returns the question.
    On resume (via Command(resume=...)): receives user reply, adds to messages.
    """

    async def node_await_input(state: dict) -> dict:
        """节点5：等待输入 —— 通过 LangGraph interrupt() 暂停工作流，等待用户回复（人机交互暂停点）。"""
        logger.info("Node: await_input (interrupt)")
        question = state.get("pending_question", "请提供更多信息")

        # interrupt() suspends here; returns user reply on resume
        user_reply: str = interrupt({"question": question})

        messages = list(state.get("messages", []))
        messages.append({"role": "user", "content": user_reply})

        return {
            "messages": messages,
            "stage": "await_input",
        }

    return node_await_input


def _make_generate_report(model: DiagnosisModel):
    """Node: Generate the final diagnosis report.

    Feeds the conversation, collected facts, scene, and completeness info to
    the LLM and produces a context-specific markdown report.
    """

    async def node_generate_report(state: dict) -> dict:
        """节点6：生成报告 —— 汇总所有收集的运营事实和完备度信息，生成结构化诊断报告。"""
        logger.info("Node: generate_report")
        raw_facts = state.get("raw_facts", [])
        comp_data = state.get("completeness", {})
        scene = state.get("user_scene", {})
        messages = state.get("messages", [])

        completeness = CompletenessEval(**comp_data) if comp_data else CompletenessEval()
        report_query = "\n".join([
            scene.get("industry", ""),
            *raw_facts,
            *[item.get("content", "") for item in messages[-8:] if item.get("role") == "user"],
        ])
        evidence = await knowledge_retrieval_service.retrieve(report_query, scene, limit=5)

        report = await model.generate_report(
            raw_facts,
            completeness,
            scene,
            messages=messages,
            evidence=evidence,
        )

        messages = list(messages)
        messages.append({"role": "assistant", "content": report})

        return {
            "final_report": report,
            "messages": messages,
            "stage": "generate_report",
            "report_evidence": [evidence_to_state(item) for item in evidence],
        }

    return node_generate_report


# =============================================================================
# Routing
# =============================================================================

def route_after_scene(state: dict) -> str:
    """Route the initial decision to a reply or the diagnosis conversation."""
    scene = state.get("user_scene", {})
    decision_state = state.get("scene_decision", {})
    decision = decision_state.get("decision") if decision_state else (
        "continue_diagnosis" if scene.get("industry", "") else "clarify_scene"
    )
    if decision == "continue_diagnosis" and scene.get("industry", ""):
        return "conversation_turn"
    return "greeting_guide"


def route_after_await(state: dict) -> str:
    """等待输入后路由：未识别场景→重新识别；强制诊断→生成报告；正常→对话回合。"""
    force = state.get("force_diagnosis", False)
    if force:
        return "generate_report"
    # 如果还没有识别出行业，先回到场景识别再试
    scene = state.get("user_scene", {})
    if not scene or not scene.get("industry", ""):
        return "scene_recognize"
    return "conversation_turn"


# =============================================================================
# Graph Builder
# =============================================================================

def build_graph(model: Optional[DiagnosisModel] = None) -> StateGraph:
    """Build the conversational diagnosis LangGraph StateGraph.

    Nodes: scene_recognize, greeting_guide, conversation_turn,
           await_input, generate_report

    Flow:
      START → scene_recognize
                ↓ (no industry) → greeting_guide → await_input → scene_recognize
                ↓ (has industry) → conversation_turn → await_input
                                      ↑_______________↓ (main loop)

      Force diagnose: skip straight to generate_report
    """
    if model is None:
        model = create_model()

    graph = StateGraph(AgentState)

    # Register conversation and report nodes. Report retrieval remains inside
    # generate_report and is intentionally separate from the tool loop.
    graph.add_node("scene_recognize", _make_scene_recognize(model))        # 节点1：场景识别
    graph.add_node("greeting_guide", _make_greeting_guide(model))
    graph.add_node("conversation_turn", _make_conversation_turn(model))
    graph.add_node("await_input", _make_await_input())
    graph.add_node("generate_report", _make_generate_report(model))

    # 构建边
    # START → 场景识别
    graph.add_edge(START, "scene_recognize")

    # 场景识别 → 引导问候（未识别到行业）或 对话回合（已识别到行业）
    graph.add_conditional_edges(
        "scene_recognize",
        route_after_scene,
        {
            "greeting_guide": "greeting_guide",
            "conversation_turn": "conversation_turn",
        },
    )

    # 引导问候 → 等待输入 → 未识别行业则回到场景识别，否则进入对话回合
    graph.add_edge("greeting_guide", "await_input")
    graph.add_conditional_edges(
        "await_input",
        route_after_await,
        {
            "scene_recognize": "scene_recognize",        # 未识别 → 重新识别行业
            "conversation_turn": "conversation_turn",
            "generate_report": "generate_report",        # 强制诊断
        },
    )

    # 对话回合 → 等待输入 → 循环回到对话回合（信息收集主循环）
    graph.add_edge("conversation_turn", "await_input")

    # 生成报告 → 结束
    graph.add_edge("generate_report", END)

    return graph


# =============================================================================
# Workflow Manager
# =============================================================================

class WorkflowManager:
    """Manages the LangGraph workflow lifecycle."""

    def __init__(self):
        self._graph: Optional[CompiledStateGraph] = None
        self._checkpointer: Optional[AsyncSqliteSaver] = None
        self._checkpointer_ctx: Optional[Any] = None
        self._model: Optional[DiagnosisModel] = None
        self._locks: Dict[str, asyncio.Lock] = {}

    async def startup(self):
        """Initialize the graph, checkpointer, and model."""
        self._model = create_model()
        graph = build_graph(self._model)

        db_url = settings.checkpoint_db_url
        if db_url.startswith("sqlite+aiosqlite://"):
            db_path = db_url[len("sqlite+aiosqlite://"):]
        else:
            db_path = db_url

        self._checkpointer_ctx = AsyncSqliteSaver.from_conn_string(db_path)
        self._checkpointer = await self._checkpointer_ctx.__aenter__()
        await self._checkpointer.setup()

        self._graph = graph.compile(checkpointer=self._checkpointer)
        logger.info("WorkflowManager started")

    async def shutdown(self):
        """Clean up resources."""
        if self._checkpointer_ctx:
            await self._checkpointer_ctx.__aexit__(None, None, None)
            self._checkpointer_ctx = None
            self._checkpointer = None
        logger.info("WorkflowManager shut down")

    async def start(self, session_id: str, user_message: str, existing_messages: list = None) -> dict:
        """Start a new diagnosis workflow for a session.

        Args:
            session_id: The diagnosis session ID (used as LangGraph thread_id).
            user_message: The latest user message to process.
            existing_messages: Previous DB messages (dicts with role/content) to
                include in the initial state so the workflow sees full history.
        """
        if not self._graph:
            raise RuntimeError("WorkflowManager not started. Call startup() first.")

        init_state = make_initial_state(user_message, existing_messages)
        config = {"configurable": {"thread_id": session_id}}

        result = await self._graph.ainvoke(init_state, config)
        return result

    async def resume(self, session_id: str, payload: ResumeInput) -> dict:
        """Resume a paused workflow after user input."""
        if not self._graph:
            raise RuntimeError("WorkflowManager not started. Call startup() first.")

        config = {"configurable": {"thread_id": session_id}}

        # Set force_diagnosis before resuming if requested
        if payload.action == "diagnose_with_current_data":
            await self._graph.aupdate_state(
                config,
                {"force_diagnosis": True},
            )

        # Resume the workflow; routing checks force_diagnosis flag
        result = await self._graph.ainvoke(
            Command(resume=payload.content),
            config,
        )
        return result

    def get_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create a per-session asyncio.Lock for concurrency control."""
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]


# Singleton
workflow_manager = WorkflowManager()
