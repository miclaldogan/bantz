"""Tests for Issue #423: Audit trail persistent storage.

Covers:
- SafetyGuard.audit_decision writes to persistent AuditLogger
- query_audit with time/action/tool filters
- cleanup_old_audit retention
- Graceful degradation when AuditLogger unavailable
- Integration with existing SafetyGuard policy checks
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from bantz.brain.safety_guard import SafetyGuard, ToolSecurityPolicy


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def tmp_audit_path(tmp_path):
    """Provide a temporary audit log path."""
    return tmp_path / "audit.log"


@pytest.fixture
def guard(tmp_audit_path):
    """SafetyGuard with persistent audit configured."""
    return SafetyGuard(
        audit_log_path=tmp_audit_path,
        audit_retention_days=90,
    )


# ============================================================================
# audit_decision: Persistent writes
# ============================================================================

class TestAuditDecisionPersistence:
    """Test that audit_decision writes to the persistent JSON-line file."""

    def test_writes_to_file(self, guard, tmp_audit_path):
        """audit_decision should create a log entry in the audit file."""
        guard.audit_decision(
            decision_type="allow",
            tool_name="calendar.create_event",
            allowed=True,
            reason="Route allows tool",
        )

        assert tmp_audit_path.exists()
        lines = tmp_audit_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["action"] == "policy.allow"
        assert entry["resource"] == "calendar.create_event"
        assert entry["outcome"] == "allowed"

    def test_deny_writes_security_level(self, guard, tmp_audit_path):
        """Denied decisions should have SECURITY level."""
        guard.audit_decision(
            decision_type="deny",
            tool_name="system.shutdown",
            allowed=False,
            reason="Tool in denylist",
        )

        lines = tmp_audit_path.read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["level"] == "security"
        assert entry["outcome"] == "denied"

    def test_multiple_entries(self, guard, tmp_audit_path):
        """Multiple decisions should append."""
        for i in range(5):
            guard.audit_decision(
                decision_type="allow",
                tool_name=f"tool_{i}",
                allowed=True,
                reason=f"Reason {i}",
            )

        lines = tmp_audit_path.read_text().strip().split("\n")
        assert len(lines) == 5

    def test_metadata_included(self, guard, tmp_audit_path):
        """Metadata should be included in the log entry."""
        guard.audit_decision(
            decision_type="filter",
            tool_name="gmail.send",
            allowed=False,
            reason="Route mismatch",
            metadata={"route": "smalltalk", "original_plan": ["gmail.send"]},
        )

        lines = tmp_audit_path.read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["details"]["route"] == "smalltalk"

    def test_allowed_has_info_level(self, guard, tmp_audit_path):
        """Allowed decisions should have INFO level."""
        guard.audit_decision(
            decision_type="allow",
            tool_name="calendar.list_events",
            allowed=True,
            reason="Safe tool",
        )

        lines = tmp_audit_path.read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["level"] == "info"


# ============================================================================
# query_audit
# ============================================================================

class TestQueryAudit:
    """Test audit query capabilities."""

    def _seed_entries(self, guard):
        """Seed 5 audit entries."""
        guard.audit_decision("allow", "calendar.list_events", True, "safe")
        guard.audit_decision("allow", "calendar.create_event", True, "route match")
        guard.audit_decision("deny", "system.shutdown", False, "denylist")
        guard.audit_decision("filter", "gmail.send", False, "route mismatch")
        guard.audit_decision("allow", "gmail.list_messages", True, "safe tool")

    def test_query_all(self, guard):
        self._seed_entries(guard)
        results = guard.query_audit()
        assert len(results) == 5

    def test_query_by_outcome(self, guard):
        self._seed_entries(guard)
        denied = guard.query_audit(outcome="denied")
        assert len(denied) == 2  # system.shutdown + gmail.send

    def test_query_by_tool_name(self, guard):
        self._seed_entries(guard)
        results = guard.query_audit(tool_name="calendar")
        assert len(results) == 2  # list_events + create_event

    def test_query_by_action(self, guard):
        self._seed_entries(guard)
        results = guard.query_audit(action="policy.deny")
        assert len(results) == 1
        assert results[0]["resource"] == "system.shutdown"

    def test_query_by_last_days(self, guard):
        self._seed_entries(guard)
        # All entries are from now, so last 1 day should include all
        results = guard.query_audit(last_days=1)
        assert len(results) == 5

    def test_query_empty_log(self, guard):
        results = guard.query_audit()
        assert results == []


# ============================================================================
# cleanup_old_audit
# ============================================================================

class TestCleanupOldAudit:
    """Test audit retention cleanup."""

    def test_cleanup_removes_old_entries(self, guard, tmp_audit_path):
        """Entries older than retention should be removed."""
        # Manually write old entries
        from bantz.security.audit import AuditEntry, AuditLevel
        old_time = datetime.now() - timedelta(days=100)
        new_time = datetime.now()

        old_entry = AuditEntry(
            timestamp=old_time,
            action="policy.allow",
            actor="safety_guard",
            resource="old_tool",
            outcome="allowed",
            level=AuditLevel.INFO,
        )
        new_entry = AuditEntry(
            timestamp=new_time,
            action="policy.deny",
            actor="safety_guard",
            resource="new_tool",
            outcome="denied",
            level=AuditLevel.SECURITY,
        )

        with open(tmp_audit_path, "w") as f:
            f.write(old_entry.to_json() + "\n")
            f.write(new_entry.to_json() + "\n")

        removed = guard.cleanup_old_audit(retention_days=90)
        assert removed == 1

        # Only new entry should remain
        lines = tmp_audit_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["resource"] == "new_tool"

    def test_cleanup_nothing_to_remove(self, guard):
        """No entries → 0 removed."""
        guard.audit_decision("allow", "test", True, "test")
        removed = guard.cleanup_old_audit(retention_days=90)
        assert removed == 0

    def test_cleanup_custom_retention(self, guard, tmp_audit_path):
        """Custom retention days override."""
        # Write an entry from 5 days ago
        from bantz.security.audit import AuditEntry, AuditLevel
        old_time = datetime.now() - timedelta(days=5)
        entry = AuditEntry(
            timestamp=old_time,
            action="policy.allow",
            actor="safety_guard",
            resource="old_tool",
            outcome="allowed",
            level=AuditLevel.INFO,
        )
        with open(tmp_audit_path, "w") as f:
            f.write(entry.to_json() + "\n")

        removed = guard.cleanup_old_audit(retention_days=3)
        assert removed == 1

    def test_cleanup_with_default_retention(self, guard, tmp_audit_path):
        """Default retention (90 days) keeps recent entries."""
        guard.audit_decision("allow", "test_tool", True, "ok")
        removed = guard.cleanup_old_audit()
        assert removed == 0


# ============================================================================
# Graceful Degradation
# ============================================================================

class TestGracefulDegradation:
    """Test that audit works even when AuditLogger is unavailable."""

    def test_no_crash_without_audit_logger(self):
        """audit_decision should not crash if AuditLogger fails to init."""
        guard = SafetyGuard()  # No audit_log_path
        # Should not raise
        guard.audit_decision("allow", "test", True, "test")

    def test_query_returns_empty_when_no_logger(self):
        """query_audit returns empty list when logger unavailable."""
        guard = SafetyGuard()
        # Force _audit_logger to False (sentinel for "init failed")
        guard._audit_logger = False
        results = guard.query_audit()
        assert results == []

    def test_cleanup_returns_zero_when_no_logger(self):
        """cleanup returns 0 when logger unavailable."""
        guard = SafetyGuard()
        guard._audit_logger = False
        assert guard.cleanup_old_audit() == 0


# ============================================================================
# Integration: audit_decision called from policy checks
# ============================================================================

class TestIntegrationWithPolicyChecks:
    """Test that policy operations can be audited end-to-end."""

    def test_filter_and_audit(self, guard, tmp_audit_path):
        """filter_tool_plan + audit_decision for violations."""
        filtered, violations = guard.filter_tool_plan(
            route="smalltalk",
            tool_plan=["gmail.send", "calendar.list_events"],
        )
        # calendar.list_events is in ROUTE_INDEPENDENT_SAFE_TOOLS
        assert "calendar.list_events" in filtered
        assert len(violations) == 1  # gmail.send dropped

        # Audit the violation
        for v in violations:
            guard.audit_decision(
                decision_type="filter",
                tool_name=v.tool_name,
                allowed=False,
                reason=v.reason,
                metadata=v.metadata,
            )

        lines = tmp_audit_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["resource"] == "gmail.send"
        assert entry["outcome"] == "denied"

    def test_check_tool_and_audit(self, guard, tmp_audit_path):
        """check_tool_allowed + audit_decision end-to-end."""
        guard.policy.denylist = {"system.shutdown"}
        allowed, reason = guard.check_tool_allowed("system.shutdown")
        assert not allowed

        guard.audit_decision(
            decision_type="deny",
            tool_name="system.shutdown",
            allowed=False,
            reason=reason,
        )

        results = guard.query_audit(outcome="denied")
        assert len(results) == 1
        assert results[0]["resource"] == "system.shutdown"


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Edge cases for audit persistence."""

    def test_unicode_metadata(self, guard, tmp_audit_path):
        """Turkish characters in metadata should not corrupt the log."""
        guard.audit_decision(
            decision_type="allow",
            tool_name="calendar.create_event",
            allowed=True,
            reason="Takvim etkinliği oluşturuluyor",
            metadata={"title": "Toplantı — Müdürler"},
        )

        lines = tmp_audit_path.read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["details"]["title"] == "Toplantı — Müdürler"

    def test_empty_metadata(self, guard, tmp_audit_path):
        """Empty metadata is fine."""
        guard.audit_decision("allow", "test", True, "ok", metadata={})
        assert tmp_audit_path.exists()

    def test_none_metadata(self, guard, tmp_audit_path):
        """None metadata is fine."""
        guard.audit_decision("allow", "test", True, "ok", metadata=None)
        lines = tmp_audit_path.read_text().strip().split("\n")
        assert len(lines) == 1
