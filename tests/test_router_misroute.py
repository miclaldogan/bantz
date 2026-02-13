"""Tests for Router Misroute Collector.

Issue #238: Test misroute collection, PII redaction, and replay functionality.

Test categories:
1. MisrouteRecord dataclass
2. PII redaction
3. MisrouteDataset operations
4. Logging utilities
5. Replay functionality
6. Statistics
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from bantz.router.misroute_collector import (
    DEFAULT_DATASET_PATH,
    MisrouteDataset,
    MisrouteRecord,
    ReplayResult,
    ReplaySummary,
    get_dataset_stats,
    log_fallback,
    log_misroute,
    log_user_correction,
    redact_pii,
    redact_record,
    replay_dataset,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def temp_dataset_path() -> Generator[str, None, None]:
    """Create a temporary dataset path."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        temp_path = f.name
    
    yield temp_path
    
    try:
        os.unlink(temp_path)
    except OSError:
        pass


@pytest.fixture
def dataset(temp_dataset_path) -> MisrouteDataset:
    """Create a test dataset."""
    return MisrouteDataset(path=temp_dataset_path, redact=True)


@pytest.fixture
def sample_record() -> MisrouteRecord:
    """Create a sample misroute record."""
    return MisrouteRecord(
        user_text="yarın saat 3te toplantı ekle",
        router_route="calendar",
        router_intent="create",
        router_slots={"time": "15:00", "title": "toplantı"},
        router_confidence=0.85,
        expected_route="calendar",
        expected_intent="create",
        reason="wrong_slot",
        notes="Time parsed incorrectly",
    )


# ============================================================================
# MISROUTE RECORD TESTS
# ============================================================================

class TestMisrouteRecord:
    """Test MisrouteRecord dataclass."""
    
    def test_create_record(self, sample_record):
        """Test record creation."""
        assert sample_record.user_text == "yarın saat 3te toplantı ekle"
        assert sample_record.router_route == "calendar"
        assert sample_record.reason == "wrong_slot"
    
    def test_record_to_dict(self, sample_record):
        """Test dictionary conversion."""
        data = sample_record.to_dict()
        
        assert data["user_text"] == "yarın saat 3te toplantı ekle"
        assert data["router_route"] == "calendar"
        assert data["router_slots"]["time"] == "15:00"
    
    def test_record_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "user_text": "test input",
            "router_route": "gmail",
            "router_intent": "read",
            "router_slots": {},
            "router_confidence": 0.9,
            "reason": "fallback",
            "timestamp": "2026-02-01T12:00:00Z",
        }
        
        record = MisrouteRecord.from_dict(data)
        
        assert record.user_text == "test input"
        assert record.router_route == "gmail"
        assert record.reason == "fallback"
    
    def test_record_roundtrip(self, sample_record):
        """Test dict roundtrip."""
        data = sample_record.to_dict()
        restored = MisrouteRecord.from_dict(data)
        
        assert restored.user_text == sample_record.user_text
        assert restored.router_route == sample_record.router_route
        assert restored.reason == sample_record.reason
    
    def test_record_default_timestamp(self):
        """Test that timestamp is auto-generated."""
        record = MisrouteRecord(
            user_text="test",
            router_route="test",
            router_intent="test",
        )
        
        assert record.timestamp
        assert "202" in record.timestamp  # Year starts with 202x
    
    def test_record_with_expected_values(self):
        """Test record with expected (correction) values."""
        record = MisrouteRecord(
            user_text="test",
            router_route="gmail",
            router_intent="read",
            expected_route="calendar",
            expected_intent="query",
            reason="user_correction",
        )
        
        assert record.expected_route == "calendar"
        assert record.reason == "user_correction"


# ============================================================================
# PII REDACTION TESTS
# ============================================================================

class TestPIIRedaction:
    """Test PII redaction functionality."""
    
    def test_redact_email(self):
        """Test email redaction."""
        text = "mail gönder john@example.com adresine"
        result = redact_pii(text)
        
        assert "john@example.com" not in result
        assert "@" in result  # Masked format still contains @
    
    def test_redact_phone(self):
        """Test phone number redaction."""
        text = "ara +90 555 123 4567"
        result = redact_pii(text)
        
        assert "555 123 4567" not in result
    
    def test_redact_record_all_fields(self, sample_record):
        """Test that record redaction covers all text fields."""
        # Add PII to record
        record = MisrouteRecord(
            user_text="mail at test@email.com",
            router_route="gmail",
            router_intent="send",
            router_slots={"to": "victim@example.com"},
            router_raw_output='{"to": "victim@example.com"}',
            notes="Contact test@email.com",
            reason="other",
        )
        
        redacted = redact_record(record)
        
        assert "test@email.com" not in redacted.user_text
        assert "victim@example.com" not in str(redacted.router_slots)
        assert "victim@example.com" not in redacted.router_raw_output
        assert "test@email.com" not in redacted.notes
    
    def test_redact_preserves_non_pii(self):
        """Test that non-PII text is preserved."""
        text = "yarın saat 15:00'te toplantı"
        result = redact_pii(text)
        
        assert result == text


