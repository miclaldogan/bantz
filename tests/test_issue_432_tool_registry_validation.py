"""
Tests for Issue #432 — Tool Registry Validation.

Covers:
- MANDATORY_TOOLS / ROUTE_TOOL_DEPENDENCIES constants
- ValidationReport: ok, healthy, to_dict
- RegistryValidator: mandatory check, route dep check, health check
- validate_registry convenience
- Edge cases: empty registry, partial registry, full registry
"""

from __future__ import annotations

import pytest

from bantz.agent.tool_validation import (
    MANDATORY_TOOLS,
    ROUTE_TOOL_DEPENDENCIES,
    TOOL_ROUTE_MAP,
    RegistryValidator,
    ValidationReport,
    validate_registry,
)
from bantz.agent.tools import Tool, ToolRegistry


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _make_registry(*tool_names: str) -> ToolRegistry:
    """Create a ToolRegistry with stub tools for given names."""
    reg = ToolRegistry()
    for name in tool_names:
        reg.register(
            Tool(
                name=name,
                description=f"Stub for {name}",
                parameters={"type": "object", "properties": {}},
            )
        )
    return reg


# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────


class TestConstants:

    def test_mandatory_tools_not_empty(self):
        assert len(MANDATORY_TOOLS) > 0

    def test_mandatory_contains_core(self):
        assert "time.now" in MANDATORY_TOOLS
        assert "calendar.list_events" in MANDATORY_TOOLS

    def test_route_deps_has_calendar(self):
        assert "calendar" in ROUTE_TOOL_DEPENDENCIES
        assert "calendar.create_event" in ROUTE_TOOL_DEPENDENCIES["calendar"]

    def test_route_deps_has_gmail(self):
        assert "gmail" in ROUTE_TOOL_DEPENDENCIES
        assert "gmail.send" in ROUTE_TOOL_DEPENDENCIES["gmail"]

    def test_route_deps_has_system(self):
        assert "system" in ROUTE_TOOL_DEPENDENCIES
        assert "time.now" in ROUTE_TOOL_DEPENDENCIES["system"]

    def test_route_deps_has_browser(self):
        assert "browser" in ROUTE_TOOL_DEPENDENCIES

    def test_tool_route_map_reverse(self):
        assert "calendar" in TOOL_ROUTE_MAP.get("calendar.list_events", [])
        assert "gmail" in TOOL_ROUTE_MAP.get("gmail.send", [])


# ─────────────────────────────────────────────────────────────────
# ValidationReport
# ─────────────────────────────────────────────────────────────────


class TestValidationReport:

    def test_empty_report_ok(self):
        r = ValidationReport()
        assert r.ok
        assert r.healthy

    def test_missing_mandatory_not_ok(self):
        r = ValidationReport(missing_mandatory=["time.now"], errors=["err"])
        assert not r.ok

    def test_healthy_when_no_checks(self):
        r = ValidationReport()
        assert r.healthy

    def test_unhealthy_when_check_fails(self):
        r = ValidationReport(health_results={"time.now": True, "gmail.list_messages": False})
        assert not r.healthy

    def test_to_dict_ok(self):
        r = ValidationReport(registered_tools=["time.now"])
        d = r.to_dict()
        assert d["ok"] is True
        assert "time.now" in d["registered_tools"]

    def test_to_dict_with_errors(self):
        r = ValidationReport(
            errors=["mandatory tool missing"],
            warnings=["route dep missing"],
            missing_mandatory=["time.now"],
            missing_route_deps={"system": ["time.now"]},
        )
        d = r.to_dict()
        assert d["ok"] is False
        assert "errors" in d
        assert "warnings" in d
        assert "missing_route_deps" in d


# ─────────────────────────────────────────────────────────────────
# RegistryValidator
# ─────────────────────────────────────────────────────────────────


