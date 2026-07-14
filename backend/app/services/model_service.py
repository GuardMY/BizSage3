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
    async def chat_extract(
        self,
        messages: List[Dict[str, str]],
        existing_facts: List[str],
        scene: Dict[str, str],
    ) -> tuple[List[str], CompletenessEval]:
        """Extract operational facts + evaluate completeness in one call."""
        ...

    @abstractmethod
    async def agent_reply(
        self,
        raw_facts: List[str],
        completeness: CompletenessEval,
        scene: Dict[str, str],
        messages: List[Dict[str, str]] = None,
    ) -> str:
        """Generate the next conversational reply to guide the user."""
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

    # ─── Scene Recognition ──────────────────────────────────────────────

    async def recognize_scene(self, user_message: str) -> Scene:
        """Identify the user's industry from conversation context.

        Uses with_structured_output(Scene) — the LLM is forced to emit a
        tool call matching the Scene schema. Returns a Scene instance
        directly; no JSON parsing needed.
        """
        system = """你是运营诊断场景识别专家。根据用户对话内容识别其所在行业。

行业命名规则：尽量具体，如"火锅""茶饮""SaaS""服装零售"，不要用笼统大类。
如果无法确定行业，industry 填空字符串。"""
        try:
            structured_llm = self.llm.with_structured_output(Scene)
            messages = [
                SystemMessage(content=system),
                HumanMessage(content=user_message),
            ]
            logger.info(
                "[scene_recognize] LLM Structured request\nsystem: %s\nuser: %s",
                system,
                user_message,
            )
            result: Scene = await structured_llm.ainvoke(messages)
            logger.info(
                "[scene_recognize] LLM Structured response:\n%s",
                result.model_dump(),
            )
            return result
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

    # ─── Chat Extract (structured output — no manual JSON parsing) ────

    async def chat_extract(
        self,
        messages: List[Dict[str, str]],
        existing_facts: List[str],
        scene: Dict[str, str],
    ) -> tuple[List[str], CompletenessEval]:
        """Extract new facts + evaluate completeness in one structured call.

        Uses with_structured_output(ChatExtractOutput) — the LLM is forced
        to emit a tool call matching the schema. Returns a ChatExtractOutput
        Pydantic instance; no _parse_json needed.
        """
        industry = scene.get("industry", "未知行业")
        existing_text = "\n".join(f"- {f}" for f in existing_facts) if existing_facts else "（无）"
        recent = messages[-20:] if len(messages) > 20 else messages
        history_text = json.dumps(recent, ensure_ascii=False)

        system = f"""你是{industry}行业运营顾问，和一位{industry}经营者对话。

已知事实：
{existing_text}

任务：
1. new_facts：从最近对话提取经营相关的新事实，每条约20字，保留模糊表述
2. completeness：基于{industry}行业特征评估信息完备度
   - score：0-100分
   - summary：一句话概括现有信息覆盖情况
   - missing_aspects：3-5个还缺的方面（行业口语）
   - next_question：一句自然追问"""

        try:
            structured_llm = self.llm.with_structured_output(ChatExtractOutput)
            messages_payload = [
                SystemMessage(content=system),
                HumanMessage(content=f"对话历史：{history_text}"),
            ]
            logger.info(
                "[chat_extract] LLM Structured request\nsystem: %s\nuser: %s",
                system,
                history_text,
            )
            result: ChatExtractOutput = await structured_llm.ainvoke(messages_payload)
            logger.info(
                "[chat_extract] LLM Structured response:\n%s",
                result.model_dump(),
            )
            return (result.new_facts, result.completeness)
        except Exception as e:
            logger.exception("[chat_extract] 对话提取失败: %s", e)
            return ([], CompletenessEval())

    # ─── Agent Reply (NEW: conversational guide) ────────────────────────

    async def agent_reply(
        self,
        raw_facts: List[str],
        completeness: CompletenessEval,
        scene: Dict[str, str],
        messages: List[Dict[str, str]] = None,
    ) -> str:
        industry = scene.get("industry", "未知行业")
        facts_text = "\n".join(f"- {f}" for f in raw_facts) if raw_facts else "（暂无）"
        missing_text = "\n".join(f"- {a}" for a in completeness.missing_aspects) if completeness.missing_aspects else "暂无"

        system = f"""你是 BizSage 运营顾问，正在和一位{industry}行业的经营者聊天。

已知信息：
{facts_text}

信息完备度：{completeness.score}%
还缺什么：
{missing_text}

请像懂行的朋友一样简短回复（80字以内），语气自然不机械。严格按以下结构输出，不得多问：
1. 对用户刚说的内容表达共情/确认（1句）
2. 紧接着只问一个问题，之前没问过的，且只涉及一个方向，内容根据上下文生成。像朋友聊天一样自然引出，不要罗列、不要用"我还需要XX数据"这种句式
3. 如果完备度 >= 80%，在回复末尾加上这一行提示：**[信息已比较充分，点击按钮即可生成诊断报告]**

直接输出对话文本，不要JSON，不要markdown代码块。"""

        recent = (messages or [])[-100:]

        try:
            return await self._invoke_chat(system, "请生成回复", history=recent, node_name="agent_reply 助手回复")
        except Exception:
            if completeness.score >= 80:
                return "⚠️ 抱歉，当前 AI 服务暂时不可用，无法生成动态回复。信息可能已比较充分，你可以尝试点击生成诊断报告，或稍后重试。"
            return "⚠️ 抱歉，当前 AI 服务暂时不可用，无法生成动态回复。请稍后重试，或联系管理员检查模型服务状态。"

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



# =============================================================================
# Factory
# =============================================================================

def create_model() -> DiagnosisModel:
    """Create the production OpenAI-compatible model."""
    return OpenAICompatibleModel()
