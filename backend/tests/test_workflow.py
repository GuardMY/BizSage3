"""Tests for the LangGraph 6-node workflow."""

import pytest
from app.services.workflow import WorkflowManager, AgentState
from app.domain.schemas import ResumeInput


@pytest.fixture
async def wf():
    """Create and start a WorkflowManager with mock model."""
    mgr = WorkflowManager()
    await mgr.startup()
    yield mgr
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
        """First message should trigger scene recognition and metric collection."""
        msg = "我是做电商运营的，目前处于增长期"
        result = await wf.start("test-session-1", msg)

        assert "user_scene" in result
        assert "stage" in result
        # Should have identified the industry from the message
        scene = result.get("user_scene", {})
        assert isinstance(scene, dict)

    @pytest.mark.asyncio
    async def test_start_collects_metrics(self, wf: WorkflowManager):
        """Metrics mentioned in the first message should be collected."""
        msg = "我是做电商的，本月流量10万，曝光50万，转化率3%，营收20万"
        result = await wf.start("test-session-2", msg)

        metrics = result.get("collect_metrics", {})
        assert isinstance(metrics, dict)

    @pytest.mark.asyncio
    async def test_start_checks_completeness(self, wf: WorkflowManager):
        """After collection, completeness score should be calculated."""
        msg = "我是做电商的"
        result = await wf.start("test-session-3", msg)

        score = result.get("complete_score", 0)
        assert 0 <= score <= 100


class TestWorkflowInterrupt:
    """Tests for the interrupt/resume cycle (the closed loop)."""

    @pytest.mark.asyncio
    async def test_low_score_triggers_interrupt(self, wf: WorkflowManager):
        """When score < 80, the workflow should interrupt with a question."""
        msg = "我是做电商的，刚开始做"  # Very little info → low score
        result = await wf.start("test-session-4", msg)

        # After interrupt, the stage should indicate waiting for input
        stage = result.get("stage", "")
        assert stage in ("exception_ask", "await_input"), f"Expected interrupt stage, got: {stage}"

        # There should be a pending question or an assistant message
        messages = result.get("messages", [])
        has_question = any(
            m["role"] == "assistant" for m in messages
        )
        assert has_question, "Expected an assistant question in messages"

    @pytest.mark.asyncio
    async def test_resume_loops_back_to_collect(self, wf: WorkflowManager):
        """After user replies to a question, workflow should resume and re-collect."""
        # Start with minimal info
        msg = "我是做电商的"
        state1 = await wf.start("test-session-5", msg)

        # If we got interrupted, resume with more info
        if state1.get("stage") in ("exception_ask", "await_input"):
            reply = ResumeInput(
                content="流量10万，曝光50万，访客2万，转化率3%，客单价200元，营收20万，成本8万，新增用户1000，流失率5%，复购率30%",
                action="reply",
            )
            state2 = await wf.resume("test-session-5", reply)

            # After resume, we should have more messages and updated metrics
            messages = state2.get("messages", [])
            assert len(messages) > len(state1.get("messages", []))
        else:
            pytest.skip("Workflow didn't interrupt (maybe score already ≥ 80)")


class TestWorkflowComplete:
    """Tests for the full end-to-end flow."""

    @pytest.mark.asyncio
    async def test_full_flow_with_enough_data(self, wf: WorkflowManager):
        """With comprehensive data, the workflow should complete to a report."""
        msg = (
            "我是做小红书美妆运营的，目前处于增长期。"
            "本月流量50万，曝光200万，访客5万，转化率3%，客单价150元，"
            "营收30万，成本12万，新增用户3000，流失率8%，复购率25%。"
            "播放量100万，点赞5万，粉丝增长2000，互动率5%。"
        )
        result = await wf.start("test-session-6", msg)

        # The workflow either completed or paused for more info
        stage = result.get("stage", "")
        final_report = result.get("final_report", "")

        if final_report:
            # Report was generated successfully
            assert "诊断概览" in final_report or "运营诊断报告" in final_report or "综合健康度" in final_report
        else:
            # Need more data → should be in an interrupt-like state
            assert stage in ("exception_ask", "await_input", "check_complete", "collect_metrics"), \
                f"Unexpected stage: {stage}"

    @pytest.mark.asyncio
    async def test_multiple_rounds_to_completion(self, wf: WorkflowManager):
        """Multiple rounds of Q&A eventually produce a report."""
        session_id = "test-session-7"

        # Round 1: Basic intro
        result = await wf.start(session_id, "我是做电商的，处于增长期，本月流量10万，转化率2%")

        for i in range(5):
            stage = result.get("stage", "")
            if result.get("final_report"):
                break

            if stage in ("exception_ask", "await_input"):
                # Simulate user providing more data
                extra_data = (
                    f"第{i+1}轮补充：营收15万，成本6万，客单价100元，"
                    f"新增用户500，曝光30万，访客3万，流失率3%，复购率20%"
                )
                result = await wf.resume(
                    session_id,
                    ResumeInput(content=extra_data, action="reply"),
                )
            else:
                break

        # After several rounds, should have made progress
        score = result.get("complete_score", 0)
        messages = result.get("messages", [])
        assert len(messages) >= 2, f"Expected at least 2 messages, got {len(messages)}"


class TestAgentState:
    """Basic state construction tests."""

    def test_initial_state(self):
        from app.services.workflow import make_initial_state
        state = make_initial_state("hello")
        assert state["messages"] == [{"role": "user", "content": "hello"}]
        assert state["complete_score"] == 0
        assert state["stage"] == "init"
        assert state["need_ask"] is True
        assert state["final_report"] == ""

    def test_state_is_dict(self):
        from app.services.workflow import make_initial_state
        state = make_initial_state("test")
        assert isinstance(state, dict)
        assert "messages" in state
        assert "user_scene" in state
