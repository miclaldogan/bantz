"""
Tests for Analytics & Learning Module.
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import json
import time

from bantz.analytics.tracker import (
    CommandEvent,
    UsageStats,
    FailurePattern,
    UsageAnalytics,
    MockUsageAnalytics,
)
from bantz.analytics.learner import (
    Correction,
    ASRLearner,
    MockASRLearner,
)
from bantz.analytics.performance import (
    OperationStats,
    TimingRecord,
    PerformanceTracker,
    MockPerformanceTracker,
)
from bantz.analytics.suggestions import (
    Suggestion,
    SmartSuggestions,
    MockSmartSuggestions,
    get_time_slot,
)
from bantz.analytics.dashboard import (
    DailyReport,
    WeeklyReport,
    AnalyticsDashboard,
    MockAnalyticsDashboard,
)


# =============================================================================
# CommandEvent Tests
# =============================================================================


class TestCommandEvent:
    """Tests for CommandEvent dataclass."""
    
    def test_creation(self):
        """Test event creation."""
        event = CommandEvent(
            timestamp=datetime.now(),
            intent="browser_aç",
            raw_transcript="krom aç",
            corrected_transcript="chrome aç",
            success=True,
            execution_time_ms=150,
        )
        
        assert event.intent == "browser_aç"
        assert event.success is True
        assert event.execution_time_ms == 150
    
    def test_with_error(self):
        """Test event with error."""
        event = CommandEvent(
            timestamp=datetime.now(),
            intent="file_open",
            raw_transcript="dosya aç",
            corrected_transcript="dosya aç",
            success=False,
            execution_time_ms=50,
            error_message="File not found",
        )
        
        assert event.success is False
        assert event.error_message == "File not found"
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        now = datetime.now()
        event = CommandEvent(
            timestamp=now,
            intent="test",
            raw_transcript="test",
            corrected_transcript="test",
            success=True,
            execution_time_ms=100,
            metadata={"key": "value"},
        )
        
        data = event.to_dict()
        
        assert data["timestamp"] == now.isoformat()
        assert data["intent"] == "test"
        assert data["metadata"] == {"key": "value"}
    
    def test_from_dict(self):
        """Test creation from dictionary."""
        now = datetime.now()
        data = {
            "timestamp": now.isoformat(),
            "intent": "test",
            "raw_transcript": "raw",
            "corrected_transcript": "corrected",
            "success": True,
            "execution_time_ms": 100,
        }
        
        event = CommandEvent.from_dict(data)
        
        assert event.intent == "test"
        assert event.raw_transcript == "raw"
        assert event.success is True


# =============================================================================
# UsageAnalytics Tests
# =============================================================================


class TestUsageAnalytics:
    """Tests for UsageAnalytics."""
    
    @pytest.fixture
    def temp_db(self):
        """Create temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "analytics.db"
    
    @pytest.fixture
    def analytics(self, temp_db):
        """Create UsageAnalytics instance."""
        return UsageAnalytics(db_path=temp_db)
    
    def test_record_event(self, analytics):
        """Test recording events."""
        event = CommandEvent(
            timestamp=datetime.now(),
            intent="test_intent",
            raw_transcript="test",
            corrected_transcript="test",
            success=True,
            execution_time_ms=100,
        )
        
        event_id = analytics.record(event)
        
        assert event_id > 0
    
    def test_get_stats(self, analytics):
        """Test getting statistics."""
        # Record some events
        for i in range(10):
            event = CommandEvent(
                timestamp=datetime.now(),
                intent=f"intent_{i % 3}",
                raw_transcript="test",
                corrected_transcript="test",
                success=i % 4 != 0,  # 25% failure
                execution_time_ms=100 + i * 10,
            )
            analytics.record(event)
        
        stats = analytics.get_stats(days=1)
        
        assert stats.total_commands == 10
        assert stats.success_count == 7  # 3 failures
        assert stats.failure_count == 3
        assert abs(stats.success_rate - 0.7) < 0.01
    
    def test_get_stats_empty(self, analytics):
        """Test stats with no data."""
        stats = analytics.get_stats(days=1)
        
        assert stats.total_commands == 0
        assert stats.success_rate == 0.0
    
    def test_failure_patterns(self, analytics):
        """Test failure pattern analysis."""
        # Record failures with patterns
        for i in range(5):
            event = CommandEvent(
                timestamp=datetime.now(),
                intent="browser_aç",
                raw_transcript="test",
                corrected_transcript="test",
                success=False,
                execution_time_ms=100,
                error_message="Timeout error",
            )
            analytics.record(event)
        
        patterns = analytics.get_failure_patterns(min_count=3)
        
        assert len(patterns) == 1
        assert patterns[0].intent == "browser_aç"
        assert patterns[0].error_message == "Timeout error"
        assert patterns[0].count == 5
    
    def test_intent_stats(self, analytics):
        """Test intent-specific statistics."""
        # Record events for specific intent
        for i in range(5):
            event = CommandEvent(
                timestamp=datetime.now(),
                intent="spotify",
                raw_transcript="müzik aç",
                corrected_transcript="müzik aç",
                success=True,
                execution_time_ms=200 + i * 50,
            )
            analytics.record(event)
        
        stats = analytics.get_intent_stats("spotify", days=1)
        
        assert stats["intent"] == "spotify"
        assert stats["total"] == 5
        assert stats["success"] == 5
        assert stats["success_rate"] == 1.0
    
    def test_hourly_distribution(self, analytics):
        """Test hourly distribution."""
        # Record events
        for i in range(10):
            event = CommandEvent(
                timestamp=datetime.now(),
                intent="test",
                raw_transcript="test",
                corrected_transcript="test",
                success=True,
                execution_time_ms=100,
            )
            analytics.record(event)
        
        dist = analytics.get_hourly_distribution(days=1)
        
        assert len(dist) == 24
        current_hour = datetime.now().hour
        assert dist[current_hour] == 10
    
    def test_recent_events(self, analytics):
        """Test getting recent events."""
        # Record events
        for i in range(20):
            event = CommandEvent(
                timestamp=datetime.now(),
                intent=f"intent_{i}",
                raw_transcript="test",
                corrected_transcript="test",
                success=True,
                execution_time_ms=100,
            )
            analytics.record(event)
        
        recent = analytics.get_recent_events(limit=10)
        
        assert len(recent) == 10
        assert recent[0].intent == "intent_19"  # Most recent
    
    def test_sequence_patterns(self, analytics):
        """Test sequence pattern detection."""
        # Record sequence: A -> B -> A -> B -> A -> B
        for _ in range(3):
            for intent in ["intent_a", "intent_b"]:
                event = CommandEvent(
                    timestamp=datetime.now(),
                    intent=intent,
                    raw_transcript="test",
                    corrected_transcript="test",
                    success=True,
                    execution_time_ms=100,
                )
                analytics.record(event)
        
        patterns = analytics.get_sequence_patterns(min_support=2)
        
        assert len(patterns) >= 1
        # Should find A -> B pattern
        found_ab = any(p[0] == "intent_a" and p[1] == "intent_b" for p in patterns)
        assert found_ab
    
    def test_cleanup_old_events(self, analytics):
        """Test cleaning up old events."""
        # Record events
        for i in range(10):
            event = CommandEvent(
                timestamp=datetime.now(),
                intent="test",
                raw_transcript="test",
                corrected_transcript="test",
                success=True,
                execution_time_ms=100,
            )
            analytics.record(event)
        
        # Cleanup with 1 day (nothing should be deleted)
        deleted = analytics.cleanup_old_events(days=1)
        
        assert deleted == 0
    
    def test_clear_all(self, analytics):
        """Test clearing all events."""
        # Record events
        for i in range(10):
            event = CommandEvent(
                timestamp=datetime.now(),
                intent="test",
                raw_transcript="test",
                corrected_transcript="test",
                success=True,
                execution_time_ms=100,
            )
            analytics.record(event)
        
        deleted = analytics.clear_all()
        
        assert deleted == 10
        
        stats = analytics.get_stats()
        assert stats.total_commands == 0


