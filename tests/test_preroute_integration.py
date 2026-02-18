"""Tests for Issue #407: Preroute → Orchestrator Integration.

Covers:
- PreRouter rule matching (unit)
- LocalResponseGenerator (unit)
- OrchestratorLoop._llm_planning_phase preroute bypass (integration)
- OrchestratorLoop._llm_planning_phase hint injection (integration)
- process_turn / run_full_cycle preroute_complete shortcut (integration)
- Event emission (preroute.bypass, preroute.hint)
- Stats tracking
"""

from __future__ import annotations

import warnings

import pytest
from unittest.mock import Mock, call

from bantz.brain.llm_router import OrchestratorOutput
from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.routing.preroute import (
    PreRouter,
    IntentCategory,
    PreRouteMatch,
    LocalResponseGenerator,
)


# ==========================================================================
# Fixtures
# ==========================================================================

@pytest.fixture(autouse=True)
def _disable_bridge(monkeypatch):
    """Disable language bridge so Turkish test inputs reach prerouter unchanged."""
    monkeypatch.setenv("BANTZ_BRIDGE_INPUT_GATE", "0")
    monkeypatch.setenv("BANTZ_BRIDGE_OUTPUT_GATE", "0")


@pytest.fixture
def event_bus():
    return Mock()


def _make_llm_output(**overrides) -> OrchestratorOutput:
    """Helper to create OrchestratorOutput with defaults."""
    defaults = dict(
        route="unknown",
        calendar_intent="none",
        slots={},
        confidence=0.5,
        tool_plan=[],
        assistant_reply="LLM replied",
        raw_output={},
    )
    defaults.update(overrides)
    return OrchestratorOutput(**defaults)


@pytest.fixture
def mock_orchestrator():
    orch = Mock()
    orch.route.return_value = _make_llm_output()
    return orch


@pytest.fixture
def loop(mock_orchestrator, event_bus):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return OrchestratorLoop(
            orchestrator=mock_orchestrator,
            tools=Mock(),
            event_bus=event_bus,
            config=OrchestratorConfig(enable_safety_guard=False),
        )


# ==========================================================================
# PreRouter Unit Tests
# ==========================================================================

class TestPreRouterMatching:
    """Direct tests for PreRouter rule matching."""

    def test_greeting_detected(self):
        router = PreRouter()
        result = router.route("Merhaba!")
        assert result.matched
        assert result.intent == IntentCategory.GREETING
        assert result.confidence >= 0.9

    def test_selam_greeting(self):
        router = PreRouter()
        result = router.route("Selam!")
        assert result.matched
        assert result.intent == IntentCategory.GREETING

    def test_farewell_detected(self):
        router = PreRouter()
        result = router.route("Güle güle")
        assert result.matched
        assert result.intent == IntentCategory.FAREWELL

    def test_thanks_detected(self):
        router = PreRouter()
        result = router.route("Teşekkürler")
        assert result.matched
        assert result.intent == IntentCategory.THANKS

    def test_time_query_detected(self):
        router = PreRouter()
        result = router.route("Saat kaç?")
        assert result.matched
        assert result.intent == IntentCategory.TIME_QUERY

    def test_date_query_detected(self):
        router = PreRouter()
        result = router.route("Bugün hangi gün?")
        assert result.matched
        assert result.intent == IntentCategory.DATE_QUERY

    def test_calendar_list_detected(self):
        router = PreRouter()
        result = router.route("Takvimimde ne var?")
        assert result.matched
        assert result.intent == IntentCategory.CALENDAR_LIST

    def test_email_send_detected(self):
        router = PreRouter()
        result = router.route("Ali'ye mail at selam de")
        assert result.matched
        assert result.intent == IntentCategory.EMAIL_SEND
        assert result.confidence >= 0.5

    def test_calendar_create_detected(self):
        router = PreRouter()
        result = router.route("Yeni toplantı ekle")
        assert result.matched
        assert result.intent == IntentCategory.CALENDAR_CREATE

    def test_smalltalk_detected(self):
        router = PreRouter()
        result = router.route("Nasılsın?")
        assert result.matched
        assert result.intent == IntentCategory.SMALLTALK

    def test_volume_detected(self):
        router = PreRouter()
        result = router.route("Sesi aç")
        assert result.matched
        assert result.intent == IntentCategory.VOLUME_CONTROL

    def test_screenshot_detected(self):
        router = PreRouter()
        result = router.route("Ekran görüntüsü al")
        assert result.matched
        assert result.intent == IntentCategory.SCREENSHOT

    def test_complex_input_no_match(self):
        router = PreRouter()
        result = router.route("2025 yılı bütçe raporunu hazırla ve gönder")
        assert not result.matched

    def test_empty_input_no_match(self):
        router = PreRouter()
        result = router.route("")
        assert not result.matched

    def test_should_bypass_greeting(self):
        router = PreRouter()
        result = router.route("Merhaba!")
        assert result.should_bypass(min_confidence=0.9)

    def test_should_bypass_time_query(self):
        router = PreRouter()
        result = router.route("Saat kaç?")
        assert result.should_bypass(min_confidence=0.9)

    def test_calendar_list_bypasses_router(self):
        """Calendar list has can_bypass_router=True but handler is 'calendar'."""
        router = PreRouter()
        result = router.route("Takvimimde ne var?")
        assert result.should_bypass(min_confidence=0.9)
        assert result.intent.handler_type == "calendar"


