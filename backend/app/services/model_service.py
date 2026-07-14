"""LLM abstraction layer for BizSage3 diagnosis workflow.

Provides:
- DiagnosisModel (abstract base)
- OpenAICompatibleModel (production)
- MockDiagnosisModel (testing)
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
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
    ) -> str:
        """Generate structured diagnosis report from facts."""
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

    async def _invoke_chat(self, system: str, user: str, history: List[Dict[str, str]] = None, node_name: str = "") -> str:
        """Invoke LLM and return plain text. Optionally include prior conversation as real messages."""
        if history:
            prompt = ChatPromptTemplate.from_messages([
                ("system", system),
                MessagesPlaceholder(variable_name="history"),
                ("user", user),
            ])
        else:
            prompt = ChatPromptTemplate.from_messages([
                ("system", system),
                ("user", user),
            ])
        logger.info("[%s] LLM Chat request\nsystem: %s\nhistory: %s\nuser: %s", node_name, system, history, user)
        chain = prompt | self.llm
        invoke_args = {"history": history} if history else {}
        res = await chain.ainvoke(invoke_args)
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
            return await structured_llm.ainvoke(messages)
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
            return await self._invoke_chat(system, user_message, "greeting_guide 问候引导")
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
            result: ChatExtractOutput = await structured_llm.ainvoke(messages_payload)
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
            return await self._invoke_chat(system, "请基于以上事实做运营诊断分析", "diagnose 运营诊断")
        except Exception:
            return "⚠️ 抱歉，当前 AI 服务暂时不可用，无法完成诊断分析。请稍后重试，或联系管理员检查模型服务状态。"

    # ─── Generate Report ────────────────────────────────────────────────

    async def generate_report(
        self,
        raw_facts: List[str],
        completeness: CompletenessEval,
        scene: Dict[str, str],
    ) -> str:
        industry = scene.get("industry", "未知行业")
        facts_text = "\n".join(f"- {f}" for f in raw_facts) if raw_facts else "（暂无运营数据）"

        warning = ""
        if completeness.score < 80:
            warning = "⚠️ **注意：当前信息完备度为 {}%，报告可能不够全面，建议继续补充信息后重新生成。**\n\n".format(completeness.score)

        system = f"""你是{industry}行业的资深运营诊断专家。

【商户背景】行业：{industry}

【已有运营信息】
{facts_text}

【信息完备度】{completeness.score}%