# ============================================================================
# MISROUTE DATASET TESTS
# ============================================================================

class TestMisrouteDataset:
    """Test MisrouteDataset operations."""
    
    def test_create_dataset(self, temp_dataset_path):
        """Test dataset creation."""
        dataset = MisrouteDataset(path=temp_dataset_path)
        assert dataset.count() == 0
    
    def test_append_record(self, dataset, sample_record):
        """Test appending a record."""
        dataset.append(sample_record)
        assert dataset.count() == 1
    
    def test_read_all(self, dataset, sample_record):
        """Test reading all records."""
        dataset.append(sample_record)
        dataset.append(sample_record)
        
        records = dataset.read_all()
        assert len(records) == 2
    
    def test_iter_records(self, dataset, sample_record):
        """Test iterating over records."""
        dataset.append(sample_record)
        dataset.append(sample_record)
        dataset.append(sample_record)
        
        count = sum(1 for _ in dataset.iter_records())
        assert count == 3
    
    def test_clear(self, dataset, sample_record):
        """Test clearing the dataset."""
        dataset.append(sample_record)
        dataset.append(sample_record)
        
        removed = dataset.clear()
        
        assert removed == 2
        assert dataset.count() == 0
    
    def test_export_json(self, dataset, sample_record, tmp_path):
        """Test JSON export."""
        dataset.append(sample_record)
        dataset.append(sample_record)
        
        output_path = str(tmp_path / "export.json")
        count = dataset.export_json(output_path)
        
        assert count == 2
        
        with open(output_path) as f:
            data = json.load(f)
        
        assert len(data) == 2
        assert data[0]["user_text"] == sample_record.user_text
    
    def test_creates_directory(self, tmp_path):
        """Test that nested directories are created."""
        nested_path = tmp_path / "deep" / "nested" / "data.jsonl"
        dataset = MisrouteDataset(path=str(nested_path))
        
        record = MisrouteRecord(
            user_text="test",
            router_route="test",
            router_intent="test",
        )
        dataset.append(record)
        
        assert nested_path.exists()
    
    def test_redaction_enabled_by_default(self, temp_dataset_path):
        """Test that PII redaction is enabled by default."""
        dataset = MisrouteDataset(path=temp_dataset_path)
        
        record = MisrouteRecord(
            user_text="mail at test@secret.com",
            router_route="gmail",
            router_intent="read",
        )
        
        dataset.append(record)
        
        # Read back raw
        with open(temp_dataset_path) as f:
            line = f.readline()
            data = json.loads(line)
        
        assert "test@secret.com" not in data["user_text"]
    
    def test_redaction_can_be_disabled(self, temp_dataset_path):
        """Test that PII redaction can be disabled."""
        dataset = MisrouteDataset(path=temp_dataset_path, redact=False)
        
        record = MisrouteRecord(
            user_text="mail at test@visible.com",
            router_route="gmail",
            router_intent="read",
        )
        
        dataset.append(record)
        
        records = dataset.read_all()
        assert "test@visible.com" in records[0].user_text


# ============================================================================
# LOGGING UTILITY TESTS
# ============================================================================

class TestLoggingUtilities:
    """Test logging convenience functions."""
    
    def test_log_misroute(self, temp_dataset_path):
        """Test log_misroute function."""
        with patch("bantz.router.misroute_collector._dataset", 
                   MisrouteDataset(path=temp_dataset_path)):
            record = log_misroute(
                user_text="test input",
                router_route="calendar",
                router_intent="create",
                reason="wrong_route",
            )
            
            assert record.user_text == "test input"
            assert record.reason == "wrong_route"
    
    def test_log_fallback(self, temp_dataset_path):
        """Test log_fallback function."""
        with patch("bantz.router.misroute_collector._dataset",
                   MisrouteDataset(path=temp_dataset_path)):
            record = log_fallback(
                user_text="gibberish input",
                fallback_reason="No matching intent",
            )
            
            assert record.router_route == "unknown"
            assert record.reason == "fallback"
            assert record.fallback_reason == "No matching intent"
    
    def test_log_user_correction(self, temp_dataset_path):
        """Test log_user_correction function."""
        with patch("bantz.router.misroute_collector._dataset",
                   MisrouteDataset(path=temp_dataset_path)):
            record = log_user_correction(
                user_text="yarın toplantım var mı",
                router_route="smalltalk",
                router_intent="greeting",
                expected_route="calendar",
                expected_intent="query",
            )
            
            assert record.router_route == "smalltalk"
            assert record.expected_route == "calendar"
            assert record.reason == "user_correction"


