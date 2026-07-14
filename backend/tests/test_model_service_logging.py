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


@pytest.mark.asyncio
async def test_generate_report_uses_full_context_and_keyword_arguments():
    model = OpenAICompatibleModel.__new__(OpenAICompatibleModel)
    model._invoke_chat = AsyncMock(return_value="# LLM 生成的报告")
    messages = [
        {"role": "user", "content": "工作日午市客流少，周末需要排队"},
        {"role": "assistant", "content": "外卖订单情况怎么样？"},
        {"role": "user", "content": "外卖约占三成"},
        {"role": "user", "content": ""},
    ]
    completeness = CompletenessEval(
        score=60,
        summary="已覆盖客流和渠道情况",
        missing_aspects=["菜品毛利", "回头客"],
    )

    report = await model.generate_report(
        ["工作日午市客流少", "外卖约占三成"],
        completeness,
        {"industry": "餐饮"},
        messages=messages,
    )

    assert report == "# LLM 生成的报告"
    call = model._invoke_chat.await_args
    system, user = call.args
    assert "餐饮" in system
    assert "工作日午市客流少" in system
    assert "已覆盖客流和渠道情况" in system
    assert "菜品毛利" in system
    assert "自行决定分析维度、报告结构与详略" in system
    assert "全部上下文" in user
    assert call.kwargs == {
        "history": messages[:3],
        "node_name": "generate_report 生成报告",
    }


@pytest.mark.asyncio
async def test_generate_report_propagates_llm_failure():
    model = OpenAICompatibleModel.__new__(OpenAICompatibleModel)
    model._invoke_chat = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

    with pytest.raises(RuntimeError, match="LLM unavailable"):
        await model.generate_report(
            ["日均营业额约 1 万元"],
            CompletenessEval(score=30),
            {"industry": "餐饮"},
            messages=[{"role": "user", "content": "日均营业额约 1 万元"}],
        )


@pytest.mark.asyncio
async def test_invoke_chat_treats_json_braces_as_literal_content():
    model = OpenAICompatibleModel.__new__(OpenAICompatibleModel)
    model.llm = Mock()
    model.llm.ainvoke = AsyncMock(return_value=Mock(content="# 报告"))

    result = await model._invoke_chat(
        '业务场景：{"industry": "餐饮"}',
        "请根据 {已有信息} 生成报告",
        history=[{"role": "user", "content": "套餐价格是 {99} 元"}],
        node_name="generate_report 生成报告",
    )

    assert result == "# 报告"
    sent_messages = model.llm.ainvoke.await_args.args[0]
    assert [message.type for message in sent_messages] == ["system", "human", "human"]
    assert sent_messages[0].content == '业务场景：{"industry": "餐饮"}'
    assert sent_messages[1].content == "套餐价格是 {99} 元"
    assert sent_messages[2].content == "请根据 {已有信息} 生成报告"