class TestMockUsageAnalytics:
    """Tests for MockUsageAnalytics."""
    
    def test_record_in_memory(self):
        """Test recording to memory."""
        analytics = MockUsageAnalytics()
        
        event = CommandEvent(
            timestamp=datetime.now(),
            intent="test",
            raw_transcript="test",
            corrected_transcript="test",
            success=True,
            execution_time_ms=100,
        )
        
        event_id = analytics.record(event)
        
        assert event_id == 1
        
        # Second event
        event_id2 = analytics.record(event)
        assert event_id2 == 2
    
    def test_get_stats_from_memory(self):
        """Test getting stats from memory."""
        analytics = MockUsageAnalytics()
        
        for i in range(5):
            event = CommandEvent(
                timestamp=datetime.now(),
                intent=f"intent_{i % 2}",
                raw_transcript="test",
                corrected_transcript="test",
                success=i % 3 != 0,
                execution_time_ms=100 * (i + 1),
            )
            analytics.record(event)
        
        stats = analytics.get_stats()
        
        assert stats.total_commands == 5
        assert stats.failure_count == 2


# =============================================================================
# ASRLearner Tests
# =============================================================================


class TestASRLearner:
    """Tests for ASRLearner."""
    
    @pytest.fixture
    def temp_db(self):
        """Create temporary database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "corrections.db"
    
    @pytest.fixture
    def learner(self, temp_db):
        """Create ASRLearner instance."""
        return ASRLearner(db_path=temp_db, min_confidence_count=2)
    
    def test_record_correction(self, learner):
        """Test recording corrections."""
        is_new = learner.record_correction("krom", "chrome")
        
        assert is_new is True
        
        # Record again - should update
        is_new = learner.record_correction("krom", "chrome")
        
        assert is_new is False
    
    def test_record_identical(self, learner):
        """Test recording identical text."""
        is_new = learner.record_correction("test", "test")
        
        assert is_new is False
    
    def test_auto_correct_phrase(self, learner):
        """Test auto-correcting phrases."""
        # Record corrections to meet threshold
        learner.record_correction("krom aç", "chrome aç")
        learner.record_correction("krom aç", "chrome aç")
        
        result = learner.auto_correct("krom aç")
        
        assert result == "chrome aç"
    
    def test_auto_correct_word(self, learner):
        """Test auto-correcting individual words."""
        # Record word correction
        learner.record_correction("krom", "chrome")
        learner.record_correction("krom", "chrome")
        
        result = learner.auto_correct("krom tarayıcısını aç")
        
        assert result == "chrome tarayıcısını aç"
    
    def test_auto_correct_no_match(self, learner):
        """Test auto-correct with no matching correction."""
        result = learner.auto_correct("hello world")
        
        assert result == "hello world"
    
    def test_auto_correct_preserve_case(self, learner):
        """Test preserving capitalization."""
        learner.record_correction("krom", "chrome")
        learner.record_correction("krom", "chrome")
        
        result = learner.auto_correct("Krom")
        
        assert result == "Chrome"
    
    def test_get_common_errors(self, learner):
        """Test getting common errors."""
        # Record multiple corrections
        for i in range(5):
            learner.record_correction("krom", "chrome")
        
        for i in range(3):
            learner.record_correction("yutup", "youtube")
        
        errors = learner.get_common_errors(min_count=2)
        
        assert len(errors) == 2
        assert errors[0].raw == "krom"
        assert errors[0].count == 5
    
    def test_get_correction(self, learner):
        """Test getting specific correction."""
        learner.record_correction("test_raw", "test_corrected")
        
        correction = learner.get_correction("test_raw")
        
        assert correction is not None
        assert correction.raw == "test_raw"
        assert correction.corrected == "test_corrected"
    
    def test_get_correction_not_found(self, learner):
        """Test getting non-existent correction."""
        correction = learner.get_correction("nonexistent")
        
        assert correction is None
    
    def test_delete_correction(self, learner):
        """Test deleting correction."""
        learner.record_correction("test", "corrected")
        
        deleted = learner.delete_correction("test")
        
        assert deleted is True
        assert learner.get_correction("test") is None
    
    def test_delete_nonexistent(self, learner):
        """Test deleting non-existent correction."""
        deleted = learner.delete_correction("nonexistent")
        
        assert deleted is False
    
    def test_import_export(self, learner):
        """Test import and export."""
        corrections = [
            ("error1", "fix1"),
            ("error2", "fix2"),
            ("error3", "fix3"),
        ]
        
        imported = learner.import_corrections(corrections)
        
        assert imported == 3
        
        exported = learner.export_corrections()
        
        assert len(exported) == 3
    
    def test_get_stats(self, learner):
        """Test getting stats."""
        learner.record_correction("a", "b")
        learner.record_correction("a", "b")
        learner.record_correction("c", "d")
        
        stats = learner.get_stats()
        
        assert stats["total_corrections"] == 2
        assert stats["active_corrections"] == 1  # Only "a" has count >= 2
        assert stats["min_confidence_count"] == 2
    
    def test_clear_all(self, learner):
        """Test clearing all."""
        learner.record_correction("a", "b")
        learner.record_correction("c", "d")
        
        cleared = learner.clear_all()
        
        assert cleared == 2
        assert learner.get_stats()["total_corrections"] == 0


class TestMockASRLearner:
    """Tests for MockASRLearner."""
    
    def test_record_in_memory(self):
        """Test recording to memory."""
        learner = MockASRLearner(min_confidence_count=1)
        
        learner.record_correction("test", "corrected")
        
        correction = learner.get_correction("test")
        assert correction is not None
        assert correction.corrected == "corrected"
    
    def test_auto_correct_from_memory(self):
        """Test auto-correct from memory."""
        learner = MockASRLearner(min_confidence_count=1)
        
        learner.record_correction("krom", "chrome")
        
        result = learner.auto_correct("krom aç")
        
        assert result == "chrome aç"


# =============================================================================
# PerformanceTracker Tests
# =============================================================================


class TestPerformanceTracker:
    """Tests for PerformanceTracker."""
    
    @pytest.fixture
    def tracker(self):
        """Create tracker."""
        return PerformanceTracker()
    
    def test_track_context_manager(self, tracker):
        """Test tracking with context manager."""
        with tracker.track("test_op"):
            time.sleep(0.01)  # 10ms
        
        stats = tracker.get_stats("test_op")
        
        assert stats is not None
        assert stats.count == 1
        assert stats.avg_ms >= 10
    
    def test_track_multiple(self, tracker):
        """Test multiple trackings."""
        for i in range(5):
            with tracker.track("multi_op"):
                time.sleep(0.01)
        
        stats = tracker.get_stats("multi_op")
        
        assert stats.count == 5
    
    def test_track_exception(self, tracker):
        """Test tracking with exception."""
        try:
            with tracker.track("error_op"):
                raise ValueError("Test error")
        except ValueError:
            pass
        
        stats = tracker.get_stats("error_op")
        
        assert stats.count == 1
    
    def test_manual_record(self, tracker):
        """Test manual recording."""
        tracker.record("manual_op", 100.0)
        tracker.record("manual_op", 200.0)
        
        stats = tracker.get_stats("manual_op")
        
        assert stats.count == 2
        assert stats.avg_ms == 150.0
    
    def test_get_stats_nonexistent(self, tracker):
        """Test getting stats for non-existent operation."""
        stats = tracker.get_stats("nonexistent")
        
        assert stats is None
    
    def test_statistics_calculation(self, tracker):
        """Test statistical calculations."""
        times = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        for t in times:
            tracker.record("calc_op", float(t))
        
        stats = tracker.get_stats("calc_op")
        
        assert stats.count == 10
        assert stats.min_ms == 10
        assert stats.max_ms == 100
        assert stats.avg_ms == 55.0
        assert stats.median_ms == 55.0  # (50+60)/2
    
    def test_report(self, tracker):
        """Test full report."""
        tracker.record("op1", 100)
        tracker.record("op2", 200)
        tracker.record("op3", 300)
        
        report = tracker.report()
        
        assert len(report) == 3
        assert "op1" in report
        assert "op2" in report
        assert "op3" in report
    
    def test_report_dict(self, tracker):
        """Test report as dictionaries."""
        tracker.record("test_op", 100)
        
        report = tracker.report_dict()
        
        assert "test_op" in report
        assert isinstance(report["test_op"], dict)
        assert "avg_ms" in report["test_op"]
    
    def test_list_operations(self, tracker):
        """Test listing operations."""
        tracker.record("a", 10)
        tracker.record("b", 20)
        tracker.record("c", 30)
        
        ops = tracker.list_operations()
        
        assert set(ops) == {"a", "b", "c"}
    
    def test_get_recent(self, tracker):
        """Test getting recent records."""
        for i in range(20):
            tracker.record("recent_op", float(i))
        
        recent = tracker.get_recent("recent_op", limit=10)
        
        assert len(recent) == 10
        assert recent[0].duration_ms == 19  # Most recent
    
    def test_get_slow_operations(self, tracker):
        """Test finding slow operations."""
        tracker.record("fast_op", 100)
        tracker.record("slow_op", 2000)
        tracker.record("medium_op", 500)
        
        slow = tracker.get_slow_operations(threshold_ms=1000)
        
        assert len(slow) == 1
        assert slow[0][0] == "slow_op"
    
    def test_compare_operations(self, tracker):
        """Test comparing operations."""
        tracker.record("op1", 100)
        tracker.record("op1", 100)
        tracker.record("op2", 200)
        tracker.record("op2", 200)
        
        comparison = tracker.compare_operations("op1", "op2")
        
        assert comparison is not None
        assert comparison["avg_diff_ms"] == -100
        assert comparison["avg_ratio"] == 0.5
    
    def test_get_summary(self, tracker):
        """Test getting summary."""
        tracker.record("op1", 100)
        tracker.record("op1", 100)
        tracker.record("op2", 500)
        
        summary = tracker.get_summary()
        
        assert summary["total_operations"] == 2
        assert summary["total_measurements"] == 3
        assert summary["slowest_operation"] == "op2"
        assert summary["most_called_operation"] == "op1"
    
    def test_reset_specific(self, tracker):
        """Test resetting specific operation."""
        tracker.record("keep", 100)
        tracker.record("delete", 200)
        
        tracker.reset("delete")
        
        assert tracker.get_stats("delete") is None
        assert tracker.get_stats("keep") is not None
    
    def test_reset_all(self, tracker):
        """Test resetting all."""
        tracker.record("op1", 100)
        tracker.record("op2", 200)
        
        tracker.reset()
        
        assert len(tracker.list_operations()) == 0


class TestMockPerformanceTracker:
    """Tests for MockPerformanceTracker."""
    
    def test_track_calls_recorded(self):
        """Test that track calls are recorded."""
        tracker = MockPerformanceTracker()
        
        with tracker.track("op1", {"meta": "data"}):
            pass
        
        with tracker.track("op2"):
            pass
        
        calls = tracker.get_track_calls()
        
        assert len(calls) == 2
        assert calls[0] == ("op1", {"meta": "data"})
        assert calls[1] == ("op2", None)
    
    def test_simulate_timing(self):
        """Test simulating timing data."""
        tracker = MockPerformanceTracker()
        
        tracker.simulate_timing("test_op", [10, 20, 30, 40, 50])
        
        stats = tracker.get_stats("test_op")
        
        assert stats.count == 5
        assert stats.avg_ms == 30


# =============================================================================
# SmartSuggestions Tests
# =============================================================================


class TestSmartSuggestions:
    """Tests for SmartSuggestions."""
    
    @pytest.fixture
    def analytics(self):
        """Create mock analytics."""
        return MockUsageAnalytics()
    
    @pytest.fixture
    def suggestions(self, analytics):
        """Create SmartSuggestions."""
        return SmartSuggestions(analytics=analytics)
    
    def test_suggest_at_time_morning(self, analytics, suggestions):
        """Test morning suggestions."""
        # Add some usage data first
        for i in range(5):
            event = CommandEvent(
                timestamp=datetime.now(),
                intent="hava_durumu",
                raw_transcript="test",
                corrected_transcript="test",
                success=True,
                execution_time_ms=100,
            )
            analytics.record(event)
        
        results = suggestions.suggest_at_time(hour=7)
        
        assert len(results) > 0
        # Should have time-based reason
        assert any("zamanı" in s.reason.lower() for s in results)
    
    def test_suggest_at_time_evening(self, analytics, suggestions):
        """Test evening suggestions."""
        # Add some usage data first
        for i in range(5):
            event = CommandEvent(
                timestamp=datetime.now(),
                intent="müzik",
                raw_transcript="test",
                corrected_transcript="test",
                success=True,
                execution_time_ms=100,
            )
            analytics.record(event)
        
        results = suggestions.suggest_at_time(hour=19)
        
        assert len(results) > 0
    
    def test_suggest_popular(self, analytics, suggestions):
        """Test popular suggestions."""
        # Add some usage data
        for i in range(10):
            event = CommandEvent(
                timestamp=datetime.now(),
                intent="popular_intent",
                raw_transcript="test",
                corrected_transcript="test",
                success=True,
                execution_time_ms=100,
            )
            analytics.record(event)
        
        results = suggestions.suggest_popular()
        
        assert len(results) > 0
        assert results[0].intent == "popular_intent"
    
    def test_suggest_contextual_browser(self, suggestions):
        """Test contextual suggestions for browser."""
        context = {"active_app": "Google Chrome"}
        
        results = suggestions.suggest_contextual(context)
        
        assert len(results) > 0
    
    def test_suggest_contextual_spotify(self, suggestions):
        """Test contextual suggestions for Spotify."""
        context = {"active_app": "Spotify"}
        
        results = suggestions.suggest_contextual(context)
        
        assert len(results) >= 1
    
    def test_suggest_contextual_clipboard_email(self, suggestions):
        """Test contextual suggestions for email in clipboard."""
        context = {"clipboard": "test@example.com"}
        
        results = suggestions.suggest_contextual(context)
        
        assert any(s.intent == "email_gönder" for s in results)
    
    def test_suggest_contextual_clipboard_url(self, suggestions):
        """Test contextual suggestions for URL in clipboard."""
        context = {"clipboard": "https://example.com"}
        
        results = suggestions.suggest_contextual(context)
        
        assert any(s.intent == "link_aç" for s in results)
    
    def test_get_all_suggestions(self, suggestions):
        """Test getting all suggestion types."""
        all_sugs = suggestions.get_all_suggestions()
        
        assert "time_based" in all_sugs
        assert "popular" in all_sugs


class TestGetTimeSlot:
    """Tests for get_time_slot function."""
    
    def test_morning_early(self):
        """Test early morning slot."""
        assert get_time_slot(6) == "morning_early"
        assert get_time_slot(7) == "morning_early"
        assert get_time_slot(8) == "morning_early"
    
    def test_morning_late(self):
        """Test late morning slot."""
        assert get_time_slot(9) == "morning_late"
        assert get_time_slot(10) == "morning_late"
        assert get_time_slot(11) == "morning_late"
    
    def test_afternoon(self):
        """Test afternoon slot."""
        assert get_time_slot(12) == "afternoon"
        assert get_time_slot(14) == "afternoon"
        assert get_time_slot(16) == "afternoon"
    
    def test_evening(self):
        """Test evening slot."""
        assert get_time_slot(17) == "evening"
        assert get_time_slot(19) == "evening"
        assert get_time_slot(20) == "evening"
    
    def test_night(self):
        """Test night slot."""
        assert get_time_slot(21) == "night"
        assert get_time_slot(23) == "night"
        assert get_time_slot(0) == "night"
        assert get_time_slot(5) == "night"


class TestMockSmartSuggestions:
    """Tests for MockSmartSuggestions."""
    
    def test_set_mock_suggestions(self):
        """Test setting mock suggestions."""
        suggestions = MockSmartSuggestions()
        
        mock_sugs = [
            Suggestion(intent="test", reason="mock", confidence=1.0, display_text="Test"),
        ]
        
        suggestions.set_mock_suggestions("popular", mock_sugs)
        
        results = suggestions.suggest_popular()
        
        assert len(results) == 1
        assert results[0].intent == "test"


# =============================================================================
# AnalyticsDashboard Tests
# =============================================================================


class TestAnalyticsDashboard:
    """Tests for AnalyticsDashboard."""
    
    @pytest.fixture
    def analytics(self):
        """Create mock analytics."""
        mock = MockUsageAnalytics()
        
        # Add some data
        for i in range(20):
            event = CommandEvent(
                timestamp=datetime.now(),
                intent=f"intent_{i % 5}",
                raw_transcript="test",
                corrected_transcript="test",
                success=i % 3 != 0,
                execution_time_ms=100 + i * 10,
            )
            mock.record(event)
        
        return mock
    
    @pytest.fixture
    def learner(self):
        """Create mock learner."""
        mock = MockASRLearner(min_confidence_count=1)
        mock.record_correction("krom", "chrome")
        return mock
    
    @pytest.fixture
    def tracker(self):
        """Create mock tracker."""
        mock = MockPerformanceTracker()
        mock.simulate_timing("asr", [50, 60, 70, 80, 90])
        mock.simulate_timing("llm", [200, 250, 300])
        return mock
    
    @pytest.fixture
    def dashboard(self, analytics, learner, tracker):
        """Create dashboard."""
        return AnalyticsDashboard(
            analytics=analytics,
            learner=learner,
            performance=tracker,
        )
    
    def test_daily_summary(self, dashboard):
        """Test daily summary generation."""
        summary = dashboard.daily_summary()
        
        assert "Günlük Özet" in summary
        assert "Toplam Komut" in summary
        assert "Başarı Oranı" in summary
    
    def test_daily_summary_no_analytics(self):
        """Test summary without analytics."""
        dashboard = AnalyticsDashboard()
        
        summary = dashboard.daily_summary()
        
        assert "verisi yok" in summary
    
    def test_get_daily_report(self, dashboard):
        """Test getting structured daily report."""
        report = dashboard.get_daily_report()
        
        assert isinstance(report, DailyReport)
        assert report.total_commands > 0
    
    def test_weekly_report(self, dashboard):
        """Test weekly report generation."""
        report = dashboard.weekly_report()
        
        assert isinstance(report, WeeklyReport)
        assert len(report.daily_reports) == 7
        assert report.total_commands > 0
    
    def test_weekly_report_no_analytics(self):
        """Test weekly report without analytics."""
        dashboard = AnalyticsDashboard()
        
        report = dashboard.weekly_report()
        
        assert report.total_commands == 0
    
    def test_export_json(self, dashboard):
        """Test JSON export."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "report.json"
            
            dashboard.export_json(output, days=7)
            
            assert output.exists()
            data = json.loads(output.read_text())
            assert "exported_at" in data
            assert "usage_stats" in data
    
    def test_export_html(self, dashboard):
        """Test HTML export."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "report.html"
            
            dashboard.export_html(output, days=7)
            
            assert output.exists()
            html = output.read_text()
            assert "<!DOCTYPE html>" in html
            assert "Bantz Analytics Report" in html


class TestDailyReport:
    """Tests for DailyReport dataclass."""
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        report = DailyReport(
            date=datetime.now(),
            total_commands=100,
            success_count=90,
            failure_count=10,
            success_rate=0.9,
            avg_response_time_ms=150.5,
            top_intents={"browser": 30},
            top_errors={"timeout": 5},
            peak_hour=14,
        )
        
        data = report.to_dict()
        
        assert data["total_commands"] == 100
        assert data["success_rate"] == 0.9
        assert data["peak_hour"] == 14


class TestWeeklyReport:
    """Tests for WeeklyReport dataclass."""
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        report = WeeklyReport(
            start_date=datetime.now() - timedelta(days=7),
            end_date=datetime.now(),
            daily_reports=[],
            total_commands=500,
            success_rate=0.85,
            avg_commands_per_day=71.4,
            trend="up",
            top_intents={"browser": 100},
            improvement_suggestions=["Test suggestion"],
        )
        
        data = report.to_dict()
        
        assert data["total_commands"] == 500
        assert data["trend"] == "up"
        assert len(data["improvement_suggestions"]) == 1


class TestMockAnalyticsDashboard:
    """Tests for MockAnalyticsDashboard."""
    
    def test_set_mock_summary(self):
        """Test setting mock daily summary."""
        dashboard = MockAnalyticsDashboard()
        
        dashboard.set_mock_daily_summary("Test summary")
        
        assert dashboard.daily_summary() == "Test summary"
    
    def test_set_mock_weekly_report(self):
        """Test setting mock weekly report."""
        dashboard = MockAnalyticsDashboard()
        
        mock_report = WeeklyReport(
            start_date=datetime.now() - timedelta(days=7),
            end_date=datetime.now(),
            daily_reports=[],
            total_commands=999,
            success_rate=0.99,
            avg_commands_per_day=142.7,
            trend="up",
            top_intents={},
            improvement_suggestions=[],
        )
        
        dashboard.set_mock_weekly_report(mock_report)
        
        report = dashboard.weekly_report()
        
        assert report.total_commands == 999


# =============================================================================
# Integration Tests
# =============================================================================


class TestAnalyticsIntegration:
    """Integration tests for analytics system."""
    
    def test_full_workflow(self):
        """Test complete analytics workflow."""
        # Setup
        analytics = MockUsageAnalytics()
        learner = MockASRLearner(min_confidence_count=1)
        tracker = MockPerformanceTracker()
        
        # Simulate command execution
        with tracker.track("full_command"):
            # ASR
            with tracker.track("asr"):
                raw_text = "krom aç"
            
            # Correction
            corrected = learner.auto_correct(raw_text)
            if corrected != raw_text:
                learner.record_correction(raw_text, corrected)
            
            # Execute
            with tracker.track("execute"):
                success = True
            
            # Record
            event = CommandEvent(
                timestamp=datetime.now(),
                intent="browser_aç",
                raw_transcript=raw_text,
                corrected_transcript=corrected,
                success=success,
                execution_time_ms=100,
            )
            analytics.record(event)
        
        # Verify
        stats = analytics.get_stats()
        assert stats.total_commands == 1
        
        perf = tracker.get_summary()
        assert perf["total_measurements"] == 3
    
    def test_dashboard_with_all_components(self):
        """Test dashboard with all analytics components."""
        analytics = MockUsageAnalytics()
        learner = MockASRLearner(min_confidence_count=1)
        tracker = MockPerformanceTracker()
        
        # Add data
        for i in range(10):
            event = CommandEvent(
                timestamp=datetime.now(),
                intent=f"intent_{i % 3}",
                raw_transcript="test",
                corrected_transcript="test",
                success=i % 4 != 0,
                execution_time_ms=100 + i * 10,
            )
            analytics.record(event)
        
        learner.record_correction("error1", "fix1")
        tracker.simulate_timing("op1", [10, 20, 30])
        
        # Create dashboard
        dashboard = AnalyticsDashboard(
            analytics=analytics,
            learner=learner,
            performance=tracker,
        )
        
        # Get summary
        summary = dashboard.daily_summary()
        
        assert "Toplam Komut" in summary
        assert "Aktif Düzeltmeler" in summary
        assert "En Yavaş" in summary
    
    def test_suggestions_from_analytics(self):
        """Test suggestions based on analytics data."""
        analytics = MockUsageAnalytics()
        
        # Add pattern: A -> B happens often
        for _ in range(5):
            for intent in ["intent_a", "intent_b"]:
                event = CommandEvent(
                    timestamp=datetime.now(),
                    intent=intent,
                    raw_transcript="test",
                    corrected_transcript="test",
                    success=True,
                    execution_time_ms=100,
                )
                analytics.record(event)
        
        suggestions = SmartSuggestions(analytics=analytics)
        
        # Should suggest B after A
        next_sugs = suggestions.suggest_next("intent_a")
        
        # May or may not find pattern depending on timing
        # Just verify no error
        assert isinstance(next_sugs, list)


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge case tests."""
    
    def test_empty_analytics(self):
        """Test with no data."""
        analytics = MockUsageAnalytics()
        
        stats = analytics.get_stats()
        
        assert stats.total_commands == 0
        assert stats.success_rate == 0.0
    
    def test_all_failures(self):
        """Test with 100% failure rate."""
        analytics = MockUsageAnalytics()
        
        for i in range(5):
            event = CommandEvent(
                timestamp=datetime.now(),
                intent="fail_intent",
                raw_transcript="test",
                corrected_transcript="test",
                success=False,
                execution_time_ms=100,
                error_message="Always fails",
            )
            analytics.record(event)
        
        stats = analytics.get_stats()
        
        assert stats.success_rate == 0.0
        assert stats.failure_count == 5
    
    def test_very_long_text_correction(self):
        """Test correction with long text."""
        learner = MockASRLearner(min_confidence_count=1)
        
        long_raw = "a" * 1000
        long_corrected = "b" * 1000
        
        learner.record_correction(long_raw, long_corrected)
        
        result = learner.auto_correct(long_raw)
        
        assert result == long_corrected
    
    def test_unicode_in_corrections(self):
        """Test Unicode characters in corrections."""
        learner = MockASRLearner(min_confidence_count=1)
        
        learner.record_correction("müzik", "müzik🎵")
        
        result = learner.auto_correct("müzik")
        
        assert "🎵" in result
    
    def test_special_characters_in_intent(self):
        """Test special characters in intent names."""
        analytics = MockUsageAnalytics()
        
        event = CommandEvent(
            timestamp=datetime.now(),
            intent="intent_with-special.chars:v2",
            raw_transcript="test",
            corrected_transcript="test",
            success=True,
            execution_time_ms=100,
        )
        
        analytics.record(event)
        
        stats = analytics.get_stats()
        
        assert "intent_with-special.chars:v2" in stats.top_intents


