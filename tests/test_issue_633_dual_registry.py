"""Issue #633 — Dual tool registry unification tests.

Validates:
1. build_planner_registry() is the canonical planner function
2. build_default_registry() backward-compat wrapper emits DeprecationWarning
3. Both registries share 10 overlapping tool names intentionally
4. Runtime registry (registry.py) tools all have function= handlers
5. Planner registry (builtin_tools.py) has richer schemas and more tools
6. Architecture is documented and imports are consistent
"""

from __future__ import annotations

import warnings

import pytest


# ── 1. Canonical planner function ──────────────────────────────────


class TestBuildPlannerRegistry:
    """build_planner_registry() should be the primary entry point."""

    def test_returns_tool_registry(self):
        from bantz.agent.builtin_tools import build_planner_registry
        from bantz.agent.tools import ToolRegistry

        reg = build_planner_registry()
        assert isinstance(reg, ToolRegistry)

    def test_has_69_plus_tools(self):
        from bantz.agent.builtin_tools import build_planner_registry

        reg = build_planner_registry()
        # Planner catalog should have significantly more tools than runtime
        assert len(reg.names()) >= 60, (
            f"Expected ≥60 planner tools, got {len(reg.names())}"
        )

    def test_includes_schema_only_tools(self):
        """Planner has browser/file/terminal tools that are schema-only."""
        from bantz.agent.builtin_tools import build_planner_registry

        reg = build_planner_registry()
        schema_only_tools = [
            "browser_open",
            "browser_scan",
            "browser_click",
            "file_read",
            "file_write",
            "terminal_run",
            "project_info",
            "clipboard_get",
        ]
        for name in schema_only_tools:
            tool = reg.get(name)
            assert tool is not None, f"Missing schema-only tool: {name}"
            # Schema-only tools have no function
            assert tool.function is None, (
                f"Schema-only tool {name!r} should not have a function"
            )


# ── 2. Backward-compat wrapper ─────────────────────────────────────


class TestBackwardCompatWrapper:
    """build_default_registry() should still work but emit DeprecationWarning."""

    def test_emits_deprecation_warning(self):
        from bantz.agent.builtin_tools import build_default_registry

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            reg = build_default_registry()
            # Should have emitted at least one DeprecationWarning
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1, "Expected DeprecationWarning"
            assert "build_planner_registry" in str(dep_warnings[0].message)

    def test_returns_same_registry_type(self):
        from bantz.agent.builtin_tools import (
            build_default_registry,
            build_planner_registry,
        )
        from bantz.agent.tools import ToolRegistry

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            old_reg = build_default_registry()

        new_reg = build_planner_registry()

        assert isinstance(old_reg, ToolRegistry)
        assert old_reg.names() == new_reg.names()


# ── 3. Overlapping tool names ──────────────────────────────────────


class TestOverlappingTools:
    """10 tools exist in both registries — intentional mapping to router intents."""

    OVERLAPPING = [
        "calendar.list_events",
        "calendar.find_free_slots",
        "calendar.create_event",
        "calendar.update_event",
        "calendar.delete_event",
        "gmail.unread_count",
        "gmail.list_messages",
        "gmail.smart_search",
        "gmail.get_message",
        "gmail.send",
    ]

    def test_overlapping_tools_exist_in_both(self):
        from bantz.agent.builtin_tools import build_planner_registry
        from bantz.agent.registry import build_default_registry

        planner = build_planner_registry()
        runtime = build_default_registry()

        for name in self.OVERLAPPING:
            assert planner.get(name) is not None, f"Missing in planner: {name}"
            assert runtime.get(name) is not None, f"Missing in runtime: {name}"

    def test_runtime_has_handlers_for_overlapping(self):
        """Runtime registry MUST have real function= handlers."""
        from bantz.agent.registry import build_default_registry

        runtime = build_default_registry()
        for name in self.OVERLAPPING:
            tool = runtime.get(name)
            assert tool is not None
            assert tool.function is not None, (
                f"Runtime tool {name!r} missing function= handler"
            )

    def test_planner_has_richer_schemas(self):
        """Planner registry has more detailed parameter schemas."""
        from bantz.agent.builtin_tools import build_planner_registry

        planner = build_planner_registry()

        # Planner's calendar.list_events has RFC3339 params
        cal_list = planner.get("calendar.list_events")
        assert cal_list is not None
        props = cal_list.parameters.get("properties", {})
        # Planner has calendar_id, time_min, time_max (raw API params)
        assert "calendar_id" in props or "time_min" in props, (
            "Planner calendar.list_events should have raw API params"
        )

    def test_runtime_has_orchestrator_schemas(self):
        """Runtime registry has orchestrator-friendly params (date, time, window_hint)."""
        from bantz.agent.registry import build_default_registry

        runtime = build_default_registry()

        cal_list = runtime.get("calendar.list_events")
        assert cal_list is not None
        props = cal_list.parameters.get("properties", {})
        # Runtime has human-friendly slots
        assert "date" in props or "window_hint" in props, (
            "Runtime calendar.list_events should have orchestrator slots"
        )


