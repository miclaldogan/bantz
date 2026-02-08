"""Tests for issue #452 — Permission Engine v0."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from bantz.policy.dsl import (
    PermissionDecision,
    PermissionRule,
    load_policy,
    load_policy_str,
    match_rule,
)
from bantz.policy.permission_engine import PermissionEngine


# ── TestPermissionDecision ────────────────────────────────────────────

class TestPermissionDecision:
    def test_enum_values(self):
        assert PermissionDecision.ALLOW.value == "allow"
        assert PermissionDecision.CONFIRM.value == "confirm"
        assert PermissionDecision.DENY.value == "deny"


# ── TestPermissionRule ────────────────────────────────────────────────

class TestPermissionRule:
    def test_string_decision_coercion(self):
        rule = PermissionRule(decision="allow")
        assert rule.decision == PermissionDecision.ALLOW

    def test_default_fields(self):
        rule = PermissionRule()
        assert rule.tool == "*"
        assert rule.action == "*"
        assert rule.risk == "medium"
        assert rule.conditions == {}


# ── TestMatchRule ─────────────────────────────────────────────────────

class TestMatchRule:
    def test_exact_match(self):
        rule = PermissionRule(tool="calendar.create_event", action="write")
        assert match_rule(rule, "calendar.create_event", "write")

    def test_wildcard_tool(self):
        rule = PermissionRule(tool="calendar.*", action="read")
        assert match_rule(rule, "calendar.list_events", "read")
        assert match_rule(rule, "calendar.get_event", "read")
        assert not match_rule(rule, "gmail.read", "read")

    def test_wildcard_action(self):
        rule = PermissionRule(tool="gmail.send", action="*")
        assert match_rule(rule, "gmail.send", "write")
        assert match_rule(rule, "gmail.send", "read")

    def test_star_star(self):
        rule = PermissionRule(tool="*", action="*")
        assert match_rule(rule, "anything", "everything")

    def test_no_match(self):
        rule = PermissionRule(tool="calendar.create_event", action="write")
        assert not match_rule(rule, "gmail.send", "write")


# ── TestDSLLoader ─────────────────────────────────────────────────────

class TestDSLLoader:
    def test_load_json_string(self):
        policy = json.dumps({
            "permissions": [
                {"tool": "x.y", "action": "read", "risk": "low", "decision": "allow"},
            ]
        })
        rules = load_policy_str(policy)
        assert len(rules) == 1
        assert rules[0].decision == PermissionDecision.ALLOW

    def test_load_yaml_string(self):
        yaml_str = """\
permissions:
  - tool: "gmail.send"
    action: "write"
    risk: "high"
    decision: "confirm"
"""
        rules = load_policy_str(yaml_str)
        assert len(rules) == 1
        assert rules[0].tool == "gmail.send"

    def test_load_policy_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"permissions": [
                {"tool": "a", "action": "b", "risk": "low", "decision": "allow"}
            ]}, f)
            f.flush()
            rules = load_policy(f.name)
        assert len(rules) == 1

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            load_policy_str("this is not valid json or yaml @@@{{{")

    def test_load_real_config(self):
        config_path = Path(__file__).resolve().parents[1] / "config" / "permissions.yaml"
        if config_path.exists():
            rules = load_policy(str(config_path))
            assert len(rules) >= 5


# ── TestPermissionEngine — Default Rules ──────────────────────────────

class TestPermissionEngineDefaults:
    def setup_method(self):
        self.engine = PermissionEngine()

    def test_calendar_read_allow(self):
        assert self.engine.evaluate("calendar.list_events", "read") == PermissionDecision.ALLOW

    def test_gmail_read_allow(self):
        assert self.engine.evaluate("gmail.read", "read") == PermissionDecision.ALLOW

    def test_calendar_create_confirm(self):
        assert self.engine.evaluate("calendar.create_event", "write") == PermissionDecision.CONFIRM

    def test_gmail_send_confirm(self):
        assert self.engine.evaluate("gmail.send", "write") == PermissionDecision.CONFIRM

    def test_system_execute_deny(self):
        assert self.engine.evaluate("system.execute_command", "execute") == PermissionDecision.DENY

    def test_system_wildcard_deny(self):
        assert self.engine.evaluate("system.run_shell", "execute") == PermissionDecision.DENY

    def test_unknown_tool_confirm(self):
        assert self.engine.evaluate("totally_new_tool", "write") == PermissionDecision.CONFIRM

    def test_file_write_confirm(self):
        assert self.engine.evaluate("file.save", "write") == PermissionDecision.CONFIRM


# ── TestPermissionEngine — Risk Levels ────────────────────────────────

class TestRiskLevels:
    def setup_method(self):
        self.engine = PermissionEngine()

    def test_calendar_read_low(self):
        assert self.engine.get_risk("calendar.list_events") == "low"

    def test_system_critical(self):
        assert self.engine.get_risk("system.execute_command") == "critical"

    def test_unknown_medium(self):
        # Catch-all rule has "medium"
        assert self.engine.get_risk("foo.bar") == "medium"


# ── TestPermissionEngine — Custom Policy Override ─────────────────────

class TestPolicyOverride:
    def test_custom_rule_takes_priority(self):
        engine = PermissionEngine()
        engine.load_policy_str("""\
