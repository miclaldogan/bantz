"""
Tests for V2-5 Audit Log Daily Summary (Issue #37).
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from bantz.security.audit import (
    AuditEntry,
    AuditLogger,
    AuditLevel,
    AuditAction,
    MockAuditLogger,
)


class TestAuditAction:
    """Tests for AuditAction enum."""
    
    def test_audit_actions_exist(self):
        """Test standard audit actions exist."""
        assert AuditAction.LOGIN is not None
        assert AuditAction.LOGOUT is not None
        assert AuditAction.COMMAND_EXECUTE is not None
        assert AuditAction.FILE_READ is not None
        assert AuditAction.FILE_WRITE is not None
        assert AuditAction.PERMISSION_GRANTED is not None
    
    def test_audit_action_values(self):
        """Test audit action string values."""
        assert AuditAction.LOGIN.value == "login"
        assert AuditAction.FILE_READ.value == "file_read"


class TestDailySummary:
    """Tests for daily summary feature."""
    
    def test_empty_summary_turkish(self):
        """Test empty summary in Turkish."""
        audit = MockAuditLogger()
        
        summary = audit.get_daily_summary(locale="tr")
        
        assert summary["total_actions"] == 0
        assert "aktivite kaydedilmedi" in summary["summary_text"]
    
    def test_empty_summary_english(self):
        """Test empty summary in English."""
        audit = MockAuditLogger()
        
        summary = audit.get_daily_summary(locale="en")
        
        assert summary["total_actions"] == 0
        assert "No activity" in summary["summary_text"]
    
    def test_summary_with_actions(self):
        """Test summary with logged actions."""
        audit = MockAuditLogger()
        
        # Log some actions
        audit.log(AuditEntry(
            timestamp=datetime.now(),
            action="command_execute",
            actor="user",
            resource="ls -la",
            outcome="success"
        ))
        audit.log(AuditEntry(
            timestamp=datetime.now(),
            action="file_read",
            actor="bantz",
            resource="/home/user/test.txt",
            outcome="success"
        ))
        audit.log(AuditEntry(
            timestamp=datetime.now(),
            action="file_write",
            actor="bantz",
            resource="/home/user/output.txt",
            outcome="success"
        ))
        
        summary = audit.get_daily_summary(locale="tr")
        
        assert summary["total_actions"] == 3
        assert summary["success_rate"] == 100.0
        assert "command_execute" in summary["actions"]
        assert "file_read" in summary["actions"]
    
    def test_summary_success_rate(self):
        """Test success rate calculation."""
        audit = MockAuditLogger()
        
        # 2 success, 1 failure = 66.7% success rate
        audit.log(AuditEntry(
            timestamp=datetime.now(),
            action="command_execute",
            actor="user",
            resource="cmd1",
            outcome="success"
        ))
        audit.log(AuditEntry(
            timestamp=datetime.now(),
            action="command_execute",
            actor="user",
            resource="cmd2",
            outcome="success"
        ))
        audit.log(AuditEntry(
            timestamp=datetime.now(),
            action="command_execute",
            actor="user",
            resource="cmd3",
            outcome="failure"
        ))
        
        summary = audit.get_daily_summary()
        
        assert summary["success_count"] == 2
        assert summary["failure_count"] == 1
        assert 66 < summary["success_rate"] < 67
    
    def test_summary_for_specific_date(self):
        """Test summary for specific date (past)."""
        audit = MockAuditLogger()
        
        # Log action for today
        audit.log(AuditEntry(
            timestamp=datetime.now(),
            action="test",
            actor="user",
            resource="test",
            outcome="success"
        ))
        
        # Request summary for yesterday (should be empty)
        yesterday = datetime.now() - timedelta(days=1)
        summary = audit.get_daily_summary(date=yesterday)
        
        assert summary["total_actions"] == 0
    
    def test_summary_action_counting(self):
        """Test action type counting in summary."""
        audit = MockAuditLogger()
        
        # Log multiple of same action
        for i in range(5):
            audit.log(AuditEntry(
                timestamp=datetime.now(),
                action="command_execute",
                actor="user",
                resource=f"cmd{i}",
                outcome="success"
            ))
        
        for i in range(3):
            audit.log(AuditEntry(
                timestamp=datetime.now(),
                action="file_read",
                actor="bantz",
                resource=f"/file{i}.txt",
                outcome="success"
            ))
        
        summary = audit.get_daily_summary()
        
        assert summary["actions"]["command_execute"] == 5
        assert summary["actions"]["file_read"] == 3


class TestAuditLoggerWithSummary:
    """Tests for AuditLogger with summary integration."""
    
    def test_log_action_convenience(self):
        """Test log_action convenience method."""
        audit = MockAuditLogger()
        
        audit.log_action(
            action=AuditAction.COMMAND_EXECUTE,
            actor="user",
            resource="ls -la",
            outcome="success"
        )
        
        entries = audit.get_all_entries()
        assert len(entries) == 1
        assert entries[0].action == "command_execute"
    
    def test_query_by_action(self):
        """Test querying by action type."""
        audit = MockAuditLogger()
        
        audit.log_action(AuditAction.FILE_READ, "user", "/file1.txt", "success")
        audit.log_action(AuditAction.FILE_WRITE, "user", "/file2.txt", "success")
        audit.log_action(AuditAction.FILE_READ, "user", "/file3.txt", "success")
        
        reads = audit.query(action="file_read")
        
        assert len(reads) == 2
    
    def test_query_by_outcome(self):
        """Test querying by outcome."""
        audit = MockAuditLogger()
        
        audit.log_action(AuditAction.COMMAND_EXECUTE, "user", "cmd1", "success")
        audit.log_action(AuditAction.COMMAND_EXECUTE, "user", "cmd2", "failure")
        audit.log_action(AuditAction.COMMAND_EXECUTE, "user", "cmd3", "success")
        
        failures = audit.query(outcome="failure")
        
        assert len(failures) == 1
        assert failures[0].resource == "cmd2"
    
    def test_query_by_time_range(self):
        """Test querying by time range."""
        audit = MockAuditLogger()
        
        now = datetime.now()
        hour_ago = now - timedelta(hours=1)
        
        # Log with current time
        audit.log(AuditEntry(
            timestamp=now,
            action="test",
            actor="user",
            resource="current",
            outcome="success"
        ))
        
        # Query from hour ago
        results = audit.query(start_time=hour_ago)
        
        assert len(results) == 1


class TestMockAuditLogger:
    """Tests for MockAuditLogger."""
    
    def test_mock_stores_in_memory(self):
        """Test mock logger stores entries in memory."""
        audit = MockAuditLogger()
        
        audit.log(AuditEntry(
            timestamp=datetime.now(),
            action="test",
            actor="user",
            resource="test",
            outcome="success"
        ))
        
        entries = audit.get_all_entries()
        assert len(entries) == 1
    
    def test_mock_clear(self):
        """Test mock logger clear."""
        audit = MockAuditLogger()
        
        audit.log(AuditEntry(
            timestamp=datetime.now(),
            action="test",
            actor="user",
            resource="test",
            outcome="success"
        ))
        
        count = audit.clear()
        
        assert count == 1
        assert len(audit.get_all_entries()) == 0
    
    def test_mock_query_with_limit(self):
        """Test mock logger query with limit."""
        audit = MockAuditLogger()
        
        for i in range(10):
            audit.log(AuditEntry(
                timestamp=datetime.now(),
                action="test",
                actor="user",
                resource=f"test{i}",
                outcome="success"
            ))
        
        results = audit.query(limit=5)
        
        assert len(results) == 5
