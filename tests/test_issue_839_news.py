"""Tests for Issue #839 — News Tracking Skill.

Covers:
- Signal collector fix (news.latest instead of news.headlines)
- News tool risk metadata
- News force_tool_plan routing
- News + Calendar cross-analysis
- Proactive config enabled
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Signal Collector Fix ──────────────────────────────────────


class TestSignalCollectorNewsFix(unittest.TestCase):
    """Verify collect_news() calls the correct tool name."""

    def test_calls_news_latest_not_headlines(self):
        """Signal collector must call 'news.latest', not 'news.headlines'."""
        import inspect
        from bantz.proactive.signals import SignalCollector

        source = inspect.getsource(SignalCollector.collect_news)
        assert "news.latest" in source, "collect_news should call 'news.latest'"
        assert "news.headlines" not in source, "collect_news should NOT call 'news.headlines'"

    def test_reads_articles_key(self):
        """Signal collector must read 'articles' key from result, not 'headlines'."""
        import inspect
        from bantz.proactive.signals import SignalCollector

        source = inspect.getsource(SignalCollector.collect_news)
        assert '"articles"' in source or "'articles'" in source, (
            "collect_news should read 'articles' key from tool result"
        )

    def test_collect_news_success(self):
        """collect_news() should populate signal.headlines from articles."""
        from bantz.proactive.signals import SignalCollector

        fake_registry = MagicMock()
        collector = SignalCollector(tool_registry=fake_registry)

        fake_result = {
            "ok": True,
            "articles": [
                {"title": "AI Breakthrough", "source": "TechCrunch"},
                {"title": "Space Launch", "source": "NASA"},
            ],
        }

        with patch("bantz.proactive.signals._call_tool_sync", return_value=fake_result):
            signal = asyncio.get_event_loop().run_until_complete(
                collector.collect_news()
            )

        assert len(signal.headlines) == 2
        assert signal.headlines[0]["title"] == "AI Breakthrough"

    def test_collect_news_failure(self):
        """collect_news() should return empty headlines on failure."""
        from bantz.proactive.signals import SignalCollector

        fake_registry = MagicMock()
        collector = SignalCollector(tool_registry=fake_registry)

        fake_result = {"ok": False, "error": "Tool not found"}

        with patch("bantz.proactive.signals._call_tool_sync", return_value=fake_result):
            signal = asyncio.get_event_loop().run_until_complete(
                collector.collect_news()
            )

        assert signal.headlines == []


# ── Risk Metadata ────────────────────────────────────────────


class TestNewsRiskMetadata(unittest.TestCase):
    """News tools should be classified as SAFE."""

    def test_news_tools_in_policy(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk

        assert get_tool_risk("news.latest") == ToolRisk.SAFE
        assert get_tool_risk("news.search") == ToolRisk.SAFE
        assert get_tool_risk("news.briefing") == ToolRisk.SAFE
        assert get_tool_risk("news.category") == ToolRisk.SAFE


# ── Force Tool Plan ──────────────────────────────────────────


class TestNewsForceToolPlan(unittest.TestCase):
    """force_tool_plan should handle news route."""

    def _make_output(self, news_intent: str = "none"):
        from bantz.brain.llm_router import OrchestratorOutput

        return OrchestratorOutput(
            route="news",
            calendar_intent="none",
            slots={},
            confidence=0.9,
            tool_plan=[],
            assistant_reply="",
            news_intent=news_intent,
        )

    def test_news_latest_default(self):
        from bantz.brain.tool_plan_sanitizer import force_tool_plan

        out = self._make_output("none")
        result = force_tool_plan(out, {}, {})
        assert "news.latest" in result.tool_plan

    def test_news_search(self):
        from bantz.brain.tool_plan_sanitizer import force_tool_plan

        out = self._make_output("search")
        result = force_tool_plan(out, {}, {})
        assert "news.search" in result.tool_plan

    def test_news_briefing(self):
        from bantz.brain.tool_plan_sanitizer import force_tool_plan

        out = self._make_output("briefing")
        result = force_tool_plan(out, {}, {})
        assert "news.briefing" in result.tool_plan


# ── Proactive Config ─────────────────────────────────────────


class TestProactiveNewsConfig(unittest.TestCase):
    """News should be enabled in proactive.yaml."""

    def test_news_enabled(self):
        import yaml
        from pathlib import Path

        config_path = Path(__file__).resolve().parents[1] / "config" / "proactive.yaml"
        if not config_path.exists():
            self.skipTest("proactive.yaml not found")

        with open(config_path) as f:
            config = yaml.safe_load(f)

        signals = config.get("signals", {})
        news_config = signals.get("news", {})
        assert news_config.get("enabled") is True, (
            "News signal should be enabled in proactive.yaml"
        )


# ── News + Calendar Cross Analysis ───────────────────────────


class TestNewsCalendarCross(unittest.TestCase):
    """Test news-calendar cross-analysis rule."""

    def test_overlap_generates_insight(self):
        from bantz.proactive.cross_analyzer import _rule_news_calendar_cross

        tool_results = {
            "calendar": {
                "events": [
                    {"title": "AI Strategy Meeting", "summary": "AI Strategy Meeting"},
                ],
            },
            "news": {
                "articles": [
                    {"title": "Major AI Strategy Shift at Google"},
                    {"title": "Climate Change Report"},
                ],
            },
        }

        insights, suggestions = _rule_news_calendar_cross(tool_results)
        assert len(insights) >= 1
        assert "strategy" in insights[0].message.lower()
        assert len(suggestions) >= 1

    def test_no_overlap_no_insight(self):
        from bantz.proactive.cross_analyzer import _rule_news_calendar_cross

        tool_results = {
            "calendar": {
                "events": [
                    {"title": "Lunch Break"},
                ],
            },
            "news": {
                "articles": [
                    {"title": "Quantum Computing Breakthrough"},
                ],
            },
        }

        insights, suggestions = _rule_news_calendar_cross(tool_results)
        assert len(insights) == 0

    def test_empty_news_no_crash(self):
        from bantz.proactive.cross_analyzer import _rule_news_calendar_cross

        tool_results = {
            "calendar": {"events": [{"title": "Meeting"}]},
            "news": {"articles": []},
        }

        insights, suggestions = _rule_news_calendar_cross(tool_results)
        assert insights == []
        assert suggestions == []

    def test_empty_calendar_no_crash(self):
        from bantz.proactive.cross_analyzer import _rule_news_calendar_cross

        tool_results = {
            "calendar": {"events": []},
            "news": {"articles": [{"title": "Breaking News"}]},
        }

        insights, suggestions = _rule_news_calendar_cross(tool_results)
        assert insights == []


# ── Router Integration ───────────────────────────────────────


class TestNewsRouterIntegration(unittest.TestCase):
    """Verify news route is properly wired in the LLM router."""

    def test_news_in_valid_routes(self):
        from bantz.brain.llm_router import VALID_ROUTES
        assert "news" in VALID_ROUTES

    def test_news_intents(self):
        from bantz.brain.llm_router import VALID_NEWS_INTENTS
        assert "briefing" in VALID_NEWS_INTENTS
        assert "search" in VALID_NEWS_INTENTS
        assert "none" in VALID_NEWS_INTENTS

    def test_news_tools_in_valid_tools(self):
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        valid_tools = JarvisLLMOrchestrator._VALID_TOOLS
        assert "news.latest" in valid_tools
        assert "news.search" in valid_tools
        assert "news.briefing" in valid_tools
        assert "news.category" in valid_tools

    def test_orchestrator_output_news_intent(self):
        from bantz.brain.llm_router import OrchestratorOutput

        out = OrchestratorOutput(
            route="news", calendar_intent="none", slots={},
            confidence=0.9, tool_plan=[], assistant_reply="",
            news_intent="briefing",
        )
        assert out.intent == "briefing"


if __name__ == "__main__":
    unittest.main()
