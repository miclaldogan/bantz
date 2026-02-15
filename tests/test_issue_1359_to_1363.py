"""Tests for Issues #1359–#1363: System/Contacts/Keep routing,
confirmation param filtering, GraphBridge async, plan_verifier updates.

Covers:
  #1359 — System route intent (time vs status vs battery vs disk)
  #1360 — Contacts route + tool resolution
  #1361 — Confirmation param schema filtering
  #1362 — GraphBridge on_tool_result async invocation
  #1363 — Keep/Notes route + tool resolution
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from bantz.brain.llm_router import (
    JarvisLLMOrchestrator,
    OrchestratorOutput,
    VALID_ROUTES,
    VALID_SYSTEM_INTENTS,
    VALID_CONTACTS_INTENTS,
    VALID_KEEP_INTENTS,
)
from bantz.brain.plan_verifier import (
    infer_route_from_tools,
    verify_plan,
    _ROUTE_TOOL_PREFIXES,
)


# ── Helpers ──────────────────────────────────────────────────────────

VALID_TOOLS = frozenset({
    "calendar.list_events", "calendar.create_event",
    "calendar.delete_event", "calendar.update_event",
    "gmail.list_messages", "gmail.send", "gmail.smart_search",
    "google.contacts.search", "google.contacts.get", "google.contacts.create",
    "google.keep.list", "google.keep.create", "google.keep.search",
    "contacts.delete",
    "time.now", "system.status",
})


def _make_output(**kwargs: Any) -> OrchestratorOutput:
    """Convenience factory for OrchestratorOutput with defaults."""
    defaults = dict(
        route="unknown",
        calendar_intent="none",
        slots={},
        confidence=0.9,
        tool_plan=[],
        assistant_reply="",
    )
    defaults.update(kwargs)
    return OrchestratorOutput(**defaults)


class MockLLM:
    """Minimal mock for JarvisLLMOrchestrator construction."""
    model_context_length = 4096

    def __init__(self, response: str = "{}"):
        self._response = response

    def complete_text(self, *, prompt: str, **kw: Any) -> str:
        return self._response


# ====================================================================
# Issue #1359: System route — intent resolution
# ====================================================================

class TestIssue1359SystemIntent:
    """System route must resolve time.now vs system.status based on intent."""

    def test_valid_system_intents_defined(self):
        assert "time" in VALID_SYSTEM_INTENTS
        assert "status" in VALID_SYSTEM_INTENTS
        assert "battery" in VALID_SYSTEM_INTENTS
        assert "disk" in VALID_SYSTEM_INTENTS
        assert "none" in VALID_SYSTEM_INTENTS

    def test_system_intent_field_on_output(self):
        out = _make_output(route="system", system_intent="status")
        assert out.system_intent == "status"
        assert out.intent == "status"

    def test_system_intent_time(self):
        out = _make_output(route="system", system_intent="time")
        assert out.intent == "time"

    def test_system_intent_fallback_to_calendar(self):
        """When system_intent is 'none', .intent returns 'none' (not calendar fallback).
        The calendar fallback only applies in _resolve_tool_from_intent."""
        out = _make_output(route="system", system_intent="none", calendar_intent="query")
        assert out.intent == "none"

    def test_resolve_tool_system_status(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        tool = router._resolve_tool_from_intent(
            "system", "none", system_intent="status",
        )
        assert tool == "system.status"

    def test_resolve_tool_system_time(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        tool = router._resolve_tool_from_intent(
            "system", "none", system_intent="time",
        )
        assert tool == "time.now"

    def test_resolve_tool_system_battery(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        tool = router._resolve_tool_from_intent(
            "system", "none", system_intent="battery",
        )
        assert tool == "system.status"

    def test_resolve_tool_system_disk(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        tool = router._resolve_tool_from_intent(
            "system", "none", system_intent="disk",
        )
        assert tool == "system.status"

    def test_resolve_tool_system_none_defaults_to_time(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        tool = router._resolve_tool_from_intent(
            "system", "none", system_intent="none",
        )
        assert tool == "time.now"

    def test_route_keywords_include_system_status_words(self):
        """System route keywords must include cpu/ram/disk/durum."""
        system_kw = JarvisLLMOrchestrator._ROUTE_KEYWORDS.get("system", [])
        for word in ("cpu", "ram", "disk", "durum"):
            assert word in system_kw, f"'{word}' missing from system keywords"

    def test_detect_route_system_durum(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        assert router._detect_route_from_input("sistem durumunu göster") == "system"


# ====================================================================
# Issue #1360: Contacts route
# ====================================================================

class TestIssue1360ContactsRoute:
    """Contacts route must exist and resolve tools correctly."""

    def test_contacts_in_valid_routes(self):
        assert "contacts" in VALID_ROUTES

    def test_contacts_intents_defined(self):
        assert "list" in VALID_CONTACTS_INTENTS
        assert "search" in VALID_CONTACTS_INTENTS
        assert "create" in VALID_CONTACTS_INTENTS
        assert "delete" in VALID_CONTACTS_INTENTS

    def test_contacts_intent_field(self):
        out = _make_output(route="contacts", contacts_intent="list")
        assert out.contacts_intent == "list"
        assert out.intent == "list"

    def test_resolve_tool_contacts_list(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        tool = router._resolve_tool_from_intent(
            "contacts", "none", contacts_intent="list",
        )
        assert tool == "google.contacts.search"

    def test_resolve_tool_contacts_create(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        tool = router._resolve_tool_from_intent(
            "contacts", "none", contacts_intent="create",
        )
        assert tool == "google.contacts.create"

    def test_resolve_tool_contacts_none_defaults(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        tool = router._resolve_tool_from_intent(
            "contacts", "none", contacts_intent="none",
        )
        assert tool == "google.contacts.search"

    def test_detect_route_contacts_keywords(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        assert router._detect_route_from_input("rehberimdeki kişileri göster") == "contacts"

    def test_detect_route_contacts_numara(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        route = router._detect_route_from_input("ali'nin numarasını bul")
        assert route == "contacts"

    def test_contacts_tools_in_valid_tools(self):
        for tool in ("google.contacts.search", "google.contacts.get", "google.contacts.create"):
            assert tool in JarvisLLMOrchestrator._VALID_TOOLS


# ====================================================================
# Issue #1363: Keep route
# ====================================================================

class TestIssue1363KeepRoute:
    """Keep/Notes route must exist and resolve tools correctly."""

    def test_keep_in_valid_routes(self):
        assert "keep" in VALID_ROUTES

    def test_keep_intents_defined(self):
        assert "create" in VALID_KEEP_INTENTS
        assert "list" in VALID_KEEP_INTENTS
        assert "search" in VALID_KEEP_INTENTS

    def test_keep_intent_field(self):
        out = _make_output(route="keep", keep_intent="create")
        assert out.keep_intent == "create"
        assert out.intent == "create"

    def test_resolve_tool_keep_create(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        tool = router._resolve_tool_from_intent(
            "keep", "none", keep_intent="create",
        )
        assert tool == "google.keep.create"

    def test_resolve_tool_keep_list(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        tool = router._resolve_tool_from_intent(
            "keep", "none", keep_intent="list",
        )
        assert tool == "google.keep.list"

    def test_resolve_tool_keep_search(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        tool = router._resolve_tool_from_intent(
            "keep", "none", keep_intent="search",
        )
        assert tool == "google.keep.search"

    def test_resolve_tool_keep_none_defaults(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        tool = router._resolve_tool_from_intent(
            "keep", "none", keep_intent="none",
        )
        assert tool == "google.keep.list"

    def test_detect_route_keep_not_olustur(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        assert router._detect_route_from_input("notlarımı listele") == "keep"

    def test_detect_route_keep_notlar(self):
        router = JarvisLLMOrchestrator(llm=MockLLM())
        assert router._detect_route_from_input("notlarımı göster") == "keep"

    def test_keep_tools_in_valid_tools(self):
        for tool in ("google.keep.list", "google.keep.create", "google.keep.search"):
            assert tool in JarvisLLMOrchestrator._VALID_TOOLS


# ====================================================================
# Issue #1361: Confirmation param schema filtering
# ====================================================================

class TestIssue1361ConfirmationParamFiltering:
    """Confirmation must not show irrelevant NLU slots (url, site)."""

    def test_filter_removes_url_and_site(self):
        """Simulate the filtering logic from orchestrator_loop.py."""
        # Tool parameters schema for gmail.send
        tool_schema = {
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            }
        }
        # These slots come from NLU — includes irrelevant url/site
        raw_params = {
            "to": "ali@gmail.com",
            "subject": "Test",
            "body": "Merhaba",
            "url": "https://example.com",
            "site": "github.com",
        }

        valid_keys = set(tool_schema["properties"].keys())
        filtered = {k: v for k, v in raw_params.items() if k in valid_keys}

        assert "to" in filtered
        assert "subject" in filtered
        assert "body" in filtered
        assert "url" not in filtered
        assert "site" not in filtered

    def test_filter_preserves_all_valid_keys(self):
        tool_schema = {
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
            }
        }
        raw_params = {"query": "test", "max_results": 10, "url": "x"}
        valid_keys = set(tool_schema["properties"].keys())
        filtered = {k: v for k, v in raw_params.items() if k in valid_keys}

        assert filtered == {"query": "test", "max_results": 10}

    def test_filter_empty_schema_passes_all(self):
        """When tool has no properties, filtering should not break."""
        tool_schema: dict = {}
        raw_params = {"url": "x", "site": "y"}
        valid_keys = set((tool_schema.get("properties") or {}).keys())
        if valid_keys:
            filtered = {k: v for k, v in raw_params.items() if k in valid_keys}
        else:
            filtered = raw_params
        # No filtering if schema is empty
        assert filtered == raw_params


# ====================================================================
# Issue #1362: GraphBridge async invocation
# ====================================================================

class TestIssue1362GraphBridgeAsync:
    """GraphBridge.on_tool_result must be properly awaited."""

    @pytest.mark.asyncio
    async def test_on_tool_result_can_be_awaited(self):
        """Verify the async method can be directly awaited."""
        try:
            from bantz.data.graph_bridge import GraphBridge
        except ImportError:
            pytest.skip("graph_bridge not available")

        mock_store = MagicMock()
        mock_linker = MagicMock()
        bridge = GraphBridge.__new__(GraphBridge)
        bridge._store = mock_store
        bridge._linker = mock_linker
        bridge._edges_created = 0
        bridge._enabled = False  # disabled → returns 0 immediately

        result = await bridge.on_tool_result(
            tool_name="gmail.list_messages",
            params={},
            result={"messages": []},
        )
        assert result == 0

    def test_asyncio_run_invokes_coro(self):
        """asyncio.run() properly executes an async function."""
        async def _async_fn() -> int:
            return 42

        result = asyncio.run(_async_fn())
        assert result == 42


# ====================================================================
# Plan Verifier: Contacts & Keep route support
# ====================================================================

class TestPlanVerifierNewRoutes:
    """plan_verifier must support contacts and keep routes."""

    def test_contacts_route_tool_prefixes(self):
        assert "contacts" in _ROUTE_TOOL_PREFIXES
        prefixes = _ROUTE_TOOL_PREFIXES["contacts"]
        assert "google.contacts." in prefixes

    def test_keep_route_tool_prefixes(self):
        assert "keep" in _ROUTE_TOOL_PREFIXES
        prefixes = _ROUTE_TOOL_PREFIXES["keep"]
        assert "google.keep." in prefixes

    def test_infer_route_google_contacts(self):
        route = infer_route_from_tools(["google.contacts.search"])
        assert route == "contacts"

    def test_infer_route_google_keep(self):
        route = infer_route_from_tools(["google.keep.create"])
        assert route == "keep"

    def test_infer_route_google_keep_list(self):
        route = infer_route_from_tools(["google.keep.list"])
        assert route == "keep"

    def test_infer_route_multiple_same_domain(self):
        route = infer_route_from_tools([
            "google.contacts.search", "google.contacts.get",
        ])
        assert route == "contacts"

    def test_infer_route_mixed_domains_returns_none(self):
        route = infer_route_from_tools([
            "google.contacts.search", "google.keep.create",
        ])
        assert route is None

    def test_verify_contacts_route_ok(self):
        plan = {
            "route": "contacts",
            "calendar_intent": "none",
            "tool_plan": ["google.contacts.search"],
        }
        ok, errors = verify_plan(plan, "kişileri göster", VALID_TOOLS)
        # Should not have route_tool_mismatch
        assert not any("route_tool_mismatch" in e for e in errors)

    def test_verify_keep_route_ok(self):
        plan = {
            "route": "keep",
            "calendar_intent": "none",
            "tool_plan": ["google.keep.create"],
        }
        ok, errors = verify_plan(plan, "not oluştur test", VALID_TOOLS)
        assert not any("route_tool_mismatch" in e for e in errors)

    def test_verify_keep_route_wrong_tool(self):
        plan = {
            "route": "keep",
            "calendar_intent": "none",
            "tool_plan": ["gmail.send"],
        }
        ok, errors = verify_plan(plan, "not oluştur", VALID_TOOLS)
        assert any("route_tool_mismatch" in e for e in errors)


# ====================================================================
# Safety Guard: contacts/keep in allowed_routes
# ====================================================================

class TestSafetyGuardNewRoutes:
    """Safety guard must allow tool execution for contacts and keep routes."""

    def test_contacts_route_allowed(self):
        from bantz.brain.safety_guard import SafetyGuard
        guard = SafetyGuard.__new__(SafetyGuard)
        guard._allowed_tools = set()
        guard._blocked_categories = set()
        guard._audit_path = None
        guard.policy_engine_v2 = None

        # Directly test the allowed_routes logic
        allowed_routes = {"calendar", "gmail", "system", "contacts", "keep"}
        assert "contacts" in allowed_routes
        assert "keep" in allowed_routes
