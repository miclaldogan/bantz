"""Tests for Issue #421: JSON repair post-validation and confidence penalty.

Covers:
- RepairTracker metrics and thread-safety
- _parse_json returning (dict, was_repaired) tuple
- _extract_output route/intent validation after repair
- Confidence penalty when JSON was repaired
- Repair events published to event bus
- Integration: full route() flow with repair scenarios
"""

from __future__ import annotations

import json
import re
import threading
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from bantz.brain.llm_router import (
    JarvisLLMOrchestrator,
    OrchestratorOutput,
    RepairTracker,
    get_repair_tracker,
    _repair_tracker,
    VALID_ROUTES,
    VALID_CALENDAR_INTENTS,
    VALID_GMAIL_INTENTS,
)


# ============================================================================
# Helper: Minimal LLM mock
# ============================================================================

class MockLLM:
    """Minimal mock LLM for testing."""

    def __init__(self, response: str = ""):
        self.response = response
        self.call_count = 0
        self.event_bus = None

    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
        self.call_count += 1
        return self.response


def _make_router(response: str, **kwargs) -> JarvisLLMOrchestrator:
    llm = MockLLM(response)
    return JarvisLLMOrchestrator(llm=llm, **kwargs)


def _valid_json(**overrides) -> str:
    base = {
        "route": "calendar",
        "calendar_intent": "create",
        "slots": {"time": "17:00", "title": "toplantı"},
        "confidence": 0.9,
        "tool_plan": ["calendar.create_event"],
        "assistant_reply": "Toplantı oluşturuyorum.",
    }
    base.update(overrides)
    return json.dumps(base)


# ============================================================================
# RepairTracker
# ============================================================================

class TestRepairTracker:
    """Test RepairTracker metrics and thread-safety."""

    def test_initial_state(self):
        tracker = RepairTracker()
        assert tracker.total_requests == 0
        assert tracker.repair_count == 0
        assert tracker.repairs_per_100 == 0.0

    def test_record_clean_request(self):
        tracker = RepairTracker()
        tracker.record_request(repaired=False)
        assert tracker.total_requests == 1
        assert tracker.repair_count == 0
        assert tracker.repairs_per_100 == 0.0

    def test_record_repaired_request(self):
        tracker = RepairTracker()
        tracker.record_request(repaired=True)
        assert tracker.total_requests == 1
        assert tracker.repair_count == 1
        assert tracker.repairs_per_100 == 100.0

    def test_repairs_per_100_mixed(self):
        tracker = RepairTracker()
        for _ in range(7):
            tracker.record_request(repaired=False)
        for _ in range(3):
            tracker.record_request(repaired=True)
        assert tracker.total_requests == 10
        assert tracker.repair_count == 3
        assert tracker.repairs_per_100 == 30.0

    def test_route_intent_corrections(self):
        tracker = RepairTracker()
        tracker.record_route_correction()
        tracker.record_route_correction()
        tracker.record_intent_correction()
        summary = tracker.summary()
        assert summary["route_corrections"] == 2
        assert summary["intent_corrections"] == 1

    def test_reset(self):
        tracker = RepairTracker()
        tracker.record_request(repaired=True)
        tracker.record_route_correction()
        tracker.reset()
        assert tracker.total_requests == 0
        assert tracker.repair_count == 0
        summary = tracker.summary()
        assert summary["route_corrections"] == 0

    def test_summary_format(self):
        tracker = RepairTracker()
        tracker.record_request(repaired=True)
        s = tracker.summary()
        assert "total_requests" in s
        assert "repair_count" in s
        assert "repairs_per_100" in s
        assert "route_corrections" in s
        assert "intent_corrections" in s

    def test_confidence_penalty_constant(self):
        assert RepairTracker.CONFIDENCE_PENALTY == 0.9

    def test_thread_safety(self):
        """Record from multiple threads without error."""
        tracker = RepairTracker()
        errors = []

        def worker():
            try:
                for _ in range(100):
                    tracker.record_request(repaired=True)
                    tracker.record_route_correction()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert tracker.total_requests == 400
        assert tracker.repair_count == 400

    def test_global_singleton(self):
        assert get_repair_tracker() is _repair_tracker


# ============================================================================
# Valid Enum Sets
# ============================================================================

class TestValidEnums:
    """Test the centralized valid enum sets."""

    def test_valid_routes(self):
        assert VALID_ROUTES == {"calendar", "gmail", "smalltalk", "system", "unknown", "contacts", "keep"}

    def test_valid_calendar_intents(self):
        assert VALID_CALENDAR_INTENTS == {"create", "modify", "cancel", "query", "none"}

    def test_valid_gmail_intents(self):
        assert VALID_GMAIL_INTENTS == {"list", "search", "read", "send", "none"}


