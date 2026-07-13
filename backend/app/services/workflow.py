"""LangGraph 6-node closed-loop workflow for operations diagnosis.

Strictly follows the reference document's architecture:
  scene_recognize -> collect_metrics -> check_complete
      ^                    |              |
      +-- exception_ask <--+[score<80]  [score>=80] -> diagnosis_analysis
            |                                              |
       [interrupt()]                              generate_report -> END
       (user replies -> back to collect_metrics)

Uses LangGraph's interrupt() for human-in-the-loop pauses.
Checkpoints persisted via AsyncSqliteSaver (SQLite).
"""

import asyncio
import logging
from typing import Any, Optional, Dict, List, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import interrupt, Command

from app.config import settings
from app.domain.catalog import calculate_score
from app.domain.schemas import ResumeInput
from app.services.model_service import DiagnosisModel, create_model

logger = logging.getLogger(__name__)


# =============================================================================
# State Definition
# =============================================================================

class AgentState(TypedDict, total=False):
    """State shared across all workflow nodes.

    Uses TypedDict (total=False) for LangGraph compatibility.
    All fields have defaults applied in make_initial_state().
    """
    messages: List[Dict[str, str]]
    user_scene: Dict[str, str]
    collect_metrics: Dict[str, Any]
    miss_metrics: List[str]
    complete_score: int
    need_ask: bool
    diagnosis_result: str
    final_report: str
    stage: str
    pending_question: str
    asked_codes: List[str]
    force_diagnosis: bool
    limited_diagnosis: bool
    error_message: str


def make_initial_state(user_message: str) -> dict:
    """Create a fresh state dict with defaults for a new session."""
    return {
        "messages": [{"role": "user", "content": user_message}],
        "user_scene": {},
        "collect_metrics": {},
        "miss_metrics": [],
        "complete_score": 0,
        "need_ask": True,
        "diagnosis_result": "",
        "final_report": "",
        "stage": "init",
        "pending_question": "",
        "asked_codes": [],
        "force_diagnosis": False,
        "limited_diagnosis": False,
        "error_message": "",
    }


# =============================================================================
# Node Implementations
# =============================================================================

def _make_scene_recognize(model: DiagnosisModel):
    """Node 1: Scene recognition - identify industry, stage, diagnosis target."""

    async def node_scene_recognize(state: dict) -> dict:
        logger.info("Node 1: scene_recognize")
        messages = state.get("messages", [])
        if not messages:
            return {"stage": "scene_recognize"}

        # Get the latest user message for scene recognition
        user_msgs = [m for m in messages if m.get("role") == "user"]
        last_user = user_msgs[-1]["content"] if user_msgs else messages[-1].get("content", "")

        scene = await model.recognize_scene(last_user)
        return {
            "user_scene": scene.model_dump(),
            "stage": "scene_recognize",
        }

    return node_scene_recognize


def _make_collect_metrics(model: DiagnosisModel):
    """Node 2: Collect metrics - extract structured indicators from conversation."""

    async def node_collect_metrics(state: dict) -> dict:
        logger.info("Node 2: collect_metrics")
        messages = state.get("messages", [])
        existing = state.get("collect_metrics", {})
        scene = state.get("user_scene", {})

        collected, missing = await model.collect_metrics(messages, existing, scene)

        # Merge with existing (don't lose previously collected metrics)
        merged = dict(existing)
        merged.update(collected)

        return {
            "collect_metrics": merged,
            "miss_metrics": missing,
            "stage": "collect_metrics",
        }

    return node_collect_metrics


