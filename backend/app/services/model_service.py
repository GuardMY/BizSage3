"""LLM abstraction layer for BizSage3 diagnosis workflow.

Provides:
- DiagnosisModel (abstract base)
- OpenAICompatibleModel (production)
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

from langchain_core.messages import SystemMessage, HumanMessage, convert_to_messages
from langchain_openai import ChatOpenAI

from app.config import settings
from app.domain.schemas import (
    Scene,
    CompletenessEval,
    ChatExtractOutput,
    AgentReplyOutput,
    ConversationTurnOutput,
)


# =============================================================================
# Abstract Base
# =============================================================================

class DiagnosisModel(ABC):
    """Abstract interface for LLM-powered diagnosis operations."""

    @abstractmethod
    async def recognize_scene(self, user_message: str) -> Scene:
        """Node 1: Recognize industry, business mode, stage, diagnosis target."""
        ...

    @abstractmethod
    async def greeting_guide(self, user_message: str) -> str:
        """Generate a self-introduction + guiding question when no scene is identified."""
        ...

    @abstractmethod
    async def conversation_turn(
        self,
        messages: List[Dict[str, str]],
        existing_facts: List[str],
        scene: Dict[str, str],
    ) -> ConversationTurnOutput:
        """Single-call conversation turn: extract facts + evaluate completeness
        + generate reply + generate quick-reply suggestions.

        Merges the old chat_extract and agent_reply into one LLM call.
        """
        ...

    @abstractmethod
    async def diagnose(
        self,
        raw_facts: List[str],
        scene: Dict[str, str],
    ) -> str:
        """Run diagnosis analysis based on collected facts."""
        ...

    @abstractmethod
    async def generate_report(
        self,
        raw_facts: List[str],
        completeness: CompletenessEval,
        scene: Dict[str, str],
        messages: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Generate a diagnosis report from the full conversation context."""
        ...


# =============================================================================
# OpenAI-Compatible Model (Production)
# =============================================================================