# ============================================================================
# _parse_json returns (dict, was_repaired) tuple
# ============================================================================

class TestParseJsonTuple:
    """Test that _parse_json returns a tuple with repair flag."""

    def test_clean_json_not_repaired(self):
        """Valid JSON on first pass → repaired=False."""
        router = _make_router(_valid_json())
        result, repaired = router._parse_json(_valid_json())
        assert isinstance(result, dict)
        assert repaired is False

    def test_trailing_comma_repaired(self):
        """JSON with trailing comma needs repair → repaired=True."""
        bad_json = '{"route": "calendar", "confidence": 0.9,}'
        router = _make_router("")
        result, repaired = router._parse_json(bad_json)
        assert isinstance(result, dict)
        assert repaired is True

    def test_markdown_wrapped_not_repaired(self):
        """Markdown-wrapped JSON extracted on first pass → repaired=False."""
        wrapped = f"```json\n{_valid_json()}\n```"
        router = _make_router("")
        result, repaired = router._parse_json(wrapped)
        assert isinstance(result, dict)
        # First pass should handle markdown extraction
        assert repaired is False

    def test_completely_invalid_raises(self):
        """Completely invalid text raises exception."""
        router = _make_router("")
        with pytest.raises(Exception):
            router._parse_json("no json here at all just text")


# ============================================================================
# _extract_output: Route/Intent validation
# ============================================================================

class TestExtractOutputValidation:
    """Test route and intent validation in _extract_output."""

    def _router(self):
        return _make_router("")

    def test_valid_route_preserved(self):
        router = self._router()
        for valid_route in VALID_ROUTES:
            parsed = {"route": valid_route, "calendar_intent": "none", "confidence": 0.9,
                       "tool_plan": [], "assistant_reply": "test", "slots": {}}
            result = router._extract_output(parsed, raw_text="", repaired=False)
            assert result.route == valid_route

    def test_invalid_route_becomes_unknown(self):
        router = self._router()
        parsed = {"route": "smaltalj", "calendar_intent": "none", "confidence": 0.9,
                   "tool_plan": [], "assistant_reply": "test", "slots": {}}
        result = router._extract_output(parsed, raw_text="", repaired=True)
        assert result.route == "unknown"

    def test_empty_route_becomes_unknown(self):
        router = self._router()
        parsed = {"route": "", "calendar_intent": "none", "confidence": 0.5,
                   "tool_plan": [], "assistant_reply": "test"}
        result = router._extract_output(parsed, raw_text="", repaired=False)
        assert result.route == "unknown"

    def test_valid_intents_preserved(self):
        router = self._router()
        for intent in ["create", "modify", "cancel", "query", "none", "list_events", "create_event"]:
            parsed = {"route": "calendar", "calendar_intent": intent, "confidence": 0.9,
                       "tool_plan": [], "assistant_reply": "test", "slots": {}}
            result = router._extract_output(parsed, raw_text="", repaired=False)
            # "none" intent on calendar route is inferred to "query" (default)
            expected = "query" if intent == "none" else intent
            assert result.calendar_intent == expected

    def test_invalid_intent_chars_becomes_none(self):
        router = self._router()
        parsed = {"route": "calendar", "calendar_intent": "creat@e!", "confidence": 0.9,
                   "tool_plan": [], "assistant_reply": "test"}
        result = router._extract_output(parsed, raw_text="", repaired=True)
        # Intent is sanitized to "none", then calendar route inference defaults to "query"
        assert result.calendar_intent == "query"


# ============================================================================
# _extract_output: Confidence penalty
# ============================================================================

