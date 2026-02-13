"""E2E test framework — runner, mock LLM, report generation.

This module contains the E2ETestRunner framework, MockLLMProvider,
TurnResult, TaskReport, and E2EReport classes.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "TurnResult",
    "TaskReport",
    "E2EReport",
    "MockLLMProvider",
    "E2ETestRunner",
]


# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class TurnResult:
    """Result of a single conversational turn."""

    response: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0
    tier: str = ""
    error: Optional[str] = None

    @property
    def tool_names(self) -> List[str]:
        return [tc.get("tool", "") for tc in self.tool_calls]


@dataclass
class TaskReport:
    """Report for a single golden task."""

    name: str
    status: str = "pending"      # pass / fail / error
    latency_ms: float = 0.0
    tool_called: Optional[str] = None
    error: Optional[str] = None


@dataclass
class E2EReport:
    """Full E2E test report."""

    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    duration_ms: float = 0.0
    tasks: List[TaskReport] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, path: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))


# ── Mock LLM provider ────────────────────────────────────────────────

class MockLLMProvider:
    """Deterministic LLM mock that returns pre-defined responses."""

    def __init__(self, responses_path: Optional[str] = None) -> None:
        self._scenarios: Dict[str, Dict[str, Any]] = {}
        self._input_map: Dict[str, str] = {}

        if responses_path:
            self.load(responses_path)

    def load(self, path: str) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for name, scenario in data.items():
            self._scenarios[name] = scenario
            inp = scenario.get("input", "")
            if inp:
                self._input_map[inp.lower().strip()] = name

    def get_scenario(self, name: str) -> Optional[Dict[str, Any]]:
        return self._scenarios.get(name)

    def generate(self, user_input: str) -> TurnResult:
        key = user_input.lower().strip()
        scenario_name = self._input_map.get(key)

        if scenario_name is None:
            return TurnResult(
                response="Anlayamadım efendim.",
                error=f"No mock scenario for: {user_input}",
            )

        scenario = self._scenarios[scenario_name]
        return TurnResult(
            response=scenario.get("response", ""),
            tool_calls=scenario.get("tool_calls", []),
            tier=scenario.get("tier", ""),
        )


# ── E2E Test Runner ──────────────────────────────────────────────────

class E2ETestRunner:
    """End-to-end test runner with mock LLM mode."""

    def __init__(
        self,
        mock_responses_path: Optional[str] = None,
        report_path: str = "artifacts/results/e2e_report.json",
    ) -> None:
        self._mock = MockLLMProvider(mock_responses_path)
        self._report_path = report_path
        self._report = E2EReport()
        self._history: List[TurnResult] = []
        self._started = False
        self._start_time = 0.0

    def setup(self) -> None:
        self._started = True
        self._start_time = time.monotonic()
        self._history.clear()
        self._report = E2EReport()

    def teardown(self) -> None:
        elapsed = (time.monotonic() - self._start_time) * 1000
        self._report.duration_ms = elapsed
        self._report.save(self._report_path)
        self._started = False

    def send(self, text: str) -> TurnResult:
        if not self._started:
            raise RuntimeError("E2ETestRunner not started — call setup() first")

        t0 = time.monotonic()
        result = self._mock.generate(text)
        result.latency_ms = (time.monotonic() - t0) * 1000

        self._history.append(result)
        return result

    @property
    def last_result(self) -> Optional[TurnResult]:
        return self._history[-1] if self._history else None

    def assert_tool_called(self, tool_name: str, result: Optional[TurnResult] = None) -> None:
        r = result or self.last_result
        assert r is not None, "No result to check"
        names = r.tool_names
        assert tool_name in names, (
            f"Expected tool '{tool_name}' to be called, got: {names}"
        )

    def assert_no_tools_called(self, result: Optional[TurnResult] = None) -> None:
        r = result or self.last_result
        assert r is not None, "No result to check"
        assert len(r.tool_calls) == 0, (
            f"Expected no tool calls, got: {r.tool_names}"
        )

    def assert_response_contains(self, substring: str, result: Optional[TurnResult] = None) -> None:
        r = result or self.last_result
        assert r is not None, "No result to check"
        assert substring.lower() in r.response.lower(), (
            f"Expected '{substring}' in response: {r.response!r}"
        )

    def assert_response_language(self, lang: str, result: Optional[TurnResult] = None) -> None:
        r = result or self.last_result
        assert r is not None, "No result to check"

        if lang == "tr":
            turkish_chars = set("çğıöşüÇĞİÖŞÜ")
            has_turkish = any(c in turkish_chars for c in r.response)
            assert has_turkish, (
                f"Expected Turkish response, got: {r.response!r}"
            )

    def record_task(self, report: TaskReport) -> None:
        self._report.tasks.append(report)
        self._report.tests_run += 1
        if report.status == "pass":
            self._report.tests_passed += 1
        elif report.status == "fail":
            self._report.tests_failed += 1

    def get_report(self) -> E2EReport:
        return self._report