# ============================================================================
# REPLAY TESTS
# ============================================================================

class TestReplay:
    """Test replay functionality."""
    
    def test_replay_result_dataclass(self, sample_record):
        """Test ReplayResult dataclass."""
        result = ReplayResult(
            record=sample_record,
            new_route="calendar",
            new_intent="create",
            new_slots={},
            new_confidence=0.9,
            route_match=True,
            improved=False,
        )
        
        assert result.route_match is True
        assert result.improved is False
    
    def test_replay_result_to_dict(self, sample_record):
        """Test ReplayResult to_dict."""
        result = ReplayResult(
            record=sample_record,
            new_route="calendar",
            new_intent="create",
            new_slots={},
            new_confidence=0.9,
            route_match=True,
            improved=True,
        )
        
        data = result.to_dict()
        
        assert data["new_route"] == "calendar"
        assert data["improved"] is True
    
    def test_replay_summary_to_dict(self):
        """Test ReplaySummary to_dict."""
        summary = ReplaySummary(
            total=10,
            improved=3,
            regressed=1,
            unchanged=6,
            route_accuracy=0.8,
        )
        
        data = summary.to_dict()
        
        assert data["total"] == 10
        assert data["improvement_rate"] == 0.3
        assert data["route_accuracy"] == 0.8
    
    def test_replay_summary_format_markdown(self):
        """Test ReplaySummary markdown formatting."""
        summary = ReplaySummary(
            total=10,
            improved=3,
            regressed=1,
            unchanged=6,
            route_accuracy=0.8,
            intent_accuracy=0.9,
        )
        
        md = summary.format_markdown()
        
        assert "# Router Replay Summary" in md
        assert "Total Records:" in md
        assert "Improved:" in md
        assert "Route Accuracy:" in md
    
    def test_replay_dataset_basic(self, temp_dataset_path):
        """Test basic replay functionality."""
        # Create dataset with records
        dataset = MisrouteDataset(path=temp_dataset_path, redact=False)
        
        dataset.append(MisrouteRecord(
            user_text="saat kaç",
            router_route="unknown",
            router_intent="fallback",
            expected_route="system",
            reason="fallback",
        ))
        dataset.append(MisrouteRecord(
            user_text="merhaba",
            router_route="calendar",
            router_intent="query",
            expected_route="smalltalk",
            reason="wrong_route",
        ))
        
        # Mock router that returns correct routes
        def mock_router(text: str) -> dict:
            if "saat" in text:
                return {"route": "system", "intent": "time", "slots": {}, "confidence": 0.9}
            if "merhaba" in text:
                return {"route": "smalltalk", "intent": "greeting", "slots": {}, "confidence": 0.9}
            return {"route": "unknown", "intent": "fallback", "slots": {}, "confidence": 0.3}
        
        summary = replay_dataset(mock_router, temp_dataset_path)
        
        assert summary.total == 2
        assert summary.improved == 2  # Both now route correctly
        assert summary.route_accuracy == 1.0
    
    def test_replay_with_limit(self, temp_dataset_path):
        """Test replay with record limit."""
        dataset = MisrouteDataset(path=temp_dataset_path, redact=False)
        
        for i in range(10):
            dataset.append(MisrouteRecord(
                user_text=f"test {i}",
                router_route="unknown",
                router_intent="fallback",
                reason="fallback",
            ))
        
        def mock_router(text: str) -> dict:
            return {"route": "unknown", "intent": "fallback", "slots": {}, "confidence": 0.5}
        
        summary = replay_dataset(mock_router, temp_dataset_path, limit=5)
        
        assert summary.total == 5
    
    def test_replay_detects_regression(self, temp_dataset_path):
        """Test that replay detects regressions."""
        dataset = MisrouteDataset(path=temp_dataset_path, redact=False)
        
        # Record where original was correct
        dataset.append(MisrouteRecord(
            user_text="merhaba",
            router_route="smalltalk",  # Was correct
            router_intent="greeting",
            expected_route="smalltalk",
            reason="low_confidence",  # Logged for confidence, not wrong route
        ))
        
        # New router is wrong
        def bad_router(text: str) -> dict:
            return {"route": "calendar", "intent": "query", "slots": {}, "confidence": 0.9}
        
        summary = replay_dataset(bad_router, temp_dataset_path)
        
        assert summary.regressed == 1
        assert summary.improved == 0