class TestConfidencePenalty:
    """Test confidence penalty when JSON is repaired."""

    def _router(self):
        return _make_router("")

    def test_no_penalty_when_not_repaired(self):
        router = self._router()
        parsed = {"route": "calendar", "calendar_intent": "create", "confidence": 0.9,
                   "tool_plan": [], "assistant_reply": "test", "slots": {}}
        result = router._extract_output(parsed, raw_text="", repaired=False)
        assert result.confidence == pytest.approx(0.9)

    def test_penalty_applied_when_repaired(self):
        router = self._router()
        parsed = {"route": "calendar", "calendar_intent": "create", "confidence": 0.9,
                   "tool_plan": [], "assistant_reply": "test", "slots": {}}
        result = router._extract_output(parsed, raw_text="", repaired=True)
        expected = 0.9 * RepairTracker.CONFIDENCE_PENALTY
        assert result.confidence == pytest.approx(expected, abs=0.01)

    def test_penalty_clamps_to_0_1(self):
        router = self._router()
        parsed = {"route": "smalltalk", "calendar_intent": "none", "confidence": 1.5,
                   "tool_plan": [], "assistant_reply": "test"}
        result = router._extract_output(parsed, raw_text="", repaired=True)
        # 1.0 (clamped) * CONFIDENCE_PENALTY
        assert result.confidence <= 1.0
        assert result.confidence == pytest.approx(1.0 * RepairTracker.CONFIDENCE_PENALTY, abs=0.01)

    def test_zero_confidence_stays_zero(self):
        router = self._router()
        parsed = {"route": "unknown", "calendar_intent": "none", "confidence": 0.0,
                   "tool_plan": [], "assistant_reply": "test"}
        result = router._extract_output(parsed, raw_text="", repaired=True)
        assert result.confidence == 0.0

    @pytest.mark.parametrize("original,expected", [
        (1.0, 1.0 * 0.9),      # 0.9 > threshold → no boost
        (0.8, 0.8 * 0.9),      # 0.72 > threshold → no boost
        (0.5, 0.55),           # 0.45 < threshold → boosted to 0.55 (threshold+0.05)
        (0.3, 0.3 * 0.9),      # 0.27 < boost_floor(0.3) → no boost
    ])
    def test_penalty_matrix(self, original, expected):
        router = self._router()
        parsed = {"route": "calendar", "calendar_intent": "create", "confidence": original,
                   "tool_plan": [], "assistant_reply": "test", "slots": {}}
        result = router._extract_output(parsed, raw_text="", repaired=True)
        assert result.confidence == pytest.approx(expected, abs=0.01)


# ============================================================================
# Repair Events Published
# ============================================================================

class TestRepairEvents:
    """Test that repair events are published to the event bus."""

    def _router_with_event_bus(self, response=""):
        llm = MockLLM(response)
        bus = MagicMock()
        llm.event_bus = bus
        router = JarvisLLMOrchestrator(llm=llm)
        return router, bus

    def test_json_repaired_event(self):
        """When JSON is repaired, json_repaired event is published."""
        bad_json = '{"route": "calendar", "confidence": 0.9,}'
        router, bus = self._router_with_event_bus()
        result, repaired = router._parse_json(bad_json)
        assert repaired is True
        # Check event was published
        calls = [c for c in bus.publish.call_args_list if "json_repaired" in str(c)]
        assert len(calls) >= 1

    def test_confidence_penalized_event(self):
        """When confidence is penalized, confidence_penalized event is published."""
        router, bus = self._router_with_event_bus()
        parsed = {"route": "calendar", "calendar_intent": "create", "confidence": 0.9,
                   "tool_plan": [], "assistant_reply": "test", "slots": {}}
        router._extract_output(parsed, raw_text="", repaired=True)
        calls = [c for c in bus.publish.call_args_list if "confidence_penalized" in str(c)]
        assert len(calls) == 1

    def test_no_penalty_event_when_clean(self):
        """No confidence_penalized event when JSON was clean."""
        router, bus = self._router_with_event_bus()
        parsed = {"route": "calendar", "calendar_intent": "create", "confidence": 0.9,
                   "tool_plan": [], "assistant_reply": "test", "slots": {}}
        router._extract_output(parsed, raw_text="", repaired=False)
        calls = [c for c in bus.publish.call_args_list if "confidence_penalized" in str(c)]
        assert len(calls) == 0

    def test_route_corrected_event(self):
        """When invalid route is corrected, route becomes 'unknown'.

        Note: apply_orchestrator_defaults normalizes invalid routes to
        'unknown' before _extract_output's own check, so the
        route_corrected event is only published when the normalizer
        misses a route.  This test verifies the overall correction
        outcome instead of the event.
        """
        router, bus = self._router_with_event_bus()
        parsed = {"route": "smaltalj", "calendar_intent": "none", "confidence": 0.5,
                   "tool_plan": [], "assistant_reply": "test"}
        result = router._extract_output(parsed, raw_text="", repaired=True)
        assert result.route == "unknown"


# ============================================================================
# Integration: Full route() flow
# ============================================================================

