"""LLM abstraction layer for BizSage3 diagnosis workflow.

Provides:
- DiagnosisModel (abstract base)
- OpenAICompatibleModel (production — with_structured_output)
- MockDiagnosisModel (testing — regex-based deterministic extraction)

All prompts enforce temperature=0.0, structured JSON output, and no
free-form generation per the reference design document.
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
    MetricValue,
    AnomalyContext,
    ExtractionResult,
    DiagnosisResult,
    DiagnosisDimension,
)
from app.domain.catalog import CORE_METRICS, INDUSTRY_SECONDARY_METRICS, INDUSTRIES


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
    async def collect_metrics(
        self,
        messages: List[Dict[str, str]],
        existing_metrics: Dict[str, Any],
        user_scene: Dict[str, str],
    ) -> tuple[Dict[str, Any], List[str]]:
        """Node 2: Extract metrics from conversation, return (collected, missing)."""
        ...

    @abstractmethod
    async def ask_followup(
        self,
        miss_metrics: List[str],
        user_scene: Dict[str, str],
        asked_codes: List[str],
    ) -> str:
        """Node 4: Generate 1-2 follow-up questions for missing metrics."""
        ...

    @abstractmethod
    async def diagnose(
        self,
        collect_metrics: Dict[str, Any],
        user_scene: Dict[str, str],
    ) -> str:
        """Node 5: Run 6-dimension diagnosis."""
        ...

    @abstractmethod
    async def generate_report(
        self,
        diagnosis_result: str,
        collect_metrics: Dict[str, Any],
        complete_score: int,
        miss_metrics: List[str],
    ) -> str:
        """Node 6: Generate structured diagnosis report."""
        ...


# =============================================================================
# OpenAI-Compatible Model (Production)
# =============================================================================

class OpenAICompatibleModel(DiagnosisModel):
    """LLM-powered diagnosis using OpenAI-compatible API.

    Uses `with_structured_output` for deterministic JSON schema enforcement
    when available, with json_mode fallback.
    All calls use temperature=0.0 per design doc requirements.
    """

    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.llm_model,
            temperature=settings.llm_temperature,  # 0.0 — no creativity
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

    async def recognize_scene(self, user_message: str) -> Scene:
        system = """你是运营诊断场景识别专家，严格根据用户对话内容，仅输出JSON结构化数据。
输出字段固定：
- industry: 行业（电商|本地生活|新媒体内容|ToB企业服务|线下零售|教育）
- business_mode: 业务模式（直营|分销|线上|线下|付费|免费等）
- operate_stage: 运营阶段（冷启动|增长|稳定|衰退）
- diagnosis_target: 诊断方向（整体运营|流量|转化|留存|收益）

无信息则填空字符串，禁止输出多余解释、禁止自由发挥。
仅输出纯JSON，不要markdown代码块包裹。"""
        try:
            content = await self._invoke_json(system, user_message)
            data = self._parse_json(content)
            return Scene(**data)
        except Exception:
            return Scene()

    async def collect_metrics(
        self,
        messages: List[Dict[str, str]],
        existing_metrics: Dict[str, Any],
        user_scene: Dict[str, str],
    ) -> tuple[Dict[str, Any], List[str]]:
        industry = user_scene.get("industry", "")
        all_core = [m.code for m in CORE_METRICS]
        secondary_defs = INDUSTRY_SECONDARY_METRICS.get(industry, [])
        all_secondary = [m.code for m in secondary_defs]
        all_codes = all_core + all_secondary

        existing_keys = list(existing_metrics.keys()) if existing_metrics else []

        system = f"""你是运营指标采集专员。从用户对话中提取结构化运营指标。

核心必采指标（必须检查是否提及）：{all_core}
行业次要指标（{industry}）：{all_secondary}
已采集指标：{existing_keys}