class TestRegistryValidator:

    def test_empty_registry_fails(self):
        reg = _make_registry()
        report = RegistryValidator().validate(reg)
        assert not report.ok
        assert len(report.missing_mandatory) == len(MANDATORY_TOOLS)

    def test_full_mandatory_passes(self):
        reg = _make_registry(*MANDATORY_TOOLS)
        validator = RegistryValidator()
        report = validator.validate(reg)
        assert report.ok
        assert len(report.missing_mandatory) == 0

    def test_partial_mandatory_reports_missing(self):
        reg = _make_registry("time.now", "system.status")
        report = RegistryValidator().validate(reg)
        assert not report.ok
        assert "calendar.list_events" in report.missing_mandatory

    def test_route_dep_warning(self):
        # Register mandatory tools but not all calendar deps
        reg = _make_registry(*MANDATORY_TOOLS)
        # calendar.update_event is a route dep for "calendar" but not mandatory
        report = RegistryValidator().validate(reg)
        # calendar route deps: calendar.update_event, delete_event, find_free_slots missing
        assert "calendar" in report.missing_route_deps
        missing_cal = report.missing_route_deps["calendar"]
        assert "calendar.update_event" in missing_cal

    def test_no_route_dep_warning_when_all_registered(self):
        all_tools = set(MANDATORY_TOOLS)
        for deps in ROUTE_TOOL_DEPENDENCIES.values():
            all_tools.update(deps)
        reg = _make_registry(*all_tools)
        report = RegistryValidator().validate(reg)
        assert report.ok
        assert len(report.missing_route_deps) == 0
        assert len(report.warnings) == 0

    def test_health_check_passes_for_registered(self):
        reg = _make_registry(*MANDATORY_TOOLS)
        report = RegistryValidator().validate(reg)
        assert report.health_results.get("time.now") is True
        assert report.health_results.get("calendar.list_events") is True

    def test_health_check_fails_for_unregistered(self):
        reg = _make_registry()
        report = RegistryValidator().validate(reg)
        assert report.health_results.get("time.now") is False

    def test_custom_mandatory_tools(self):
        custom_mandatory = ["custom.tool", "another.tool"]
        reg = _make_registry("custom.tool")
        validator = RegistryValidator(mandatory_tools=custom_mandatory)
        report = validator.validate(reg)
        assert "another.tool" in report.missing_mandatory
        assert "custom.tool" not in report.missing_mandatory

    def test_custom_route_deps(self):
        custom_deps = {"myroute": ["my.tool", "my.other_tool"]}
        reg = _make_registry("my.tool")
        validator = RegistryValidator(
            mandatory_tools=["my.tool"],
            route_deps=custom_deps,
        )
        report = validator.validate(reg)
        assert report.ok  # mandatory satisfied
        assert "myroute" in report.missing_route_deps
        assert "my.other_tool" in report.missing_route_deps["myroute"]


# ─────────────────────────────────────────────────────────────────
# validate_registry convenience
# ─────────────────────────────────────────────────────────────────


class TestValidateRegistryConvenience:

    def test_full_registry_ok(self):
        all_tools = set(MANDATORY_TOOLS)
        for deps in ROUTE_TOOL_DEPENDENCIES.values():
            all_tools.update(deps)
        reg = _make_registry(*all_tools)
        report = validate_registry(reg)
        assert report.ok
        assert report.healthy

    def test_empty_registry_not_ok(self):
        reg = _make_registry()
        report = validate_registry(reg)
        assert not report.ok

    def test_report_has_registered_tools(self):
        reg = _make_registry("time.now", "system.status")
        report = validate_registry(reg)
        assert "time.now" in report.registered_tools
        assert "system.status" in report.registered_tools


# ─────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_duplicate_registration(self):
        """Registering same tool twice should keep latest."""
        reg = ToolRegistry()
        reg.register(
            Tool(name="time.now", description="v1", parameters={})
        )
        reg.register(
            Tool(name="time.now", description="v2", parameters={})
        )
        assert reg.get("time.now").description == "v2"
        assert reg.names().count("time.now") == 1

    def test_report_warnings_are_strings(self):
        reg = _make_registry()
        report = RegistryValidator().validate(reg)
        for w in report.warnings:
            assert isinstance(w, str)

    def test_report_errors_are_strings(self):
        reg = _make_registry()
        report = RegistryValidator().validate(reg)
        for e in report.errors:
            assert isinstance(e, str)

    def test_tool_route_map_all_routes_covered(self):
        """Every route in ROUTE_TOOL_DEPENDENCIES should appear in TOOL_ROUTE_MAP."""
        for route, tools in ROUTE_TOOL_DEPENDENCIES.items():
            for tool in tools:
                assert route in TOOL_ROUTE_MAP[tool]
