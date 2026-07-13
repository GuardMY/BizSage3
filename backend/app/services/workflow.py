"""LangGraph conversational workflow for operations diagnosis.

New graph (after removing hardcoded metric matching):

    START → scene_recognize
                ↓ (no industry)
           greeting_guide → await_input → back to scene_recognize
                ↓ (has industry)
           chat_extract (facts + LLM completeness)
                ↓
           agent_reply (industry-aware conversational guide)
                ↓
           await_input (interrupt, wait for user reply) ←── loop ──┐
                ↓                                                    │
           user triggers diagnosis ──→ generate_report → END         │
                                                                     │
           (normal reply) ──────────────────────────────────────────┘

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
from app.domain.schemas import ResumeInput, CompletenessEval
from app.services.model_service import DiagnosisModel, create_model

logger = logging.getLogger(__name__)


# =============================================================================
# State Definition
# =============================================================================

class AgentState(TypedDict, total=False):
    """State shared across all workflow nodes."""
    messages: List[Dict[str, str]]
    user_scene: Dict[str, str]
    raw_facts: List[str]
    completeness: Dict[str, Any]        # serialized CompletenessEval
    diagnosis_result: str
    final_report: str
    stage: str
    pending_question: str
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
        "raw_facts": [],
        "completeness": {},
        "diagnosis_result": "",
        "final_report": "",
        "stage": "init",
        "pending_question": "",
        "force_diagnosis": False,
        "error_message": "",
    }


# =============================================================================
# Node Implementations
# =============================================================================

def _make_scene_recognize(model: DiagnosisModel):
    """Node 1: Scene recognition — identify industry, stage."""

    async def node_scene_recognize(state: dict) -> dict:
        logger.info("Node: scene_recognize")
        messages = state.get("messages", [])
        if not messages:
            return {"stage": "scene_recognize"}

        user_msgs = [m for m in messages if m.get("role") == "user"]
        last_user = user_msgs[-1]["content"] if user_msgs else messages[-1].get("content", "")

        scene = await model.recognize_scene(last_user)
        return {
            "user_scene": scene.model_dump(),
            "stage": "scene_recognize",
        }

    return node_scene_recognize


def _make_greeting_guide(model: DiagnosisModel):
    """Node: Greeting guide — when no industry was identified."""

    async def node_greeting_guide(state: dict) -> dict:
        logger.info("Node: greeting_guide")
        messages = state.get("messages", [])

        user_msgs = [m for m in messages if m.get("role") == "user"]
        last_user = user_msgs[-1]["content"] if user_msgs else "你好"

        guide_text = await model.greeting_guide(last_user)

        messages = list(messages)
        messages.append({"role": "assistant", "content": guide_text})

        return {
            "messages": messages,
            "pending_question": guide_text,
            "stage": "greeting_guide",
        }

    return node_greeting_guide


def _make_chat_extract(model: DiagnosisModel):
    """Node: Extract operational facts + LLM completeness evaluation.

    Replaces the old collect_metrics + check_complete pair.
    One LLM call does both: extracts facts and scores completeness.
    """

    async def node_chat_extract(state: dict) -> dict:
        logger.info("Node: chat_extract")
        messages = state.get("messages", [])
        existing_facts = state.get("raw_facts", [])
        scene = state.get("user_scene", {})

        new_facts, completeness = await model.chat_extract(messages, existing_facts, scene)

        # Merge new facts with existing
        all_facts = list(existing_facts)
        for f in new_facts:
            if f not in all_facts:
                all_facts.append(f)

        return {
            "raw_facts": all_facts,
            "completeness": completeness.model_dump(),
            "stage": "chat_extract",
        }

    return node_chat_extract


def _make_agent_reply(model: DiagnosisModel):
    """Node: Generate industry-aware conversational reply.

    Uses the completeness evaluation to decide what to ask next.
    If score >= 80, includes a hint that the user can trigger diagnosis.
    """

    async def node_agent_reply(state: dict) -> dict:
        logger.info("Node: agent_reply")
        raw_facts = state.get("raw_facts", [])
        comp_data = state.get("completeness", {})
        scene = state.get("user_scene", {})

        completeness = CompletenessEval(**comp_data) if comp_data else CompletenessEval()

        reply = await model.agent_reply(raw_facts, completeness, scene)

        messages = list(state.get("messages", []))
        messages.append({"role": "assistant", "content": reply})

        return {
            "messages": messages,
            "pending_question": reply,
            "stage": "agent_reply",
        }

    return node_agent_reply


def _make_await_input():
    """Interrupt node: pause workflow and wait for user reply.

    On first invocation: interrupt() suspends the graph, returns the question.
    On resume (via Command(resume=...)): receives user reply, adds to messages.
    """

    async def node_await_input(state: dict) -> dict:
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

    Feeds all collected raw facts + completeness info to the LLM
    and produces a structured markdown report.
    """

    async def node_generate_report(state: dict) -> dict:
        logger.info("Node: generate_report")
        raw_facts = state.get("raw_facts", [])
        comp_data = state.get("completeness", {})
        scene = state.get("user_scene", {})
        force = state.get("force_diagnosis", False)

        completeness = CompletenessEval(**comp_data) if comp_data else CompletenessEval()

        report = await model.generate_report(raw_facts, completeness, scene)

        messages = list(state.get("messages", []))
        messages.append({"role": "assistant", "content": report})

        return {
            "final_report": report,
            "messages": messages,
            "stage": "generate_report",
        }

    return node_generate_report


