"""Comprehensive tests for the Proactive Intelligence Engine (Issue #835).

Tests cover:
- Data models (CheckSchedule, Insight, Suggestion, CrossAnalysis, etc.)
- ProactiveCheck lifecycle
- NotificationPolicy filtering
- NotificationQueue queueing + rate limiting + dedup
- Built-in checks (morning briefing, weather×calendar, email digest)
- CrossAnalyzer rules
- ProactiveEngine orchestration
- CLI commands
"""
from __future__ import annotations

import argparse
import json
import time
import threading
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ── Models under test ──────────────────────────────────────────

from bantz.proactive.models import (
    CheckResult,
    CheckSchedule,
    CrossAnalysis,
    Insight,
    InsightSeverity,
    NotificationPolicy,
    ProactiveCheck,
    ProactiveNotification,
    ScheduleType,
    Suggestion,
    _next_cron_run,
    _parse_cron_field,
)


# ================================================================
# Test: ScheduleType & CheckSchedule
# ================================================================


class TestCheckSchedule:
    """Tests for CheckSchedule model."""

    def test_daily_at_shortcut(self):
        s = CheckSchedule.daily_at(8, 30)
        assert s.type == ScheduleType.DAILY
        assert s.time_of_day == dt_time(8, 30)
        assert s.enabled is True

    def test_every_shortcut(self):
        s = CheckSchedule.every(hours=2)
        assert s.type == ScheduleType.INTERVAL
        assert s.interval_seconds == 7200

    def test_every_minimum_60s(self):
        s = CheckSchedule.every(seconds=10)
        assert s.interval_seconds == 60  # Min 60s

    def test_on_event_shortcut(self):
        s = CheckSchedule.on_event("calendar_changed")
        assert s.type == ScheduleType.EVENT
        assert s.event_type == "calendar_changed"

    def test_daily_next_run_after(self):
        s = CheckSchedule.daily_at(8, 0)
        # If it's past 08:00, next run is tomorrow
        now = datetime(2026, 2, 11, 10, 0)
        nxt = s.next_run_after(now)
        assert nxt is not None
        assert nxt.hour == 8
        assert nxt.minute == 0
        assert nxt.day == 12  # Tomorrow

    def test_daily_next_run_before_time(self):
        s = CheckSchedule.daily_at(20, 0)
        now = datetime(2026, 2, 11, 10, 0)
        nxt = s.next_run_after(now)
        assert nxt is not None
        assert nxt.day == 11  # Today (20:00 hasn't passed)
        assert nxt.hour == 20

    def test_interval_next_run(self):
        s = CheckSchedule.every(hours=1)
        now = datetime(2026, 2, 11, 10, 0)
        nxt = s.next_run_after(now)
        assert nxt == now + timedelta(hours=1)

    def test_event_no_scheduled_time(self):
        s = CheckSchedule.on_event("test_event")
        nxt = s.next_run_after(datetime.now())
        assert nxt is None

    def test_to_dict_from_dict_roundtrip(self):
        s = CheckSchedule.daily_at(8, 0)
        d = s.to_dict()
        s2 = CheckSchedule.from_dict(d)
        assert s2.type == ScheduleType.DAILY
        assert s2.time_of_day == dt_time(8, 0)


# ================================================================
# Test: Insight & Suggestion
# ================================================================


class TestInsightSuggestion:
    """Tests for Insight and Suggestion models."""

    def test_insight_icon(self):
        assert Insight(message="test", severity=InsightSeverity.INFO).icon == "ℹ️"
        assert Insight(message="test", severity=InsightSeverity.WARNING).icon == "⚠️"
        assert Insight(message="test", severity=InsightSeverity.CRITICAL).icon == "🚨"

    def test_insight_to_dict(self):
        insight = Insight(
            message="Test insight",
            severity=InsightSeverity.WARNING,
            source_tools=["tool_a", "tool_b"],
            data={"key": "value"},
        )
        d = insight.to_dict()
        assert d["severity"] == "warning"
        assert d["source_tools"] == ["tool_a", "tool_b"]

    def test_suggestion_to_dict(self):
        suggestion = Suggestion(
            text="Do something",
            action="calendar.update_event",
            action_params={"id": "123"},
            auto_applicable=True,
        )
        d = suggestion.to_dict()
        assert d["auto_applicable"] is True
        assert d["action"] == "calendar.update_event"


# ================================================================
# Test: CrossAnalysis
# ================================================================