# ============================================================================
# STATISTICS TESTS
# ============================================================================

class TestStatistics:
    """Test statistics functionality."""
    
    def test_empty_dataset_stats(self, temp_dataset_path):
        """Test stats for empty dataset."""
        stats = get_dataset_stats(temp_dataset_path)
        
        assert stats["total"] == 0
        assert stats["by_reason"] == {}
    
    def test_dataset_stats(self, temp_dataset_path):
        """Test stats calculation."""
        dataset = MisrouteDataset(path=temp_dataset_path, redact=False)
        
        dataset.append(MisrouteRecord(
            user_text="t1", router_route="calendar", router_intent="",
            reason="wrong_route", model_name="model-a",
        ))
        dataset.append(MisrouteRecord(
            user_text="t2", router_route="calendar", router_intent="",
            reason="fallback", model_name="model-a",
        ))
        dataset.append(MisrouteRecord(
            user_text="t3", router_route="gmail", router_intent="",
            reason="fallback", model_name="model-b",
        ))
        
        stats = get_dataset_stats(temp_dataset_path)
        
        assert stats["total"] == 3
        assert stats["by_reason"]["fallback"] == 2
        assert stats["by_reason"]["wrong_route"] == 1
        assert stats["by_route"]["calendar"] == 2
        assert stats["by_route"]["gmail"] == 1
        assert stats["by_model"]["model-a"] == 2
        assert stats["by_model"]["model-b"] == 1


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for full workflow."""
    
    def test_full_workflow(self, temp_dataset_path):
        """Test complete logging -> replay workflow."""
        # Simulate misroute logging during conversation
        dataset = MisrouteDataset(path=temp_dataset_path)
        
        # Log some misroutes
        dataset.append(MisrouteRecord(
            user_text="yarın toplantım var mı",
            router_route="smalltalk",
            router_intent="greeting",
            expected_route="calendar",
            expected_intent="query",
            reason="wrong_route",
            model_name="qwen-3b",
        ))
        
        dataset.append(MisrouteRecord(
            user_text="ahmet bey'e mail at",
            router_route="unknown",
            router_intent="fallback",
            expected_route="gmail",
            expected_intent="send",
            reason="fallback",
            fallback_reason="No matching pattern",
            model_name="qwen-3b",
        ))
        
        # Verify records are saved
        assert dataset.count() == 2
        
        # Get stats
        stats = get_dataset_stats(temp_dataset_path)
        assert stats["total"] == 2
        assert stats["by_reason"]["wrong_route"] == 1
        assert stats["by_reason"]["fallback"] == 1
        
        # Simulate improved router
        def improved_router(text: str) -> dict:
            if "toplantı" in text or "yarın" in text:
                return {"route": "calendar", "intent": "query", "slots": {}, "confidence": 0.9}
            if "mail" in text:
                return {"route": "gmail", "intent": "send", "slots": {}, "confidence": 0.85}
            return {"route": "unknown", "intent": "fallback", "slots": {}, "confidence": 0.3}
        
        # Replay
        summary = replay_dataset(improved_router, temp_dataset_path)
        
        # Both should be improved
        assert summary.improved == 2
        assert summary.regressed == 0
        assert summary.route_accuracy == 1.0
    
    def test_pii_not_leaked(self, temp_dataset_path):
        """Test that PII is never written to disk."""
        dataset = MisrouteDataset(path=temp_dataset_path)
        
        # Log with PII
        dataset.append(MisrouteRecord(
            user_text="ahmet@secret.com adresine mail at",
            router_route="gmail",
            router_intent="send",
            router_slots={"to": "ahmet@secret.com"},
            notes="User email: ahmet@secret.com",
            reason="wrong_slot",
        ))
        
        # Read raw file
        with open(temp_dataset_path, "r") as f:
            content = f.read()
        
        # PII should be masked
        assert "ahmet@secret.com" not in content