permissions:
  - tool: "system.execute_command"
    action: "execute"
    risk: "low"
    decision: "allow"
""")
        # Custom rule overrides built-in DENY
        assert engine.evaluate("system.execute_command", "execute") == PermissionDecision.ALLOW

    def test_custom_deny_overrides_default_confirm(self):
        engine = PermissionEngine()
        engine.load_policy_str("""\
permissions:
  - tool: "gmail.send"
    action: "write"
    risk: "critical"
    decision: "deny"
""")
        assert engine.evaluate("gmail.send", "write") == PermissionDecision.DENY


# ── TestRateLimiting ──────────────────────────────────────────────────

class TestRateLimiting:
    def test_max_per_session_exceeded(self):
        engine = PermissionEngine(rules=[
            PermissionRule(
                tool="api.call",
                action="write",
                risk="medium",
                decision=PermissionDecision.ALLOW,
                conditions={"max_per_session": 3},
            ),
        ])
        assert engine.evaluate("api.call", "write") == PermissionDecision.ALLOW
        assert engine.evaluate("api.call", "write") == PermissionDecision.ALLOW
        assert engine.evaluate("api.call", "write") == PermissionDecision.ALLOW
        # 4th call should DENY
        assert engine.evaluate("api.call", "write") == PermissionDecision.DENY

    def test_max_per_day_exceeded(self):
        engine = PermissionEngine(rules=[
            PermissionRule(
                tool="api.call",
                action="write",
                risk="medium",
                decision=PermissionDecision.ALLOW,
                conditions={"max_per_day": 2},
            ),
        ])
        assert engine.evaluate("api.call", "write") == PermissionDecision.ALLOW
        assert engine.evaluate("api.call", "write") == PermissionDecision.ALLOW
        assert engine.evaluate("api.call", "write") == PermissionDecision.DENY

    def test_reset_session_clears_counter(self):
        engine = PermissionEngine(rules=[
            PermissionRule(
                tool="api.call",
                action="write",
                risk="medium",
                decision=PermissionDecision.ALLOW,
                conditions={"max_per_session": 1},
            ),
        ])
        assert engine.evaluate("api.call", "write") == PermissionDecision.ALLOW
        assert engine.evaluate("api.call", "write") == PermissionDecision.DENY
        engine.reset_session()
        assert engine.evaluate("api.call", "write") == PermissionDecision.ALLOW

    def test_different_tools_independent_counters(self):
        engine = PermissionEngine(rules=[
            PermissionRule(
                tool="a", action="write", decision=PermissionDecision.ALLOW,
                conditions={"max_per_session": 1},
            ),
            PermissionRule(
                tool="b", action="write", decision=PermissionDecision.ALLOW,
                conditions={"max_per_session": 1},
            ),
        ])
        assert engine.evaluate("a", "write") == PermissionDecision.ALLOW
        assert engine.evaluate("b", "write") == PermissionDecision.ALLOW
        assert engine.evaluate("a", "write") == PermissionDecision.DENY
        assert engine.evaluate("b", "write") == PermissionDecision.DENY


# ── TestWildcardEdgeCases ─────────────────────────────────────────────

class TestWildcardEdgeCases:
    def test_question_mark_wildcard(self):
        rule = PermissionRule(tool="calendar.?et_event", action="read")
        assert match_rule(rule, "calendar.get_event", "read")
        assert not match_rule(rule, "calendar.list_event", "read")

    def test_nested_wildcard(self):
        rule = PermissionRule(tool="google.*.read", action="*")
        assert match_rule(rule, "google.drive.read", "read")