class TestPreRouterStats:
    """Test stats tracking."""

    def test_stats_accumulate(self):
        router = PreRouter()
        router.route("Merhaba!")
        router.route("Nasılsın?")
        router.route("Karmaşık bir soru sor bana lütfen")
        stats = router.get_stats()
        assert stats["total_queries"] == 3
        assert stats["bypassed_queries"] >= 1

    def test_bypass_rate_all_bypass(self):
        router = PreRouter()
        for _ in range(5):
            router.route("Selam")
        assert router.get_bypass_rate() == 1.0

    def test_bypass_rate_no_bypass(self):
        router = PreRouter()
        for _ in range(3):
            router.route("Karmaşık karışık bir cümle")
        assert router.get_bypass_rate() == 0.0

    def test_reset_stats(self):
        router = PreRouter()
        router.route("Merhaba!")
        router.reset_stats()
        assert router.get_stats()["total_queries"] == 0


# ==========================================================================
# LocalResponseGenerator Unit Tests
# ==========================================================================

class TestLocalResponseGenerator:

    def test_greeting_response_nonempty(self):
        gen = LocalResponseGenerator()
        reply = gen.generate(IntentCategory.GREETING)
        assert reply
        assert isinstance(reply, str)

    def test_farewell_response(self):
        gen = LocalResponseGenerator()
        reply = gen.generate(IntentCategory.FAREWELL)
        assert "Görüşmek üzere" in reply

    def test_thanks_response(self):
        gen = LocalResponseGenerator()
        reply = gen.generate(IntentCategory.THANKS)
        assert "Rica ederim" in reply

    def test_time_response(self):
        gen = LocalResponseGenerator()
        reply = gen.generate(IntentCategory.TIME_QUERY)
        assert "Saat" in reply

    def test_date_response(self):
        gen = LocalResponseGenerator()
        reply = gen.generate(IntentCategory.DATE_QUERY)
        assert "Bugün" in reply

    def test_smalltalk_response(self):
        gen = LocalResponseGenerator()
        reply = gen.generate(IntentCategory.SMALLTALK)
        assert reply

    def test_unknown_fallback(self):
        gen = LocalResponseGenerator()
        reply = gen.generate(IntentCategory.UNKNOWN)
        assert reply == "Anladım."


# ==========================================================================
# IntentCategory Tests
# ==========================================================================

