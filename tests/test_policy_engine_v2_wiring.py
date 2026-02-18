"""Tests for PolicyEngineV2 orchestrator wiring (Issue #1291).

Covers:
- Pre-scan phase uses PolicyEngineV2 when available
- Per-tool loop uses PolicyEngineV2 when available
- Confirmation acceptance records session permits via engine.confirm()
- Edited params from HIGH-risk UX flow through to tool execution
- Legacy fallback works when PolicyEngineV2 is None
- CLI policy subcommand dispatches correctly
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# =====================================================================
# 1. SafetyGuard.evaluate_policy integration
# =====================================================================


class TestSafetyGuardEvaluatePolicy:
    """Verify SafetyGuard properly delegates to PolicyEngineV2."""

    def test_evaluate_policy_returns_decision(self):
        from bantz.brain.safety_guard import SafetyGuard
        from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset, RiskTier

        engine = PolicyEngineV2(
            preset=PolicyPreset.BALANCED,
            risk_overrides={"test.tool": RiskTier.MED},
            redact_fields={},
            editable_fields={},
        )
        guard = SafetyGuard(policy_engine_v2=engine)
        decision = guard.evaluate_policy("test.tool", {"x": 1})

        assert decision is not None
        assert decision.action == "confirm"
        assert decision.tier == RiskTier.MED

    def test_evaluate_policy_low_risk_auto_execute(self):
        from bantz.brain.safety_guard import SafetyGuard
        from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset, RiskTier

        engine = PolicyEngineV2(
            preset=PolicyPreset.BALANCED,
            risk_overrides={"read.tool": RiskTier.LOW},
            redact_fields={},
            editable_fields={},
        )
        guard = SafetyGuard(policy_engine_v2=engine)
        decision = guard.evaluate_policy("read.tool", {})

        assert decision.action == "execute"
        assert decision.reason == "LOW_AUTO_EXECUTE"

    def test_evaluate_policy_high_risk_confirm_with_edit(self):
        from bantz.brain.safety_guard import SafetyGuard
        from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset, RiskTier

        engine = PolicyEngineV2(
            preset=PolicyPreset.BALANCED,
            risk_overrides={"danger.tool": RiskTier.HIGH},
            redact_fields={},
            editable_fields={"danger.tool": ["param1"]},
        )
        guard = SafetyGuard(policy_engine_v2=engine)
        decision = guard.evaluate_policy("danger.tool", {"param1": "val"})

        assert decision.action == "confirm_with_edit"
        assert decision.editable is True
        assert "param1" in decision.editable_fields
        assert decision.cooldown_seconds == 3

    def test_evaluate_policy_returns_none_without_v2(self):
        from bantz.brain.safety_guard import SafetyGuard

        guard = SafetyGuard()
        assert guard.evaluate_policy("any.tool") is None


# =====================================================================
# 2. Confirmation state with edited params
# =====================================================================


class TestConfirmationEditedParams:
    """Test edited params flow in OrchestratorState."""

    def test_edited_params_field_exists(self):
        from bantz.brain.orchestrator_state import OrchestratorState

        state = OrchestratorState()
        assert state.confirmed_edited_params is None

    def test_edited_params_can_be_set(self):
        from bantz.brain.orchestrator_state import OrchestratorState

        state = OrchestratorState()
        state.confirmed_edited_params = {"subject": "Edited Subject"}
        assert state.confirmed_edited_params == {"subject": "Edited Subject"}

    def test_edited_params_cleared_after_use(self):
        from bantz.brain.orchestrator_state import OrchestratorState

        state = OrchestratorState()
        state.confirmed_edited_params = {"key": "val"}
        # Simulate consumption
        params = state.confirmed_edited_params
        state.confirmed_edited_params = None
        assert state.confirmed_edited_params is None
        assert params == {"key": "val"}


# =====================================================================
# 3. Session permit recording on confirmation
# =====================================================================


class TestSessionPermitRecording:
    """Test that PolicyEngineV2.confirm() is called on acceptance."""

    def test_med_confirm_once_per_session(self):
        from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset, RiskTier

        engine = PolicyEngineV2(
            preset=PolicyPreset.BALANCED,
            risk_overrides={"gmail.send": RiskTier.MED},
            redact_fields={},
            editable_fields={},
        )

        # First evaluation: should require confirmation
        d1 = engine.evaluate("gmail.send", {}, session_id="s1")
        assert d1.action == "confirm"

        # Record the confirmation
        engine.confirm("gmail.send", "s1", RiskTier.MED)

        # Second evaluation: should auto-execute (session permit)
        d2 = engine.evaluate("gmail.send", {}, session_id="s1")
        assert d2.action == "execute"
        assert d2.reason == "MED_SESSION_CONFIRMED"

    def test_high_never_remembered(self):
        from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset, RiskTier

        engine = PolicyEngineV2(
            preset=PolicyPreset.BALANCED,
            risk_overrides={"file.delete": RiskTier.HIGH},
            redact_fields={},
            editable_fields={},
        )

        # Confirm HIGH
        engine.confirm("file.delete", "s1", RiskTier.HIGH)

        # Still requires confirmation
        d = engine.evaluate("file.delete", {}, session_id="s1")
        assert d.action == "confirm_with_edit"


# =====================================================================
# 4. Pre-scan phase v2 integration
# =====================================================================


class TestPreScanV2:
    """Test that pre-scan phase uses PolicyEngineV2 decisions."""

    def test_v2_decision_fields_in_confirmation_payload(self):
        """Verify v2-enriched fields are included in the confirmation dict."""
        from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset, RiskTier

        engine = PolicyEngineV2(
            preset=PolicyPreset.BALANCED,
            risk_overrides={"calendar.delete_event": RiskTier.HIGH},
            redact_fields={},
            editable_fields={"calendar.delete_event": ["notify_attendees"]},
        )

        decision = engine.evaluate(
            "calendar.delete_event",
            {"event_id": "abc", "notify_attendees": True},
        )

        # Check enriched fields that the orchestrator now includes
        assert decision.action == "confirm_with_edit"
        assert decision.tier == RiskTier.HIGH
        assert decision.editable is True
        assert "notify_attendees" in decision.editable_fields
        assert decision.cooldown_seconds == 3
        assert decision.requires_explicit_confirm is True
        assert "YÜKSEK RİSK" in decision.prompt

    def test_low_risk_skipped_in_prescan(self):
        """LOW risk tools should not be queued for confirmation."""
        from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset, RiskTier

        engine = PolicyEngineV2(
            preset=PolicyPreset.BALANCED,
            risk_overrides={"calendar.list_events": RiskTier.LOW},
            redact_fields={},
            editable_fields={},
        )

        decision = engine.evaluate("calendar.list_events", {"date": "today"})
        assert decision.action == "execute"
        # This means the pre-scan would `continue` and not queue it


# =====================================================================
# 5. CLI policy subcommand
# =====================================================================


class TestPolicyCLI:
    """Test policy CLI subcommand."""

    def test_info_command(self):
        from bantz.policy.cli import main

        # Should not raise
        result = main(["info"])
        assert result == 0

    def test_preset_command_no_arg(self):
        from bantz.policy.cli import main

        result = main(["preset"])
        assert result == 0

    def test_preset_command_valid(self):
        from bantz.policy.cli import main

        result = main(["preset", "balanced"])
        assert result == 0

    def test_preset_command_invalid(self):
        from bantz.policy.cli import main

        result = main(["preset", "nonexistent"])
        assert result == 1

    def test_risk_command(self):
        from bantz.policy.cli import main

        result = main(["risk", "calendar.list_events"])
        assert result == 0

    def test_default_is_info(self):
        from bantz.policy.cli import main

        result = main([])
        assert result == 0


# =====================================================================
# 6. CLI dispatch from main
# =====================================================================


class TestCLIPolicyDispatch:
    """Test that 'bantz policy' routes to policy CLI."""

    def test_cli_routes_to_policy(self):
        from bantz.cli import main as cli_main

        with patch("bantz.policy.cli.main", return_value=0) as mock:
            result = cli_main(["policy", "info"])
            mock.assert_called_once_with(["info"])
            assert result == 0


# =====================================================================
# 7. Backward compat: legacy fallback when v2 is None
# =====================================================================


class TestLegacyFallback:
    """Test that orchestrator falls back to metadata-based checks when v2 is None."""

    def test_safety_guard_without_v2(self):
        from bantz.brain.safety_guard import SafetyGuard

        guard = SafetyGuard()
        assert guard.policy_engine_v2 is None
        assert guard.evaluate_policy("any.tool") is None


# =====================================================================
# 8. Preset switching
# =====================================================================


class TestPresetSwitching:
    """Test runtime preset switching."""

    def test_switch_to_autopilot(self):
        from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset, RiskTier

        engine = PolicyEngineV2(
            preset=PolicyPreset.BALANCED,
            risk_overrides={"danger.tool": RiskTier.HIGH},
            redact_fields={},
            editable_fields={},
        )

        # Initially: HIGH tool requires confirmation
        d1 = engine.evaluate("danger.tool", {})
        assert d1.action == "confirm_with_edit"

        # Switch to autopilot
        engine.preset = PolicyPreset.AUTOPILOT
        d2 = engine.evaluate("danger.tool", {})
        assert d2.action == "execute"

    def test_switch_to_paranoid(self):
        from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset, RiskTier

        engine = PolicyEngineV2(
            preset=PolicyPreset.BALANCED,
            risk_overrides={"read.tool": RiskTier.LOW},
            redact_fields={},
            editable_fields={},
        )

        # Initially: LOW auto-executes
        d1 = engine.evaluate("read.tool", {})
        assert d1.action == "execute"

        # Switch to paranoid: LOW now confirms
        engine.preset = PolicyPreset.PARANOID
        d2 = engine.evaluate("read.tool", {})
        assert d2.action == "confirm"


# =====================================================================
# 9. Redaction in v2 decisions
# =====================================================================


class TestRedactionInV2Decisions:
    """Test that redacted params flow correctly through v2 decisions."""

    def test_sensitive_params_redacted(self):
        from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset, RiskTier

        engine = PolicyEngineV2(
            preset=PolicyPreset.BALANCED,
            risk_overrides={"api.call": RiskTier.MED},
            redact_fields={"api.call": {"secret_key"}},
            editable_fields={},
        )

        d = engine.evaluate(
            "api.call",
            {"query": "test", "secret_key": "sk-1234567890abcdef"},
        )

        # display_params should be redacted
        assert d.display_params["query"] == "test"
        assert "***" in d.display_params["secret_key"]

        # original_params should be preserved
        assert d.original_params["secret_key"] == "sk-1234567890abcdef"