class TestRouteIntegration:
    """Test the full route() flow with repair scenarios."""

    def test_clean_json_high_confidence(self):
        """Clean JSON → no penalty, confidence preserved."""
        response = _valid_json(confidence=0.95)
        router = _make_router(response)
        result = router.route(user_input="saat 5te toplantı yap")
        assert result.confidence == pytest.approx(0.95)
        assert result.route == "calendar"

    def test_clean_json_with_markdown(self):
        """Markdown-wrapped clean JSON → no penalty."""
        response = f"```json\n{_valid_json(confidence=0.85)}\n```"
        router = _make_router(response)
        result = router.route(user_input="toplantı yap")
        assert result.confidence == pytest.approx(0.85)

    def test_fallback_on_total_failure(self):
        """Completely invalid response → fallback output."""
        router = _make_router("no json here")
        result = router.route(user_input="test")
        assert result.route == "unknown"
        assert result.confidence == 0.0

    def test_repair_tracker_incremented(self):
        """route() increments the global repair tracker."""
        _repair_tracker.reset()
        response = _valid_json()
        router = _make_router(response)
        router.route(user_input="test")
        assert _repair_tracker.total_requests >= 1


# ============================================================================
# llm/json_repair.py: repair_route_enum expanded validation
# ============================================================================

class TestLLMJsonRepairRouteEnum:
    """Test that llm/json_repair.py accepts expanded valid routes."""

    def test_gmail_valid(self):
        from bantz.llm.json_repair import repair_route_enum
        assert repair_route_enum("gmail") == "gmail"

    def test_system_valid(self):
        from bantz.llm.json_repair import repair_route_enum
        assert repair_route_enum("system") == "system"

    def test_calendar_valid(self):
        from bantz.llm.json_repair import repair_route_enum
        assert repair_route_enum("calendar") == "calendar"

    def test_smalltalk_valid(self):
        from bantz.llm.json_repair import repair_route_enum
        assert repair_route_enum("smalltalk") == "smalltalk"

    def test_unknown_valid(self):
        from bantz.llm.json_repair import repair_route_enum
        assert repair_route_enum("unknown") == "unknown"

    def test_mapping_still_works(self):
        from bantz.llm.json_repair import repair_route_enum
        assert repair_route_enum("create_meeting") == "calendar"
        assert repair_route_enum("chat") == "smalltalk"

    def test_garbage_defaults_unknown(self):
        from bantz.llm.json_repair import repair_route_enum
        assert repair_route_enum("xyzabc") == "unknown"


# ============================================================================
# Edge cases
# ============================================================================

class TestEdgeCases:
    """Edge cases for repair validation."""

    def test_repaired_false_no_event_bus(self):
        """No event bus → no crash when repaired=True."""
        router = _make_router("")
        parsed = {"route": "calendar", "calendar_intent": "create", "confidence": 0.8,
                   "tool_plan": [], "assistant_reply": "test", "slots": {}}
        result = router._extract_output(parsed, raw_text="", repaired=True)
        assert result.confidence == pytest.approx(0.8 * RepairTracker.CONFIDENCE_PENALTY, abs=0.01)

    def test_repaired_true_with_turkish_time(self):
        """Repaired JSON + Turkish time → both fixes applied."""
        router = _make_router("")
        parsed = {"route": "calendar", "calendar_intent": "create", "confidence": 0.9,
                   "tool_plan": [], "assistant_reply": "test",
                   "slots": {"time": "05:00", "title": "toplantı"}}
        result = router._extract_output(parsed, raw_text="", user_input="saat beşte toplantı yap", repaired=True)
        # Confidence penalized
        assert result.confidence == pytest.approx(0.9 * RepairTracker.CONFIDENCE_PENALTY, abs=0.01)
        # Turkish time post-processing should have corrected 05:00 → 17:00
        assert result.slots.get("time") == "17:00"

    def test_missing_route_field(self):
        """Missing route field gets default from apply_orchestrator_defaults."""
        router = _make_router("")
        parsed = {"calendar_intent": "create", "confidence": 0.9,
                   "tool_plan": [], "assistant_reply": "test"}
        result = router._extract_output(parsed, raw_text="", repaired=False)
        # apply_orchestrator_defaults provides a default route (smalltalk or unknown)
        assert result.route in VALID_ROUTES

    def test_none_confidence(self):
        """None confidence defaults to 0.0."""
        router = _make_router("")
        parsed = {"route": "calendar", "calendar_intent": "create", "confidence": None,
                   "tool_plan": [], "assistant_reply": "test"}
        result = router._extract_output(parsed, raw_text="", repaired=True)
        assert result.confidence == 0.0
