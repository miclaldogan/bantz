"""Tests for issue #453 — Audit Log JSONL + PII redaction."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from bantz.security.audit_log import (
    AuditEvent,
    AuditEventType,
    AuditLogger,
    hash_value,
    redact_pii,
)


# ── Helpers ───────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_log(tmp_path):
    """Return path to a temporary audit log."""
    return str(tmp_path / "audit.jsonl")


@pytest.fixture()
def audit(tmp_log):
    return AuditLogger(log_path=tmp_log, redact=True)


# ── TestPIIRedaction ──────────────────────────────────────────────────

class TestPIIRedaction:
    def test_email_redacted(self):
        result = redact_pii("iletişim: user@example.com")
        assert "user@example.com" not in result
        assert "u***@***.com" in result

    def test_phone_redacted(self):
        result = redact_pii("Ara: +90 532 123 4567")
        assert "[PHONE]" in result
        assert "532" not in result

    def test_token_redacted(self):
        result = redact_pii("api_key=sk_live_abc123xyz")
        assert "[REDACTED]" in result
        assert "sk_live" not in result

    def test_turkish_password_redacted(self):
        result = redact_pii("şifre: gizli1234")
        assert "[REDACTED]" in result
        assert "gizli1234" not in result

    def test_path_redacted(self):
        result = redact_pii("dosya: /home/ahmet/Documents/secret.txt")
        assert "/home/ahmet/" not in result
        assert "~/" in result

    def test_clean_text_unchanged(self):
        text = "Bugün hava güzel"
        assert redact_pii(text) == text

    def test_empty_string(self):
        assert redact_pii("") == ""

    def test_multiple_pii(self):
        text = "Email: a@b.com, Tel: +90 555 111 2233"
        result = redact_pii(text)
        assert "a@b.com" not in result
        assert "555" not in result


# ── TestHashValue ─────────────────────────────────────────────────────

class TestHashValue:
    def test_deterministic(self):
        assert hash_value({"a": 1}) == hash_value({"a": 1})

    def test_different_values(self):
        assert hash_value({"a": 1}) != hash_value({"a": 2})

    def test_prefix(self):
        assert hash_value("test").startswith("sha256:")


# ── TestAuditEvent ────────────────────────────────────────────────────

class TestAuditEvent:
    def test_to_dict_and_from_dict(self):
        ev = AuditEvent(
            event_type=AuditEventType.TOOL_CALL,
            tool="calendar.create_event",
            success=True,
        )
        d = ev.to_dict()
        assert d["event_type"] == "tool_call"
        restored = AuditEvent.from_dict(d)
        assert restored.event_type == AuditEventType.TOOL_CALL
        assert restored.tool == "calendar.create_event"

    def test_none_values_excluded(self):
        ev = AuditEvent(event_type=AuditEventType.ERROR, message="boom")
        d = ev.to_dict()
        assert "tool" not in d
        assert "latency_ms" not in d

    def test_all_event_types(self):
        for et in AuditEventType:
            ev = AuditEvent(event_type=et)
            d = ev.to_dict()
            assert d["event_type"] == et.value


# ── TestAuditLogger ───────────────────────────────────────────────────

class TestAuditLogger:
    def test_log_and_tail(self, audit):
        audit.log(AuditEvent(event_type=AuditEventType.SESSION_START))
        audit.log(AuditEvent(event_type=AuditEventType.TOOL_CALL, tool="x"))
        events = audit.tail(10)
        assert len(events) == 2
        assert events[0].event_type == AuditEventType.SESSION_START

    def test_tail_limit(self, audit):
        for i in range(10):
            audit.log(AuditEvent(event_type=AuditEventType.TOOL_CALL, tool=f"t{i}"))
        events = audit.tail(3)
        assert len(events) == 3
        assert events[0].tool == "t7"

    def test_log_tool_call_convenience(self, audit):
        audit.log_tool_call(
            tool="calendar.create_event",
            args={"title": "Toplantı"},
            decision="CONFIRM",
            result={"id": "123"},
            latency_ms=245,
        )
        events = audit.tail(1)
        assert events[0].event_type == AuditEventType.TOOL_CALL
        assert events[0].tool == "calendar.create_event"
        assert events[0].args_hash.startswith("sha256:")
        assert events[0].latency_ms == 245

    def test_search_by_query(self, audit):
        audit.log(AuditEvent(event_type=AuditEventType.TOOL_CALL, tool="calendar.create"))
        audit.log(AuditEvent(event_type=AuditEventType.TOOL_CALL, tool="gmail.send"))
        results = audit.search(query="calendar")
        assert len(results) == 1
        assert results[0].tool == "calendar.create"

    def test_search_by_event_type(self, audit):
        audit.log(AuditEvent(event_type=AuditEventType.TOOL_CALL, tool="x"))
        audit.log(AuditEvent(event_type=AuditEventType.ERROR, message="fail"))
        results = audit.search(event_type=AuditEventType.ERROR)
        assert len(results) == 1
        assert results[0].message == "fail"

    def test_search_by_since(self, audit, tmp_log):
        # Manually write an old event
        old = AuditEvent(
            event_type=AuditEventType.SESSION_START,
            timestamp=datetime.utcnow() - timedelta(hours=5),
        )
        audit.log(old)
        audit.log(AuditEvent(event_type=AuditEventType.SESSION_END))

        results = audit.search(since=timedelta(hours=1))
        assert len(results) == 1
        assert results[0].event_type == AuditEventType.SESSION_END

    def test_pii_redacted_in_log(self, audit, tmp_log):
        audit.log(AuditEvent(
            event_type=AuditEventType.TOOL_CALL,
            message="Email: user@example.com token: api_key=secret123",
        ))
        raw = Path(tmp_log).read_text()
        assert "user@example.com" not in raw
        assert "secret123" not in raw

    def test_empty_log_tail(self, tmp_log):
        a = AuditLogger(log_path=tmp_log)
        assert a.tail(10) == []

    def test_empty_log_search(self, tmp_log):
        a = AuditLogger(log_path=tmp_log)
        assert a.search(query="anything") == []


# ── TestFileRotation ──────────────────────────────────────────────────

class TestFileRotation:
    def test_rotation_on_size(self, tmp_path):
        log_path = str(tmp_path / "audit.jsonl")
        # max_bytes = 500 so rotation triggers quickly
        a = AuditLogger(log_path=log_path, max_bytes=500, max_backups=2)

        # Write enough to exceed 500 bytes
        for i in range(30):
            a.log(AuditEvent(
                event_type=AuditEventType.TOOL_CALL,
                tool=f"tool_{i}",
                message="x" * 50,
            ))

        # Should have rotated at least once
        backup = tmp_path / "audit.jsonl.1"
        assert backup.exists()

    def test_max_backups_respected(self, tmp_path):
        log_path = str(tmp_path / "audit.jsonl")
        a = AuditLogger(log_path=log_path, max_bytes=200, max_backups=2)

        for i in range(100):
            a.log(AuditEvent(
                event_type=AuditEventType.TOOL_CALL,
                tool=f"t{i}",
                message="y" * 50,
            ))

        # Should NOT have .3 (max_backups=2)
        assert not (tmp_path / "audit.jsonl.3").exists()


# ── TestGoldenPIISafety ──────────────────────────────────────────────

class TestGoldenPIISafety:
    """Golden tests: sensitive data must NEVER appear in the log file."""

    SENSITIVE_STRINGS = [
        "user@example.com",
        "+90 532 123 4567",
        "api_key=sk_live_abc",
        "şifre: gizli1234",
    ]

    def test_no_pii_leaks_in_log(self, tmp_path):
        log_path = str(tmp_path / "audit.jsonl")
        a = AuditLogger(log_path=log_path, redact=True)

        for s in self.SENSITIVE_STRINGS:
            a.log(AuditEvent(
                event_type=AuditEventType.TOOL_CALL,
                message=s,
            ))

        raw = Path(log_path).read_text()
        for s in self.SENSITIVE_STRINGS:
            # The original sensitive string must not be in the log
            assert s not in raw, f"PII leak: {s!r} found in audit log"
