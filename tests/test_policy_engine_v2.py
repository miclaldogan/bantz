"""
Tests for Policy Engine v2 — Risk Tiers + Presets + Redaction (Issue #1291).

Covers:
- RiskTier enum & PolicyPreset enum
- PolicyDecision dataclass
- redact_value / redact_sensitive
- PolicyEngineV2: get_risk_tier, evaluate, confirm, deny
- All 3 presets: balanced, paranoid, autopilot
- MED confirm-once-per-session
- HIGH confirm_with_edit + cooldown + editable fields
- Per-tool redact_fields config
- Backward compat bridges (ToolRisk ↔ RiskTier)
- SafetyGuard.evaluate_policy integration
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────


@pytest.fixture
def balanced_engine():
    """PolicyEngineV2 with balanced preset and inline config (no filesystem)."""
    from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset, RiskTier

    return PolicyEngineV2(
        preset=PolicyPreset.BALANCED,
        risk_overrides={
            "calendar.list_events": RiskTier.LOW,
            "calendar.create_event": RiskTier.MED,
            "calendar.delete_event": RiskTier.HIGH,
            "gmail.send": RiskTier.MED,
            "gmail.read": RiskTier.LOW,
            "system.execute_command": RiskTier.HIGH,
            "file.delete": RiskTier.HIGH,
            "web.search": RiskTier.LOW,
        },
        redact_fields={
            "gmail.send": {"password", "token"},
            "system.execute_command": {"env_vars"},
        },
        editable_fields={
            "calendar.delete_event": ["notify_attendees"],
            "gmail.send": ["subject", "body", "to"],
        },
    )


@pytest.fixture
def paranoid_engine():
    """PolicyEngineV2 with paranoid preset."""
    from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset, RiskTier

    return PolicyEngineV2(
        preset=PolicyPreset.PARANOID,
        risk_overrides={
            "calendar.list_events": RiskTier.LOW,
            "calendar.create_event": RiskTier.MED,
            "calendar.delete_event": RiskTier.HIGH,
            "web.search": RiskTier.LOW,
        },
        redact_fields={},
        editable_fields={},
    )


@pytest.fixture
def autopilot_engine():
    from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset, RiskTier

    return PolicyEngineV2(
        preset=PolicyPreset.AUTOPILOT,
        risk_overrides={
            "calendar.delete_event": RiskTier.HIGH,
        },
        redact_fields={},
        editable_fields={},
    )


# =====================================================================
# 1. Enum & Dataclass Tests
# =====================================================================


class TestRiskTier:
    def test_values(self):
        from bantz.policy.engine_v2 import RiskTier

        assert RiskTier.LOW.value == "LOW"
        assert RiskTier.MED.value == "MED"
        assert RiskTier.HIGH.value == "HIGH"

    def test_is_string(self):
        from bantz.policy.engine_v2 import RiskTier

        assert isinstance(RiskTier.LOW, str)
        assert RiskTier.HIGH == "HIGH"


class TestPolicyPreset:
    def test_values(self):
        from bantz.policy.engine_v2 import PolicyPreset

        assert PolicyPreset.PARANOID.value == "paranoid"
        assert PolicyPreset.BALANCED.value == "balanced"
        assert PolicyPreset.AUTOPILOT.value == "autopilot"


class TestPolicyDecision:
    def test_to_dict(self):
        from bantz.policy.engine_v2 import PolicyDecision, RiskTier

        d = PolicyDecision(
            action="confirm",
            tier=RiskTier.MED,
            prompt="Test?",
            display_params={"a": 1},
            reason="MED_REQUIRE_CONFIRMATION",
        )
        out = d.to_dict()
        assert out["action"] == "confirm"
        assert out["tier"] == "MED"
        assert out["prompt"] == "Test?"

    def test_defaults(self):
        from bantz.policy.engine_v2 import PolicyDecision, RiskTier

        d = PolicyDecision(action="execute", tier=RiskTier.LOW)
        assert d.editable is False
        assert d.cooldown_seconds == 0
        assert d.display_params == {}


# =====================================================================
# 2. Redaction Tests
# =====================================================================


class TestRedactValue:
    def test_short_string(self):
        from bantz.policy.engine_v2 import redact_value

        assert redact_value("abc") == "***"
        assert redact_value("123456") == "***"

    def test_long_string(self):
        from bantz.policy.engine_v2 import redact_value

        assert redact_value("sk-abc123xyz") == "sk-***xyz"
        assert redact_value("1234567") == "123***567"


class TestRedactSensitive:
    def test_global_keys_always_redacted(self):
        from bantz.policy.engine_v2 import redact_sensitive

        params = {
            "password": "secret123",
            "api_key": "sk-abc123def456",
            "name": "Test",
        }
        result = redact_sensitive(params)
        assert "***" in result["password"]  # 9 chars → "sec***123"
        assert "***" in result["api_key"]
        assert result["name"] == "Test"  # Not redacted

    def test_extra_fields(self):
        from bantz.policy.engine_v2 import redact_sensitive

        params = {"custom_field": "sensitive_data_here", "normal": "ok"}
        result = redact_sensitive(params, extra_fields={"custom_field"})
        assert "***" in result["custom_field"]
        assert result["normal"] == "ok"

    def test_nested_dict_redacted(self):
        from bantz.policy.engine_v2 import redact_sensitive

        params = {"headers": {"authorization": "Bearer xyz123abc"}}
        result = redact_sensitive(params)
        assert "***" in result["headers"]["authorization"]

    def test_non_string_sensitive_value(self):
        from bantz.policy.engine_v2 import redact_sensitive

        params = {"token": 12345}
        result = redact_sensitive(params)
        assert result["token"] == "***"


# =====================================================================
# 3. Balanced Preset Tests
# =====================================================================


class TestBalancedPreset:
    def test_low_risk_auto_execute(self, balanced_engine):
        d = balanced_engine.evaluate("calendar.list_events", {"date": "tomorrow"})
        assert d.action == "execute"
        assert d.tier.value == "LOW"
        assert d.reason == "LOW_AUTO_EXECUTE"

    def test_med_risk_requires_confirmation(self, balanced_engine):
        d = balanced_engine.evaluate(
            "calendar.create_event",
            {"title": "Standup", "date": "2025-02-01"},
        )
        assert d.action == "confirm"
        assert d.tier.value == "MED"
        assert "MED" in d.reason
        assert d.editable is False

    def test_med_risk_confirm_once_per_session(self, balanced_engine):
        """After confirming once, MED tools auto-execute in same session."""
        from bantz.policy.engine_v2 import RiskTier

        d1 = balanced_engine.evaluate(
            "calendar.create_event", {}, session_id="s1"
        )
        assert d1.action == "confirm"

        # Simulate confirmation
        balanced_engine.confirm(
            "calendar.create_event", "s1", RiskTier.MED
        )

        d2 = balanced_engine.evaluate(
            "calendar.create_event", {}, session_id="s1"
        )
        assert d2.action == "execute"
        assert d2.reason == "MED_SESSION_CONFIRMED"

    def test_med_confirm_not_shared_across_sessions(self, balanced_engine):
        from bantz.policy.engine_v2 import RiskTier

        balanced_engine.confirm("calendar.create_event", "s1", RiskTier.MED)

        # Different session should still require confirmation
        d = balanced_engine.evaluate(
            "calendar.create_event", {}, session_id="s2"
        )
        assert d.action == "confirm"

    def test_high_risk_confirm_with_edit(self, balanced_engine):
        d = balanced_engine.evaluate(
            "calendar.delete_event",
            {"event_id": "abc123", "notify_attendees": True},
        )
        assert d.action == "confirm_with_edit"
        assert d.tier.value == "HIGH"
        assert d.requires_explicit_confirm is True
        assert d.cooldown_seconds == 3
        assert d.editable_fields == ["notify_attendees"]
        assert d.editable is True

    def test_high_risk_never_remembered(self, balanced_engine):
        """HIGH risk tools always require fresh confirmation."""
        from bantz.policy.engine_v2 import RiskTier

        balanced_engine.confirm(
            "calendar.delete_event", "s1", RiskTier.HIGH
        )

        d = balanced_engine.evaluate(
            "calendar.delete_event", {}, session_id="s1"
        )
        # Still requires confirmation — HIGH is never remembered
        assert d.action == "confirm_with_edit"

    def test_unknown_tool_defaults_to_med(self, balanced_engine):
        """Tools not in risk map default to MED."""
        d = balanced_engine.evaluate("unknown.tool", {"x": 1})
        assert d.tier.value == "MED"
        assert d.action == "confirm"


# =====================================================================
# 4. Paranoid Preset Tests
# =====================================================================


class TestParanoidPreset:
    def test_low_risk_still_confirms(self, paranoid_engine):
        d = paranoid_engine.evaluate("calendar.list_events", {"date": "today"})
        assert d.action == "confirm"
        assert d.reason == "PARANOID_CONFIRM"

    def test_med_risk_confirms(self, paranoid_engine):
        d = paranoid_engine.evaluate("calendar.create_event", {"title": "test"})
        assert d.action == "confirm"

    def test_high_risk_confirm_with_edit(self, paranoid_engine):
        d = paranoid_engine.evaluate("calendar.delete_event", {})
        assert d.action == "confirm_with_edit"

    def test_web_search_also_confirms(self, paranoid_engine):
        d = paranoid_engine.evaluate("web.search", {"query": "test"})
        assert d.action == "confirm"


# =====================================================================
# 5. Autopilot Preset Tests
# =====================================================================


class TestAutopilotPreset:
    def test_low_auto_execute(self, autopilot_engine):
        d = autopilot_engine.evaluate("web.search", {})
        assert d.action == "execute"
        assert d.reason == "AUTOPILOT_ALLOW"

    def test_high_also_auto_execute(self, autopilot_engine):
        d = autopilot_engine.evaluate("calendar.delete_event", {"id": "x"})
        assert d.action == "execute"
        assert d.reason == "AUTOPILOT_ALLOW"


# =====================================================================
# 6. Redaction in Decisions
# =====================================================================


class TestRedactionInDecisions:
    def test_sensitive_params_redacted_in_display(self, balanced_engine):
        d = balanced_engine.evaluate(
            "gmail.send",
            {"to": "ali@test.com", "password": "gizli123", "token": "tk-abc123def"},
        )
        assert d.display_params["to"] == "ali@test.com"  # Not sensitive
        assert "***" in d.display_params["password"]
        assert "***" in d.display_params["token"]
        # Original params preserved
        assert d.original_params["password"] == "gizli123"

    def test_system_command_env_redacted(self, balanced_engine):
        d = balanced_engine.evaluate(
            "system.execute_command",
            {"command": "ls", "env_vars": "SECRET=abc"},
        )
        assert "***" in d.display_params["env_vars"]

    def test_non_sensitive_params_preserved(self, balanced_engine):
        d = balanced_engine.evaluate(
            "calendar.create_event",
            {"title": "Meeting", "date": "2025-01-15"},
        )
        assert d.display_params["title"] == "Meeting"


# =====================================================================
# 7. Prompt Generation
# =====================================================================


class TestPromptGeneration:
    def test_high_risk_prompt_format(self, balanced_engine):
        d = balanced_engine.evaluate(
            "calendar.delete_event",
            {"event_id": "abc", "notify_attendees": True},
        )
        assert "YÜKSEK RİSK" in d.prompt
        assert "calendar.delete_event" in d.prompt
        assert "event_id" in d.prompt

    def test_med_risk_prompt_format(self, balanced_engine):
        d = balanced_engine.evaluate(
            "calendar.create_event",
            {"title": "Standup"},
        )
        assert "calendar.create_event" in d.prompt
        assert "evet/hayır" in d.prompt


# =====================================================================
# 8. Preset Override & Runtime Switch
# =====================================================================


class TestPresetSwitching:
    def test_runtime_preset_change(self, balanced_engine):
        from bantz.policy.engine_v2 import PolicyPreset

        # Start balanced → LOW auto-executes
        d1 = balanced_engine.evaluate("web.search", {})
        assert d1.action == "execute"

        # Switch to paranoid → LOW now confirms
        balanced_engine.preset = PolicyPreset.PARANOID
        d2 = balanced_engine.evaluate("web.search", {})
        assert d2.action == "confirm"

        # Switch to autopilot → everything executes
        balanced_engine.preset = PolicyPreset.AUTOPILOT
        d3 = balanced_engine.evaluate("calendar.delete_event", {})
        assert d3.action == "execute"

    def test_per_call_preset_override(self, balanced_engine):
        from bantz.policy.engine_v2 import PolicyPreset

        # Engine is balanced, but override to autopilot for this call
        d = balanced_engine.evaluate(
            "calendar.delete_event",
            {"id": "x"},
            preset=PolicyPreset.AUTOPILOT,
        )
        assert d.action == "execute"

        # Next call without override is still balanced
        d2 = balanced_engine.evaluate("calendar.delete_event", {"id": "x"})
        assert d2.action == "confirm_with_edit"

    def test_env_var_preset(self, tmp_path):
        """BANTZ_POLICY_PRESET env var sets default preset."""
        from bantz.policy.engine_v2 import PolicyEngineV2, RiskTier

        with patch.dict(os.environ, {"BANTZ_POLICY_PRESET": "autopilot"}):
            engine = PolicyEngineV2(
                risk_overrides={"test.tool": RiskTier.HIGH},
                redact_fields={},
                editable_fields={},
            )
            d = engine.evaluate("test.tool", {})
            assert d.action == "execute"


# =====================================================================
# 9. Session Management
# =====================================================================


class TestSessionManagement:
    def test_clear_session_revokes_permits(self, balanced_engine):
        from bantz.policy.engine_v2 import RiskTier

        balanced_engine.confirm("gmail.send", "s1", RiskTier.MED)
        d1 = balanced_engine.evaluate("gmail.send", {}, session_id="s1")
        assert d1.action == "execute"

        balanced_engine.clear_session("s1")
        d2 = balanced_engine.evaluate("gmail.send", {}, session_id="s1")
        assert d2.action == "confirm"


# =====================================================================
# 10. Backward Compat Bridges
# =====================================================================


class TestBackwardCompat:
    def test_tier_from_tool_risk(self):
        from bantz.policy.engine_v2 import PolicyEngineV2, RiskTier

        assert PolicyEngineV2.tier_from_tool_risk("safe") == RiskTier.LOW
        assert PolicyEngineV2.tier_from_tool_risk("moderate") == RiskTier.MED
        assert PolicyEngineV2.tier_from_tool_risk("destructive") == RiskTier.HIGH
        assert PolicyEngineV2.tier_from_tool_risk("unknown") == RiskTier.MED

    def test_tier_to_tool_risk_value(self):
        from bantz.policy.engine_v2 import PolicyEngineV2, RiskTier

        assert PolicyEngineV2.tier_to_tool_risk_value(RiskTier.LOW) == "safe"
        assert PolicyEngineV2.tier_to_tool_risk_value(RiskTier.MED) == "moderate"
        assert PolicyEngineV2.tier_to_tool_risk_value(RiskTier.HIGH) == "destructive"

    def test_tier_to_risk_level(self):
        from bantz.policy.engine_v2 import PolicyEngineV2, RiskTier

        assert PolicyEngineV2.tier_to_risk_level(RiskTier.LOW) == "LOW"
        assert PolicyEngineV2.tier_to_risk_level(RiskTier.MED) == "MED"


# =====================================================================
# 11. SafetyGuard Integration
# =====================================================================


class TestSafetyGuardIntegration:
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

    def test_evaluate_policy_returns_none_when_no_v2(self):
        from bantz.brain.safety_guard import SafetyGuard

        guard = SafetyGuard()
        assert guard.evaluate_policy("any.tool") is None

    def test_evaluate_policy_handles_exception(self):
        from unittest.mock import Mock
        from bantz.brain.safety_guard import SafetyGuard

        broken_engine = Mock()
        broken_engine.evaluate.side_effect = RuntimeError("boom")
        guard = SafetyGuard(policy_engine_v2=broken_engine)
        result = guard.evaluate_policy("any.tool")
        assert result is None  # Graceful degradation


# =====================================================================
# 12. to_dict / Serialisation
# =====================================================================


class TestSerialisation:
    def test_engine_to_dict(self, balanced_engine):
        d = balanced_engine.to_dict()
        assert d["preset"] == "balanced"
        assert d["risk_map_size"] >= 8  # 8 overrides + policy.json entries
        assert d["redact_fields_count"] == 2
        assert d["editable_fields_count"] == 2


# =====================================================================
# 13. Editable Fields
# =====================================================================


class TestEditableFields:
    def test_high_tool_with_editable_fields(self, balanced_engine):
        d = balanced_engine.evaluate(
            "gmail.send",
            {"to": "ali@test.com", "subject": "Hi", "body": "Hello"},
            session_id="s1",
        )
        # gmail.send is MED in our override, so confirm (not confirm_with_edit)
        assert d.action == "confirm"

    def test_high_tool_has_editable_fields(self, balanced_engine):
        d = balanced_engine.evaluate(
            "calendar.delete_event",
            {"event_id": "x", "notify_attendees": True},
        )
        assert d.editable is True
        assert "notify_attendees" in d.editable_fields

    def test_high_tool_without_editable_config(self):
        from bantz.policy.engine_v2 import PolicyEngineV2, PolicyPreset, RiskTier

        engine = PolicyEngineV2(
            preset=PolicyPreset.BALANCED,
            risk_overrides={"file.delete": RiskTier.HIGH},
            redact_fields={},
            editable_fields={},  # No editable config for file.delete
        )
        d = engine.evaluate("file.delete", {"path": "/tmp/x"})
        assert d.action == "confirm_with_edit"
        assert d.editable is False
        assert d.editable_fields == []


# =====================================================================
# 14. Config Loading (YAML)
# =====================================================================


class TestConfigLoading:
    def test_load_redact_fields_from_yaml(self, tmp_path):
        yaml_content = """
