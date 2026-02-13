"""Tests for issue #459 — Tool registry startup validation."""

from __future__ import annotations

import pytest

from bantz.agent.tool_validator import (
    ToolValidationReport,
    ToolValidator,
    ValidatedTool,
    ValidationResult,
)


# ── helpers ───────────────────────────────────────────────────────────

def _make_tool(name: str, **kw) -> ValidatedTool:
    return ValidatedTool(name=name, description=f"Tool {name}", **kw)


# ── All valid ─────────────────────────────────────────────────────────

class TestAllValid:
    def test_all_enabled(self):
        v = ToolValidator()
        v.register(_make_tool("a"))
        v.register(_make_tool("b"))
        report = v.validate_all()
        assert report.total == 2
        assert report.enabled_count == 2
        assert report.disabled == []

    def test_summary_format(self):
        v = ToolValidator()
        v.register(_make_tool("x"))
        report = v.validate_all()
        assert "[TOOLS] 1/1 tools ready" in report.summary


# ── Missing secret ────────────────────────────────────────────────────

class TestMissingSecret:
    def test_missing_secret_disables(self):
        v = ToolValidator(secret_checker=lambda s: s != "GOOGLE_API_KEY")
        v.register(_make_tool("gmail", required_secrets=["GOOGLE_API_KEY"]))
        report = v.validate_all()
        assert report.enabled_count == 0
        assert "missing secret" in report.disabled[0][1]

    def test_available_secret_ok(self):
        v = ToolValidator(secret_checker=lambda s: True)
        v.register(_make_tool("gmail", required_secrets=["KEY"]))
        report = v.validate_all()
        assert report.enabled_count == 1


# ── Missing package ───────────────────────────────────────────────────

class TestMissingPackage:
    def test_missing_package_disables(self):
        v = ToolValidator(package_checker=lambda p: p != "serpapi")
        v.register(_make_tool("search", required_packages=["serpapi"]))
        report = v.validate_all()
        assert report.enabled_count == 0
        assert "missing package" in report.disabled[0][1]

    def test_available_package_ok(self):
        v = ToolValidator(package_checker=lambda p: True)
        v.register(_make_tool("search", required_packages=["json"]))
        report = v.validate_all()
        assert report.enabled_count == 1

    def test_default_package_checker_real(self):
        """json is always available."""
        v = ToolValidator()
        v.register(_make_tool("t", required_packages=["json"]))
        report = v.validate_all()
        assert report.enabled_count == 1

    def test_default_package_checker_missing(self):
        v = ToolValidator()
        v.register(_make_tool("t", required_packages=["__nonexistent_pkg_xyz__"]))
        report = v.validate_all()
        assert report.enabled_count == 0


# ── Health check ──────────────────────────────────────────────────────

class TestHealthCheck:
    def test_health_check_pass(self):
        v = ToolValidator()
        v.register(_make_tool("ok", health_check=lambda: True))
        report = v.validate_all()
        assert report.enabled_count == 1

    def test_health_check_fail(self):
        v = ToolValidator()
        v.register(_make_tool("bad", health_check=lambda: False))
        report = v.validate_all()
        assert report.enabled_count == 0
        assert "health check returned False" in report.disabled[0][1]

    def test_health_check_exception(self):
        v = ToolValidator()
        v.register(_make_tool("err", health_check=lambda: 1 / 0))
        report = v.validate_all()
        assert report.enabled_count == 0
        assert "health check error" in report.disabled[0][1]


# ── Dependency graph ──────────────────────────────────────────────────

class TestDependencyGraph:
    def test_disabled_dependency_propagates(self):
        v = ToolValidator()
        v.register(_make_tool("auth", health_check=lambda: False))
        v.register(_make_tool("calendar", depends_on=["auth"]))
        report = v.validate_all()
        assert report.enabled_count == 0
        cal = v.get("calendar")
        assert "dependency disabled" in cal.disable_reason

    def test_valid_dependency_ok(self):
        v = ToolValidator()
        v.register(_make_tool("auth"))
        v.register(_make_tool("calendar", depends_on=["auth"]))
        report = v.validate_all()
        assert report.enabled_count == 2

    def test_missing_dependency_disables(self):
        v = ToolValidator()
        v.register(_make_tool("calendar", depends_on=["nonexistent"]))
        report = v.validate_all()
        assert report.enabled_count == 0


# ── Disabled tool call ────────────────────────────────────────────────

class TestCheckEnabled:
    def test_enabled_tool(self):
        v = ToolValidator()
        v.register(_make_tool("t"))
        v.validate_all()
        ok, msg = v.check_enabled("t")
        assert ok and msg == "ok"

    def test_disabled_tool(self):
        v = ToolValidator()
        v.register(_make_tool("t", health_check=lambda: False))
        v.validate_all()
        ok, msg = v.check_enabled("t")
        assert not ok
        assert "disabled" in msg

    def test_unknown_tool(self):
        v = ToolValidator()
        ok, msg = v.check_enabled("unknown")
        assert not ok
        assert "not found" in msg


# ── Reload (hot-reload) ──────────────────────────────────────────────

class TestReload:
    def test_reload_revalidates(self):
        state = {"healthy": False}
        v = ToolValidator()
        v.register(_make_tool("svc", health_check=lambda: state["healthy"]))
        r1 = v.validate_all()
        assert r1.enabled_count == 0

        state["healthy"] = True
        r2 = v.reload()
        assert r2.enabled_count == 1


# ── list_tools ────────────────────────────────────────────────────────

class TestListTools:
    def test_sorted(self):
        v = ToolValidator()
        v.register(_make_tool("z"))
        v.register(_make_tool("a"))
        names = [t.name for t in v.list_tools()]
        assert names == ["a", "z"]
