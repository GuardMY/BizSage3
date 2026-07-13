"""Tests for completeness scoring logic."""

import pytest
from app.domain.catalog import calculate_score, ScoreResult, CORE_METRIC_CODES


def _core_codes() -> list:
    return [m.code for m in [
        __import__("app.domain.catalog", fromlist=["CORE_METRICS"]).CORE_METRICS
    ]]


class TestScoringCore:
    """Tests for the core metric portion (60 points)."""

    def test_all_core_provided_gives_60(self):
        """When all 10 core metrics are provided, score starts at 60 + 20 (anomaly)."""
        core = ["traffic", "exposure", "visitors", "conversion_rate", "avg_order_value",
                "revenue", "cost", "new_users", "churn_rate", "repurchase_rate"]
        result = calculate_score(core, "电商")
        assert result.core_complete is True
        assert result.core_provided_count == 10
        assert 60 <= result.score

    def test_missing_one_core_0_score_core(self):
        """Missing one core metric: core_complete=False, score < 60."""
        core = ["traffic", "exposure", "visitors", "conversion_rate", "avg_order_value",
                "revenue", "cost", "new_users", "churn_rate"]  # missing repurchase_rate
        result = calculate_score(core, "电商")
        assert result.core_complete is False
        assert len(result.missing_core) == 1
        assert "repurchase_rate" in result.missing_core
        assert result.score < 60

    def test_no_core_provided(self):
        """No metrics at all: core_complete=False, low score."""
        result = calculate_score([], "电商")
        assert result.core_provided_count == 0
        assert result.core_complete is False
        assert len(result.missing_core) == 10
        assert result.score < 80


class TestScoringSecondary:
    """Tests for secondary metric coverage (20 points)."""

    def test_all_secondary_covered_gives_20(self):
        """When all industry-specific secondary metrics are covered, gain +20."""
        core = ["traffic", "exposure", "visitors", "conversion_rate", "avg_order_value",
                "revenue", "cost", "new_users", "churn_rate", "repurchase_rate"]
        secondary = ["refund_rate", "ad_roi", "inventory_turnover", "customer_acquisition_cost", "gmv"]
        result = calculate_score(core + secondary, "电商")
        assert result.secondary_coverage == 1.0
        assert result.score >= 80

    def test_70_percent_coverage_gives_20(self):
        """Exactly 70% coverage still passes. 3.5/5 or better."""
        core = ["traffic", "exposure", "visitors", "conversion_rate", "avg_order_value",
                "revenue", "cost", "new_users", "churn_rate", "repurchase_rate"]
        # 电商 has 5 secondary metrics. 4/5 = 80% ≥ 70%
        secondary = ["refund_rate", "ad_roi", "inventory_turnover", "customer_acquisition_cost"]
        result = calculate_score(core + secondary, "电商")
        assert result.secondary_coverage >= 0.7
        assert result.score >= 80

    def test_below_70_percent_no_secondary_points(self):
        """Coverage below 70% yields 0 from secondary category.
        However, with all core (+60) and no anomalies (+20), base = 80 which passes."""
        core = ["traffic", "exposure", "visitors", "conversion_rate", "avg_order_value",
                "revenue", "cost", "new_users", "churn_rate", "repurchase_rate"]
        # 1/5 = 20% < 70%
        result = calculate_score(core + ["refund_rate"], "电商")
        assert result.secondary_coverage < 0.7
        # Score = 60 (core) + 0 (secondary<70%) + 20 (no anomalies) = 80
        assert result.score == 80
        assert result.passed is True  # threshold is exactly 80

    def test_unknown_industry_full_secondary_marks(self):
        """Unknown industry has no secondary metrics → full 20 marks automatically."""
        core = ["traffic", "exposure", "visitors", "conversion_rate", "avg_order_value",
                "revenue", "cost", "new_users", "churn_rate", "repurchase_rate"]
        result = calculate_score(core, "未知行业")
        assert result.secondary_coverage == 1.0
        assert result.score >= 80


class TestScoringAnomaly:
    """Tests for anomaly resolution (20 points)."""

    def test_no_anomalies_full_marks(self):
        """No unresolved anomalies: full anomaly points."""
        core = ["traffic", "exposure", "visitors", "conversion_rate", "avg_order_value",
                "revenue", "cost", "new_users", "churn_rate", "repurchase_rate"]
        result = calculate_score(core, "电商", unresolved_anomaly_codes=[])
        assert result.anomaly_complete is True
        assert result.score >= 80

    def test_unresolved_anomalies_reduce_score(self):
        """Unresolved anomalies reduce the anomaly score."""
        core = ["traffic", "exposure", "visitors", "conversion_rate", "avg_order_value",
                "revenue", "cost", "new_users", "churn_rate", "repurchase_rate"]
        result = calculate_score(core, "电商", unresolved_anomaly_codes=["anomaly_1"])
        assert result.anomaly_complete is False


class TestScoreResult:
    """Tests for ScoreResult fields."""

    def test_passed_when_above_threshold(self):
        core = ["traffic", "exposure", "visitors", "conversion_rate", "avg_order_value",
                "revenue", "cost", "new_users", "churn_rate", "repurchase_rate"]
        secondary = ["refund_rate", "ad_roi", "inventory_turnover", "customer_acquisition_cost", "gmv"]
        result = calculate_score(core + secondary, "电商")
        assert result.passed is True

    def test_not_passed_when_below_threshold(self):
        result = calculate_score(["traffic", "exposure"], "电商")
        assert result.passed is False

    def test_can_limited_diagnose_with_5_core(self):
        """With at least 5 core metrics, limited diagnosis is possible."""
        result = calculate_score(
            ["traffic", "exposure", "visitors", "conversion_rate", "avg_order_value"],
            "电商"
        )
        assert result.can_limited_diagnose is True

    def test_cannot_limited_diagnose_with_4_core(self):
        """With fewer than 5 core metrics, limited diagnosis is NOT possible."""
        result = calculate_score(
            ["traffic", "exposure", "visitors", "conversion_rate"],
            "电商"
        )
        assert result.can_limited_diagnose is False


class TestAllIndustries:
    """Smoke tests across all supported industries."""

    @pytest.mark.parametrize("industry", ["电商", "本地生活", "新媒体内容", "ToB企业服务", "线下零售", "教育"])
    def test_industry_recognition(self, industry):
        """Each industry should produce valid ScoreResult without errors."""
        core = ["traffic", "exposure", "visitors", "conversion_rate", "avg_order_value",
                "revenue", "cost", "new_users", "churn_rate", "repurchase_rate"]
        result = calculate_score(core, industry)
        assert isinstance(result, ScoreResult)
        assert 0 <= result.score <= 100