redact_fields:
  gmail.send:
    - password
    - token
  system.execute_command:
    - env_vars
"""
        yaml_file = tmp_path / "perms.yaml"
        yaml_file.write_text(yaml_content)

        from bantz.policy.engine_v2 import _load_redact_fields

        fields = _load_redact_fields(yaml_file)
        assert "password" in fields["gmail.send"]
        assert "token" in fields["gmail.send"]
        assert "env_vars" in fields["system.execute_command"]

    def test_load_editable_fields_from_yaml(self, tmp_path):
        yaml_content = """
editable_fields:
  calendar.delete_event:
    - notify_attendees
  gmail.send:
    - subject
    - body
"""
        yaml_file = tmp_path / "perms.yaml"
        yaml_file.write_text(yaml_content)

        from bantz.policy.engine_v2 import _load_editable_fields

        fields = _load_editable_fields(yaml_file)
        assert fields["calendar.delete_event"] == ["notify_attendees"]
        assert fields["gmail.send"] == ["subject", "body"]

    def test_load_risk_map_from_policy_json(self, tmp_path):
        policy = {
            "tool_levels": {
                "calendar.list_events": "safe",
                "calendar.delete_event": "destructive",
                "gmail.send": "moderate",
            }
        }
        json_file = tmp_path / "policy.json"
        json_file.write_text(json.dumps(policy))

        from bantz.policy.engine_v2 import _load_risk_map_from_policy_json, RiskTier

        risk_map = _load_risk_map_from_policy_json(json_file)
        assert risk_map["calendar.list_events"] == RiskTier.LOW
        assert risk_map["calendar.delete_event"] == RiskTier.HIGH
        assert risk_map["gmail.send"] == RiskTier.MED

    def test_missing_policy_json_returns_empty(self, tmp_path):
        from bantz.policy.engine_v2 import _load_risk_map_from_policy_json

        result = _load_risk_map_from_policy_json(tmp_path / "nonexistent.json")
        assert result == {}


# =====================================================================
# 15. Package Exports
# =====================================================================


class TestPackageExports:
    def test_policy_package_exports_v2(self):
        from bantz.policy import (
            PolicyDecision,
            PolicyEngineV2,
            PolicyPreset,
            RiskTier,
            redact_sensitive,
            redact_value,
        )

        assert PolicyDecision is not None
        assert PolicyEngineV2 is not None
        assert PolicyPreset is not None
        assert RiskTier is not None

    def test_policy_package_still_exports_v1(self):
        from bantz.policy import Decision, PolicyEngine

        assert Decision is not None
        assert PolicyEngine is not None
