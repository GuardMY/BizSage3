"""Logging coverage for production structured LLM calls."""

import logging
from unittest.mock import AsyncMock, Mock

import pytest

from app.domain.schemas import ChatExtractOutput, CompletenessEval, Scene
from app.services.model_service import OpenAICompatibleModel


def model_with_structured_result(result):
    """Build a production model instance without constructing a real API client."""
    structured_llm = Mock()
    structured_llm.ainvoke = AsyncMock(return_value=result)

    model = OpenAICompatibleModel.__new__(OpenAICompatibleModel)
    model.llm = Mock()
    model.llm.with_structured_output.return_value = structured_llm
    return model


@pytest.mark.asyncio
async def test_recognize_scene_logs_structured_request_and_response(caplog):
    model = model_with_structured_result(Scene(industry="餐饮"))
    caplog.set_level(logging.INFO, logger="app.services.model_service")

    result = await model.recognize_scene("我在经营一家餐厅")

    assert result.industry == "餐饮"
    assert "[scene_recognize] LLM Structured request" in caplog.text
    assert "我在经营一家餐厅" in caplog.text
    assert "[scene_recognize] LLM Structured response" in caplog.text
    assert "'industry': '餐饮'" in caplog.text


@pytest.mark.asyncio
async def test_chat_extract_logs_structured_request_and_response(caplog):
    structured_result = ChatExtractOutput(
        new_facts=["日均营业额约1万元"],
        completeness=CompletenessEval(
            score=30,
            summary="已有基础营收信息",
            missing_aspects=["客单价"],
            next_question="客单价大概是多少？",
        ),
    )
    model = model_with_structured_result(structured_result)
    caplog.set_level(logging.INFO, logger="app.services.model_service")

    facts, completeness = await model.chat_extract(
        [{"role": "user", "content": "日均营业额约1万元"}],
        [],
        {"industry": "餐饮"},
    )

    assert facts == ["日均营业额约1万元"]
    assert completeness.score == 30
    assert "[chat_extract] LLM Structured request" in caplog.text
    assert "日均营业额约1万元" in caplog.text
    assert "[chat_extract] LLM Structured response" in caplog.text
    assert "'score': 30" in caplog.text
