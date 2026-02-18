# SPDX-License-Identifier: MIT
"""Tests for Issue #1222: Capability model, gate, and audit log."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from bantz.security.capability_model import (
    Capability,
    ToolCapability,
    CapabilityGate,
    CapabilityAuditLog,
    AuditEntry,
    get_tool_capabilities,
)


# ============================================================================
# Capability taxonomy
# ============================================================================
class TestCapability:

    def test_all_capabilities_defined(self) -> None:
        assert len(Capability) == 6
        assert Capability.READ.value == "read"
        assert Capability.EXECUTE_EXTERNAL.value == "execute_external"


# ============================================================================
# Tool → Capability mapping
# ============================================================================
class TestToolCapabilities:

    def test_safe_read_tool(self) -> None:
        tc = get_tool_capabilities("calendar.list_events")
        assert Capability.READ in tc.capabilities
        assert tc.risk_level == "safe"
        assert not tc.requires_confirmation

    def test_moderate_write_tool(self) -> None:
        tc = get_tool_capabilities("calendar.create_event")
        assert Capability.WRITE in tc.capabilities
        assert tc.risk_level == "moderate"
        assert tc.requires_confirmation

    def test_destructive_delete_tool(self) -> None:
        tc = get_tool_capabilities("calendar.delete_event")
        assert Capability.DELETE in tc.capabilities
        assert tc.risk_level == "destructive"

    def test_send_capability(self) -> None:
        tc = get_tool_capabilities("gmail.send")
        assert Capability.SEND in tc.capabilities

    def test_multi_capability_tool(self) -> None:
        tc = get_tool_capabilities("gmail.generate_reply")
        assert Capability.SEND in tc.capabilities
        assert Capability.WRITE in tc.capabilities

    def test_unknown_tool_defaults(self) -> None:
        tc = get_tool_capabilities("unknown.mystery_tool")
        assert Capability.EXECUTE_EXTERNAL in tc.capabilities
        assert tc.risk_level == "destructive"

    def test_max_risk_capability(self) -> None:
        tc = get_tool_capabilities("gmail.generate_reply")
        assert tc.max_risk_capability == Capability.SEND


# ============================================================================
# Capability gate
# ============================================================================
class TestCapabilityGate:

    def test_default_allows_read(self) -> None:
        gate = CapabilityGate()
        decision, reason = gate.check("calendar.list_events")
        assert decision == "allow"

    def test_default_confirms_write(self) -> None:
        gate = CapabilityGate()
        decision, reason = gate.check("calendar.create_event")
        assert decision == "confirm"

    def test_default_confirms_send(self) -> None:
        gate = CapabilityGate()
        decision, reason = gate.check("gmail.send")
        assert decision == "confirm"

    def test_default_denies_execute(self) -> None:
        gate = CapabilityGate()
        decision, reason = gate.check("system.execute_command")
        assert decision == "deny"

    def test_custom_allowed(self) -> None:
        gate = CapabilityGate(allowed_capabilities={Capability.READ, Capability.WRITE})
        decision, _ = gate.check("calendar.create_event")
        assert decision == "allow"

    def test_unknown_tool_denied(self) -> None:
        gate = CapabilityGate()
        decision, _ = gate.check("foo.bar")
        assert decision == "deny"


# ============================================================================
# Audit log
# ============================================================================
class TestCapabilityAuditLog:

    def test_write_entry(self, tmp_path: Path) -> None:
        log = CapabilityAuditLog(path=str(tmp_path / "audit.jsonl"), enabled=True)
        ok = log.log(
            tool_name="calendar.create_event",
            decision="confirm",
            reason="write requires confirmation",
            trace_id="abc123",
            user_input="yarın toplantı ekle",
        )
        assert ok is True
        assert log.count == 1

        lines = (tmp_path / "audit.jsonl").read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["tool_name"] == "calendar.create_event"
        assert entry["decision"] == "confirm"
        assert "write" in entry["capabilities"]
        assert entry["trace_id"] == "abc123"

    def test_disabled_log(self, tmp_path: Path) -> None:
        log = CapabilityAuditLog(path=str(tmp_path / "nope.jsonl"), enabled=False)
        ok = log.log(tool_name="x", decision="allow")
        assert ok is False
        assert log.count == 0

    def test_multiple_entries(self, tmp_path: Path) -> None:
        log = CapabilityAuditLog(path=str(tmp_path / "audit.jsonl"), enabled=True)
        for i in range(5):
            log.log(tool_name="web.search", decision="allow")
        assert log.count == 5


# ============================================================================
# AuditEntry
# ============================================================================
class TestAuditEntry:

    def test_to_dict_omits_empty(self) -> None:
        entry = AuditEntry(tool_name="test", decision="allow")
        d = entry.to_dict()
        assert "trace_id" not in d
        assert "params" not in d
        assert "result_summary" not in d

    def test_to_dict_includes_non_empty(self) -> None:
        entry = AuditEntry(
            tool_name="test", decision="confirm",
            trace_id="xyz", params={"key": "val"},
        )
        d = entry.to_dict()
        assert d["trace_id"] == "xyz"
        assert d["params"] == {"key": "val"}
