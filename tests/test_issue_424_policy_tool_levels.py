"""Tests for Issue #424 – Policy Gmail/Calendar tool definitions.

Validates that:
1. policy.json is the single source of truth for tool risk levels
2. All gmail/calendar tools are defined in policy.json
3. metadata.py loads tool_levels from policy.json
4. Undefined tools get explicit deny (DESTRUCTIVE) by default
5. ALWAYS_CONFIRM_TOOLS is loaded from policy.json
6. reload_policy() refreshes module globals
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "policy.json"


def _load_policy() -> dict[str, Any]:
    """Load the real policy.json."""
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


# ===================================================================
# 1. policy.json structure tests
# ===================================================================


class TestPolicyJsonStructure:
    """Verify the policy.json file has all required sections."""

    def test_tool_levels_section_exists(self):
        policy = _load_policy()
        assert "tool_levels" in policy
        assert isinstance(policy["tool_levels"], dict)

    def test_always_confirm_tools_section_exists(self):
        policy = _load_policy()
        assert "always_confirm_tools" in policy
        assert isinstance(policy["always_confirm_tools"], list)

    def test_undefined_tool_policy_exists(self):
        policy = _load_policy()
        assert "undefined_tool_policy" in policy
        assert policy["undefined_tool_policy"] in ("deny", "moderate")

    def test_tool_levels_has_valid_risk_values(self):
        policy = _load_policy()
        valid_risks = {"safe", "moderate", "destructive"}
        for tool_name, risk in policy["tool_levels"].items():
            if tool_name == "__comment":
                continue
            assert risk in valid_risks, f"{tool_name} has invalid risk '{risk}'"


# ===================================================================
# 2. Gmail tools in policy.json
# ===================================================================


class TestGmailToolsInPolicy:
    """Issue #424: All gmail tools must be defined in policy.json."""

    REQUIRED_GMAIL_TOOLS = [
        "gmail.send",
        "gmail.create_draft",
        "gmail.send_draft",
        "gmail.list_messages",
        "gmail.get_message",
        "gmail.unread_count",
        "gmail.smart_search",
        "gmail.send_to_contact",
        "gmail.download_attachment",
        "gmail.generate_reply",
        "gmail.archive",
        "gmail.batch_modify",
        "gmail.list_labels",
        "gmail.add_label",
        "gmail.remove_label",
        "gmail.mark_read",
        "gmail.mark_unread",
        "gmail.list_drafts",
        "gmail.update_draft",
        "gmail.delete_draft",
    ]

    def test_all_gmail_tools_present(self):
        policy = _load_policy()
        tool_levels = policy["tool_levels"]
        for tool in self.REQUIRED_GMAIL_TOOLS:
            assert tool in tool_levels, f"Missing gmail tool in policy.json: {tool}"

    def test_gmail_send_is_moderate(self):
        policy = _load_policy()
        assert policy["tool_levels"]["gmail.send"] == "moderate"

    def test_gmail_create_draft_is_safe(self):
        policy = _load_policy()
        assert policy["tool_levels"]["gmail.create_draft"] == "safe"

    def test_gmail_send_draft_is_moderate(self):
        policy = _load_policy()
        assert policy["tool_levels"]["gmail.send_draft"] == "moderate"

    def test_gmail_list_messages_is_safe(self):
        policy = _load_policy()
        assert policy["tool_levels"]["gmail.list_messages"] == "safe"


# ===================================================================
# 3. Calendar tools in policy.json
# ===================================================================