class TestCrossAnalysis:
    """Tests for CrossAnalysis model."""

    def test_has_warnings_true(self):
        analysis = CrossAnalysis(
            check_name="test",
            insights=[
                Insight(message="info", severity=InsightSeverity.INFO),
                Insight(message="warn", severity=InsightSeverity.WARNING),
            ],
        )
        assert analysis.has_warnings is True

    def test_has_warnings_false(self):
        analysis = CrossAnalysis(
            check_name="test",
            insights=[Insight(message="info", severity=InsightSeverity.INFO)],
        )
        assert analysis.has_warnings is False

    def test_max_severity(self):
        analysis = CrossAnalysis(
            check_name="test",
            insights=[
                Insight(message="info", severity=InsightSeverity.INFO),
                Insight(message="critical", severity=InsightSeverity.CRITICAL),
                Insight(message="warn", severity=InsightSeverity.WARNING),
            ],
        )
        assert analysis.max_severity == InsightSeverity.CRITICAL

    def test_empty_insights(self):
        analysis = CrossAnalysis(check_name="test")
        assert analysis.has_warnings is False
        assert analysis.max_severity == InsightSeverity.INFO

    def test_to_dict(self):
        analysis = CrossAnalysis(
            check_name="test",
            insights=[Insight(message="hello", severity=InsightSeverity.INFO)],
            suggestions=[Suggestion(text="do this")],
            tool_results={"calendar": {"events": []}},
        )
        d = analysis.to_dict()
        assert d["check_name"] == "test"
        assert len(d["insights"]) == 1
        assert len(d["suggestions"]) == 1


# ================================================================
# Test: CheckResult
# ================================================================


class TestCheckResult:
    """Tests for CheckResult model."""

    def test_basic_result(self):
        result = CheckResult(check_name="test", ok=True, summary="All good")
        assert result.ok is True
        assert result.check_name == "test"

    def test_error_result(self):
        result = CheckResult(check_name="test", ok=False, error="Tool failed")
        assert result.ok is False
        assert result.error == "Tool failed"

    def test_to_dict(self):
        result = CheckResult(check_name="test", ok=True, summary="OK", duration_ms=42.5)
        d = result.to_dict()
        assert d["duration_ms"] == 42.5


# ================================================================
# Test: ProactiveCheck
# ================================================================


class TestProactiveCheck:
    """Tests for ProactiveCheck model."""

    def test_is_due_when_past(self):
        check = ProactiveCheck(
            name="test",
            description="Test check",
            schedule=CheckSchedule.daily_at(8, 0),
            next_run=datetime(2026, 2, 11, 8, 0),
        )
        assert check.is_due(datetime(2026, 2, 11, 8, 1)) is True

    def test_is_due_when_future(self):
        check = ProactiveCheck(
            name="test",
            description="Test check",
            schedule=CheckSchedule.daily_at(20, 0),
            next_run=datetime(2026, 2, 11, 20, 0),
        )
        assert check.is_due(datetime(2026, 2, 11, 10, 0)) is False

    def test_is_due_when_disabled(self):
        check = ProactiveCheck(
            name="test",
            description="Test check",
            schedule=CheckSchedule.daily_at(8, 0),
            enabled=False,
            next_run=datetime(2026, 2, 11, 8, 0),
        )
        assert check.is_due(datetime(2026, 2, 11, 9, 0)) is False

    def test_is_due_event_based(self):
        check = ProactiveCheck(
            name="test",
            description="Test check",
            schedule=CheckSchedule.on_event("something"),
        )
        assert check.is_due() is False  # Event-based never "due" by time

    def test_update_next_run(self):
        check = ProactiveCheck(
            name="test",
            description="Test check",
            schedule=CheckSchedule.daily_at(8, 0),
        )
        now = datetime(2026, 2, 11, 8, 0)
        check.update_next_run(now)
        assert check.last_run == now
        assert check.next_run is not None
        assert check.next_run > now

    def test_to_dict(self):
        check = ProactiveCheck(
            name="test",
            description="Desc",
            schedule=CheckSchedule.daily_at(8, 0),
            tags=["daily"],
        )
        d = check.to_dict()
        assert d["name"] == "test"
        assert "daily" in d["tags"]


# ================================================================
# Test: NotificationPolicy
# ================================================================


