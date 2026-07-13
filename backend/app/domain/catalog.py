"""Industry metric catalogs and completeness scoring logic.

All definitions follow the design document:
- Core metrics: 10 universal indicators (60 points)
- Secondary metrics: industry-specific (20 points, ≥70% coverage)
- Anomaly resolution: +20 points
- Threshold: ≥80 to trigger diagnosis
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


# =============================================================================
# Metric Definitions
# =============================================================================

@dataclass
class MetricDefinition:
    code: str
    label: str
    category: str           # traffic | conversion | user | content_product | revenue_cost | retention
    description: str
    unit: str = ""
    is_core: bool = False


# --- Core metrics (10 universal indicators) ---
CORE_METRICS: List[MetricDefinition] = [
    MetricDefinition("traffic", "流量", "traffic", "周期内总流量/访问量", "次", is_core=True),
    MetricDefinition("exposure", "曝光", "traffic", "内容/商品曝光量", "次", is_core=True),
    MetricDefinition("visitors", "访客", "traffic", "独立访客数", "人", is_core=True),
    MetricDefinition("conversion_rate", "转化率", "conversion", "访客到成交的转化率", "%", is_core=True),
    MetricDefinition("avg_order_value", "客单价", "conversion", "平均每单金额", "元", is_core=True),
    MetricDefinition("revenue", "营收", "revenue_cost", "周期总营收", "元", is_core=True),
    MetricDefinition("cost", "成本", "revenue_cost", "周期总成本（含投放、人力、货品等）", "元", is_core=True),
    MetricDefinition("new_users", "新增用户", "user", "周期内新增用户/粉丝数", "人", is_core=True),
    MetricDefinition("churn_rate", "流失率", "retention", "用户流失比例", "%", is_core=True),
    MetricDefinition("repurchase_rate", "复购率", "retention", "老用户重复购买/消费比例", "%", is_core=True),
]

CORE_METRIC_CODES: set = {m.code for m in CORE_METRICS}


# --- Industry-specific secondary metrics ---

INDUSTRY_SECONDARY_METRICS: Dict[str, List[MetricDefinition]] = {
    "电商": [
        MetricDefinition("refund_rate", "退款率", "conversion", "退款/退货订单占比", "%"),
        MetricDefinition("ad_roi", "广告ROI", "revenue_cost", "广告投放回报率"),
        MetricDefinition("inventory_turnover", "库存周转率", "content_product", "库存周转速度", "次/月"),
        MetricDefinition("customer_acquisition_cost", "获客成本", "revenue_cost", "单客获取成本", "元"),
        MetricDefinition("gmv", "GMV", "revenue_cost", "总成交额", "元"),
    ],
    "本地生活": [
        MetricDefinition("store_visits", "门店访问", "traffic", "线下到店人数", "人"),
        MetricDefinition("order_volume", "订单量", "conversion", "总订单数", "单"),
        MetricDefinition("peak_hours", "高峰时段", "traffic", "客流/订单高峰时段"),
        MetricDefinition("service_rating", "服务评分", "user", "用户服务评价分数"),
        MetricDefinition("repeat_customer_rate", "回头客率", "retention", "重复消费客户占比", "%"),
    ],
    "新媒体内容": [
        MetricDefinition("views", "播放/阅读量", "traffic", "内容播放或阅读次数", "次"),
        MetricDefinition("likes", "点赞数", "user", "点赞/收藏总数", "次"),
        MetricDefinition("follower_growth", "粉丝增长", "user", "周期内粉丝净增长", "人"),
        MetricDefinition("engagement_rate", "互动率", "user", "互动（点赞+评论+分享）/曝光", "%"),
        MetricDefinition("publish_frequency", "发布频率", "content_product", "内容发布频次", "篇/周"),
    ],
    "ToB企业服务": [
        MetricDefinition("leads", "线索量", "traffic", "销售线索总数", "条"),
        MetricDefinition("qualified_leads", "有效线索", "conversion", "合格销售线索", "条"),
        MetricDefinition("sales_cycle", "成交周期", "conversion", "从线索到成交平均天数", "天"),
        MetricDefinition("customer_ltv", "客户LTV", "revenue_cost", "客户生命周期价值", "元"),
        MetricDefinition("churn_mrr", "流失MRR", "retention", "月度经常性收入流失", "元"),
    ],
    "线下零售": [
        MetricDefinition("foot_traffic", "客流量", "traffic", "进店人流量", "人"),
        MetricDefinition("conversion_rate_offline", "进店转化率", "conversion", "进店到购买转化", "%"),
        MetricDefinition("sku_count", "SKU数", "content_product", "在售商品SKU总数", "个"),
        MetricDefinition("inventory_days", "库存天数", "content_product", "库存可支撑销售天数", "天"),
        MetricDefinition("average_basket", "连带率", "conversion", "单次购买商品件数", "件"),
    ],
    "教育": [
        MetricDefinition("trial_signups", "试听报名", "conversion", "试听课报名人数", "人"),
        MetricDefinition("trial_to_paid", "试听转化率", "conversion", "试听到付费转化", "%"),
        MetricDefinition("course_completion", "完课率", "user", "课程完成比例", "%"),
        MetricDefinition("student_satisfaction", "学员满意度", "user", "学员评价均分"),
        MetricDefinition("renewal_rate", "续费率", "retention", "学期/课程续费比例", "%"),
    ],
}

# All recognized industry keys
INDUSTRIES: Dict[str, str] = {
    "电商": "电商行业（淘宝/京东/拼多多/抖音电商/独立站等）",
    "本地生活": "本地生活服务（餐饮/美容/健身/家政等到店或上门服务）",
    "新媒体内容": "新媒体内容（小红书/抖音/公众号/B站/播客等）",
    "ToB企业服务": "ToB企业服务（SaaS/咨询/代理/软件外包等）",
    "线下零售": "线下零售（商超/便利店/专柜/门店等）",
    "教育": "教育行业（在线教育/培训机构/知识付费等）",
}


def get_secondary_metrics(industry: str) -> List[MetricDefinition]:
    """Return industry-specific secondary metrics. Falls back to empty list for unknown industries."""
    return INDUSTRY_SECONDARY_METRICS.get(industry, [])


def get_all_metric_codes(industry: str) -> List[str]:
    """Return all expected metric codes (core + industry secondary) for a given industry."""
    core_codes = [m.code for m in CORE_METRICS]
    secondary = get_secondary_metrics(industry)
    return core_codes + [m.code for m in secondary]


# =============================================================================
# Completeness Scoring (Pure Python — no LLM)
# =============================================================================

@dataclass
class ScoreResult:
    """Result of completeness scoring."""
    score: int                                          # 0-100
    core_complete: bool                                 # All 10 core metrics present
    core_provided_count: int                            # How many core metrics provided
    secondary_coverage: float                           # 0.0 - 1.0
    anomaly_complete: bool                              # Whether anomaly info is resolved
    missing_core: List[str] = field(default_factory=list)
    missing_secondary: List[str] = field(default_factory=list)
    unresolved_anomalies: List[str] = field(default_factory=list)
    can_limited_diagnose: bool = False                  # Enough data for limited diagnosis
    passed: bool = False                                # score >= threshold


def calculate_score(
    provided_metric_codes: List[str],
    industry: str,
    unresolved_anomaly_codes: Optional[List[str]] = None,
    threshold: int = 80,
) -> ScoreResult:
    """Calculate completeness score per design-doc rules.

    Rules (max 100):
      - Core metrics all present → +60
      - Secondary metrics coverage ≥ 70% → +20
      - All anomalies resolved (none outstanding) → +20

    Args:
        provided_metric_codes: Codes of metrics the user has provided.
        industry: Industry key (e.g., "电商", "新媒体内容").
        unresolved_anomaly_codes: Anomaly codes that still need clarification.
        threshold: Score threshold to pass (default 80).
    """
    unresolved = unresolved_anomaly_codes or []
    score = 0

    # 1. Core metrics (60 points)
    core_codes = [m.code for m in CORE_METRICS]
    missing_core = [c for c in core_codes if c not in provided_metric_codes]
    core_provided = len(core_codes) - len(missing_core)
    if len(missing_core) == 0:
        score += 60

    # 2. Secondary metrics (20 points, ≥70% coverage)
    secondary = get_secondary_metrics(industry)
    secondary_codes = [m.code for m in secondary]
    if len(secondary_codes) == 0:
        # No secondary metrics defined for this industry → full marks
        score += 20
        secondary_coverage = 1.0
        missing_secondary = []
    else:
        provided_secondary = [c for c in secondary_codes if c in provided_metric_codes]
        missing_secondary = [c for c in secondary_codes if c not in provided_metric_codes]
        secondary_coverage = len(provided_secondary) / len(secondary_codes)
        if secondary_coverage >= 0.7:
            score += 20

    # 3. Anomaly resolution (20 points)
    anomaly_complete = len(unresolved) == 0
    # Also award points if there are no core metric gaps (simple heuristic from reference)
    if len(missing_core) == 0 and anomaly_complete:
        score += 20
    elif anomaly_complete and len(missing_core) <= 2:
        # Partial anomaly credit when core is almost complete
        score += 10

    # Can do limited diagnosis if at least 5 core metrics are present
    can_limited = core_provided >= 5

    return ScoreResult(
        score=score,
        core_complete=len(missing_core) == 0,
        core_provided_count=core_provided,
        secondary_coverage=round(secondary_coverage, 2),
        anomaly_complete=anomaly_complete,
        missing_core=missing_core,
        missing_secondary=missing_secondary,
        unresolved_anomalies=unresolved,
        can_limited_diagnose=can_limited,
        passed=score >= threshold,
    )
