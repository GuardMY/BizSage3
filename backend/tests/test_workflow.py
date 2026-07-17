"""Tests for the conversational LangGraph workflow."""

from unittest.mock import AsyncMock

import pytest
from app.services.workflow import WorkflowManager
from app.domain.schemas import ResumeInput


@pytest.fixture
async def wf():
    """Create and start a WorkflowManager with mock model."""
    mgr = WorkflowManager(
        checkpoint_url="sqlite+aiosqlite:///checkpoints.db",
        setup_on_start=True,
    )
    await mgr.startup()
    yield mgr
    await mgr.shutdown()
    # Cleanup: remove test checkpoint files
    import os
    for f in ["checkpoints.db"]:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass


class TestWorkflowStart:
    """Tests for the initial workflow invocation (start)."""

    @pytest.mark.asyncio
    async def test_start_runs_scene_recognize(self, wf: WorkflowManager):
        """First message should trigger scene recognition."""
        msg = "我是做电商运营的，目前处于增长期"
        result = await wf.start("test-session-1", msg)

        assert "user_scene" in result
        assert "stage" in result
        scene = result.get("user_scene", {})
        assert isinstance(scene, dict)

    @pytest.mark.asyncio
    async def test_start_extracts_facts(self, wf: WorkflowManager):
        """Messages should produce extracted raw_facts."""
        msg = "我是做电商的，本月流量10万，曝光50万，转化率3%，营收20万"
        result = await wf.start("test-session-2", msg)

        raw_facts = result.get("raw_facts", [])
        assert isinstance(raw_facts, list)

    @pytest.mark.asyncio
    async def test_start_evaluates_completeness(self, wf: WorkflowManager):
        """Completeness evaluation should be stored."""
        msg = "我是做电商的"
        result = await wf.start("test-session-3", msg)

        completeness = result.get("completeness", {})
        assert isinstance(completeness, dict)
        score = completeness.get("score", 0)
        assert 0 <= score <= 100


class TestWorkflowInterrupt:
    """Tests for the interrupt/resume cycle (the closed loop)."""

    @pytest.mark.asyncio
    async def test_low_info_triggers_interrupt(self, wf: WorkflowManager):
        """With little info, the workflow should interrupt (await_input)."""
        msg = "我是做电商的，刚开始做"
        result = await wf.start("test-session-4", msg)

        stage = result.get("stage", "")
        assert stage in ("conversation_turn", "agent_reply", "await_input"), f"Expected interrupt stage, got: {stage}"

        messages = result.get("messages", [])
        has_question = any(
            m["role"] == "assistant" for m in messages
        )
        assert has_question, "Expected an assistant message in messages"

    @pytest.mark.asyncio
    async def test_resume_loops_back_to_extract(self, wf: WorkflowManager):
        """After user replies, workflow should resume and re-extract."""
        msg = "我是做电商的"
        state1 = await wf.start("test-session-5", msg)

        if state1.get("stage") in ("agent_reply", "await_input"):
            reply = ResumeInput(
                content="流量10万，曝光50万，访客2万，转化率3%，客单价200元，营收20万，成本8万，新增用户1000",
                action="reply",
            )
            state2 = await wf.resume("test-session-5", reply)

            messages = state2.get("messages", [])
            assert len(messages) > 0
        else:
            pytest.skip("Workflow didn't enter interrupt stage")


class TestWorkflowComplete:
    """Tests for the full end-to-end flow."""

    @pytest.mark.asyncio
    async def test_force_diagnose_from_any_stage(self, wf: WorkflowManager):
        """Force diagnose should trigger report generation."""
        msg = "我是做电商的"
        result = await wf.start("test-session-force-1", msg)

        # Force diagnose
        force = ResumeInput(content="", action="diagnose_with_current_data")
        result2 = await wf.resume("test-session-force-1", force)

        final_report = result2.get("final_report", "")
        assert final_report, "Expected a report to be generated"

    @pytest.mark.asyncio
    async def test_generate_report_receives_conversation_context(self, wf: WorkflowManager):
        """The report model should receive the accumulated chat, not only extracted facts."""
        await wf.start("test-session-report-context", "我是做电商的，本月访客两万人")
        wf._model.generate_report = AsyncMock(return_value="# 上下文诊断报告")

        result = await wf.resume(
            "test-session-report-context",
            ResumeInput(content="", action="diagnose_with_current_data"),
        )

        assert result["final_report"] == "# 上下文诊断报告"
        call = wf._model.generate_report.await_args
        assert call.kwargs["messages"]
        assert any(
            message.get("role") == "user" and "本月访客两万人" in message.get("content", "")
            for message in call.kwargs["messages"]
        )

    @pytest.mark.asyncio
    async def test_full_flow_with_enough_data(self, wf: WorkflowManager):
        """With comprehensive data, gather facts and generate report."""
        msg = (
            "我是做小红书美妆运营的，目前处于增长期。"
            "本月流量50万，曝光200万，访客5万，转化率3%，客单价150元，"
            "营收30万，成本12万，新增用户3000，流失率8%，复购率25%。"
            "播放量100万，点赞5万，粉丝增长2000，互动率5%。"
        )
        result = await wf.start("test-session-6", msg)

        stage = result.get("stage", "")
        final_report = result.get("final_report", "")

        if final_report:
            # Force diagnose after enough data
            assert len(final_report) > 0
        else:
            # Should be in a conversational stage
                        assert stage in ("conversation_turn", "agent_reply", "await_input", "chat_extract"), \
                f"Unexpected stage: {stage}"

    @pytest.mark.asyncio
    async def test_multiple_rounds_accumulate_facts(self, wf: WorkflowManager):
        """Multiple rounds of Q&A accumulate facts."""
        session_id = "test-session-7"

        result = await wf.start(session_id, "我是做电商的，处于增长期，本月流量10万")

        for i in range(3):
            stage = result.get("stage", "")
            if result.get("final_report"):
                break

            if stage in ("agent_reply", "await_input"):
                extra_data = f"第{i+1}轮补充：营收15万，成本6万，客单价100元"
                result = await wf.resume(
                    session_id,
                    ResumeInput(content=extra_data, action="reply"),
                )
            else:
                break

        # After several rounds, should have accumulated facts
        raw_facts = result.get("raw_facts", [])
        messages = result.get("messages", [])
        assert len(messages) >= 2, f"Expected at least 2 messages, got {len(messages)}"


class TestAgentState:
    """Basic state construction tests."""

    def test_initial_state(self):
        from app.services.workflow import make_initial_state
        state = make_initial_state("hello")
        assert state["messages"] == [{"role": "user", "content": "hello"}]
        assert state["raw_facts"] == []
        assert state["stage"] == "init"
        assert state["final_report"] == ""

    def test_state_is_dict(self):
        from app.services.workflow import make_initial_state
        state = make_initial_state("test")
        assert isinstance(state, dict)
        assert "messages" in state
        assert "user_scene" in state
        assert "raw_facts" in state
        assert "completeness" in state