class TestNotificationPolicy:
    """Tests for NotificationPolicy."""

    def test_default_policy(self):
        policy = NotificationPolicy()
        assert policy.min_severity == InsightSeverity.INFO
        assert policy.dnd is False

    def test_should_notify_above_threshold(self):
        policy = NotificationPolicy(min_severity=InsightSeverity.WARNING)
        assert policy.should_notify(InsightSeverity.WARNING) is True
        assert policy.should_notify(InsightSeverity.CRITICAL) is True
        assert policy.should_notify(InsightSeverity.INFO) is False

    def test_dnd_blocks_all(self):
        policy = NotificationPolicy(dnd=True)
        assert policy.should_notify(InsightSeverity.CRITICAL) is False

    def test_quiet_hours_overnight(self):
        policy = NotificationPolicy(
            quiet_start=dt_time(23, 0),
            quiet_end=dt_time(7, 0),
        )
        # 2 AM → should be quiet
        assert policy.is_quiet_time(datetime(2026, 2, 11, 2, 0)) is True
        # 10 AM → not quiet
        assert policy.is_quiet_time(datetime(2026, 2, 11, 10, 0)) is False

    def test_quiet_hours_daytime(self):
        policy = NotificationPolicy(
            quiet_start=dt_time(12, 0),
            quiet_end=dt_time(14, 0),
        )
        # 13:00 → quiet
        assert policy.is_quiet_time(datetime(2026, 2, 11, 13, 0)) is True
        # 15:00 → not quiet
        assert policy.is_quiet_time(datetime(2026, 2, 11, 15, 0)) is False

    def test_to_dict_from_dict_roundtrip(self):
        policy = NotificationPolicy(
            min_severity=InsightSeverity.WARNING,
            quiet_start=dt_time(23, 0),
            quiet_end=dt_time(7, 0),
            max_notifications_per_hour=5,
        )
        d = policy.to_dict()
        p2 = NotificationPolicy.from_dict(d)
        assert p2.min_severity == InsightSeverity.WARNING
        assert p2.quiet_start == dt_time(23, 0)
        assert p2.max_notifications_per_hour == 5


# ================================================================
# Test: ProactiveNotification
# ================================================================


class TestProactiveNotification:
    """Tests for ProactiveNotification."""

    def test_format_text(self):
        n = ProactiveNotification(
            title="Test",
            body="Hello world",
            severity=InsightSeverity.WARNING,
            suggestions=[Suggestion(text="Do this")],
        )
        text = n.format_text()
        assert "⚠️" in text
        assert "Hello world" in text
        assert "Do this" in text

    def test_icon(self):
        assert ProactiveNotification(severity=InsightSeverity.INFO).icon == "ℹ️"
        assert ProactiveNotification(severity=InsightSeverity.CRITICAL).icon == "🚨"

    def test_to_dict(self):
        n = ProactiveNotification(
            id=1, check_name="test", title="T", body="B",
            severity=InsightSeverity.INFO,
        )
        d = n.to_dict()
        assert d["id"] == 1
        assert d["severity"] == "info"


# ================================================================
# Test: Cron Helpers
# ================================================================


class TestCronHelpers:
    """Tests for cron expression parsing."""

    def test_parse_cron_field_star(self):
        assert _parse_cron_field("*", 0, 23) == list(range(24))

    def test_parse_cron_field_single(self):
        assert _parse_cron_field("5", 0, 59) == [5]

    def test_parse_cron_field_comma(self):
        assert _parse_cron_field("0,30", 0, 59) == [0, 30]

    def test_parse_cron_field_step(self):
        assert _parse_cron_field("*/15", 0, 59) == [0, 15, 30, 45]

    def test_parse_cron_field_range(self):
        assert _parse_cron_field("8-12", 0, 23) == [8, 9, 10, 11, 12]

    def test_next_cron_run(self):
        # "0 8 * * *" → daily at 08:00
        after = datetime(2026, 2, 11, 7, 30)
        nxt = _next_cron_run("0 8 * * *", after)
        assert nxt is not None
        assert nxt.hour == 8
        assert nxt.minute == 0

    def test_next_cron_run_past(self):
        # "0 8 * * *" → if past 08:00, should be tomorrow
        after = datetime(2026, 2, 11, 9, 0)
        nxt = _next_cron_run("0 8 * * *", after)
        assert nxt is not None
        assert nxt.day == 12  # Tomorrow

    def test_cron_multi_hour(self):
        # "0 8,20 * * *" → at 08:00 and 20:00
        after = datetime(2026, 2, 11, 9, 0)
        nxt = _next_cron_run("0 8,20 * * *", after)
        assert nxt is not None
        assert nxt.hour == 20
        assert nxt.day == 11  # Today at 20:00


# ================================================================
# Test: NotificationQueue
# ================================================================