请生成诊断报告。要求：
1. {warning}
2. 只基于已有事实分析，不编造数据
3. 根据{industry}行业特征自行决定报告结构——有多少事实就分析多少维度
4. 没有覆盖的方向统一归入"信息盲区"，说明还需收集什么
5. 每个维度包含：现状 → 判断 → 建议
6. 输出完整Markdown格式，用##二级标题分节
7. 用{industry}从业者熟悉的语言，不用"流量""转化率""指标"等通用术语"""
        try:
            return await self._invoke_chat(
                system,
                "请生成完整的运营诊断报告",
                "generate_report 生成报告",
            )
        except Exception:
            return (
                f"# 诊断报告\n\n"
                f"⚠️ **注意：AI 服务暂时不可用，以下为基于已知数据的静态汇总，非完整诊断报告。请稍后重试或联系管理员。**\n\n"
                f"{warning}\n"
                f"## 诊断概览\n\n"
                f"基于{len(raw_facts)}条运营信息，为{industry}行业商户生成初步诊断。\n\n"
                f"## 已知信息\n\n"
                f"{facts_text}\n\n"
                f"## 信息盲区\n\n"
                f"当前信息尚不完整，建议补充更多运营数据后重新生成详细报告。\n"
            )



# =============================================================================
# Mock Model (Testing — no API calls)
# =============================================================================

class MockDiagnosisModel(DiagnosisModel):
    """Deterministic mock for testing without LLM API calls."""

    INDUSTRY_PATTERNS = [
        (re.compile(r"电商|淘宝|京东|拼多多|抖音电商|独立站|天猫"), "电商"),
        (re.compile(r"本地生活|餐饮|美容|健身|家政|到店|上门|门店"), "本地生活"),
        (re.compile(r"小红书|抖音|公众号|B站|b站|播客|新媒体|内容|自媒体|短视频"), "新媒体内容"),
        (re.compile(r"ToB|tob|SaaS|saas|企业服务|软件|咨询|代理"), "ToB企业服务"),
        (re.compile(r"零售|商超|便利店|专柜|线下|商场|超市"), "线下零售"),
        (re.compile(r"教育|培训|知识付费|在线教育|课程"), "教育"),
    ]
    async def recognize_scene(self, user_message: str) -> Scene:
        industry = ""
        for pattern, label in self.INDUSTRY_PATTERNS:
            if pattern.search(user_message):
                industry = label
                break

        return Scene(industry=industry)

    async def greeting_guide(self, user_message: str) -> str:
        return (
            "你好！我是 BizSage 运营诊断助手。\n\n"
            "⚠️ 抱歉，当前 AI 服务暂不可用（Mock 模式），请联系管理员检查模型配置。"
        )

    async def chat_extract(
        self,
        messages: List[Dict[str, str]],
        existing_facts: List[str],
        scene: Dict[str, str],
    ) -> tuple[List[str], CompletenessEval]:
        # Simple regex-based extraction from the latest user message
        user_msgs = [m for m in messages if m.get("role") == "user"]
        latest = user_msgs[-1]["content"] if user_msgs else ""

        new_facts = []
        if latest and len(latest) > 3:
            new_facts.append(latest[:100])  # truncate as a "fact"

        # Mock completeness: grows with number of facts
        total = len(existing_facts) + len(new_facts)
        score = min(total * 20, 100)

        industry = scene.get("industry", "未知行业")
        all_aspects = {
            "餐饮": ["客流量", "客单价", "回头客", "成本结构", "高峰时段", "外卖情况"],
            "电商": ["店铺流量来源", "转化率", "客单价", "退货率", "广告投放", "爆款品"],
            "新媒体内容": ["播放量", "粉丝增长", "互动率", "内容发布频率", "变现情况"],
        }
        aspects = all_aspects.get(industry, all_aspects["电商"])
        missing = [a for a in aspects if a not in str(existing_facts)]

        completeness = CompletenessEval(
            score=score,
            summary=f"已收集{total}条运营信息" if total > 0 else "暂无运营信息",
            missing_aspects=missing[:4],
            next_question=f"最近{missing[0] if missing else '经营'}情况怎么样？",
        )
        return (new_facts, completeness)

    async def agent_reply(
        self,
        raw_facts: List[str],
        completeness: CompletenessEval,
        scene: Dict[str, str],
        messages: List[Dict[str, str]] = None,
    ) -> str:
        industry = scene.get("industry", "餐饮")
        next_q = completeness.next_question or "还有其他方面可以聊聊吗？"
        reply = f"了解了{'，'.join(raw_facts[-2:]) if raw_facts else ''}。"
        if completeness.score >= 80:
            reply += "\n\n**[信息已比较充分，点击按钮即可生成诊断报告]**"
        else:
            reply += f"{next_q}"
        return reply

    async def diagnose(self, raw_facts, scene) -> str:
        industry = scene.get("industry", "未知行业")
        facts_text = "\n".join(f"- {f}" for f in raw_facts) if raw_facts else "暂无数据"
        return (
            f"## {industry}运营诊断\n\n"
            f"基于{len(raw_facts)}条事实分析：\n\n{facts_text}\n\n"
            f"### 整体判断\n数据有限，初步判断运营状况需进一步了解。\n\n"
            f"### 建议\n继续补充运营信息以获得更全面的诊断。\n"
        )

    async def generate_report(
        self,
        raw_facts: List[str],
        completeness: CompletenessEval,
        scene: Dict[str, str],
    ) -> str:
        industry = scene.get("industry", "未知行业")
        warning = ""
        if completeness.score < 80:
            warning = f"⚠️ **注意：当前信息完备度为 {completeness.score}%，报告可能不够全面。**\n\n"
        facts_text = "\n".join(f"- {f}" for f in raw_facts) if raw_facts else "（暂无）"
        return (
            f"# {industry}运营诊断报告\n\n"
            f"{warning}"
            f"## 诊断概览\n\n"
            f"信息完备度：{completeness.score}%\n"
            f"已收集{len(raw_facts)}条运营信息\n\n"
            f"## 已知信息\n\n{facts_text}\n\n"
            f"## 信息盲区\n\n"
            + ("\n".join(f"- {a}" for a in completeness.missing_aspects) if completeness.missing_aspects else "暂无") +
            f"\n\n## 下一步建议\n\n继续补充运营信息后重新生成以获得更全面的诊断报告。\n"
        )


# =============================================================================
# Factory
# =============================================================================

def create_model() -> DiagnosisModel:
    """Create the appropriate model based on LLM_MODE setting."""
    if settings.llm_mode == "mock":
        return MockDiagnosisModel()
    return OpenAICompatibleModel()
