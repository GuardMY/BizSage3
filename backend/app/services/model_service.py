"""LLM abstraction layer for BizSage3 diagnosis workflow.

Provides:
- DiagnosisModel (abstract base)
- OpenAICompatibleModel (production)
- MockDiagnosisModel (testing)
"""

import json
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from app.config import settings
from app.domain.schemas import (
    Scene,
    CompletenessEval,
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

    async def _invoke_json(self, system: str, user: str) -> str:
        """Invoke LLM with system+user prompt, return raw content."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", system),
            ("user", user),
        ])
        chain = prompt | self.llm
        res = await chain.ainvoke({})
        return res.content

    async def _invoke_chat(self, system: str, user: str) -> str:
        """Invoke LLM and return plain text (no JSON enforcement)."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", system),
            ("user", user),
        ])
        chain = prompt | self.llm
        res = await chain.ainvoke({})
        return res.content

    # ─── Scene Recognition (unchanged) ──────────────────────────────────

    async def recognize_scene(self, user_message: str) -> Scene:
        system = """你是运营诊断场景识别专家，严格根据用户对话内容提取场景信息，仅输出JSON结构化数据。
输出字段固定：
- industry: 从对话中提取的行业类别，自由命名，尽量具体（例如：火锅、茶饮、快餐、服装零售、在线教育、SaaS等），不要用笼统的大类。如果用户提到多个相关行业，选最核心的那个

无信息则填空字符串，禁止输出多余解释、禁止自由发挥。
仅输出纯JSON，不要markdown代码块包裹。"""
        try:
            content = await self._invoke_json(system, user_message)
            data = self._parse_json(content)
            return Scene(**data)
        except Exception:
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
            return await self._invoke_chat(system, user_message)
        except Exception:
            return (
                "你好！我是 BizSage 运营诊断助手。\n\n"
                "⚠️ 抱歉，当前 AI 服务暂时不可用，无法生成动态回复。请稍后重试，或联系管理员检查模型服务状态。"
            )

    # ─── Chat Extract (NEW: facts + completeness in one call) ────────────

    async def chat_extract(
        self,
        messages: List[Dict[str, str]],
        existing_facts: List[str],
        scene: Dict[str, str],
    ) -> tuple[List[str], CompletenessEval]:
        industry = scene.get("industry", "未知行业")
        existing_text = "\n".join(f"- {f}" for f in existing_facts) if existing_facts else "（无）"
        history_text = json.dumps(messages, ensure_ascii=False)

        system = f"""你是一位熟悉{industry}行业的运营顾问，正在和一个{industry}行业的经营者对话。

已记录的事实：
{existing_text}

你的任务：
1. 从最新对话中提取所有与经营相关的新信息，用一句话概括每条事实。保留用户的语气和模糊度——数值可以是"约""大概""左右"，定性描述也要记录（如"最近下雨天人流少""感觉回头客变多了"）。
2. 基于{industry}行业的经营特征，综合评估目前收集到的信息完备度（0-100分）——思考：要做一份有参考价值的经营诊断，还需要哪些方面的信息。
3. completeness.summary：用一句话概括目前已有信息，例如"目前掌握了客流和成本两方面情况，但营收和顾客反馈方面还是空白"
4. completeness.missing_aspects：列出为了做好诊断还缺什么（3-5个方面，用行业口语描述）
5. completeness.next_question：生成一条友好的追问，用{industry}从业者习惯的口语自然引导用户继续补充

输出纯JSON（不要markdown包裹）：
{{"new_facts": ["事实1", "事实2"], "completeness": {{"score": 50, "summary": "...", "missing_aspects": ["..."], "next_question": "..."}}}}

禁止：编造未提及的数据、使用"指标""流量""转化率"等通用术语、堆砌数字"""

        try:
            content = await self._invoke_json(system, f"对话历史：{history_text}")
            data = self._parse_json(content)
            new_facts = data.get("new_facts", [])
            comp_data = data.get("completeness", {})
            completeness = CompletenessEval(
                score=comp_data.get("score", 0),
                summary=comp_data.get("summary", ""),
                missing_aspects=comp_data.get("missing_aspects", []),
                next_question=comp_data.get("next_question", ""),
            )
            return (new_facts, completeness)
        except Exception:
            return ([], CompletenessEval())

    # ─── Agent Reply (NEW: conversational guide) ────────────────────────

    async def agent_reply(
        self,
        raw_facts: List[str],
        completeness: CompletenessEval,
        scene: Dict[str, str],
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

请像懂行的朋友一样简短回复（80字以内），语气自然不机械。内容包含：
1. 对用户刚说的内容表达共情/确认（1句）
2. 自然引导到下一个话题，方向参考"还缺什么"，但不要直接说"我还需要XX数据"，应该像朋友聊天一样引导
3. 如果完备度 >= 80%，在回复末尾加上这一行提示：**[信息已比较充分，点击按钮即可生成诊断报告]**

直接输出对话文本，不要JSON，不要markdown代码块。"""

        try:
            return await self._invoke_chat(system, "请生成回复")
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
            return await self._invoke_chat(system, "请基于以上事实做运营诊断分析")
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
                "请生成完整的运营诊断报告"
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

    @staticmethod
    def _parse_json(content: str) -> dict:
        """Parse JSON from LLM response, stripping markdown fences if present."""
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return json.loads(text)


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