class TestNotificationQueue:
    """Tests for NotificationQueue."""

    def _make_result(self, insights=None, suggestions=None, severity=InsightSeverity.INFO):
        analysis = CrossAnalysis(
            check_name="test",
            insights=insights or [Insight(message="Test", severity=severity)],
            suggestions=suggestions or [],
        )
        return CheckResult(
            check_name="test",
            ok=True,
            summary="Test summary",
            analysis=analysis,
        )

    def test_submit_queues_notification(self):
        from bantz.proactive.notification_queue import NotificationQueue

        nq = NotificationQueue(policy=NotificationPolicy())
        result = self._make_result()
        queued = nq.submit(result)
        assert len(queued) >= 1
        assert nq.size >= 1

    def test_submit_respects_dnd(self):
        from bantz.proactive.notification_queue import NotificationQueue

        policy = NotificationPolicy(dnd=True)
        nq = NotificationQueue(policy=policy)
        result = self._make_result()
        queued = nq.submit(result)
        assert len(queued) == 0

    def test_get_unread_count(self):
        from bantz.proactive.notification_queue import NotificationQueue

        nq = NotificationQueue(policy=NotificationPolicy(desktop_notifications=False))
        result = self._make_result()
        nq.submit(result)
        assert nq.get_unread_count() >= 1

    def test_mark_read(self):
        from bantz.proactive.notification_queue import NotificationQueue

        nq = NotificationQueue(policy=NotificationPolicy(desktop_notifications=False))
        result = self._make_result()
        queued = nq.submit(result)
        assert len(queued) >= 1
        nq.mark_read(queued[0].id)
        assert nq.get_unread_count() == len(queued) - 1

    def test_mark_all_read(self):
        from bantz.proactive.notification_queue import NotificationQueue

        nq = NotificationQueue(policy=NotificationPolicy(desktop_notifications=False))
        nq.submit(self._make_result())
        nq.submit(self._make_result(
            insights=[Insight(message="Another", severity=InsightSeverity.INFO)]
        ))
        count = nq.mark_all_read()
        assert count >= 1
        assert nq.get_unread_count() == 0

    def test_clear(self):
        from bantz.proactive.notification_queue import NotificationQueue

        nq = NotificationQueue(policy=NotificationPolicy(desktop_notifications=False))
        nq.submit(self._make_result())
        count = nq.clear()
        assert count >= 1
        assert nq.size == 0

    def test_severity_filtering(self):
        from bantz.proactive.notification_queue import NotificationQueue

        policy = NotificationPolicy(
            min_severity=InsightSeverity.WARNING,
            desktop_notifications=False,
        )
        nq = NotificationQueue(policy=policy)
        # INFO should be filtered out
        info_result = self._make_result(severity=InsightSeverity.INFO)
        queued_info = nq.submit(info_result)
        assert len(queued_info) == 0

        # WARNING should pass
        warn_result = self._make_result(
            insights=[Insight(message="Warn", severity=InsightSeverity.WARNING)],
            severity=InsightSeverity.WARNING,
        )
        queued_warn = nq.submit(warn_result)
        assert len(queued_warn) >= 1

    def test_rate_limiting(self):
        from bantz.proactive.notification_queue import NotificationQueue

        policy = NotificationPolicy(
            max_notifications_per_hour=3,
            cooldown_seconds=0,
            desktop_notifications=False,
            group_similar=False,
        )
        nq = NotificationQueue(policy=policy)
        total_queued = 0
        for i in range(5):
            n = ProactiveNotification(
                check_name="test",
                title="Test",
                body=f"Notification {i}",
                severity=InsightSeverity.INFO,
            )
            if nq.submit_notification(n):
                total_queued += 1
        assert total_queued == 3  # Limited to 3 per hour

    def test_dedup(self):
        from bantz.proactive.notification_queue import NotificationQueue

        policy = NotificationPolicy(
            group_similar=True,
            cooldown_seconds=0,
            desktop_notifications=False,
        )
        nq = NotificationQueue(policy=policy)
        n1 = ProactiveNotification(body="Same message", severity=InsightSeverity.INFO)
        n2 = ProactiveNotification(body="Same message", severity=InsightSeverity.INFO)
        assert nq.submit_notification(n1) is True
        assert nq.submit_notification(n2) is False  # Duplicate

    def test_event_bus_publish(self):
        from bantz.proactive.notification_queue import NotificationQueue

        mock_bus = MagicMock()
        nq = NotificationQueue(
            policy=NotificationPolicy(desktop_notifications=False),
            event_bus=mock_bus,
        )
        result = self._make_result()
        nq.submit(result)
        mock_bus.publish.assert_called()
        call_kwargs = mock_bus.publish.call_args
        assert call_kwargs[1].get("source") == "proactive" or \
               (len(call_kwargs[0]) >= 1 and "bantz_message" in str(call_kwargs))


# ================================================================
# Test: Built-in Checks
# ================================================================