class TestCalendarToolsInPolicy:
    """Issue #424: All calendar tools must be defined in policy.json."""

    REQUIRED_CALENDAR_TOOLS = [
        "calendar.list_events",
        "calendar.find_event",
        "calendar.get_event",
        "calendar.create_event",
        "calendar.update_event",
        "calendar.delete_event",
    ]

    def test_all_calendar_tools_present(self):
        policy = _load_policy()
        tool_levels = policy["tool_levels"]
        for tool in self.REQUIRED_CALENDAR_TOOLS:
            assert tool in tool_levels, f"Missing calendar tool in policy.json: {tool}"

    def test_calendar_create_event_is_moderate(self):
        policy = _load_policy()
        assert policy["tool_levels"]["calendar.create_event"] == "moderate"

    def test_calendar_delete_event_is_destructive(self):
        policy = _load_policy()
        assert policy["tool_levels"]["calendar.delete_event"] == "destructive"


# ===================================================================
# 4. always_confirm_tools in policy.json
# ===================================================================


class TestAlwaysConfirmInPolicy:
    """Verify always_confirm_tools includes critical send/create operations."""

    REQUIRED_ALWAYS_CONFIRM = [
        "calendar.create_event",
        "calendar.update_event",
        "gmail.send",
        "gmail.send_draft",
        "gmail.send_to_contact",
        "gmail.download_attachment",
        "gmail.generate_reply",
    ]

    def test_all_required_always_confirm(self):
        policy = _load_policy()
        confirm_list = policy["always_confirm_tools"]
        for tool in self.REQUIRED_ALWAYS_CONFIRM:
            assert tool in confirm_list, f"Missing in always_confirm_tools: {tool}"


# ===================================================================
# 5. metadata.py loads from policy.json (single source of truth)
# ===================================================================


class TestMetadataLoadsFromPolicy:
    """metadata.py TOOL_REGISTRY should match policy.json tool_levels."""

    def test_registry_loaded_from_policy(self):
        from bantz.tools.metadata import TOOL_REGISTRY, ToolRisk

        policy = _load_policy()
        tool_levels = policy["tool_levels"]
        risk_map = {"safe": ToolRisk.SAFE, "moderate": ToolRisk.MODERATE, "destructive": ToolRisk.DESTRUCTIVE}

        for tool_name, risk_str in tool_levels.items():
            if tool_name == "__comment":
                continue
            expected = risk_map[risk_str]
            assert tool_name in TOOL_REGISTRY, f"{tool_name} from policy.json not in TOOL_REGISTRY"
            assert TOOL_REGISTRY[tool_name] == expected, (
                f"{tool_name}: expected {expected}, got {TOOL_REGISTRY[tool_name]}"
            )

    def test_always_confirm_loaded(self):
        from bantz.tools.metadata import ALWAYS_CONFIRM_TOOLS

        policy = _load_policy()
        expected = set(policy["always_confirm_tools"])
        assert ALWAYS_CONFIRM_TOOLS == expected

    def test_undefined_tool_policy_loaded(self):
        from bantz.tools.metadata import UNDEFINED_TOOL_POLICY

        policy = _load_policy()
        assert UNDEFINED_TOOL_POLICY == policy["undefined_tool_policy"]


# ===================================================================
# 6. Undefined tool → explicit deny
# ===================================================================