# =============================================================================
# Routing
# =============================================================================

def route_after_scene(state: dict) -> str:
    """After scene recognition: if no industry identified, guide user."""
    scene = state.get("user_scene", {})
    if not scene or not scene.get("industry", ""):
        return "greeting_guide"
    # First message with scene? Check if we should go to chat_extract
    return "chat_extract"


def route_after_await(state: dict) -> str:
    """After user input: chat_extract (normal) or generate_report (forced)."""
    force = state.get("force_diagnosis", False)
    if force:
        return "generate_report"
    return "chat_extract"


def route_after_greeting(state: dict) -> str:
    """After greeting guide: go to await_input."""
    return "await_input"


# =============================================================================
# Graph Builder
# =============================================================================

def build_graph(model: Optional[DiagnosisModel] = None) -> StateGraph:
    """Build the conversational diagnosis LangGraph StateGraph.

    Nodes: scene_recognize, greeting_guide, chat_extract, agent_reply,
           await_input, generate_report

    Flow:
      START → scene_recognize
                ↓ (no industry) → greeting_guide → await_input → scene_recognize
                ↓ (has industry) → chat_extract → agent_reply → await_input → chat_extract
      Force diagnose: skip straight to generate_report
    """
    if model is None:
        model = create_model()

    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("scene_recognize", _make_scene_recognize(model))
    graph.add_node("greeting_guide", _make_greeting_guide(model))
    graph.add_node("chat_extract", _make_chat_extract(model))
    graph.add_node("agent_reply", _make_agent_reply(model))
    graph.add_node("await_input", _make_await_input())
    graph.add_node("generate_report", _make_generate_report(model))

    # Build edges
    graph.add_edge(START, "scene_recognize")

    # scene_recognize → greeting_guide (no industry) or chat_extract (has industry)
    graph.add_conditional_edges(
        "scene_recognize",
        route_after_scene,
        {
            "greeting_guide": "greeting_guide",
            "chat_extract": "chat_extract",
        },
    )

    # greeting_guide → await_input → back to scene_recognize (to re-identify)
    graph.add_edge("greeting_guide", "await_input")
    graph.add_conditional_edges(
        "await_input",
        route_after_await,
        {
            "chat_extract": "chat_extract",
            "generate_report": "generate_report",
        },
    )

    # chat_extract → agent_reply → await_input → loop back to chat_extract
    graph.add_edge("chat_extract", "agent_reply")
    graph.add_edge("agent_reply", "await_input")

    # generate_report → END
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
        logger.info("WorkflowManager started with %s model", settings.llm_mode)

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