class TestBuiltinChecks:
    """Tests for built-in proactive check handlers."""

    def _mock_tool_registry(self, tool_results: Dict[str, Any] = None):
        """Create a mock tool registry."""
        results = tool_results or {}
        registry = MagicMock()

        def get_tool(name: str):
            tool = MagicMock()
            tool.handler = MagicMock(return_value=results.get(name, {"ok": False, "error": "not configured"}))
            return tool

        registry.get = get_tool
        return registry

    def test_morning_briefing_handler(self):
        from bantz.proactive.checks import morning_briefing_handler

        registry = self._mock_tool_registry({
            "calendar.list_events": {"ok": True, "events": [
                {"summary": "Standup", "start": "09:00"},
                {"summary": "1:1", "start": "14:00"},
            ]},
            "weather.get_current": {"ok": True, "data": {
                "temperature": 15, "condition": "Partly cloudy",
            }},
            "gmail.unread_count": {"ok": True, "unread": 5},
        })

        check = ProactiveCheck(
            name="morning_briefing",
            description="Test",
            schedule=CheckSchedule.daily_at(8, 0),
        )
        result = morning_briefing_handler(check, {"tool_registry": registry})

        assert result.ok is True
        assert result.analysis is not None
        assert len(result.analysis.insights) >= 3  # calendar + weather + mail
        assert "Günaydın" in result.summary

    def test_morning_briefing_weather_calendar_cross(self):
        from bantz.proactive.checks import morning_briefing_handler

        registry = self._mock_tool_registry({
            "calendar.list_events": {"ok": True, "events": [
                {"summary": "Park buluşması", "start": "14:00", "location": "Maçka Parkı"},
            ]},
            "weather.get_current": {"ok": True, "data": {
                "temperature": 8, "condition": "Yağmur",
            }},
            "gmail.unread_count": {"ok": True, "unread": 0},
        })

        check = ProactiveCheck(
            name="morning_briefing",
            description="Test",
            schedule=CheckSchedule.daily_at(8, 0),
        )
        result = morning_briefing_handler(check, {"tool_registry": registry})

        assert result.ok is True
        # Should detect outdoor + rain
        warnings = [i for i in result.analysis.insights if i.severity == InsightSeverity.WARNING]
        assert len(warnings) >= 1
        assert len(result.analysis.suggestions) >= 1

    def test_weather_calendar_handler_no_conflict(self):
        from bantz.proactive.checks import weather_calendar_handler

        registry = self._mock_tool_registry({
            "calendar.list_events": {"ok": True, "events": [
                {"summary": "Online meeting", "start": "10:00"},
            ]},
            "weather.get_current": {"ok": True, "data": {
                "temperature": 20, "condition": "Sunny",
            }},
        })

        check = ProactiveCheck(
            name="weather_calendar",
            description="Test",
            schedule=CheckSchedule.every(hours=3),
        )
        result = weather_calendar_handler(check, {"tool_registry": registry})

        assert result.ok is True
        assert result.analysis is not None
        # No warnings since no outdoor events + bad weather
        assert not result.analysis.has_warnings

    def test_email_digest_handler(self):
        from bantz.proactive.checks import email_digest_handler

        registry = self._mock_tool_registry({
            "gmail.unread_count": {"ok": True, "unread": 25},
        })

        check = ProactiveCheck(
            name="email_digest",
            description="Test",
            schedule=CheckSchedule.every(hours=2),
        )
        result = email_digest_handler(check, {"tool_registry": registry})

        assert result.ok is True
        assert result.analysis is not None
        # High unread → should be critical
        assert result.analysis.insights[0].severity == InsightSeverity.CRITICAL

    def test_email_digest_zero(self):
        from bantz.proactive.checks import email_digest_handler

        registry = self._mock_tool_registry({
            "gmail.unread_count": {"ok": True, "unread": 0},
        })

        check = ProactiveCheck(
            name="email_digest",
            description="Test",
            schedule=CheckSchedule.every(hours=2),
        )
        result = email_digest_handler(check, {"tool_registry": registry})

        assert result.ok is True
        assert "inbox sıfır" in result.summary.lower() or "okunmamış mail yok" in result.summary.lower()

    def test_no_tool_registry(self):
        from bantz.proactive.checks import morning_briefing_handler

        check = ProactiveCheck(
            name="test",
            description="Test",
            schedule=CheckSchedule.daily_at(8, 0),
        )
        result = morning_briefing_handler(check, {})
        assert result.ok is False

    def test_get_builtin_checks(self):
        from bantz.proactive.checks import get_builtin_checks

        checks = get_builtin_checks()
        assert len(checks) >= 3
        names = {c.name for c in checks}
        assert "morning_briefing" in names
        assert "weather_calendar" in names
        assert "email_digest" in names


# ================================================================
# Test: CrossAnalyzer
# ================================================================


