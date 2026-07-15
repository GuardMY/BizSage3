"""Test fixtures for backend tests."""

import re
from typing import Dict, List

import pytest

from app.domain.schemas import Scene, CompletenessEval, ConversationTurnOutput
from app.services.model_service import DiagnosisModel


# =============================================================================
# Test-only mock model (no API calls needed for deterministic tests)
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
            "⚠️ 当前为测试模式，未连接真实 AI 服务。"
        )

    async def conversation_turn(
        self,
        messages: List[Dict[str, str]],
        existing_facts: List[str],
        scene: Dict[str, str],
    ) -> ConversationTurnOutput:
        """Merged chat_extract + agent_reply for deterministic testing."""
        user_msgs = [m for m in messages if m.get("role") == "user"]
        latest = user_msgs[-1]["content"] if user_msgs else ""

        new_facts = []
        if latest and len(latest) > 3:
            new_facts.append(latest[:100])

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

        # Build conversational reply (same logic as old agent_reply)
        next_q = completeness.next_question or "还有其他方面可以聊聊吗？"
        all_facts = existing_facts + new_facts
        reply = f"了解了{'，'.join(all_facts[-2:]) if all_facts else ''}。"
        if completeness.score >= 80:
            reply += "\n\n**[信息已比较充分，点击按钮即可生成诊断报告]**"
        else:
            reply += f"{next_q}"

        # Generate quick-reply suggestions
        suggested = [next_q[:15]] if next_q else []

        return ConversationTurnOutput(
            new_facts=new_facts,
            completeness=completeness,
            reply=reply,
            suggested_replies=suggested,
        )

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
        messages: List[Dict[str, str]] = None,
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
            + ("\n".join(f"- {a}" for a in completeness.missing_aspects) if completeness.missing_aspects else "暂无")
            + f"\n\n## 下一步建议\n\n继续补充运营信息后重新生成以获得更全面的诊断报告。\n"
        )


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_model():
    """Return a MockDiagnosisModel for deterministic testing."""
    return MockDiagnosisModel()


@pytest.fixture(autouse=True)
def use_mock_model(monkeypatch):
    """Force mock model for all tests by default."""
    monkeypatch.setattr("app.services.workflow.create_model", lambda: MockDiagnosisModel())