class TestUndefinedToolDeny:
    """Issue #424: tools not in policy.json must be denied (DESTRUCTIVE)."""

    def test_unknown_tool_returns_destructive(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk

        risk = get_tool_risk("totally.unknown.tool")
        assert risk == ToolRisk.DESTRUCTIVE

    def test_unknown_tool_requires_confirmation(self):
        from bantz.tools.metadata import requires_confirmation

        assert requires_confirmation("totally.unknown.tool", llm_requested=False) is True

    def test_unknown_tool_is_destructive_flag(self):
        from bantz.tools.metadata import is_destructive

        assert is_destructive("totally.unknown.tool") is True

    def test_explicit_default_overrides_policy(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk

        # Caller can override with explicit default
        risk = get_tool_risk("totally.unknown.tool", default=ToolRisk.SAFE)
        assert risk == ToolRisk.SAFE


# ===================================================================
# 7. load_policy_json with custom file
# ===================================================================


class TestLoadPolicyJson:
    """Test loading from custom / missing / malformed policy files."""

    def test_load_from_custom_path(self, tmp_path):
        from bantz.tools.metadata import load_policy_json, ToolRisk

        custom = tmp_path / "custom_policy.json"
        custom.write_text(json.dumps({
            "tool_levels": {
                "my.tool": "safe",
                "my.danger": "destructive",
            },
            "always_confirm_tools": ["my.danger"],
            "undefined_tool_policy": "moderate",
        }), encoding="utf-8")

        registry, confirm_set, undef_policy = load_policy_json(custom)

        assert registry["my.tool"] == ToolRisk.SAFE
        assert registry["my.danger"] == ToolRisk.DESTRUCTIVE
        assert confirm_set == {"my.danger"}
        assert undef_policy == "moderate"

    def test_missing_file_returns_fallback(self, tmp_path):
        from bantz.tools.metadata import load_policy_json, ToolRisk

        missing = tmp_path / "does_not_exist.json"
        registry, confirm_set, undef_policy = load_policy_json(missing)

        # Should fall back to hardcoded registry
        assert "gmail.send" in registry
        assert registry["gmail.send"] == ToolRisk.MODERATE
        assert "gmail.send" in confirm_set
        assert undef_policy == "deny"

    def test_malformed_json_returns_fallback(self, tmp_path):
        from bantz.tools.metadata import load_policy_json

        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json!!!", encoding="utf-8")

        registry, confirm_set, undef_policy = load_policy_json(bad_file)

        assert "gmail.send" in registry
        assert undef_policy == "deny"

    def test_missing_tool_levels_key_returns_fallback(self, tmp_path):
        from bantz.tools.metadata import load_policy_json

        no_levels = tmp_path / "no_levels.json"
        no_levels.write_text(json.dumps({"intent_levels": {}}), encoding="utf-8")

        registry, confirm_set, undef_policy = load_policy_json(no_levels)

        assert "gmail.send" in registry  # fallback

    def test_invalid_risk_value_skipped(self, tmp_path):
        from bantz.tools.metadata import load_policy_json

        invalid = tmp_path / "invalid_risk.json"
        invalid.write_text(json.dumps({
            "tool_levels": {
                "good.tool": "safe",
                "bad.tool": "banana",  # invalid
            },
            "always_confirm_tools": [],
            "undefined_tool_policy": "deny",
        }), encoding="utf-8")

        registry, _, _ = load_policy_json(invalid)

        assert "good.tool" in registry
        assert "bad.tool" not in registry  # skipped

    def test_comment_key_ignored(self, tmp_path):
        from bantz.tools.metadata import load_policy_json

        with_comment = tmp_path / "comment.json"
        with_comment.write_text(json.dumps({
            "tool_levels": {
                "__comment": "This is a comment",
                "real.tool": "safe",
            },
            "always_confirm_tools": [],
            "undefined_tool_policy": "deny",
        }), encoding="utf-8")

        registry, _, _ = load_policy_json(with_comment)

        assert "__comment" not in registry
        assert "real.tool" in registry


# ===================================================================
# 8. reload_policy refreshes globals
# ===================================================================


class TestReloadPolicy:
    """reload_policy() should refresh TOOL_REGISTRY and related globals."""

    def test_reload_updates_registry(self, tmp_path):
        import bantz.tools.metadata as mod

        custom = tmp_path / "reload_test.json"
        custom.write_text(json.dumps({
            "tool_levels": {
                "new.tool": "destructive",
            },
            "always_confirm_tools": ["new.tool"],
            "undefined_tool_policy": "moderate",
        }), encoding="utf-8")

        # Save originals
        orig_registry = dict(mod.TOOL_REGISTRY)
        orig_confirm = set(mod.ALWAYS_CONFIRM_TOOLS)
        orig_policy = mod.UNDEFINED_TOOL_POLICY

        try:
            mod.reload_policy(custom)

            assert "new.tool" in mod.TOOL_REGISTRY
            assert mod.TOOL_REGISTRY["new.tool"] == mod.ToolRisk.DESTRUCTIVE
            assert "new.tool" in mod.ALWAYS_CONFIRM_TOOLS
            assert mod.UNDEFINED_TOOL_POLICY == "moderate"
        finally:
            # Restore originals
            mod.TOOL_REGISTRY = orig_registry
            mod.ALWAYS_CONFIRM_TOOLS = orig_confirm
            mod.UNDEFINED_TOOL_POLICY = orig_policy


# ===================================================================
# 9. Sync: metadata.py ↔ policy.json parity
# ===================================================================


class TestRegistryPolicySync:
    """All tools in policy.json tool_levels should be in TOOL_REGISTRY and vice versa."""

    def test_policy_tools_in_registry(self):
        from bantz.tools.metadata import TOOL_REGISTRY

        policy = _load_policy()
        for tool in policy["tool_levels"]:
            if tool == "__comment":
                continue
            assert tool in TOOL_REGISTRY, f"policy.json tool '{tool}' not in TOOL_REGISTRY"

    def test_registry_tools_in_policy(self):
        from bantz.tools.metadata import TOOL_REGISTRY

        policy = _load_policy()
        policy_tools = {k for k in policy["tool_levels"] if k != "__comment"}
        for tool in TOOL_REGISTRY:
            assert tool in policy_tools, f"TOOL_REGISTRY tool '{tool}' not in policy.json"


# ===================================================================
# 10. Existing API backward compatibility
# ===================================================================


class TestBackwardCompat:
    """Ensure all existing public API still works after #424 refactor."""

    def test_get_tool_risk(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk

        assert get_tool_risk("web.search") == ToolRisk.SAFE
        assert get_tool_risk("calendar.delete_event") == ToolRisk.DESTRUCTIVE
        assert get_tool_risk("gmail.send") == ToolRisk.MODERATE

    def test_is_destructive(self):
        from bantz.tools.metadata import is_destructive

        assert is_destructive("calendar.delete_event") is True
        assert is_destructive("web.search") is False

    def test_requires_confirmation(self):
        from bantz.tools.metadata import requires_confirmation

        # Destructive always True
        assert requires_confirmation("calendar.delete_event", llm_requested=False) is True
        # Safe + no LLM request → False
        assert requires_confirmation("web.search", llm_requested=False) is False
        # Safe + LLM request → True
        assert requires_confirmation("web.search", llm_requested=True) is True
        # Always-confirm tools
        assert requires_confirmation("gmail.send", llm_requested=False) is True

    def test_get_confirmation_prompt(self):
        from bantz.tools.metadata import get_confirmation_prompt

        prompt = get_confirmation_prompt("gmail.send", {"to": "user@test.com", "subject": "Test"})
        assert "user@test.com" in prompt

    def test_register_tool_risk(self):
        from bantz.tools.metadata import register_tool_risk, ToolRisk, TOOL_REGISTRY

        register_tool_risk("test.dynamic_tool", ToolRisk.SAFE)
        assert TOOL_REGISTRY["test.dynamic_tool"] == ToolRisk.SAFE
        # Cleanup
        del TOOL_REGISTRY["test.dynamic_tool"]

    def test_get_all_tools_by_risk(self):
        from bantz.tools.metadata import get_all_tools_by_risk, ToolRisk

        destructive = get_all_tools_by_risk(ToolRisk.DESTRUCTIVE)
        assert "calendar.delete_event" in destructive

    def test_get_registry_stats(self):
        from bantz.tools.metadata import get_registry_stats

        stats = get_registry_stats()
        assert stats["safe"] > 0
        assert stats["moderate"] > 0
        assert stats["destructive"] > 0
        assert stats["total"] == stats["safe"] + stats["moderate"] + stats["destructive"]
