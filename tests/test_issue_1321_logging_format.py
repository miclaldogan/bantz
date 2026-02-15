"""Tests for Issue #1321: f-string → lazy % logging conversion.

Verifies that all logger calls in llm_router.py and orchestrator_loop.py
use lazy %-formatting instead of eager f-string interpolation.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Root of the project
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _find_fstring_logger_calls(filepath: Path) -> list[tuple[int, str]]:
    """Return (line, code) for any logger call using an f-string argument."""
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))
    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match logger.warning(...), logger.info(...), etc.
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "logger"
            and func.attr in ("debug", "info", "warning", "error", "exception", "critical")
        ):
            continue
        # Check if the first positional arg is a JoinedStr (f-string)
        if node.args and isinstance(node.args[0], ast.JoinedStr):
            line = node.lineno
            snippet = ast.get_source_segment(source, node) or "<unknown>"
            violations.append((line, snippet[:120]))

    return violations


class TestNoFStringLoggerCalls:
    """Ensure no f-string interpolation in logger calls for target files."""

    def test_llm_router_no_fstring_loggers(self):
        filepath = _PROJECT_ROOT / "src" / "bantz" / "brain" / "llm_router.py"
        violations = _find_fstring_logger_calls(filepath)
        assert violations == [], (
            "Found f-string logger calls in llm_router.py:\n"
            + "\n".join(f"  L{line}: {code}" for line, code in violations)
        )

    def test_orchestrator_loop_no_fstring_loggers(self):
        filepath = _PROJECT_ROOT / "src" / "bantz" / "brain" / "orchestrator_loop.py"
        violations = _find_fstring_logger_calls(filepath)
        assert violations == [], (
            "Found f-string logger calls in orchestrator_loop.py:\n"
            + "\n".join(f"  L{line}: {code}" for line, code in violations)
        )


class TestLazyFormatStringsPresent:
    """Spot-check that key log messages now use %-formatting."""

    def test_router_health_check_lazy(self):
        source = (_PROJECT_ROOT / "src" / "bantz" / "brain" / "llm_router.py").read_text()
        assert 'logger.warning("[router_health] Health check failed: %s", e)' in source

    def test_router_json_parse_lazy(self):
        source = (_PROJECT_ROOT / "src" / "bantz" / "brain" / "llm_router.py").read_text()
        assert 'logger.warning("Router JSON parse failed: %s", e)' in source

    def test_orchestrator_fallback_lazy(self):
        source = (_PROJECT_ROOT / "src" / "bantz" / "brain" / "llm_router.py").read_text()
        assert 'logger.warning("Orchestrator fallback triggered: %s", error)' in source

    def test_safety_violation_lazy(self):
        source = (_PROJECT_ROOT / "src" / "bantz" / "brain" / "orchestrator_loop.py").read_text()
        assert '"[SAFETY] Tool plan violation: %s", violation.reason' in source

    def test_tool_denied_lazy(self):
        source = (_PROJECT_ROOT / "src" / "bantz" / "brain" / "orchestrator_loop.py").read_text()
        assert "\"[SAFETY] Tool '%s' denied: %s\", tool_name, deny_reason" in source

    def test_firewall_confirmation_lazy(self):
        source = (_PROJECT_ROOT / "src" / "bantz" / "brain" / "orchestrator_loop.py").read_text()
        assert '"[FIREWALL] Tool %s (%s) requires confirmation.", tool_name, risk.value' in source