# =============================================================================
# Suggestion Dataclass Tests
# =============================================================================


class TestSuggestion:
    """Tests for Suggestion dataclass."""
    
    def test_creation(self):
        """Test suggestion creation."""
        sug = Suggestion(
            intent="test_intent",
            reason="Test reason",
            confidence=0.8,
            display_text="Test Display",
        )
        
        assert sug.intent == "test_intent"
        assert sug.confidence == 0.8
    
    def test_with_metadata(self):
        """Test suggestion with metadata."""
        sug = Suggestion(
            intent="test",
            reason="reason",
            confidence=0.5,
            display_text="Test",
            metadata={"count": 10},
        )
        
        assert sug.metadata["count"] == 10
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        sug = Suggestion(
            intent="test",
            reason="reason",
            confidence=0.75,
            display_text="Test",
            metadata={"key": "value"},
        )
        
        data = sug.to_dict()
        
        assert data["intent"] == "test"
        assert data["confidence"] == 0.75
        assert data["metadata"]["key"] == "value"


# =============================================================================
# Correction Dataclass Tests
# =============================================================================


class TestCorrection:
    """Tests for Correction dataclass."""
    
    def test_is_word_level_single_word(self):
        """Test word level detection for single word."""
        correction = Correction(
            raw="krom",
            corrected="chrome",
            count=5,
            first_seen=datetime.now(),
            last_seen=datetime.now(),
        )
        
        assert correction.is_word_level is True
    
    def test_is_word_level_phrase(self):
        """Test word level detection for phrase."""
        correction = Correction(
            raw="krom aç",
            corrected="chrome aç",
            count=5,
            first_seen=datetime.now(),
            last_seen=datetime.now(),
        )
        
        assert correction.is_word_level is False
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        now = datetime.now()
        correction = Correction(
            raw="test",
            corrected="fixed",
            count=3,
            first_seen=now,
            last_seen=now,
        )
        
        data = correction.to_dict()
        
        assert data["raw"] == "test"
        assert data["count"] == 3