class TestIntentCategory:

    @pytest.mark.parametrize("intent", [
        IntentCategory.GREETING,
        IntentCategory.FAREWELL,
        IntentCategory.THANKS,
        IntentCategory.SMALLTALK,
        IntentCategory.TIME_QUERY,
        IntentCategory.DATE_QUERY,
        IntentCategory.CALENDAR_LIST,
        IntentCategory.VOLUME_CONTROL,
    ])
    def test_bypassable_intents(self, intent):
        assert intent.can_bypass_router

    @pytest.mark.parametrize("intent", [
        IntentCategory.UNKNOWN,
        IntentCategory.COMPLEX,
        IntentCategory.AMBIGUOUS,
    ])
    def test_non_bypassable_intents(self, intent):
        assert not intent.can_bypass_router

    def test_handler_types(self):
        assert IntentCategory.GREETING.handler_type == "local"
        assert IntentCategory.TIME_QUERY.handler_type == "system"
        assert IntentCategory.CALENDAR_LIST.handler_type == "calendar"
        assert IntentCategory.UNKNOWN.handler_type == "router"


# ==========================================================================
# Orchestrator Loop — Preroute Bypass
# ==========================================================================

class TestPrerouteBypass:
    """High-confidence preroute bypasses LLM call."""

    def test_greeting_bypasses_llm(self, loop, mock_orchestrator):
        state = OrchestratorState()
        output = loop._llm_planning_phase("Merhaba!", state)

        # LLM route() should NOT be called
        mock_orchestrator.route.assert_not_called()

        # Should return local response
        assert output.route == "smalltalk"
        assert output.confidence >= 0.9
        assert output.assistant_reply  # Non-empty
        assert output.raw_output.get("preroute") is True
        assert output.raw_output.get("preroute_complete") is True
        assert output.tool_plan == []

    def test_farewell_bypasses_llm(self, loop, mock_orchestrator):
        state = OrchestratorState()
        output = loop._llm_planning_phase("Güle güle", state)
        mock_orchestrator.route.assert_not_called()
        assert output.route == "smalltalk"
        assert output.raw_output.get("preroute_complete")

    def test_thanks_bypasses_llm(self, loop, mock_orchestrator):
        state = OrchestratorState()
        output = loop._llm_planning_phase("Teşekkürler", state)
        mock_orchestrator.route.assert_not_called()
        assert output.route == "smalltalk"
        assert "Rica ederim" in output.assistant_reply

    def test_selam_bypasses_llm(self, loop, mock_orchestrator):
        state = OrchestratorState()
        output = loop._llm_planning_phase("Selam!", state)
        mock_orchestrator.route.assert_not_called()
        assert output.route == "smalltalk"

    def test_smalltalk_bypasses_llm(self, loop, mock_orchestrator):
        state = OrchestratorState()
        output = loop._llm_planning_phase("Nasılsın?", state)
        mock_orchestrator.route.assert_not_called()
        assert output.route == "smalltalk"

    def test_time_query_bypasses_with_tools(self, loop, mock_orchestrator):
        state = OrchestratorState()
        output = loop._llm_planning_phase("Saat kaç?", state)
        mock_orchestrator.route.assert_not_called()
        assert output.route == "system"
        assert output.calendar_intent == "time"
        assert "time.now" in output.tool_plan
        # System bypass is NOT preroute_complete (tools still execute)
        assert output.raw_output.get("preroute") is True
        assert output.raw_output.get("preroute_complete") is None

    def test_date_query_bypasses_with_tools(self, loop, mock_orchestrator):
        state = OrchestratorState()
        output = loop._llm_planning_phase("Bugün hangi gün?", state)
        mock_orchestrator.route.assert_not_called()
        assert output.route == "system"
        assert "time.now" in output.tool_plan

    def test_screenshot_bypasses_with_tools(self, loop, mock_orchestrator):
        state = OrchestratorState()
        output = loop._llm_planning_phase("Ekran görüntüsü al", state)
        mock_orchestrator.route.assert_not_called()
        assert output.route == "system"
        assert "system.screenshot" in output.tool_plan

    def test_volume_does_not_bypass_system(self, loop, mock_orchestrator):
        """Volume control is 'system' handler but NOT in tool map → hint injection."""
        state = OrchestratorState()
        loop._llm_planning_phase("Sesi aç", state)
        # Volume should fall through to LLM with hint
        mock_orchestrator.route.assert_called_once()