class TestCrossAnalyzer:
    """Tests for CrossAnalyzer."""

    def test_builtin_rules_registered(self):
        from bantz.proactive.cross_analyzer import CrossAnalyzer

        analyzer = CrossAnalyzer()
        assert "high_email_volume" in analyzer.rule_names
        assert "busy_calendar_day" in analyzer.rule_names
        assert "weather_extreme" in analyzer.rule_names

    def test_add_remove_rule(self):
        from bantz.proactive.cross_analyzer import CrossAnalyzer

        analyzer = CrossAnalyzer()
        analyzer.add_rule("custom", lambda data: ([], []))
        assert "custom" in analyzer.rule_names
        assert analyzer.remove_rule("custom") is True
        assert "custom" not in analyzer.rule_names

    def test_analyze_high_email(self):
        from bantz.proactive.cross_analyzer import CrossAnalyzer

        analyzer = CrossAnalyzer()
        analysis = analyzer.analyze("test", {
            "mail": {"unread": 30},
        }, rules=["high_email_volume"])

        assert len(analysis.insights) >= 1
        assert any("mail" in i.message.lower() or "30" in i.message for i in analysis.insights)

    def test_analyze_busy_day(self):
        from bantz.proactive.cross_analyzer import CrossAnalyzer

        analyzer = CrossAnalyzer()
        analysis = analyzer.analyze("test", {
            "calendar": {"events": [{"summary": f"Event {i}"} for i in range(6)]},
        }, rules=["busy_calendar_day"])

        assert len(analysis.insights) >= 1
        assert analysis.has_warnings

    def test_analyze_extreme_weather(self):
        from bantz.proactive.cross_analyzer import CrossAnalyzer

        analyzer = CrossAnalyzer()
        analysis = analyzer.analyze("test", {
            "weather": {"data": {"temperature": -15, "condition": "Snow"}},
        }, rules=["weather_extreme"])

        assert len(analysis.insights) >= 1
        critical = [i for i in analysis.insights if i.severity == InsightSeverity.CRITICAL]
        assert len(critical) >= 1

    def test_analyze_storm_warning(self):
        from bantz.proactive.cross_analyzer import CrossAnalyzer

        analyzer = CrossAnalyzer()
        analysis = analyzer.analyze("test", {
            "weather": {"data": {"temperature": 25, "condition": "Thunderstorm"}},
        }, rules=["weather_extreme"])

        assert len(analysis.insights) >= 1
        assert any("fırtına" in i.message.lower() or "storm" in i.message.lower() for i in analysis.insights)

    def test_analyze_no_data(self):
        from bantz.proactive.cross_analyzer import CrossAnalyzer

        analyzer = CrossAnalyzer()
        analysis = analyzer.analyze("test", {})
        # Should not crash, may have 0 insights
        assert isinstance(analysis, CrossAnalysis)

    def test_rule_failure_handled(self):
        from bantz.proactive.cross_analyzer import CrossAnalyzer

        analyzer = CrossAnalyzer()

        def broken_rule(data):
            raise ValueError("broken!")

        analyzer.add_rule("broken", broken_rule)
        analysis = analyzer.analyze("test", {}, rules=["broken"])
        # Should capture error as insight
        assert len(analysis.insights) >= 1
        assert "broken" in analysis.insights[0].message.lower()


# ================================================================
# Test: ProactiveEngine
# ================================================================