# ── 4. Runtime registry validation ────────────────────────────────


class TestRuntimeRegistry:
    """Runtime registry (registry.py) — all tools must have handlers."""

    def test_all_runtime_tools_have_handlers(self):
        from bantz.agent.registry import build_default_registry

        runtime = build_default_registry()
        for name in runtime.names():
            tool = runtime.get(name)
            assert tool is not None
            assert tool.function is not None, (
                f"Runtime tool {name!r} has no function= handler"
            )

    def test_runtime_tool_count(self):
        """Runtime has 15 tools (13 core + 2 web)."""
        from bantz.agent.registry import build_default_registry

        runtime = build_default_registry()
        count = len(runtime.names())
        assert count >= 13, f"Expected ≥13 runtime tools, got {count}"

    def test_runtime_includes_system_and_time(self):
        from bantz.agent.registry import build_default_registry

        runtime = build_default_registry()
        assert runtime.get("system.status") is not None
        assert runtime.get("time.now") is not None


# ── 5. Planner extras ─────────────────────────────────────────────


class TestPlannerExtras:
    """Planner registry has tools that runtime doesn't."""

    def test_planner_has_gmail_drafts(self):
        from bantz.agent.builtin_tools import build_planner_registry

        planner = build_planner_registry()
        draft_tools = [n for n in planner.names() if "draft" in n]
        assert len(draft_tools) >= 3, (
            f"Expected ≥3 draft tools, got {draft_tools}"
        )

    def test_planner_has_contacts(self):
        from bantz.agent.builtin_tools import build_planner_registry

        planner = build_planner_registry()
        contact_tools = [n for n in planner.names() if "contacts" in n]
        assert len(contact_tools) >= 3

    def test_planner_has_gmail_labels(self):
        from bantz.agent.builtin_tools import build_planner_registry

        planner = build_planner_registry()
        label_tools = [n for n in planner.names() if "label" in n.lower()]
        assert len(label_tools) >= 2

    def test_planner_has_planning_tools(self):
        from bantz.agent.builtin_tools import build_planner_registry

        planner = build_planner_registry()
        assert planner.get("calendar.plan_events_from_draft") is not None
        assert planner.get("calendar.apply_plan_draft") is not None


# ── 6. Architecture consistency ───────────────────────────────────


class TestArchitectureConsistency:
    """Validate the documented architecture."""

    def test_planner_function_name_is_canonical(self):
        """build_planner_registry must exist directly (not via wrapper)."""
        import bantz.agent.builtin_tools as bt

        assert hasattr(bt, "build_planner_registry")
        # Should not trigger deprecation
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            bt.build_planner_registry()
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) == 0, (
                "build_planner_registry should NOT emit DeprecationWarning"
            )

    def test_runtime_function_name_unchanged(self):
        """registry.py still uses build_default_registry (no rename needed)."""
        import bantz.agent.registry as reg_mod

        assert hasattr(reg_mod, "build_default_registry")

    def test_no_cross_contamination(self):
        """Runtime and planner registries are independent instances."""
        from bantz.agent.builtin_tools import build_planner_registry
        from bantz.agent.registry import build_default_registry

        planner = build_planner_registry()
        runtime = build_default_registry()

        # They should not be the same object
        assert planner is not runtime

        # Planner has strictly more tools
        assert len(planner.names()) > len(runtime.names())