class TestPrerouteBypassEvents:
    """Verify event emission for bypass."""

    def test_greeting_emits_bypass_event(self, loop, event_bus):
        state = OrchestratorState()
        loop._llm_planning_phase("Merhaba!", state)
        event_bus.publish.assert_any_call("preroute.bypass", {
            "intent": "greeting",
            "confidence": pytest.approx(0.95, abs=0.1),
            "rule": "greeting",
            "handler_type": "local",
        })

    def test_time_emits_bypass_event(self, loop, event_bus):
        state = OrchestratorState()
        loop._llm_planning_phase("Saat kaç?", state)
        event_bus.publish.assert_any_call("preroute.bypass", {
            "intent": "time_query",
            "confidence": pytest.approx(0.95, abs=0.1),
            "rule": "time_query",
            "handler_type": "system",
        })


# ==========================================================================
# Orchestrator Loop — Preroute Hint Injection
# ==========================================================================

class TestPrerouteHintInjection:
    """Medium-confidence or calendar preroute injects hint into session_context."""

    def test_calendar_list_injects_hint(self, loop, mock_orchestrator):
        state = OrchestratorState()
        loop._llm_planning_phase("Takvimimde ne var?", state)

        # Should call LLM (calendar needs slot extraction)
        mock_orchestrator.route.assert_called_once()

        # Check session_context contains preroute_hint
        call_kwargs = mock_orchestrator.route.call_args
        session_ctx = call_kwargs.kwargs.get("session_context") or {}
        assert "preroute_hint" in session_ctx
        hint = session_ctx["preroute_hint"]
        assert hint["preroute_intent"] == "calendar_list"
        assert hint["preroute_confidence"] >= 0.5
        assert hint["preroute_rule"] == "calendar_list"

    def test_calendar_create_injects_hint(self, loop, mock_orchestrator):
        state = OrchestratorState()
        loop._llm_planning_phase("Yeni toplantı ekle", state)
        mock_orchestrator.route.assert_called_once()
        call_kwargs = mock_orchestrator.route.call_args
        session_ctx = call_kwargs.kwargs.get("session_context") or {}
        assert "preroute_hint" in session_ctx
        assert session_ctx["preroute_hint"]["preroute_intent"] == "calendar_create"

    def test_volume_injects_hint(self, loop, mock_orchestrator):
        """Volume control should inject hint (not bypass, no known tool mapping)."""
        state = OrchestratorState()
        loop._llm_planning_phase("Sesi aç", state)
        mock_orchestrator.route.assert_called_once()
        call_kwargs = mock_orchestrator.route.call_args
        session_ctx = call_kwargs.kwargs.get("session_context") or {}
        assert "preroute_hint" in session_ctx
        assert session_ctx["preroute_hint"]["preroute_intent"] == "volume_control"

    def test_hint_emits_event(self, loop, event_bus):
        state = OrchestratorState()
        loop._llm_planning_phase("Takvimimde ne var?", state)
        event_bus.publish.assert_any_call("preroute.hint", {
            "intent": "calendar_list",
            "confidence": pytest.approx(0.9, abs=0.1),
            "rule": "calendar_list",
        })

    def test_email_send_injects_hint(self, loop, mock_orchestrator):
        state = OrchestratorState()
        loop._llm_planning_phase("Ali'ye mail at selam de", state)

        mock_orchestrator.route.assert_called_once()
        call_kwargs = mock_orchestrator.route.call_args
        session_ctx = call_kwargs.kwargs.get("session_context") or {}
        assert "preroute_hint" in session_ctx
        assert session_ctx["preroute_hint"]["preroute_intent"] == "email_send"