def _make_check_complete():
    """Node 3: Completeness check - pure Python scoring, no LLM."""

    async def node_check_complete(state: dict) -> dict:
        logger.info("Node 3: check_complete")
        metrics = state.get("collect_metrics", {})
        scene = state.get("user_scene", {})
        force = state.get("force_diagnosis", False)

        industry = scene.get("industry", "")
        provided_codes = list(metrics.keys())

        result = calculate_score(
            provided_metric_codes=provided_codes,
            industry=industry,
            threshold=settings.complete_threshold,
        )

        # Determine if we should ask or diagnose
        if force and result.can_limited_diagnose:
            need_ask = False
            limited = True
        else:
            need_ask = not result.passed
            limited = False

        return {
            "complete_score": result.score,
            "need_ask": need_ask,
            "limited_diagnosis": limited,
            "stage": "check_complete",
        }

    return node_check_complete


def _make_exception_ask(model: DiagnosisModel):
    """Node 4: Exception ask - generate 1-2 targeted follow-up questions."""

    async def node_exception_ask(state: dict) -> dict:
        logger.info("Node 4: exception_ask")
        miss_metrics = state.get("miss_metrics", [])
        scene = state.get("user_scene", {})
        asked = state.get("asked_codes", [])

        question = await model.ask_followup(miss_metrics, scene, asked)

        # Track which metrics we're asking about
        new_asked = list(asked)
        for m in miss_metrics[:2]:
            if m not in new_asked:
                new_asked.append(m)

        # Add the question to messages
        messages = list(state.get("messages", []))
        messages.append({"role": "assistant", "content": question})

        return {
            "messages": messages,
            "pending_question": question,
            "asked_codes": new_asked,
            "stage": "exception_ask",
        }

    return node_exception_ask


def _make_await_input():
    """Interrupt node: pause workflow and wait for user reply.

    Uses LangGraph's interrupt() - on first invocation it suspends the graph
    and returns the question to the caller. On resume (via Command(resume=...)),
    it receives the user's reply and adds it to messages.
    """

    async def node_await_input(state: dict) -> dict:
        logger.info("Node: await_input (interrupt)")
        question = state.get("pending_question", "Please provide more information")

        # interrupt() suspends here; returns user reply on resume
        user_reply: str = interrupt({"question": question})

        # Add user reply to messages
        messages = list(state.get("messages", []))
        messages.append({"role": "user", "content": user_reply})

        return {
            "messages": messages,
            "stage": "await_input",
        }

    return node_await_input


def _make_diagnosis_analysis(model: DiagnosisModel):
    """Node 5: 6-dimension diagnosis analysis."""

    async def node_diagnosis_analysis(state: dict) -> dict:
        logger.info("Node 5: diagnosis_analysis")
        metrics = state.get("collect_metrics", {})
        scene = state.get("user_scene", {})

        result = await model.diagnose(metrics, scene)

        return {
            "diagnosis_result": result,
            "stage": "diagnosis_analysis",
        }

    return node_diagnosis_analysis


def _make_generate_report(model: DiagnosisModel):
    """Node 6: Generate structured diagnosis report (LLM-based per design doc)."""

    async def node_generate_report(state: dict) -> dict:
        logger.info("Node 6: generate_report")
        diagnosis = state.get("diagnosis_result", "")
        metrics = state.get("collect_metrics", {})
        score = state.get("complete_score", 0)
        miss = state.get("miss_metrics", [])
        limited = state.get("limited_diagnosis", False)

        report = await model.generate_report(diagnosis, metrics, score, miss)

        # Append report to messages
        messages = list(state.get("messages", []))
        messages.append({"role": "assistant", "content": report})

        return {
            "final_report": report,
            "messages": messages,
            "limited_diagnosis": limited,
            "stage": "generate_report",
        }

    return node_generate_report


# =============================================================================
# Routing
# =============================================================================

def route_after_check(state: dict) -> str:
    """Branch: ask follow-up OR proceed to diagnosis."""
    need_ask = state.get("need_ask", False)
    if need_ask:
        return "exception_ask"
    return "diagnosis_analysis"


def route_after_await(state: dict) -> str:
    """After user input received, loop back to collect_metrics."""
    return "collect_metrics"


# =============================================================================
# Graph Builder
# =============================================================================