class OpenAICompatibleModel(DiagnosisModel):
    """LLM-powered diagnosis using OpenAI-compatible API."""

    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
        # Separate LLM instance with JSON mode for structured outputs
        self.json_llm = ChatOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            model_kwargs={"response_format": {"type": "json_object"}},
        )

    async def _invoke_chat(
        self,
        system: str,
        user: str,
        *,
        history: Optional[List[Dict[str, str]]] = None,
        node_name: str = "",
    ) -> str:
        """Invoke LLM and return plain text. Optionally include prior conversation as real messages."""
        messages = [SystemMessage(content=system)]
        if history:
            messages.extend(convert_to_messages(history))
        messages.append(HumanMessage(content=user))

        logger.info("[%s] LLM Chat request\nsystem: %s\nhistory: %s\nuser: %s", node_name, system, history, user)
        res = await self.llm.ainvoke(messages)
        content = res.content
        logger.info("[%s] LLM Chat response:\n%s", node_name, content)
        return content

    async def _invoke_json(
        self,
        system: str,
        user: str,
        *,
        history: Optional[List[Dict[str, str]]] = None,
        node_name: str = "",
    ) -> str:
        """Invoke LLM with JSON mode (response_format={'type': 'json_object'}).

        Uses DeepSeek-compatible JSON mode. The system or user prompt MUST contain
        the word 'json' and a sample JSON structure to guide the model.
        """
        messages = [SystemMessage(content=system)]
        if history:
            messages.extend(convert_to_messages(history))
        messages.append(HumanMessage(content=user))

        logger.info("[%s] LLM JSON request\nsystem: %s\nhistory: %s\nuser: %s", node_name, system, history, user)
        res = await self.json_llm.ainvoke(messages)
        content = res.content
        logger.info("[%s] LLM JSON response:\n%s", node_name, content)
        return content

    # ─── Scene Recognition ──────────────────────────────────────────────

    async def recognize_scene(self, user_message: str) -> Scene:
        """Identify the user's industry from conversation context.

        Uses JSON-mode prompt for maximum provider compatibility.
        """
        system = """你是运营诊断场景识别专家。根据用户对话内容识别其所在行业。

行业命名规则：尽量具体，如"火锅""茶饮""SaaS""服装零售"，不要用笼统大类。
如果无法确定行业，industry 填空字符串。

请严格按照 JSON 格式输出，不要包含 markdown 代码块标记：
{"industry": "识别到的行业名称"}"""
        try:
            raw = await self._invoke_json(
                system,
                user_message,
                node_name="scene_recognize 场景识别",
            )
            data = json.loads(raw.strip())
            if isinstance(data, dict) and "industry" in data:
                return Scene(industry=str(data["industry"]))
            return Scene()
        except Exception:
            logger.exception("[scene_recognize] 场景识别失败")
            return Scene()

    # ─── Greeting Guide ─────────────────────────────────────────────────

    async def greeting_guide(self, user_message: str) -> str:
        system = """你是 BizSage 运营诊断助手。用户刚刚跟你打招呼或没有提供足够的业务信息。
请做简短自我介绍（你是谁、能做什么）。

规则：
1. 自我介绍不超过3句话
2. 话术友好自然，不要用机械语气
3. 直接输出对话文本，不要JSON"""

        try:
            return await self._invoke_chat(
                system,
                user_message,
                node_name="greeting_guide 问候引导",
            )
        except Exception:
            return (
                "你好！我是 BizSage 运营诊断助手。\n\n"
                "⚠️ 抱歉，当前 AI 服务暂时不可用，无法生成动态回复。请稍后重试，或联系管理员检查模型服务状态。"
            )

    # ─── Conversation Turn (merged: chat_extract + agent_reply) ────────

    async def conversation_turn(
        self,
        messages: List[Dict[str, str]],
        existing_facts: List[str],
        scene: Dict[str, str],
    ) -> ConversationTurnOutput:
        """Single LLM call: extract facts, evaluate completeness, generate reply
        and quick-reply suggestions — all in one turn.

        Uses JSON-mode prompt for maximum provider compatibility.
        """
        industry = scene.get("industry", "未知行业")
        existing_text = "\n".join(f"- {f}" for f in existing_facts) if existing_facts else "（无）"
        recent = messages[-20:] if len(messages) > 20 else messages
        history_text = json.dumps(recent, ensure_ascii=False)

        system = f"""你是{industry}行业运营顾问，正在和一位{industry}经营者对话。

已知事实：
{existing_text}

请在一次回复中完成以下所有任务。严格按 JSON 格式输出，不要包含 markdown 代码块标记：

{{{{
  "new_facts": ["新提取的运营事实1", "新提取的运营事实2", ...],
  "completeness": {{{{
    "score": 0-100的整数,
    "summary": "一句话概括现有信息覆盖情况",
    "missing_aspects": ["还缺的方面1", "还缺的方面2", ...],
    "next_question": "一句自然追问"
  }}}},
  "reply": "你的对话回复文本",
  "suggested_replies": ["预测回答1", "预测回答2", ...]
}}}}

各字段要求：
- new_facts：从最近对话提取经营相关的新事实，每条约20字，保留模糊表述。如无新事实则为空数组
- completeness.score：基于{industry}行业特征评估信息完备度，0-100
- completeness.summary：一句话概括现有信息
- completeness.missing_aspects：3-5个还缺的方面（行业口语）
- completeness.next_question：一句自然追问
- reply：像懂行的朋友一样简短回复（80字以内），语气自然不机械：
  1. 对用户刚说的内容表达共情/确认（1句）
  2. 只问一个问题，之前没问过的，只涉及一个方向，像朋友聊天自然引出
  3. 如果完备度 >= 80%，在末尾加上：**[信息已比较充分，点击按钮即可生成诊断报告]**
- suggested_replies：3-10个预测用户可能回复的答案（每条10字以内），用户视角的回答，不是追问"""

        try:
            raw = await self._invoke_json(
                system,
                f"对话历史：{history_text}",
                history=None,  # history already embedded in user message
                node_name="conversation_turn 对话回合",
            )
            result = _parse_conversation_turn_output(raw)
            return result
        except Exception:
            logger.exception("[conversation_turn] 对话回合失败")
            return ConversationTurnOutput(
                new_facts=[],
                completeness=CompletenessEval(),
                reply="⚠️ 抱歉，当前 AI 服务暂时不可用，无法生成动态回复。请稍后重试，或联系管理员检查模型服务状态。",
                suggested_replies=[],
            )

    # ─── Diagnose ───────────────────────────────────────────────────────

    async def diagnose(
        self,
        raw_facts: List[str],
        scene: Dict[str, str],
    ) -> str:
        industry = scene.get("industry", "未知行业")
        facts_text = "\n".join(f"- {f}" for f in raw_facts) if raw_facts else "（暂无运营数据）"

        system = f"""你是{industry}行业的资深运营诊断专家。

请基于下列运营事实，自行选择适合{industry}行业的分析维度做诊断（可以是流量、转化、用户、产品、成本、运营动作等维度中与已有数据相关的部分，不必面面俱到）。

【已有运营事实】
{facts_text}

要求：
1. 只基于已有事实分析，不编造数据
2. 有多少信息就分析多少维度，没有覆盖到的方向标为"信息不足"
3. 每个维度的分析包括：现状判断 → 可能原因 → 优化建议
4. 用{industry}从业者熟悉的语言

直接输出分析文本，不要JSON。"""

        try:
            return await self._invoke_chat(
                system,
                "请基于以上事实做运营诊断分析",
                node_name="diagnose 运营诊断",
            )
        except Exception:
            return "⚠️ 抱歉，当前 AI 服务暂时不可用，无法完成诊断分析。请稍后重试，或联系管理员检查模型服务状态。"

    # ─── Generate Report ────────────────────────────────────────────────

    async def generate_report(
        self,
        raw_facts: List[str],
        completeness: CompletenessEval,
        scene: Dict[str, str],
        messages: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        industry = scene.get("industry") or "未知行业"
        scene_text = json.dumps(scene, ensure_ascii=False) if scene else "（未识别）"
        facts_text = "\n".join(f"- {f}" for f in raw_facts) if raw_facts else "（暂无运营数据）"
        summary = completeness.summary or "（暂无概括）"
        missing_text = (
            "\n".join(f"- {aspect}" for aspect in completeness.missing_aspects)
            if completeness.missing_aspects
            else "（暂无）"
        )
        history = [
            {"role": message.get("role", "user"), "content": message.get("content", "")}
            for message in (messages or [])[-100:]
            if message.get("role") in {"user", "assistant"} and message.get("content")
        ]

        coverage_instruction = "无需添加信息完备度警告。"
        if completeness.score < 80:
            coverage_instruction = (
                f"当前信息完备度为 {completeness.score}%，请在报告开头明确提示结论的局限性。"
            )

        system = f"""你是{industry}行业的资深运营诊断专家。

【业务场景】
{scene_text}

【已提取的运营事实】
{facts_text}

【信息完备度评估】
- 得分：{completeness.score}%
- 概括：{summary}
- 尚缺信息：
{missing_text}

请结合上述结构化信息和随后提供的对话上下文，自主生成诊断报告。要求：
1. 只基于上下文中已经出现的信息分析，不编造数据或经营背景
2. 根据{industry}行业特征和已有信息自行决定分析维度、报告结构与详略，不套用固定维度
3. 对有依据的关键信息给出现状、判断、可能原因和可执行建议，并区分事实与推断
4. 未覆盖但会影响判断的内容统一归入“信息盲区”，说明需要补充什么
5. {coverage_instruction}
6. 输出可直接展示的完整 Markdown，使用二级标题分节
7. 使用{industry}从业者熟悉的具体语言，避免空泛套话"""
        try:
            return await self._invoke_chat(
                system,
                "请基于以上全部上下文生成完整的运营诊断报告",
                history=history,
                node_name="generate_report 生成报告",
            )
        except Exception:
            logger.exception("[generate_report] 诊断报告生成失败")
            raise



def _parse_conversation_turn_output(raw: str) -> ConversationTurnOutput:
    """Parse the LLM response into ConversationTurnOutput.

    Handles:
    - Clean JSON
    - JSON wrapped in ```json code blocks
    - Plain text fallback (treat the whole text as reply, empty everything else)
    """
    import re

    text = raw.strip()

    # Try to extract JSON from ```json ... ``` blocks
    code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if code_block_match:
        text = code_block_match.group(1).strip()

    # Try to find a JSON object in the text
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            if isinstance(data, dict) and "reply" in data:
                # Parse completeness sub-object
                comp_raw = data.get("completeness", {})
                completeness = CompletenessEval(
                    score=int(comp_raw.get("score", 0)),
                    summary=str(comp_raw.get("summary", "")),
                    missing_aspects=_ensure_str_list(comp_raw.get("missing_aspects", [])),
                    next_question=str(comp_raw.get("next_question", "")),
                )
                return ConversationTurnOutput(
                    new_facts=_ensure_str_list(data.get("new_facts", [])),
                    completeness=completeness,
                    reply=str(data["reply"]),
                    suggested_replies=_ensure_str_list(data.get("suggested_replies", [])),
                )
        except (json.JSONDecodeError, TypeError, KeyError, ValueError):
            pass

    # Fallback: treat the entire text as the reply
    logger.warning("[conversation_turn] Could not parse JSON from response, using raw text as reply")
    return ConversationTurnOutput(
        new_facts=[],
        completeness=CompletenessEval(),
        reply=raw,
        suggested_replies=[],
    )


def _ensure_str_list(val: Any) -> List[str]:
    """Coerce a value to a list of strings, capped at 10 items."""
    if not isinstance(val, list):
        return []
    return [str(v) for v in val[:10]]


# =============================================================================
# Factory
# =============================================================================

def create_model() -> DiagnosisModel:
    """Create the production OpenAI-compatible model."""
    return OpenAICompatibleModel()