class TestEmailSendPostRouteCorrection:
    def test_misrouted_smalltalk_is_corrected_to_gmail_send_to_contact(self, loop, mock_orchestrator):
        state = OrchestratorState()

        # Simulate a misroute from the LLM.
        mock_orchestrator.route.return_value = _make_llm_output(
            route="smalltalk",
            calendar_intent="none",
            confidence=0.2,
            tool_plan=[],
            gmail_intent="none",
            gmail={},
            assistant_reply="Merhaba efendim!",
        )

        output = loop._llm_planning_phase("Ali'ye mail at selam de", state)
        assert output.route == "gmail"
        assert output.gmail_intent == "send"
        assert "gmail.send_to_contact" in output.tool_plan
        assert output.ask_user is False
        assert (output.gmail or {}).get("name")

    def test_email_address_uses_gmail_send(self, loop, mock_orchestrator):
        state = OrchestratorState()
        mock_orchestrator.route.return_value = _make_llm_output(
            route="unknown",
            calendar_intent="none",
            confidence=0.2,
            tool_plan=[],
            gmail_intent="none",
            gmail={},
            assistant_reply="",
        )

        output = loop._llm_planning_phase("mail at test@example.com selam", state)
        assert output.route == "gmail"
        assert output.gmail_intent == "send"
        assert "gmail.send" in output.tool_plan
        assert (output.gmail or {}).get("to") == "test@example.com"

    def test_missing_body_asks_user(self, loop, mock_orchestrator):
        state = OrchestratorState()
        mock_orchestrator.route.return_value = _make_llm_output(
            route="smalltalk",
            calendar_intent="none",
            confidence=0.2,
            tool_plan=[],
            gmail_intent="none",
            gmail={"to": "test@example.com"},
            assistant_reply="",
        )

        output = loop._llm_planning_phase("mail at test@example.com", state)
        assert output.route == "gmail"
        assert output.gmail_intent == "send"
        assert output.ask_user is True
        assert "ne yaz" in (output.question or "").lower()


# ==========================================================================
# Orchestrator Loop — Passthrough (no preroute match)
# ==========================================================================

class TestPreroutePassthrough:
    """Unknown/complex inputs pass through to LLM with no preroute."""

    def test_complex_query_calls_llm(self, loop, mock_orchestrator, event_bus):
        state = OrchestratorState()
        loop._llm_planning_phase("2025 bütçe raporunu analiz et", state)

        mock_orchestrator.route.assert_called_once()

        # No preroute events
        preroute_calls = [
            c for c in event_bus.publish.call_args_list
            if isinstance(c.args[0], str) and c.args[0].startswith("preroute.")
        ]
        assert len(preroute_calls) == 0

    def test_empty_input_calls_llm(self, loop, mock_orchestrator):
        state = OrchestratorState()
        loop._llm_planning_phase("", state)
        mock_orchestrator.route.assert_called_once()

    def test_no_hint_for_low_confidence(self, loop, mock_orchestrator):
        """Gibberish input → no match → no hint."""
        state = OrchestratorState()
        loop._llm_planning_phase("asdfghjklöçü", state)
        mock_orchestrator.route.assert_called_once()
        call_kwargs = mock_orchestrator.route.call_args
        session_ctx = call_kwargs.kwargs.get("session_context") or {}
        assert "preroute_hint" not in session_ctx


# ==========================================================================
# process_turn — preroute_complete shortcut
# ==========================================================================

class TestProcessTurnPreroute:
    """process_turn skips tools + finalization for preroute_complete."""

    def test_greeting_skips_tools_and_finalization(self, loop):
        output, state = loop.process_turn("Merhaba!")

        assert output.route == "smalltalk"
        assert output.assistant_reply  # Local response
        assert output.raw_output.get("preroute_complete") is True
        # Verify state was updated (conversation history)
        assert len(state.conversation_history) > 0

    def test_greeting_does_not_call_llm_route(self, loop, mock_orchestrator):
        loop.process_turn("Selam!")
        mock_orchestrator.route.assert_not_called()

    def test_complex_query_calls_full_pipeline(self, loop, mock_orchestrator):
        loop.process_turn("Karmaşık bir analiz yap")
        mock_orchestrator.route.assert_called_once()


# ==========================================================================
# run_full_cycle — preroute_complete shortcut
# ==========================================================================

