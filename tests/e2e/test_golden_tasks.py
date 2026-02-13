"""E2E golden-task tests (Issue #463).

Three golden tasks verified against mock LLM responses:
1. Smalltalk — Turkish greeting with "efendim"
2. Calendar — create_event tool called
3. System info — system.info tool called, Turkish response

Plus meta-tests for the E2E framework itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure the e2e dir is importable
_e2e_dir = Path(__file__).resolve().parent
if str(_e2e_dir) not in sys.path:
    sys.path.insert(0, str(_e2e_dir))

from e2e_framework import (  # noqa: E402
    E2EReport,
    E2ETestRunner,
    MockLLMProvider,
    TaskReport,
    TurnResult,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
MOCK_RESPONSES_PATH = str(FIXTURES_DIR / "mock_llm_responses.json")


# ═══════════════════════════════════════════════════════════════════════
#  Golden Task Tests
# ═══════════════════════════════════════════════════════════════════════

class TestGoldenSmallTalk:
    """Golden task 1: Smalltalk — 'Nasılsın?' → Turkish + efendim."""

    def test_smalltalk_response(self, e2e_runner: E2ETestRunner):
        result = e2e_runner.send("Nasılsın?")
        e2e_runner.assert_response_contains("efendim", result)

    def test_smalltalk_turkish(self, e2e_runner: E2ETestRunner):
        result = e2e_runner.send("Nasılsın?")
        e2e_runner.assert_response_language("tr", result)

    def test_smalltalk_no_tools(self, e2e_runner: E2ETestRunner):
        result = e2e_runner.send("Nasılsın?")
        e2e_runner.assert_no_tools_called(result)


class TestGoldenCalendar:
    """Golden task 2: Calendar — create_event tool called."""

    def test_calendar_tool_called(self, e2e_runner: E2ETestRunner):
        result = e2e_runner.send("Yarın saat 3'te toplantı kur")
        e2e_runner.assert_tool_called("calendar.create_event", result)

    def test_calendar_response_turkish(self, e2e_runner: E2ETestRunner):
        result = e2e_runner.send("Yarın saat 3'te toplantı kur")
        e2e_runner.assert_response_language("tr", result)

    def test_calendar_response_contains_keyword(self, e2e_runner: E2ETestRunner):
        result = e2e_runner.send("Yarın saat 3'te toplantı kur")
        e2e_runner.assert_response_contains("toplantı", result)


class TestGoldenSystemInfo:
    """Golden task 3: System info — system.info tool called."""

    def test_sysinfo_tool_called(self, e2e_runner: E2ETestRunner):
        result = e2e_runner.send("Sistem durumu nedir?")
        e2e_runner.assert_tool_called("system.info", result)

    def test_sysinfo_response_turkish(self, e2e_runner: E2ETestRunner):
        result = e2e_runner.send("Sistem durumu nedir?")
        e2e_runner.assert_response_language("tr", result)

    def test_sysinfo_response_contains_status(self, e2e_runner: E2ETestRunner):
        result = e2e_runner.send("Sistem durumu nedir?")
        e2e_runner.assert_response_contains("sistem", result)


# ═══════════════════════════════════════════════════════════════════════
#  Meta-tests: E2E Framework
# ═══════════════════════════════════════════════════════════════════════

class TestMockLLMProvider:
    """Tests for MockLLMProvider itself."""

    def test_load_scenarios(self):
        provider = MockLLMProvider(MOCK_RESPONSES_PATH)
        assert provider.get_scenario("smalltalk") is not None
        assert provider.get_scenario("calendar_create") is not None
        assert provider.get_scenario("system_info") is not None

    def test_generate_known_input(self):
        provider = MockLLMProvider(MOCK_RESPONSES_PATH)
        result = provider.generate("Nasılsın?")
        assert "efendim" in result.response.lower()
        assert result.error is None

    def test_generate_unknown_input(self):
        provider = MockLLMProvider(MOCK_RESPONSES_PATH)
        result = provider.generate("Bu bilinmeyen bir komut")
        assert result.error is not None
        assert "No mock scenario" in result.error


class TestTurnResult:
    def test_tool_names_property(self):
        tr = TurnResult(
            tool_calls=[{"tool": "a"}, {"tool": "b"}]
        )
        assert tr.tool_names == ["a", "b"]

    def test_empty_tool_calls(self):
        tr = TurnResult(response="hello")
        assert tr.tool_names == []


class TestE2ERunnerAssertions:
    def test_assert_tool_called_passes(self, e2e_runner: E2ETestRunner):
        result = e2e_runner.send("Yarın saat 3'te toplantı kur")
        e2e_runner.assert_tool_called("calendar.create_event", result)

    def test_assert_tool_called_fails(self, e2e_runner: E2ETestRunner):
        result = e2e_runner.send("Nasılsın?")
        with pytest.raises(AssertionError, match="Expected tool"):
            e2e_runner.assert_tool_called("calendar.create_event", result)

    def test_assert_response_contains_fails(self, e2e_runner: E2ETestRunner):
        result = e2e_runner.send("Nasılsın?")
        with pytest.raises(AssertionError, match="Expected"):
            e2e_runner.assert_response_contains("impossible_string_xyz", result)

    def test_runner_not_started_raises(self):
        runner = E2ETestRunner()
        with pytest.raises(RuntimeError, match="not started"):
            runner.send("hello")


class TestE2EReport:
    def test_report_saved(self, e2e_runner: E2ETestRunner, tmp_path):
        e2e_runner.send("Nasılsın?")
        e2e_runner.record_task(TaskReport(
            name="smalltalk", status="pass", latency_ms=10.0,
        ))
        report = e2e_runner.get_report()
        assert report.tests_run == 1
        assert report.tests_passed == 1

    def test_report_json_structure(self, tmp_path):
        report = E2EReport(
            tests_run=3, tests_passed=2, tests_failed=1,
            duration_ms=5000.0,
            tasks=[
                TaskReport(name="smalltalk", status="pass", latency_ms=1000),
                TaskReport(name="calendar", status="pass", latency_ms=2000, tool_called="calendar.create_event"),
                TaskReport(name="sysinfo", status="fail", latency_ms=2000, error="timeout"),
            ],
        )
        path = str(tmp_path / "report.json")
        report.save(path)
        loaded = json.loads(Path(path).read_text())
        assert loaded["tests_run"] == 3
        assert loaded["tests_passed"] == 2
        assert loaded["tests_failed"] == 1
        assert len(loaded["tasks"]) == 3
        assert loaded["tasks"][0]["name"] == "smalltalk"

    def test_report_to_dict(self):
        report = E2EReport(tests_run=1, tests_passed=1)
        d = report.to_dict()
        assert isinstance(d, dict)
        assert d["tests_run"] == 1
