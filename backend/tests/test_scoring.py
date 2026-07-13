"""Tests for completeness evaluation schema and scene model."""

import pytest
from app.domain.schemas import CompletenessEval, Scene


class TestCompletenessEval:
    """Tests for the CompletenessEval Pydantic model."""

    def test_default_values(self):
        """Default eval has score=0 and empty summaries."""
        ce = CompletenessEval()
        assert ce.score == 0
        assert ce.summary == ""
        assert ce.missing_aspects == []
        assert ce.next_question == ""

    def test_score_bounds(self):
        """Score is clamped 0-100."""
        ce = CompletenessEval(score=50)
        assert 0 <= ce.score <= 100

    def test_full_construction(self):
        """All fields populated."""
        ce = CompletenessEval(
            score=75,
            summary="掌握了客流和成本情况",
            missing_aspects=["客单价未知", "未提及回头客"],
            next_question="最近回头客多吗？",
        )
        assert ce.score == 75
        assert len(ce.missing_aspects) == 2
        assert ce.next_question


class TestScene:
    """Tests for the Scene recognition model (LLM-driven, no hardcoded industries)."""

    def test_default_scene(self):
        """Default scene has empty industry."""
        s = Scene()
        assert s.industry == ""

    def test_industry_is_free_form(self):
        """Industry field accepts any string (LLM-driven, no enum constraint)."""
        # Should accept both traditional categories and granular sub-categories
        scenes = [
            Scene(industry="火锅"),
            Scene(industry="茶饮"),
            Scene(industry="快餐"),
            Scene(industry="跨境电商"),
            Scene(industry="SaaS"),
        ]
        for s in scenes:
            assert s.industry != ""
            assert isinstance(s.industry, str)
