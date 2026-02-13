"""Tests for Issue #1274: Structured Tool Calling — Ollama Native tools API.

Tests cover:
- ToolRegistry.as_openai_tools() schema generation
- ToolRegistry.as_openai_tools_for_route() filtering
- LLMResponse.tool_calls field
- VLLMOpenAIClient.chat_with_tools() parameter passing
- JarvisLLMOrchestrator._extract_from_tool_calls() output building
- JarvisLLMOrchestrator._infer_intent_from_tool() intent derivation
- _try_structured_tool_call() dual-path logic
- Feature flag gating (BANTZ_STRUCTURED_TOOLS)
- Fallback to legacy text path on failure
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from bantz.agent.tools import Tool, ToolRegistry
from bantz.llm.base import LLMMessage, LLMResponse, LLMToolCall


# ── Fixtures ──────────────────────────────────────────────────────


def _make_registry() -> ToolRegistry:
    """Build a small ToolRegistry with calendar + gmail + system tools."""
    reg = ToolRegistry()
    reg.register(Tool(
        name="calendar.create_event",
        description="Takvime etkinlik ekler",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Etkinlik başlığı"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "time": {"type": "string", "description": "HH:MM"},
            },
            "required": ["title"],
        },
        requires_confirmation=True,
    ))
    reg.register(Tool(
        name="calendar.list_events",
        description="Takvim etkinliklerini listeler",
        parameters={
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": [],
        },
    ))
    reg.register(Tool(
        name="gmail.send",
        description="E-posta gönderir",
        parameters={
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
        requires_confirmation=True,
    ))
    reg.register(Tool(
        name="gmail.list_messages",
        description="E-postaları listeler",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
                "label": {"type": "string"},
            },
            "required": [],
        },
    ))
    reg.register(Tool(
        name="gmail.smart_search",
        description="E-posta arar",
        parameters={
            "type": "object",
            "properties": {
                "natural_query": {"type": "string"},
            },
            "required": ["natural_query"],
        },
    ))
    reg.register(Tool(
        name="system.status",
        description="Sistem durumunu gösterir",
        parameters={"type": "object", "properties": {}, "required": []},
    ))
    reg.register(Tool(
        name="time.now",
        description="Şu anki saati gösterir",
        parameters={"type": "object", "properties": {}, "required": []},
    ))
    return reg


# ── ToolRegistry.as_openai_tools() ───────────────────────────────


class TestToolRegistryOpenAISchema:
    """Tests for ToolRegistry.as_openai_tools() and as_openai_tools_for_route()."""

    def test_as_openai_tools_returns_all_tools(self):
        reg = _make_registry()
        tools = reg.as_openai_tools()
        assert len(tools) == 7
        names = {t["function"]["name"] for t in tools}
        assert "calendar.create_event" in names
        assert "gmail.send" in names
        assert "time.now" in names

    def test_openai_tool_format(self):
        reg = _make_registry()
        tools = reg.as_openai_tools()
        for tool in tools:
            assert tool["type"] == "function"
            assert "function" in tool
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert func["parameters"]["type"] == "object"

    def test_as_openai_tools_with_filter(self):
        reg = _make_registry()
        tools = reg.as_openai_tools(tool_names={"gmail.send", "gmail.list_messages"})
        assert len(tools) == 2
        names = {t["function"]["name"] for t in tools}
        assert names == {"gmail.send", "gmail.list_messages"}

    def test_as_openai_tools_empty_filter(self):
        reg = _make_registry()
        tools = reg.as_openai_tools(tool_names=set())
        assert tools == []

    def test_as_openai_tools_for_route_calendar(self):
        reg = _make_registry()
        tools = reg.as_openai_tools_for_route("calendar")
        assert len(tools) == 2
        names = {t["function"]["name"] for t in tools}
        assert names == {"calendar.create_event", "calendar.list_events"}

    def test_as_openai_tools_for_route_gmail(self):
        reg = _make_registry()
        tools = reg.as_openai_tools_for_route("gmail")
        assert len(tools) == 3
        names = {t["function"]["name"] for t in tools}
        assert names == {"gmail.send", "gmail.list_messages", "gmail.smart_search"}

    def test_as_openai_tools_for_route_system(self):
        reg = _make_registry()
        tools = reg.as_openai_tools_for_route("system")
        names = {t["function"]["name"] for t in tools}
        assert "system.status" in names

    def test_as_openai_tools_for_route_unknown(self):
        reg = _make_registry()
        tools = reg.as_openai_tools_for_route("browser")
        assert tools == []

    def test_as_openai_tools_for_route_with_valid_tools_filter(self):
        reg = _make_registry()
        tools = reg.as_openai_tools_for_route(
            "gmail",
            valid_tools=frozenset({"gmail.send"}),
        )
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "gmail.send"

    def test_parameters_include_required(self):
        reg = _make_registry()
        tools = reg.as_openai_tools(tool_names={"gmail.send"})
        params = tools[0]["function"]["parameters"]
        assert "required" in params
        assert set(params["required"]) == {"to", "subject", "body"}

    def test_parameters_no_type_gets_added(self):
        """Tools with parameters missing 'type' get it added."""
        reg = ToolRegistry()
        reg.register(Tool(
            name="test.foo",
            description="Test",
            parameters={"properties": {"x": {"type": "string"}}},
        ))
        tools = reg.as_openai_tools()
        assert tools[0]["function"]["parameters"]["type"] == "object"


# ── LLMToolCall / LLMResponse ────────────────────────────────────


class TestLLMToolCall:
    """Tests for LLMToolCall and LLMResponse.tool_calls field."""

    def test_tool_call_creation(self):
        tc = LLMToolCall(id="call_1", name="gmail.send", arguments={"to": "a@b.com"})
        assert tc.id == "call_1"
        assert tc.name == "gmail.send"
        assert tc.arguments == {"to": "a@b.com"}

    def test_response_without_tool_calls(self):
        resp = LLMResponse(
            content="hello",
            model="test",
            tokens_used=10,
            finish_reason="stop",
        )
        assert resp.tool_calls is None

    def test_response_with_tool_calls(self):
        tc = LLMToolCall(id="call_1", name="gmail.send", arguments={"to": "a@b.com"})
        resp = LLMResponse(
            content="",
            model="test",
            tokens_used=10,
            finish_reason="stop",
            tool_calls=[tc],
        )
        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "gmail.send"


# ── _infer_intent_from_tool() ────────────────────────────────────


class TestInferIntentFromTool:
    """Tests for JarvisLLMOrchestrator._infer_intent_from_tool()."""

    def _infer(self, tool_name: str, route: str) -> str:
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        return JarvisLLMOrchestrator._infer_intent_from_tool(tool_name, route)

    def test_calendar_create(self):
        assert self._infer("calendar.create_event", "calendar") == "create"

    def test_calendar_modify(self):
        assert self._infer("calendar.modify_event", "calendar") == "modify"

    def test_calendar_cancel(self):
        assert self._infer("calendar.cancel_event", "calendar") == "cancel"

    def test_calendar_list(self):
        assert self._infer("calendar.list_events", "calendar") == "query"

    def test_calendar_free_slots(self):
        assert self._infer("calendar.free_slots", "calendar") == "query"

    def test_calendar_unknown_action(self):
        assert self._infer("calendar.foo_bar", "calendar") == "query"

    def test_gmail_send(self):
        assert self._infer("gmail.send", "gmail") == "send"

    def test_gmail_list(self):
        assert self._infer("gmail.list_messages", "gmail") == "list"

    def test_gmail_search(self):
        assert self._infer("gmail.smart_search", "gmail") == "search"

    def test_gmail_read(self):
        assert self._infer("gmail.read_message", "gmail") == "read"

    def test_gmail_unknown(self):
        assert self._infer("gmail.something", "gmail") == "list"

    def test_no_dot(self):
        assert self._infer("standalone", "calendar") == "none"

    def test_system_route(self):
        assert self._infer("system.status", "system") == "none"


# ── _extract_from_tool_calls() ───────────────────────────────────


class TestExtractFromToolCalls:
    """Tests for _extract_from_tool_calls() output building."""

    def _make_orchestrator(self, registry=None):
        from bantz.brain.llm_router import JarvisLLMOrchestrator

        mock_llm = MagicMock()
        mock_llm.backend_name = "vllm"
        mock_llm.model_name = "test"
        mock_llm.is_available.return_value = True

        orch = JarvisLLMOrchestrator(llm_client=mock_llm)
        if registry:
            JarvisLLMOrchestrator.sync_valid_tools(
                set(registry.names()), registry=registry,
            )
        return orch

    def test_calendar_create_event(self):
        reg = _make_registry()
        orch = self._make_orchestrator(reg)
        tc = LLMToolCall(
            id="call_1",
            name="calendar.create_event",
            arguments={"title": "Toplantı", "date": "2025-01-15", "time": "14:00"},
        )
        result = orch._extract_from_tool_calls(
            [tc], content="", user_input="yarın iki de toplantı koy",
            detected_route="calendar",
        )
        assert result.route == "calendar"
        assert result.calendar_intent == "create"
        assert result.tool_plan == ["calendar.create_event"]
        assert result.confidence == 0.95
        assert result.requires_confirmation is True
        assert result.slots.get("title") == "Toplantı"
        assert result.slots.get("date") == "2025-01-15"
        assert result.slots.get("time") == "14:00"
        assert result.status == "done"

    def test_gmail_send(self):
        reg = _make_registry()
        orch = self._make_orchestrator(reg)
        tc = LLMToolCall(
            id="call_2",
            name="gmail.send",
            arguments={"to": "test@example.com", "subject": "Merhaba", "body": "Selam"},
        )
        result = orch._extract_from_tool_calls(
            [tc], content="", user_input="test@gmail.com a merhaba gönder",
            detected_route="gmail",
        )
        assert result.route == "gmail"
        assert result.gmail_intent == "send"
        assert result.tool_plan == ["gmail.send"]
        assert result.requires_confirmation is True
        assert result.gmail["to"] == "test@example.com"
        assert result.gmail["subject"] == "Merhaba"

    def test_gmail_list_messages(self):
        reg = _make_registry()
        orch = self._make_orchestrator(reg)
        tc = LLMToolCall(
            id="call_3",
            name="gmail.list_messages",
            arguments={"query": "from:boss", "max_results": 5},
        )
        result = orch._extract_from_tool_calls(
            [tc], content="", user_input="son 5 maili göster",
            detected_route="gmail",
        )
        assert result.route == "gmail"
        assert result.gmail_intent == "list"
        assert result.requires_confirmation is False
        assert result.gmail.get("max_results") == 5

    def test_unknown_tool_dropped(self):
        reg = _make_registry()
        orch = self._make_orchestrator(reg)
        tc = LLMToolCall(
            id="call_x",
            name="nonexistent.tool",
            arguments={},
        )
        result = orch._extract_from_tool_calls(
            [tc], content="some text", user_input="test",
            detected_route="gmail",
        )
        assert result.tool_plan == []
        assert result.assistant_reply == "some text"

    def test_deterministic_tool_clears_reply(self):
        reg = _make_registry()
        orch = self._make_orchestrator(reg)
        tc = LLMToolCall(id="call_t", name="time.now", arguments={})
        result = orch._extract_from_tool_calls(
            [tc], content="saat 3:47", user_input="saat kaç",
            detected_route="system",
        )
        # time.now is deterministic → reply should be cleared
        assert result.assistant_reply == ""

    def test_raw_output_has_marker(self):
        reg = _make_registry()
        orch = self._make_orchestrator(reg)
        tc = LLMToolCall(id="call_m", name="calendar.list_events", arguments={})
        result = orch._extract_from_tool_calls(
            [tc], content="", user_input="bugün ne var",
            detected_route="calendar",
        )
        assert result.raw_output.get("_structured_tool_call") is True

    def test_multiple_tool_calls(self):
        reg = _make_registry()
        orch = self._make_orchestrator(reg)
        tc1 = LLMToolCall(id="c1", name="calendar.list_events", arguments={"date": "2025-01-15"})
        tc2 = LLMToolCall(id="c2", name="calendar.create_event", arguments={"title": "Meeting"})
        result = orch._extract_from_tool_calls(
            [tc1, tc2], content="", user_input="bugün ne var, bir de toplantı ekle",
            detected_route="calendar",
        )
        assert len(result.tool_plan) == 2
        assert "calendar.list_events" in result.tool_plan
        assert "calendar.create_event" in result.tool_plan

    def test_route_derived_from_tool_prefix(self):
        """Route is derived from tool name prefix if it differs from detected."""
        reg = _make_registry()
        orch = self._make_orchestrator(reg)
        tc = LLMToolCall(id="c", name="system.status", arguments={})
        result = orch._extract_from_tool_calls(
            [tc], content="", user_input="sistem durumu",
            detected_route="calendar",  # Wrong detected route
        )
        # Route should be corrected from tool prefix
        assert result.route == "system"


# ── _try_structured_tool_call() integration ──────────────────────


class TestTryStructuredToolCall:
    """Tests for the dual-path logic in _try_structured_tool_call()."""

    def _make_orchestrator(self, registry=None, *, llm_response=None):
        from bantz.brain.llm_router import JarvisLLMOrchestrator

        mock_llm = MagicMock()
        mock_llm.backend_name = "vllm"
        mock_llm.model_name = "test"
        mock_llm.is_available.return_value = True

        if llm_response is not None:
            mock_llm.chat_with_tools.return_value = llm_response

        orch = JarvisLLMOrchestrator(llm_client=mock_llm)
        if registry:
            JarvisLLMOrchestrator.sync_valid_tools(
                set(registry.names()), registry=registry,
            )
        return orch, mock_llm

    def test_returns_none_without_registry(self):
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        mock_llm = MagicMock()
        mock_llm.backend_name = "vllm"
        mock_llm.model_name = "test"
        orch = JarvisLLMOrchestrator(llm_client=mock_llm)
        JarvisLLMOrchestrator._tool_registry = None

        result = orch._try_structured_tool_call(
            user_input="bugün ne var",
            session_context=None,
            prompt="test prompt",
            call_temperature=0.0,
            call_max_tokens=200,
        )
        assert result is None

    def test_returns_none_for_smalltalk(self):
        """No route detected for smalltalk → returns None."""
        reg = _make_registry()
        orch, _ = self._make_orchestrator(reg)
        result = orch._try_structured_tool_call(
            user_input="nasılsın",  # No route keywords match
            session_context=None,
            prompt="test",
            call_temperature=0.0,
            call_max_tokens=200,
        )
        assert result is None

    def test_returns_output_on_tool_call(self):
        """Model returns tool_calls → structured output."""
        reg = _make_registry()
        tc = LLMToolCall(id="c1", name="calendar.list_events", arguments={"date": "2025-01-15"})
        resp = LLMResponse(
            content="",
            model="test",
            tokens_used=50,
            finish_reason="stop",
            tool_calls=[tc],
        )
        orch, mock_llm = self._make_orchestrator(reg, llm_response=resp)

        result = orch._try_structured_tool_call(
            user_input="bugün takvimde ne var",
            session_context=None,
            prompt="test",
            call_temperature=0.0,
            call_max_tokens=200,
        )
        assert result is not None
        assert result.route == "calendar"
        assert result.tool_plan == ["calendar.list_events"]
        mock_llm.chat_with_tools.assert_called_once()

    def test_returns_none_when_model_gives_text(self):
        """Model returns text only (no tool_calls) → returns None for fallback."""
        reg = _make_registry()
        resp = LLMResponse(
            content='{"route":"calendar","confidence":0.9}',
            model="test",
            tokens_used=50,
            finish_reason="stop",
            tool_calls=None,
        )
        orch, _ = self._make_orchestrator(reg, llm_response=resp)

        result = orch._try_structured_tool_call(
            user_input="bugün takvimde ne var",
            session_context=None,
            prompt="test",
            call_temperature=0.0,
            call_max_tokens=200,
        )
        assert result is None  # Falls to legacy path

    def test_returns_none_on_exception(self):
        """LLM call raises → returns None for fallback."""
        reg = _make_registry()
        orch, mock_llm = self._make_orchestrator(reg)
        mock_llm.chat_with_tools.side_effect = RuntimeError("Connection refused")

        result = orch._try_structured_tool_call(
            user_input="bugün takvimde ne var",
            session_context=None,
            prompt="test",
            call_temperature=0.0,
            call_max_tokens=200,
        )
        assert result is None

    def test_returns_none_without_chat_with_tools(self):
        """LLM client without chat_with_tools → returns None."""
        reg = _make_registry()
        mock_llm = MagicMock(spec=["complete_text", "backend_name", "model_name", "is_available"])
        mock_llm.backend_name = "vllm"
        mock_llm.model_name = "test"
        mock_llm.is_available.return_value = True

        from bantz.brain.llm_router import JarvisLLMOrchestrator
        orch = JarvisLLMOrchestrator(llm_client=mock_llm)
        JarvisLLMOrchestrator.sync_valid_tools(set(reg.names()), registry=reg)

        result = orch._try_structured_tool_call(
            user_input="bugün takvimde ne var",
            session_context=None,
            prompt="test",
            call_temperature=0.0,
            call_max_tokens=200,
        )
        assert result is None


# ── Feature flag gating ──────────────────────────────────────────


class TestFeatureFlag:
    """Tests for BANTZ_STRUCTURED_TOOLS feature flag."""

    def _make_router_and_call(self, *, env_val: str, tool_calls=None):
        """Set up a router and call route() with the given feature flag value."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator

        reg = _make_registry()
        mock_llm = MagicMock()
        mock_llm.backend_name = "vllm"
        mock_llm.model_name = "test"
        mock_llm.is_available.return_value = True

        # Legacy text response (always available)
        mock_llm.complete_text.return_value = json.dumps({
            "route": "calendar",
            "confidence": 0.9,
            "calendar_intent": "query",
            "tool_plan": ["calendar.list_events"],
            "slots": {},
            "assistant_reply": "",
            "status": "done",
        })

        # Structured tool response
        if tool_calls:
            mock_llm.chat_with_tools.return_value = LLMResponse(
                content="",
                model="test",
                tokens_used=50,
                finish_reason="stop",
                tool_calls=tool_calls,
            )

        orch = JarvisLLMOrchestrator(llm_client=mock_llm)
        JarvisLLMOrchestrator.sync_valid_tools(set(reg.names()), registry=reg)

        with patch.dict(os.environ, {"BANTZ_STRUCTURED_TOOLS": env_val}):
            result = orch.route(user_input="bugün takvimde ne var")

        return result, mock_llm

    def test_flag_off_uses_legacy_path(self):
        """BANTZ_STRUCTURED_TOOLS=0 → legacy text path."""
        result, mock_llm = self._make_router_and_call(env_val="0")
        mock_llm.complete_text.assert_called()
        mock_llm.chat_with_tools.assert_not_called()
        assert result.route == "calendar"

    def test_flag_on_tries_structured_first(self):
        """BANTZ_STRUCTURED_TOOLS=1 → tries structured path first."""
        tc = LLMToolCall(id="c1", name="calendar.list_events", arguments={})
        result, mock_llm = self._make_router_and_call(
            env_val="1",
            tool_calls=[tc],
        )
        mock_llm.chat_with_tools.assert_called()
        assert result.route == "calendar"
        assert result.confidence == 0.95  # Structured path confidence
        assert result.raw_output.get("_structured_tool_call") is True

    def test_flag_on_falls_back_when_no_tool_calls(self):
        """Structured path returns no tool_calls → falls to legacy."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator

        reg = _make_registry()
        mock_llm = MagicMock()
        mock_llm.backend_name = "vllm"
        mock_llm.model_name = "test"
        mock_llm.is_available.return_value = True

        # Structured call returns text (no tool_calls)
        mock_llm.chat_with_tools.return_value = LLMResponse(
            content="some text",
            model="test",
            tokens_used=50,
            finish_reason="stop",
            tool_calls=None,
        )

        # Legacy text response
        mock_llm.complete_text.return_value = json.dumps({
            "route": "calendar",
            "confidence": 0.85,
            "calendar_intent": "query",
            "tool_plan": ["calendar.list_events"],
            "slots": {},
            "assistant_reply": "",
            "status": "done",
        })

        orch = JarvisLLMOrchestrator(llm_client=mock_llm)
        JarvisLLMOrchestrator.sync_valid_tools(set(reg.names()), registry=reg)

        with patch.dict(os.environ, {"BANTZ_STRUCTURED_TOOLS": "1"}):
            result = orch.route(user_input="bugün takvimde ne var")

        # Structured failed → legacy used
        mock_llm.complete_text.assert_called()
        assert result.route == "calendar"
        assert result.raw_output.get("_structured_tool_call") is not True


# ── VLLMOpenAIClient tools parameter passing ─────────────────────


class TestVLLMClientToolsParam:
    """Tests for VLLMOpenAIClient tools parameter threading."""

    def test_chat_detailed_passes_tools_to_do_chat_request(self):
        """tools param flows from chat_detailed → _do_chat_request → API call."""
        from bantz.llm.vllm_openai_client import VLLMOpenAIClient

        client = VLLMOpenAIClient.__new__(VLLMOpenAIClient)
        client.base_url = "http://localhost:11434"
        client.model = "test"
        client.timeout_seconds = 5.0
        client.track_ttft = False
        client.ttft_phase = "router"
        client._client = None
        client._lock = __import__("threading").Lock()
        client._cached_model_context_len = None

        # Mock _do_chat_request to capture kwargs
        captured_kwargs = {}
        original_return = LLMResponse(
            content="test",
            model="test",
            tokens_used=10,
            finish_reason="stop",
        )

        def mock_do_chat(self_inner, client_arg, messages, *, temperature, max_tokens,
                         seed, response_format, stop, tools=None, tool_choice=None):
            captured_kwargs["tools"] = tools
            captured_kwargs["tool_choice"] = tool_choice
            return original_return

        tools_schema = [{"type": "function", "function": {"name": "test.foo", "parameters": {}}}]

        with patch.object(VLLMOpenAIClient, "_do_chat_request", mock_do_chat):
            with patch.object(VLLMOpenAIClient, "_get_client", return_value=MagicMock()):
                with patch.object(VLLMOpenAIClient, "_resolve_auto_model"):
                    resp = client.chat_detailed(
                        [LLMMessage(role="user", content="test")],
                        tools=tools_schema,
                        tool_choice="auto",
                    )

        assert captured_kwargs["tools"] == tools_schema
        assert captured_kwargs["tool_choice"] == "auto"

    def test_chat_with_tools_convenience(self):
        """chat_with_tools() delegates to chat_detailed with tools."""
        from bantz.llm.vllm_openai_client import VLLMOpenAIClient

        client = VLLMOpenAIClient.__new__(VLLMOpenAIClient)
        client.base_url = "http://localhost:11434"
        client.model = "test"
        client.timeout_seconds = 5.0
        client.track_ttft = False
        client.ttft_phase = "router"
        client._client = None
        client._lock = __import__("threading").Lock()
        client._cached_model_context_len = None

        expected_resp = LLMResponse(
            content="", model="test", tokens_used=10, finish_reason="stop",
            tool_calls=[LLMToolCall(id="c1", name="test.foo", arguments={})],
        )

        with patch.object(VLLMOpenAIClient, "chat_detailed", return_value=expected_resp) as mock:
            tools = [{"type": "function", "function": {"name": "test.foo"}}]
            msgs = [LLMMessage(role="user", content="test")]
            resp = client.chat_with_tools(msgs, tools=tools, temperature=0.1, tool_choice="required")

        mock.assert_called_once()
        call_kwargs = mock.call_args
        assert call_kwargs.kwargs["tools"] == tools
        assert call_kwargs.kwargs["tool_choice"] == "required"
        assert resp.tool_calls is not None