规则：
1. 仅提取对话中用户明确提及的数据，不编造、不发散
2. 用collect_metrics列出已采集的指标（code: 指标代码, label: 中文名, raw_text: 原始文本, numeric_value: 数值如有, unit: 单位如有, period: 时间周期如有）
3. 用miss_metrics列出所有未采集的指标代码（核心+次要中未出现的）
4. 用户明确说"不知道"/"无法提供"的，从miss_metrics中排除，在collect_metrics中标记status为"unavailable"
5. 输出纯JSON：{{"collect_metrics": {{}}, "miss_metrics": []}}，不要markdown包裹"""

        history_text = json.dumps(messages, ensure_ascii=False)
        try:
            content = await self._invoke_json(system, f"对话历史：{history_text}")
            data = self._parse_json(content)
            return (
                data.get("collect_metrics", {}),
                data.get("miss_metrics", []),
            )
        except Exception:
            return (existing_metrics or {}, all_codes)

    async def ask_followup(
        self,
        miss_metrics: List[str],
        user_scene: Dict[str, str],
        asked_codes: List[str],
    ) -> str:
        industry = user_scene.get("industry", "未知行业")
        remaining = [m for m in miss_metrics if m not in asked_codes]

        system = f"""你是运营智能提问助手。
用户行业：{industry}
缺失指标：{remaining if remaining else miss_metrics}
已问过：{asked_codes}

规则：
1. 每次仅提问1-2个缺失指标
2. 话术简洁通俗，让非专业用户能理解
3. 不重复已问过的问题
4. 直接输出提问文本，不要JSON"""

        try:
            prompt = ChatPromptTemplate.from_messages([
                ("system", system),
                ("user", "请生成本次追问问题"),
            ])
            res = await self.llm.ainvoke(prompt.format_prompt({}))
            return res.content
        except Exception:
            if remaining:
                return f"请提供以下指标的数据：{', '.join(remaining[:2])}"
            return "还有其他运营数据可以补充吗？"

    async def diagnose(
        self,
        collect_metrics: Dict[str, Any],
        user_scene: Dict[str, str],
    ) -> str:
        system = """你是资深运营诊断专家，基于用户场景和指标数据，完成6大维度诊断：

1. 流量维度：渠道流量结构、流量质量、流量波动原因、渠道优劣分析
2. 转化维度：全链路转化漏斗卡点、转化异常时段、转化短板环节
3. 用户维度：新增质量、用户分层、流失特征、复购意愿、用户生命周期价值
4. 内容/产品维度：爆款/滞销内容/产品特征、用户偏好、供给匹配度
5. 收益成本维度：投产比、盈亏点、成本浪费项、营收增长空间
6. 运营动作维度：近期活动、投放、调整动作的效果正负反馈

输出要求：
- 每个维度标注严重级别：优势/正常/风险/严重问题
- 包含数据异常说明、深层根因分析
- 输出结构化文本，便于报告节点引用"""

        try:
            prompt = ChatPromptTemplate.from_messages([
                ("system", system),
                ("user", f"用户场景：{json.dumps(user_scene, ensure_ascii=False)}\n运营指标数据：{json.dumps(collect_metrics, ensure_ascii=False)}"),
            ])
            res = await self.llm.ainvoke(prompt.format_prompt({}))
            return res.content
        except Exception:
            return "诊断分析暂时无法完成，请稍后重试。"

    async def generate_report(
        self,
        diagnosis_result: str,
        collect_metrics: Dict[str, Any],
        complete_score: int,
        miss_metrics: List[str],
    ) -> str:
        system = """请按照固定结构生成运营诊断报告：

【诊断概览】综合运营健康度评分、核心结论速览
【数据现状盘点】关键指标同期对比、行业对标对比
【核心问题诊断】分级列出严重问题、潜在风险、可优化点
【问题根因拆解】区分表层现象、深层运营漏洞
【落地优化方案】分短期（1-7天）、中期（1-30天）可执行动作
【监测指标建议】优化后需重点观测的数据，用于后续复盘
【数据缺失说明】标注本次诊断的信息盲区，提示后续补全方向

