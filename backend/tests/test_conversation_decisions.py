"""Regression coverage for LLM conversation routing decisions."""

import pytest

from app.domain.schemas import CompletenessEval, ConversationTurnOutput, Scene
from app.services.model_service import _parse_conversation_turn_output
from app.services.workflow import _make_conversation_turn


def test_parser_preserves_parent_and_child_industry_fields():
    result = _parse_conversation_turn_output(
        """{
          "decision": "continue_diagnosis",
          "scene_action": "set",
          "scene": {
            "industry": "food service",
            "sub_industry": "hot pot restaurant",
            "business_mode": "dine-in and delivery",
            "operating_stage": "growth"
          },
          "new_facts": ["monthly revenue is down"],
          "completeness": {"score": 30, "summary": "basic revenue", "missing_aspects": ["traffic"], "next_question": "How is traffic?"},
          "reply": "I understand. How has customer traffic changed?",
          "suggested_replies": ["down 20%"],
          "reason": "single business confirmed"
        }"""
    )

    assert result.decision == "continue_diagnosis"
    assert result.scene_action == "set"
    assert result.scene.industry == "food service"
    assert result.scene.sub_industry == "hot pot restaurant"
    assert result.scene.business_mode == "dine-in and delivery"


class StaticTurnModel:
    def __init__(self, result: ConversationTurnOutput):
        self.result = result

    async def conversation_turn(self, *args, **kwargs) -> ConversationTurnOutput:
        return self.result


@pytest.mark.asyncio
async def test_general_reply_does_not_pollute_diagnosis_context():
    node = _make_conversation_turn(StaticTurnModel(ConversationTurnOutput(
        decision="general_reply",
        scene_action="keep",
        new_facts=["unrelated statement"],
        completeness=CompletenessEval(score=90, summary="should be ignored"),
        reply="I can help with operations diagnosis when you are ready.",
    )))

    result = await node({
        "messages": [{"role": "user", "content": "Tell me a joke"}],
        "user_scene": {"industry": "retail"},
        "raw_facts": ["weekly sales are 1000"],
        "completeness": {"score": 30, "summary": "existing context"},
    })

    assert result["raw_facts"] == ["weekly sales are 1000"]
    assert result["completeness"] == {"score": 30, "summary": "existing context"}
    assert result["user_scene"] == {"industry": "retail"}


@pytest.mark.asyncio
async def test_confirmed_business_switch_starts_a_new_fact_context():
    node = _make_conversation_turn(StaticTurnModel(ConversationTurnOutput(
        decision="continue_diagnosis",
        scene_action="replace",
        scene=Scene(industry="home renovation"),
        new_facts=["new business has low lead volume"],
        completeness=CompletenessEval(score=20, summary="new business only"),
        reply="We can start with the renovation business. How are leads coming in?",
    )))

    result = await node({
        "messages": [{"role": "user", "content": "I want to diagnose my renovation business instead"}],
        "user_scene": {"industry": "food service", "sub_industry": "hot pot"},
        "raw_facts": ["old restaurant traffic is down"],
        "completeness": {"score": 60},
    })

    assert result["user_scene"] == {"industry": "home renovation"}
    assert result["raw_facts"] == ["new business has low lead volume"]
    assert result["completeness"]["score"] == 20