class TestProactiveEngine:
    """Tests for ProactiveEngine."""

    def _make_engine(self, **kwargs):
        from bantz.proactive.engine import ProactiveEngine

        return ProactiveEngine(
            config_path=Path("/tmp/bantz_test_proactive.json"),
            **kwargs,
        )

    def test_init_registers_builtins(self):
        engine = self._make_engine()
        checks = engine.get_all_checks()
        assert len(checks) >= 3
        names = {c.name for c in checks}
        assert "morning_briefing" in names

    def test_register_custom_check(self):
        engine = self._make_engine()

        def custom_handler(check, ctx):
            return CheckResult(check_name=check.name, ok=True, summary="Custom!")

        custom = ProactiveCheck(
            name="custom_check",
            description="Custom test",
            schedule=CheckSchedule.every(hours=1),
            handler=custom_handler,
        )
        engine.register_check(custom)
        assert engine.get_check("custom_check") is not None

    def test_unregister_check(self):
        engine = self._make_engine()
        assert engine.unregister_check("morning_briefing") is True
        assert engine.get_check("morning_briefing") is None
        assert engine.unregister_check("nonexistent") is False

    def test_enable_disable_check(self):
        engine = self._make_engine()
        engine.disable_check("morning_briefing")
        assert engine.get_check("morning_briefing").enabled is False
        engine.enable_check("morning_briefing")
        assert engine.get_check("morning_briefing").enabled is True

    def test_run_check_manually(self):
        engine = self._make_engine()

        def simple_handler(check, ctx):
            return CheckResult(
                check_name=check.name,
                ok=True,
                summary="Manual run!",
                analysis=CrossAnalysis(
                    check_name=check.name,
                    insights=[Insight(message="Test insight", severity=InsightSeverity.INFO)],
                ),
            )

        custom = ProactiveCheck(
            name="manual_test",
            description="Manual test",
            schedule=CheckSchedule.every(hours=1),
            handler=simple_handler,
        )
        engine.register_check(custom)
        result = engine.run_check("manual_test")
        assert result is not None
        assert result.ok is True
        assert "Manual run" in result.summary

    def test_run_nonexistent_check(self):
        engine = self._make_engine()
        result = engine.run_check("nonexistent")
        assert result is None

    def test_get_status(self):
        engine = self._make_engine()
        status = engine.get_status()
        assert "running" in status
        assert "checks" in status
        assert "total_checks" in status
        assert status["total_checks"] >= 3

    def test_dnd_toggle(self):
        engine = self._make_engine()
        engine.set_dnd(True)
        assert engine.policy.dnd is True
        engine.set_dnd(False)
        assert engine.policy.dnd is False

    def test_history_tracking(self):
        engine = self._make_engine()

        def tracked_handler(check, ctx):
            return CheckResult(
                check_name=check.name,
                ok=True,
                summary="Tracked!",
                analysis=CrossAnalysis(
                    check_name=check.name,
                    insights=[Insight(message="Insight", severity=InsightSeverity.INFO)],
                ),
            )

        custom = ProactiveCheck(
            name="history_test",
            description="History test",
            schedule=CheckSchedule.every(hours=1),
            handler=tracked_handler,
        )
        engine.register_check(custom)
        engine.run_check("history_test")
        engine.run_check("history_test")

        history = engine.get_history("history_test")
        assert len(history) == 2

    def test_start_stop(self):
        engine = self._make_engine()
        engine.start()
        assert engine.is_running is True
        time.sleep(0.1)
        engine.stop()
        assert engine.is_running is False

    def test_start_idempotent(self):
        engine = self._make_engine()
        engine.start()
        engine.start()  # Should not crash
        assert engine.is_running is True
        engine.stop()

    def test_run_all_checks_with_handler(self):
        engine = self._make_engine()
        # Unregister builtins and add a simple one
        for name in list(engine._checks.keys()):
            engine.unregister_check(name)

        def all_handler(check, ctx):
            return CheckResult(check_name=check.name, ok=True, summary="OK")

        engine.register_check(ProactiveCheck(
            name="check_a", description="A",
            schedule=CheckSchedule.every(hours=1),
            handler=all_handler,
        ))
        engine.register_check(ProactiveCheck(
            name="check_b", description="B",
            schedule=CheckSchedule.every(hours=1),
            handler=all_handler,
        ))

        results = engine.run_all_checks()
        assert len(results) == 2

    def test_check_handler_exception_handled(self):
        engine = self._make_engine()

        def broken_handler(check, ctx):
            raise RuntimeError("Boom!")

        engine.register_check(ProactiveCheck(
            name="broken",
            description="Broken",
            schedule=CheckSchedule.every(hours=1),
            handler=broken_handler,
        ))

        result = engine.run_check("broken")
        assert result is not None
        assert result.ok is False
        assert "Boom" in result.error


# ================================================================
# Test: CLI
# ================================================================