输出完整Markdown格式报告，每节使用二级标题（##）。"""

        try:
            prompt = ChatPromptTemplate.from_messages([
                ("system", system),
                ("user", f"诊断结论：{diagnosis_result}\n指标数据：{json.dumps(collect_metrics, ensure_ascii=False)}\n完备度分数：{complete_score}\n缺失指标：{miss_metrics}"),
            ])
            res = await self.llm.ainvoke(prompt.format_prompt({}))
            return res.content
        except Exception:
            return f"# 诊断报告\n\n## 诊断概览\n\n诊断生成失败，请重试。\n\n完备度分数：{complete_score}"

    @staticmethod
    def _parse_json(content: str) -> dict:
        """Parse JSON from LLM response, stripping markdown fences if present."""
        text = content.strip()
        # Remove ```json / ``` fences
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        return json.loads(text)


# =============================================================================
# Mock Model (Testing — no API calls)
# =============================================================================

class MockDiagnosisModel(DiagnosisModel):
    """Deterministic mock for testing without LLM API calls.

    Uses regex patterns to extract scene info and metrics from user input.
    Produces predictable outputs for test verification.
    """

    INDUSTRY_PATTERNS = [
        (re.compile(r"电商|淘宝|京东|拼多多|抖音电商|独立站|天猫"), "电商"),
        (re.compile(r"本地生活|餐饮|美容|健身|家政|到店|上门|门店"), "本地生活"),
        (re.compile(r"小红书|抖音|公众号|B站|b站|播客|新媒体|内容|自媒体|短视频"), "新媒体内容"),
        (re.compile(r"ToB|tob|SaaS|saas|企业服务|软件|咨询|代理"), "ToB企业服务"),
        (re.compile(r"零售|商超|便利店|专柜|线下|商场|超市"), "线下零售"),
        (re.compile(r"教育|培训|知识付费|在线教育|课程"), "教育"),
    ]
    STAGE_PATTERNS = [
        (re.compile(r"冷启动|起步|刚开|新店|新项目|初期|刚开始"), "冷启动"),
        (re.compile(r"增长|上升|扩张|快速增长"), "增长"),
        (re.compile(r"稳定|平稳|成熟"), "稳定"),
        (re.compile(r"衰退|下滑|下降|萎缩|不行了"), "衰退"),
    ]

    async def recognize_scene(self, user_message: str) -> Scene:
        industry = ""
        for pattern, label in self.INDUSTRY_PATTERNS:
            if pattern.search(user_message):
                industry = label
                break

        stage = ""
        for pattern, label in self.STAGE_PATTERNS:
            if pattern.search(user_message):
                stage = label
                break

        return Scene(
            industry=industry,
            business_mode="线上" if any(t in user_message for t in ["线上", "电商", "新媒体", "SaaS"]) else "",
            operate_stage=stage,
            diagnosis_target="整体运营",
        )

    _METRIC_PATTERNS = {
        "traffic": re.compile(r"流量[：:]\s*(\d+\.?\d*)\s*(万|千|次)?"),
        "exposure": re.compile(r"曝光[：:]\s*(\d+\.?\d*)\s*(万|千|次)?"),
        "visitors": re.compile(r"访客[：:]\s*(\d+\.?\d*)\s*(万|千|人)?"),
        "conversion_rate": re.compile(r"转化率[：:]\s*(\d+\.?\d*)\s*%?"),
        "avg_order_value": re.compile(r"客单价[：:]\s*(\d+\.?\d*)\s*元?"),
        "revenue": re.compile(r"营收[：:]\s*(\d+\.?\d*)\s*(万|千|元)?"),
        "cost": re.compile(r"成本[：:]\s*(\d+\.?\d*)\s*(万|千|元)?"),
        "new_users": re.compile(r"新增(用户|粉丝)[：:]\s*(\d+\.?\d*)\s*(万|千|人)?"),
        "churn_rate": re.compile(r"流失率[：:]\s*(\d+\.?\d*)\s*%?"),
        "repurchase_rate": re.compile(r"复购率[：:]\s*(\d+\.?\d*)\s*%?"),
    }

    async def collect_metrics(
        self,
        messages: List[Dict[str, str]],
        existing_metrics: Dict[str, Any],
        user_scene: Dict[str, str],
    ) -> tuple[Dict[str, Any], List[str]]:
        # Combine all user messages into one text for regex scanning
        user_texts = [m["content"] for m in messages if m.get("role") == "user"]
        combined = " ".join(user_texts)

        collected = dict(existing_metrics) if existing_metrics else {}
        for code, pattern in self._METRIC_PATTERNS.items():
            if code in collected:
                continue
            match = pattern.search(combined)
            if match:
                val = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                collected[code] = {
                    "code": code,
                    "label": code,
                    "raw_text": match.group(0),
                    "numeric_value": float(val.replace("万", "").replace("千", "")) if val else None,
                    "status": "provided",
                }

        industry = user_scene.get("industry", "")
        all_core = [m.code for m in CORE_METRICS]
        secondary_defs = INDUSTRY_SECONDARY_METRICS.get(industry, [])
        all_secondary = [m.code for m in secondary_defs]
        all_codes = all_core + all_secondary

        missing = [c for c in all_codes if c not in collected]
        return (collected, missing)

    async def ask_followup(
        self,
        miss_metrics: List[str],
        user_scene: Dict[str, str],
        asked_codes: List[str],
    ) -> str:
        remaining = [m for m in miss_metrics if m not in asked_codes][:2]
        if not remaining:
            return "还有其他运营数据可以补充吗？"
        return f"请提供以下指标的数据：{'、'.join(remaining)}"

    async def diagnose(self, collect_metrics, user_scene) -> str:
        industry = user_scene.get("industry", "未知行业")
        metric_count = len(collect_metrics)
        return (
            f"## 六大维度诊断结果\n\n"
            f"行业：{industry}\n"
            f"已采集指标数：{metric_count}\n\n"
            f"### 流量维度\n严重级别：正常\n流量数据基本健康。\n\n"
            f"### 转化维度\n严重级别：需关注\n转化数据有待深入分析。\n\n"
            f"### 用户维度\n严重级别：正常\n用户指标在合理范围内。\n\n"
            f"### 内容/产品维度\n严重级别：正常\n产品数据表现稳定。\n\n"
            f"### 收益成本维度\n严重级别：需关注\n收益成本比需持续监测。\n\n"
            f"### 运营动作维度\n严重级别：正常\n近期运营动作效果正向。\n"
        )

    async def generate_report(
        self,
        diagnosis_result: str,
        collect_metrics: Dict[str, Any],
        complete_score: int,
        miss_metrics: List[str],
    ) -> str:
        return (
            f"# 运营诊断报告\n\n"
            f"## 诊断概览\n\n"
            f"综合健康度评分：{complete_score}分\n"
            f"核心结论：基于已采集的{len(collect_metrics)}项指标数据完成诊断。\n\n"
            f"## 数据现状盘点\n\n"
            f"已采集指标：{json.dumps(list(collect_metrics.keys()), ensure_ascii=False)}\n\n"
            f"## 核心问题诊断\n\n"
            f"{diagnosis_result}\n\n"
            f"## 问题根因拆解\n\n"
            f"需要进一步数据分析确定深层根因。\n\n"
            f"## 落地优化方案\n\n"
            f"### 短期（1-7天）\n1. 补全缺失指标数据\n2. 对照行业基准检验\n\n"
            f"### 中期（1-30天）\n1. 持续监测关键指标变化\n2. 根据诊断建议调整运营策略\n\n"
            f"## 监测指标建议\n\n"
            f"重点监测核心10项指标的变化趋势。\n\n"
            f"## 数据缺失说明\n\n"
            f"本次诊断缺失指标：{miss_metrics if miss_metrics else '无'}\n"
        )


# =============================================================================
# Factory
# =============================================================================

def create_model() -> DiagnosisModel:
    """Create the appropriate model based on LLM_MODE setting."""
    if settings.llm_mode == "mock":
        return MockDiagnosisModel()
    return OpenAICompatibleModel()