class TestRunFullCyclePreroute:
    """run_full_cycle returns correct trace for preroute bypass."""

    def test_greeting_bypass_trace(self, loop):
        trace = loop.run_full_cycle("Selam!")

        assert trace["route"] == "smalltalk"
        assert trace["final_output"]["assistant_reply"]
        assert trace["tools_attempted"] == 0
        assert trace["tools_executed"] == 0

    def test_complex_query_trace(self, loop, mock_orchestrator):
        trace = loop.run_full_cycle("Karmaşık bir soru")
        mock_orchestrator.route.assert_called_once()


# ==========================================================================
# Prerouter Stats within OrchestratorLoop
# ==========================================================================

class TestLoopPrerouterStats:
    """Test that prerouter stats accumulate across turns."""

    def test_bypass_stats_accumulate(self, loop):
        state = OrchestratorState()
        for _ in range(3):
            loop._llm_planning_phase("Merhaba!", state)

        stats = loop.prerouter.get_stats()
        assert stats["total_queries"] == 3
        assert stats["bypassed_queries"] == 3
        assert stats["bypass_rate"] == 1.0

    def test_mixed_stats(self, loop, mock_orchestrator):
        state = OrchestratorState()
        # 2 bypass + 1 passthrough
        loop._llm_planning_phase("Merhaba!", state)
        loop._llm_planning_phase("Selam", state)
        loop._llm_planning_phase("Karmaşık bir analiz yap", state)

        stats = loop.prerouter.get_stats()
        assert stats["total_queries"] == 3
        assert stats["bypassed_queries"] == 2
        assert stats["bypass_rate"] == pytest.approx(2 / 3, abs=0.01)

    def test_hint_does_not_count_as_bypass(self, loop, mock_orchestrator):
        """Calendar list gets hint but not bypass in stats."""
        state = OrchestratorState()
        loop._llm_planning_phase("Takvimimde ne var?", state)

        stats = loop.prerouter.get_stats()
        assert stats["total_queries"] == 1
        # Calendar list matches and bypasses in prerouter stats (confidence >= 0.8)
        # but does NOT bypass LLM in orchestrator (handler_type == "calendar")
        assert stats["bypassed_queries"] >= 0


# ==========================================================================
# Edge Cases
# ==========================================================================

class TestPrerouteEdgeCases:

    def test_preroute_output_has_correct_raw_output(self, loop):
        state = OrchestratorState()
        output = loop._llm_planning_phase("Merhaba!", state)
        assert output.raw_output["preroute"] is True
        assert output.raw_output["intent"] == "greeting"
        assert output.raw_output["rule"] == "greeting"

    def test_consecutive_bypass_and_passthrough(self, loop, mock_orchestrator):
        state = OrchestratorState()

        # First: bypass
        out1 = loop._llm_planning_phase("Merhaba!", state)
        assert out1.raw_output.get("preroute_complete")
        mock_orchestrator.route.assert_not_called()

        # Second: passthrough
        out2 = loop._llm_planning_phase("Bütçe raporunu analiz et", state)
        mock_orchestrator.route.assert_called_once()
        assert not out2.raw_output.get("preroute")

    def test_preroute_preserves_empty_tool_plan_for_local(self, loop):
        state = OrchestratorState()
        output = loop._llm_planning_phase("Teşekkürler", state)
        assert output.tool_plan == []

    def test_preroute_system_output_not_complete(self, loop):
        """System bypass needs tools → not preroute_complete."""
        state = OrchestratorState()
        output = loop._llm_planning_phase("Saat kaç?", state)
        assert output.raw_output.get("preroute") is True
        assert output.raw_output.get("preroute_complete") is None

    def test_affirmative_detected(self):
        """Exact match rule for 'evet' / 'tamam'."""
        router = PreRouter()
        result = router.route("evet")
        assert result.matched
        assert result.intent == IntentCategory.AFFIRMATIVE

    def test_negative_detected(self):
        router = PreRouter()
        result = router.route("hayır")
        assert result.matched
        assert result.intent == IntentCategory.NEGATIVE