class TestCLI:
    """Tests for proactive CLI commands."""

    def test_cmd_status(self):
        from bantz.proactive.cli import handle_proactive_command

        args = argparse.Namespace(
            proactive_action="status",
            as_json=True,
        )
        result = handle_proactive_command(args)
        assert result == 0

    def test_cmd_list(self):
        from bantz.proactive.cli import handle_proactive_command

        args = argparse.Namespace(
            proactive_action="list",
            as_json=False,
        )
        result = handle_proactive_command(args)
        assert result == 0

    def test_cmd_list_json(self):
        from bantz.proactive.cli import handle_proactive_command

        args = argparse.Namespace(
            proactive_action="list",
            as_json=True,
        )
        result = handle_proactive_command(args)
        assert result == 0

    def test_cmd_policy(self):
        from bantz.proactive.cli import handle_proactive_command

        args = argparse.Namespace(
            proactive_action="policy",
            as_json=True,
            set=None,
        )
        result = handle_proactive_command(args)
        assert result == 0

    def test_cmd_dnd_on(self):
        from bantz.proactive.cli import handle_proactive_command

        args = argparse.Namespace(proactive_action="dnd", mode="on")
        result = handle_proactive_command(args)
        assert result == 0

    def test_cmd_dnd_off(self):
        from bantz.proactive.cli import handle_proactive_command

        args = argparse.Namespace(proactive_action="dnd", mode="off")
        result = handle_proactive_command(args)
        assert result == 0

    def test_cmd_notifications_empty(self):
        from bantz.proactive.cli import handle_proactive_command

        args = argparse.Namespace(
            proactive_action="notifications",
            unread=False,
            clear=False,
            as_json=False,
        )
        result = handle_proactive_command(args)
        assert result == 0

    def test_cmd_history_empty(self):
        from bantz.proactive.cli import handle_proactive_command

        args = argparse.Namespace(
            proactive_action="history",
            name=None,
            limit=10,
        )
        result = handle_proactive_command(args)
        assert result == 0

    def test_cmd_run_nonexistent(self):
        from bantz.proactive.cli import handle_proactive_command

        args = argparse.Namespace(
            proactive_action="run",
            name="nonexistent_check_xyz",
            all=False,
        )
        result = handle_proactive_command(args)
        assert result == 1  # Check not found


# ================================================================
# Test: Integration
# ================================================================


class TestIntegration:
    """Integration tests combining multiple components."""

    def test_full_pipeline(self):
        """Test complete pipeline: check → analysis → notification."""
        from bantz.proactive.engine import ProactiveEngine

        mock_bus = MagicMock()
        engine = ProactiveEngine(
            event_bus=mock_bus,
            config_path=Path("/tmp/bantz_test_proactive_integration.json"),
        )

        # Register a check that produces warnings
        def warning_check(check, ctx):
            return CheckResult(
                check_name=check.name,
                ok=True,
                summary="Warning found!",
                analysis=CrossAnalysis(
                    check_name=check.name,
                    insights=[
                        Insight(message="Something bad", severity=InsightSeverity.WARNING),
                    ],
                    suggestions=[Suggestion(text="Fix it")],
                ),
            )

        engine.register_check(ProactiveCheck(
            name="integration_test",
            description="Integration",
            schedule=CheckSchedule.every(hours=1),
            handler=warning_check,
        ))

        # Run the check
        result = engine.run_check("integration_test")
        assert result is not None
        assert result.ok is True

        # Notification should have been published
        assert mock_bus.publish.called
        calls = mock_bus.publish.call_args_list
        proactive_calls = [
            c for c in calls
            if c[1].get("source") == "proactive" or
               (len(c[0]) >= 2 and isinstance(c[0][1], dict) and c[0][1].get("proactive"))
        ]
        assert len(proactive_calls) >= 1

    def test_engine_with_mock_tools(self):
        """Test engine with mock tool registry calling actual check handlers."""
        from bantz.proactive.engine import ProactiveEngine

        mock_registry = MagicMock()

        def make_mock_tool(result):
            tool = MagicMock()
            tool.handler = MagicMock(return_value=result)
            return tool

        mock_registry.get.side_effect = lambda name: {
            "calendar.list_events": make_mock_tool({"ok": True, "events": []}),
            "weather.get_current": make_mock_tool({"ok": True, "data": {"temperature": 20, "condition": "Sunny"}}),
            "gmail.unread_count": make_mock_tool({"ok": True, "unread": 3}),
        }.get(name)

        engine = ProactiveEngine(
            tool_registry=mock_registry,
            policy=NotificationPolicy(desktop_notifications=False),
            config_path=Path("/tmp/bantz_test_proactive_tools.json"),
        )

        result = engine.run_check("morning_briefing")
        assert result is not None
        assert result.ok is True
        assert "Günaydın" in result.summary

    def test_cross_analyzer_with_engine(self):
        """Test that engine exposes cross-analyzer for custom rules."""
        from bantz.proactive.engine import ProactiveEngine

        engine = ProactiveEngine(
            config_path=Path("/tmp/bantz_test_proactive_analyzer.json"),
        )

        # Add custom rule
        def custom_rule(data):
            if data.get("custom_signal"):
                return (
                    [Insight(message="Custom signal detected!", severity=InsightSeverity.WARNING)],
                    [Suggestion(text="Act on it")],
                )
            return ([], [])

        engine.analyzer.add_rule("custom_signal", custom_rule)
        assert "custom_signal" in engine.analyzer.rule_names

        # Analyze with custom data
        analysis = engine.analyzer.analyze("test", {"custom_signal": True}, rules=["custom_signal"])
        assert len(analysis.insights) == 1
        assert "Custom signal" in analysis.insights[0].message