def build_graph(model: Optional[DiagnosisModel] = None) -> StateGraph:
    """Build the 6-node LangGraph StateGraph for operations diagnosis.

    Returns a compiled StateGraph with:
      - 6 processing nodes (scene_recognize through generate_report)
      - 1 interrupt node (await_input)
      - Conditional routing based on completeness score
      - AsyncSqliteSaver checkpointing
    """
    if model is None:
        model = create_model()

    graph = StateGraph(AgentState)

    # Register all nodes
    graph.add_node("scene_recognize", _make_scene_recognize(model))
    graph.add_node("collect_metrics", _make_collect_metrics(model))
    graph.add_node("check_complete", _make_check_complete())
    graph.add_node("exception_ask", _make_exception_ask(model))
    graph.add_node("await_input", _make_await_input())
    graph.add_node("diagnosis_analysis", _make_diagnosis_analysis(model))
    graph.add_node("generate_report", _make_generate_report(model))

    # Build edges matching the reference document's flow
    graph.add_edge(START, "scene_recognize")
    graph.add_edge("scene_recognize", "collect_metrics")
    graph.add_edge("collect_metrics", "check_complete")

    # Conditional branch: score < 80 -> ask, score >= 80 -> diagnose
    graph.add_conditional_edges(
        "check_complete",
        route_after_check,
        {
            "exception_ask": "exception_ask",
            "diagnosis_analysis": "diagnosis_analysis",
        },
    )

    # exception_ask -> await_input (interrupt) -> back to collect_metrics
    graph.add_edge("exception_ask", "await_input")
    graph.add_conditional_edges(
        "await_input",
        route_after_await,
        {
            "collect_metrics": "collect_metrics",
        },
    )

    # diagnosis -> report -> END
    graph.add_edge("diagnosis_analysis", "generate_report")
    graph.add_edge("generate_report", END)

    return graph


# =============================================================================
# Workflow Manager
# =============================================================================

class WorkflowManager:
    """Manages the LangGraph workflow lifecycle.

    Responsibilities:
      - Initialize and hold the compiled graph with checkpointer
      - start(): Run from START to first interrupt() (or END)
      - resume(): Resume from an interrupt() checkpoint
      - delete_thread(): Clean up a session's checkpoint state
    """

    def __init__(self):
        self._graph: Optional[CompiledStateGraph] = None
        self._checkpointer: Optional[AsyncSqliteSaver] = None
        self._checkpointer_ctx: Optional[Any] = None
        self._model: Optional[DiagnosisModel] = None
        self._locks: Dict[str, asyncio.Lock] = {}

    async def startup(self):
        """Initialize the graph, checkpointer, and model. Call once at app startup."""
        self._model = create_model()
        graph = build_graph(self._model)

        # Set up SQLite checkpointer for persistence
        db_url = settings.checkpoint_db_url
        if db_url.startswith("sqlite+aiosqlite://"):
            db_path = db_url[len("sqlite+aiosqlite://"):]
        else:
            db_path = db_url

        # from_conn_string is an async context manager - enter it and hold
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

    async def start(self, session_id: str, user_message: str) -> dict:
        """Start a new diagnosis workflow for a session.

        Args:
            session_id: Unique session identifier (used as thread_id).
            user_message: The first user message.

        Returns:
            The final state dict after running until interrupt or completion.
        """
        if not self._graph:
            raise RuntimeError("WorkflowManager not started. Call startup() first.")

        init_state = make_initial_state(user_message)
        config = {"configurable": {"thread_id": session_id}}

        result = await self._graph.ainvoke(init_state, config)
        return result

    async def resume(self, session_id: str, payload: ResumeInput) -> dict:
        """Resume a paused workflow after user input.

        Args:
            session_id: Session identifier (thread_id).
            payload: The user's reply (content + action).

        Returns:
            The final state dict after running until next interrupt or END.
        """
        if not self._graph:
            raise RuntimeError("WorkflowManager not started. Call startup() first.")

        config = {"configurable": {"thread_id": session_id}}

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