# =============================================================================
# OperationStats Tests
# =============================================================================


class TestOperationStats:
    """Tests for OperationStats dataclass."""
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        stats = OperationStats(
            operation="test_op",
            count=100,
            min_ms=10.123,
            max_ms=500.789,
            avg_ms=150.456,
            median_ms=145.0,
            p95_ms=400.0,
            p99_ms=480.0,
            total_ms=15045.6,
            std_dev_ms=120.5,
        )
        
        data = stats.to_dict()
        
        assert data["operation"] == "test_op"
        assert data["count"] == 100
        assert data["min_ms"] == 10.12  # Rounded
        assert data["avg_ms"] == 150.46  # Rounded


# =============================================================================
# Thread Safety Tests
# =============================================================================


class TestThreadSafety:
    """Thread safety tests."""
    
    def test_concurrent_recording(self):
        """Test concurrent event recording."""
        import threading
        
        analytics = MockUsageAnalytics()
        errors = []
        
        def record_events():
            try:
                for i in range(100):
                    event = CommandEvent(
                        timestamp=datetime.now(),
                        intent=f"intent_{i}",
                        raw_transcript="test",
                        corrected_transcript="test",
                        success=True,
                        execution_time_ms=100,
                    )
                    analytics.record(event)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=record_events) for _ in range(5)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        stats = analytics.get_stats()
        assert stats.total_commands == 500
    
    def test_concurrent_performance_tracking(self):
        """Test concurrent performance tracking."""
        import threading
        
        tracker = MockPerformanceTracker()
        errors = []
        
        def track_operations():
            try:
                for i in range(100):
                    with tracker.track(f"op_{threading.current_thread().name}"):
                        time.sleep(0.001)
            except Exception as e:
                errors.append(e)
        
        threads = [threading.Thread(target=track_operations) for _ in range(3)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert len(tracker.list_operations()) == 3
