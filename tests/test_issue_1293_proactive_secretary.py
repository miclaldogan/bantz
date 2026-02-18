"""Tests for Issue #1293 — Proactive Secretary Engine.

Tests cover:
- Signal data models (FreeSlot, CalendarSignal, EmailSignal, etc.)
- SignalCollector (parallel collection, free-slot detection, error isolation)
- Rule definitions and ProactiveRuleEngine evaluation
- DailyBriefGenerator (generate, format, status)
- Delivery channels (Terminal, Desktop, EventBus, Callback)
- Engine integration (_init_secretary, YAML config loading)
- Proactive tools registration (daily_brief, status)

Target: ≥ 35 tests
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════
# Signal Data Models
# ═══════════════════════════════════════════════════════════════


class TestFreeSlot:
    def test_duration_minutes(self):
        from bantz.proactive.signals import FreeSlot

        slot = FreeSlot(start="09:00", end="10:30")
        assert slot.duration_minutes == 90

    def test_duration_minutes_zero(self):
        from bantz.proactive.signals import FreeSlot

        slot = FreeSlot(start="bad", end="data")
        assert slot.duration_minutes == 0

    def test_to_dict(self):
        from bantz.proactive.signals import FreeSlot

        slot = FreeSlot(start="14:00", end="15:00")
        d = slot.to_dict()
        assert d["start"] == "14:00"
        assert d["end"] == "15:00"
        assert d["duration_minutes"] == 60


class TestCalendarSignal:
    def test_empty_signal(self):
        from bantz.proactive.signals import CalendarSignal

        sig = CalendarSignal()
        d = sig.to_dict()
        assert d["today_count"] == 0
        assert d["pending_rsvp_count"] == 0

    def test_with_events(self):
        from bantz.proactive.signals import CalendarSignal

        sig = CalendarSignal(
            today_events=[{"summary": "A"}, {"summary": "B"}],
            pending_rsvp=[{"summary": "C"}],
        )
        assert sig.to_dict()["today_count"] == 2
        assert sig.to_dict()["pending_rsvp_count"] == 1


class TestEmailSignal:
    def test_to_dict(self):
        from bantz.proactive.signals import EmailSignal

        sig = EmailSignal(unread_count=5, urgent=[{"id": "1"}])
        d = sig.to_dict()
        assert d["unread_count"] == 5
        assert d["urgent_count"] == 1


class TestWeatherSignal:
    def test_to_dict(self):
        from bantz.proactive.signals import WeatherSignal

        sig = WeatherSignal(temperature=22.5, condition="sunny", rain_probability=0.1)
        d = sig.to_dict()
        assert d["temperature"] == 22.5
        assert d["condition"] == "sunny"


class TestTaskSignal:
    def test_has_pending(self):
        from bantz.proactive.signals import TaskSignal

        sig = TaskSignal(active_tasks=[{"title": "X"}])
        assert sig.has_pending is True

    def test_no_pending(self):
        from bantz.proactive.signals import TaskSignal

        sig = TaskSignal()
        assert sig.has_pending is False


class TestNewsSignal:
    def test_to_dict(self):
        from bantz.proactive.signals import NewsSignal

        sig = NewsSignal(headlines=[{"title": "Breaking"}])
        assert sig.to_dict()["headline_count"] == 1


class TestDailySignals:
    def test_to_dict(self):
        from bantz.proactive.signals import DailySignals

        signals = DailySignals(collected_at=datetime(2025, 1, 15, 8, 0))
        d = signals.to_dict()
        assert d["collected_at"] is not None
        assert d["calendar"]["today_count"] == 0

    def test_empty_signals(self):
        from bantz.proactive.signals import DailySignals

        signals = DailySignals()
        assert signals.collected_at is None
        d = signals.to_dict()
        assert d["collected_at"] is None


# ═══════════════════════════════════════════════════════════════
# Time Parsing Utility
# ═══════════════════════════════════════════════════════════════


class TestParseTimeToMinutes:
    def test_simple_time(self):
        from bantz.proactive.signals import _parse_time_to_minutes

        assert _parse_time_to_minutes("10:30") == 630

    def test_iso_datetime(self):
        from bantz.proactive.signals import _parse_time_to_minutes

        assert _parse_time_to_minutes("2025-01-15T14:00:00+03:00") == 840

    def test_dict_with_datetime(self):
        from bantz.proactive.signals import _parse_time_to_minutes

        assert _parse_time_to_minutes({"dateTime": "2025-01-15T09:00:00"}) == 540

    def test_invalid(self):
        from bantz.proactive.signals import _parse_time_to_minutes

        assert _parse_time_to_minutes(None) is None
        assert _parse_time_to_minutes(123) is None
        assert _parse_time_to_minutes("bad") is None


# ═══════════════════════════════════════════════════════════════
# Free Slot Calculator
# ═══════════════════════════════════════════════════════════════


class TestFreeSlotCalculator:
    def test_no_events(self):
        from bantz.proactive.signals import SignalCollector

        slots = SignalCollector._find_free_slots([], (9, 18))
        assert len(slots) == 1
        assert slots[0].start == "09:00"
        assert slots[0].end == "18:00"

    def test_with_one_event(self):
        from bantz.proactive.signals import SignalCollector

        events = [{"start": "10:00", "end": "11:00"}]
        slots = SignalCollector._find_free_slots(events, (9, 18))
        # 09:00-10:00, 11:00-18:00
        assert len(slots) == 2
        assert slots[0].start == "09:00"
        assert slots[0].end == "10:00"
        assert slots[1].start == "11:00"
        assert slots[1].end == "18:00"

    def test_gap_too_small(self):
        from bantz.proactive.signals import SignalCollector

        events = [
            {"start": "09:00", "end": "09:20"},
            {"start": "09:20", "end": "18:00"},
        ]
        # No gap ≥ 30 min
        slots = SignalCollector._find_free_slots(events, (9, 18))
        assert len(slots) == 0

    def test_overlapping_events(self):
        from bantz.proactive.signals import SignalCollector

        events = [
            {"start": "09:00", "end": "11:00"},
            {"start": "10:00", "end": "12:00"},
        ]
        # Merged: 09:00-12:00 → free: 12:00-18:00
        slots = SignalCollector._find_free_slots(events, (9, 18))
        assert len(slots) == 1
        assert slots[0].start == "12:00"


# ═══════════════════════════════════════════════════════════════
# SignalCollector
# ═══════════════════════════════════════════════════════════════


class TestSignalCollector:
    @pytest.mark.asyncio
    async def test_collect_all_no_registry(self):
        from bantz.proactive.signals import SignalCollector

        collector = SignalCollector(tool_registry=None)
        signals = await collector.collect_all()
        assert signals.collected_at is not None
        assert signals.calendar.today_events == []

    @pytest.mark.asyncio
    async def test_collect_calendar_with_mock(self):
        from bantz.proactive.signals import SignalCollector

        mock_reg = MagicMock()
        tool = MagicMock()
        tool.function.return_value = {"ok": True, "events": [{"summary": "Test"}]}
        tool.handler = None  # Force fallback to function
        mock_reg.get.return_value = tool

        collector = SignalCollector(tool_registry=mock_reg)
        cal = await collector.collect_calendar()
        assert len(cal.today_events) == 1

    @pytest.mark.asyncio
    async def test_collect_emails_with_mock(self):
        from bantz.proactive.signals import SignalCollector

        mock_reg = MagicMock()
        tool = MagicMock()
        tool.function.return_value = {"ok": True, "unread": 7}
        tool.handler = None
        mock_reg.get.return_value = tool

        collector = SignalCollector(tool_registry=mock_reg)
        email = await collector.collect_emails()
        assert email.unread_count == 7

    @pytest.mark.asyncio
    async def test_collect_all_error_isolation(self):
        """If one collector fails, others still return data."""
        from bantz.proactive.signals import SignalCollector

        mock_reg = MagicMock()
        # Every tool call raises
        mock_reg.get.side_effect = RuntimeError("boom")

        collector = SignalCollector(tool_registry=mock_reg)
        signals = await collector.collect_all()
        # Should not raise — all signals are empty defaults
        assert signals.collected_at is not None


# ═══════════════════════════════════════════════════════════════
# Rule Engine
# ═══════════════════════════════════════════════════════════════


class TestRule:
    def test_rule_fields(self):
        from bantz.proactive.rule_engine import Rule

        r = Rule(name="test", condition=lambda s: True, action="do stuff")
        assert r.name == "test"
        assert r.enabled is True
        assert r.priority == 1


class TestRuleSuggestion:
    def test_to_dict(self):
        from bantz.proactive.models import InsightSeverity
        from bantz.proactive.rule_engine import RuleSuggestion

        rs = RuleSuggestion(
            rule_name="rain",
            message="Take umbrella",
            priority=3,
            severity=InsightSeverity.WARNING,
        )
        d = rs.to_dict()
        assert d["rule"] == "rain"
        assert d["severity"] == "warning"
        assert d["priority"] == 3


class TestDefaultRules:
    def test_count(self):
        from bantz.proactive.rule_engine import DEFAULT_RULES

        assert len(DEFAULT_RULES) >= 7

    def test_all_have_conditions(self):
        from bantz.proactive.rule_engine import DEFAULT_RULES

        for rule in DEFAULT_RULES:
            assert callable(rule.condition)


class TestProactiveRuleEngine:
    def test_rule_names(self):
        from bantz.proactive.rule_engine import ProactiveRuleEngine

        engine = ProactiveRuleEngine()
        names = engine.rule_names
        assert "rain_alert" in names
        assert "urgent_mail" in names

    def test_add_remove_rule(self):
        from bantz.proactive.rule_engine import ProactiveRuleEngine, Rule

        engine = ProactiveRuleEngine(rules=[])
        engine.add_rule(Rule(name="custom", condition=lambda s: True, action="hi"))
        assert "custom" in engine.rule_names
        assert engine.remove_rule("custom") is True
        assert "custom" not in engine.rule_names

    def test_enable_disable_rule(self):
        from bantz.proactive.rule_engine import ProactiveRuleEngine

        engine = ProactiveRuleEngine()
        assert engine.disable_rule("rain_alert") is True
        r = engine.get_rule("rain_alert")
        assert r is not None and r.enabled is False
        assert engine.enable_rule("rain_alert") is True
        assert r.enabled is True

    @pytest.mark.asyncio
    async def test_evaluate_rain_alert(self):
        from bantz.proactive.rule_engine import ProactiveRuleEngine
        from bantz.proactive.signals import DailySignals, WeatherSignal

        signals = DailySignals(weather=WeatherSignal(rain_probability=0.8))
        engine = ProactiveRuleEngine()
        suggestions = await engine.evaluate(signals)
        rain_msgs = [s for s in suggestions if s.rule_name == "rain_alert"]
        assert len(rain_msgs) == 1
        assert "yağmur" in rain_msgs[0].message.lower() or "şemsiye" in rain_msgs[0].message.lower()

    @pytest.mark.asyncio
    async def test_evaluate_no_triggers(self):
        from bantz.proactive.rule_engine import ProactiveRuleEngine
        from bantz.proactive.signals import DailySignals

        signals = DailySignals()
        engine = ProactiveRuleEngine()
        suggestions = await engine.evaluate(signals)
        assert len(suggestions) == 0

    @pytest.mark.asyncio
    async def test_evaluate_multiple_rules(self):
        from bantz.proactive.rule_engine import ProactiveRuleEngine
        from bantz.proactive.signals import (DailySignals, EmailSignal,
                                             TaskSignal, WeatherSignal)

        signals = DailySignals(
            weather=WeatherSignal(rain_probability=0.9),
            emails=EmailSignal(unread_count=20, urgent=[{"id": "1"}]),
            tasks=TaskSignal(overdue=[{"title": "old task"}]),
        )
        engine = ProactiveRuleEngine()
        suggestions = await engine.evaluate(signals)
        rule_names = [s.rule_name for s in suggestions]
        assert "rain_alert" in rule_names
        assert "urgent_mail" in rule_names
        assert "overdue_tasks" in rule_names
        # Should be sorted by priority descending
        priorities = [s.priority for s in suggestions]
        assert priorities == sorted(priorities, reverse=True)

    @pytest.mark.asyncio
    async def test_evaluate_with_llm_callback(self):
        from bantz.proactive.rule_engine import (ProactiveRuleEngine,
                                                 RuleSuggestion)
        from bantz.proactive.signals import DailySignals

        async def mock_llm(signals, existing):
            return [RuleSuggestion(
                rule_name="llm_insight",
                message="LLM says hello",
                priority=10,
            )]

        engine = ProactiveRuleEngine(llm_callback=mock_llm)
        suggestions = await engine.evaluate(DailySignals())
        assert any(s.rule_name == "llm_insight" for s in suggestions)

    def test_evaluate_sync(self):
        from bantz.proactive.rule_engine import ProactiveRuleEngine
        from bantz.proactive.signals import DailySignals, WeatherSignal

        signals = DailySignals(weather=WeatherSignal(rain_probability=0.8))
        engine = ProactiveRuleEngine()
        suggestions = engine.evaluate_sync(signals)
        assert any(s.rule_name == "rain_alert" for s in suggestions)

    @pytest.mark.asyncio
    async def test_disabled_rule_not_triggered(self):
        from bantz.proactive.rule_engine import ProactiveRuleEngine
        from bantz.proactive.signals import DailySignals, WeatherSignal

        signals = DailySignals(weather=WeatherSignal(rain_probability=0.9))
        engine = ProactiveRuleEngine()
        engine.disable_rule("rain_alert")
        suggestions = await engine.evaluate(signals)
        assert not any(s.rule_name == "rain_alert" for s in suggestions)

    @pytest.mark.asyncio
    async def test_rule_condition_error_handled(self):
        from bantz.proactive.rule_engine import ProactiveRuleEngine, Rule
        from bantz.proactive.signals import DailySignals

        def bad_condition(signals):
            raise ValueError("broken")

        engine = ProactiveRuleEngine(rules=[
            Rule(name="broken", condition=bad_condition, action="x"),
        ])
        # Should not raise
        suggestions = await engine.evaluate(DailySignals())
        assert len(suggestions) == 0


# ═══════════════════════════════════════════════════════════════
# Daily Brief Generator
# ═══════════════════════════════════════════════════════════════


class TestDailyBriefGenerator:
    @pytest.mark.asyncio
    async def test_generate_brief(self):
        from bantz.proactive.daily_brief import DailyBriefGenerator
        from bantz.proactive.rule_engine import ProactiveRuleEngine
        from bantz.proactive.signals import (CalendarSignal, DailySignals,
                                             EmailSignal, SignalCollector,
                                             WeatherSignal)

        # Mock collector
        mock_collector = MagicMock(spec=SignalCollector)
        mock_signals = DailySignals(
            calendar=CalendarSignal(today_events=[
                {"summary": "Proje sync", "start": "10:00"},
            ]),
            emails=EmailSignal(unread_count=3),
            weather=WeatherSignal(temperature=18, condition="cloudy"),
            collected_at=datetime.now(),
        )
        mock_collector.collect_all = AsyncMock(return_value=mock_signals)

        rule_engine = ProactiveRuleEngine()
        gen = DailyBriefGenerator(mock_collector, rule_engine)
        brief = await gen.generate()

        assert "Günaydın" in brief
        assert "Proje sync" in brief
        assert "3 okunmamış" in brief
        assert gen.last_brief == brief
        assert gen.last_generated_at is not None

    def test_format_brief_empty(self):
        from bantz.proactive.daily_brief import DailyBriefGenerator
        from bantz.proactive.rule_engine import ProactiveRuleEngine
        from bantz.proactive.signals import DailySignals, SignalCollector

        gen = DailyBriefGenerator(
            MagicMock(spec=SignalCollector),
            ProactiveRuleEngine(),
        )
        brief = gen.format_brief(DailySignals(), [])
        assert "Günaydın" in brief
        assert "toplantı yok" in brief

    def test_format_brief_with_suggestions(self):
        from bantz.proactive.daily_brief import DailyBriefGenerator
        from bantz.proactive.rule_engine import (ProactiveRuleEngine,
                                                 RuleSuggestion)
        from bantz.proactive.signals import (DailySignals, SignalCollector,
                                             WeatherSignal)

        gen = DailyBriefGenerator(
            MagicMock(spec=SignalCollector),
            ProactiveRuleEngine(),
        )
        brief = gen.format_brief(
            DailySignals(weather=WeatherSignal(temperature=22, condition="sunny")),
            [RuleSuggestion(rule_name="test", message="Do something", priority=1)],
        )
        assert "Öneriler" in brief
        assert "Do something" in brief

    def test_get_status_no_brief(self):
        from bantz.proactive.daily_brief import DailyBriefGenerator
        from bantz.proactive.rule_engine import ProactiveRuleEngine
        from bantz.proactive.signals import SignalCollector

        gen = DailyBriefGenerator(
            MagicMock(spec=SignalCollector),
            ProactiveRuleEngine(),
        )
        status = gen.get_status()
        assert status["has_brief"] is False
        assert status["last_generated_at"] is None

    def test_extract_time_iso(self):
        from bantz.proactive.daily_brief import DailyBriefGenerator

        assert DailyBriefGenerator._extract_time({"start": "2025-01-15T10:30:00"}) == "10:30"

    def test_extract_time_dict(self):
        from bantz.proactive.daily_brief import DailyBriefGenerator

        evt = {"start": {"dateTime": "2025-01-15T14:00:00+03:00"}}
        assert DailyBriefGenerator._extract_time(evt) == "14:00"

    def test_extract_time_simple(self):
        from bantz.proactive.daily_brief import DailyBriefGenerator

        assert DailyBriefGenerator._extract_time({"start": "09:00"}) == "09:00"

    def test_extract_time_unknown(self):
        from bantz.proactive.daily_brief import DailyBriefGenerator

        assert DailyBriefGenerator._extract_time({"start": "bad"}) == "??:??"


# ═══════════════════════════════════════════════════════════════
# Delivery Channels
# ═══════════════════════════════════════════════════════════════


class TestDeliveryChannels:
    @pytest.mark.asyncio
    async def test_terminal_delivery(self, capsys):
        from bantz.proactive.delivery import TerminalDelivery

        channel = TerminalDelivery()
        await channel.deliver("Hello!")
        captured = capsys.readouterr()
        assert "Hello!" in captured.out

    @pytest.mark.asyncio
    async def test_callback_delivery(self):
        from bantz.proactive.delivery import CallbackDelivery

        received = []

        async def cb(text):
            received.append(text)

        channel = CallbackDelivery(cb)
        await channel.deliver("Test brief")
        assert received == ["Test brief"]

    @pytest.mark.asyncio
    async def test_eventbus_delivery(self):
        from bantz.proactive.delivery import EventBusDelivery

        bus = MagicMock()
        channel = EventBusDelivery(bus)
        await channel.deliver("Brief text")
        bus.publish.assert_called_once()
        call_kwargs = bus.publish.call_args
        assert call_kwargs[1]["data"]["proactive"] is True

    @pytest.mark.asyncio
    async def test_eventbus_delivery_no_bus(self):
        from bantz.proactive.delivery import EventBusDelivery

        channel = EventBusDelivery(None)
        # Should not raise
        await channel.deliver("ignored")

    @pytest.mark.asyncio
    async def test_desktop_notification_no_binary(self):
        from bantz.proactive.delivery import DesktopNotificationDelivery

        channel = DesktopNotificationDelivery()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            # Should not raise
            await channel.deliver("Test")

    def test_channel_name(self):
        from bantz.proactive.delivery import TerminalDelivery

        assert TerminalDelivery().name == "TerminalDelivery"


# ═══════════════════════════════════════════════════════════════
# Engine Integration
# ═══════════════════════════════════════════════════════════════


class TestEngineSecretary:
    def test_init_secretary(self):
        from bantz.proactive.engine import ProactiveEngine

        engine = ProactiveEngine()
        # Secretary components should be initialized
        assert engine.signal_collector is not None
        assert engine.rule_engine is not None
        assert engine.brief_generator is not None

    def test_secretary_rule_engine_has_rules(self):
        from bantz.proactive.engine import ProactiveEngine

        engine = ProactiveEngine()
        re = engine.rule_engine
        assert len(re.rule_names) >= 7

    def test_load_yaml_config(self):
        from bantz.proactive.engine import ProactiveEngine

        engine = ProactiveEngine()
        config = engine._load_yaml_config()
        # Should load from config/proactive.yaml
        assert isinstance(config, dict)
        # Even if pyyaml is missing, should return empty dict

    def test_brief_generator_has_channels(self):
        from bantz.proactive.engine import ProactiveEngine

        engine = ProactiveEngine()
        gen = engine.brief_generator
        assert gen is not None
        status = gen.get_status()
        # Should have at least terminal channel
        assert status["delivery_channels"] >= 1


# ═══════════════════════════════════════════════════════════════
# YAML Config
# ═══════════════════════════════════════════════════════════════


class TestYAMLConfig:
    def test_config_file_exists(self):
        from pathlib import Path

        yaml_path = Path(__file__).resolve().parents[1] / "config" / "proactive.yaml"
        assert yaml_path.exists()

    def test_config_loads(self):
        from pathlib import Path

        yaml_path = Path(__file__).resolve().parents[1] / "config" / "proactive.yaml"
        try:
            import yaml

            config = yaml.safe_load(yaml_path.read_text())
            assert "scheduler" in config
            assert "daily_brief" in config
            assert "rules" in config
            assert "delivery" in config
            assert config["daily_brief"]["time"] == "08:00"
        except ImportError:
            pytest.skip("pyyaml not installed")

    def test_rules_section(self):
        from pathlib import Path

        yaml_path = Path(__file__).resolve().parents[1] / "config" / "proactive.yaml"
        try:
            import yaml

            config = yaml.safe_load(yaml_path.read_text())
            rules = config["rules"]
            assert "rain_alert" in rules
            assert "pending_rsvp" in rules
            assert "deadline_approaching" in rules
            assert "free_slot_suggestion" in rules
            assert "urgent_mail" in rules
        except ImportError:
            pytest.skip("pyyaml not installed")


# ═══════════════════════════════════════════════════════════════
# Rule Conditions (unit test each rule function)
# ═══════════════════════════════════════════════════════════════


class TestRuleConditions:
    def test_rain_alert_triggers(self):
        from bantz.proactive.rule_engine import _rain_alert
        from bantz.proactive.signals import DailySignals, WeatherSignal

        assert _rain_alert(DailySignals(weather=WeatherSignal(rain_probability=0.7))) is True

    def test_rain_alert_no_trigger(self):
        from bantz.proactive.rule_engine import _rain_alert
        from bantz.proactive.signals import DailySignals, WeatherSignal

        assert _rain_alert(DailySignals(weather=WeatherSignal(rain_probability=0.3))) is False

    def test_pending_rsvp_triggers(self):
        from bantz.proactive.rule_engine import _pending_rsvp
        from bantz.proactive.signals import CalendarSignal, DailySignals

        sig = DailySignals(calendar=CalendarSignal(pending_rsvp=[{"summary": "X"}]))
        assert _pending_rsvp(sig) is True

    def test_deadline_approaching_overdue(self):
        from bantz.proactive.rule_engine import _deadline_approaching
        from bantz.proactive.signals import DailySignals, TaskSignal

        sig = DailySignals(tasks=TaskSignal(overdue=[{"title": "old"}]))
        assert _deadline_approaching(sig) is True

    def test_free_slot_suggestion(self):
        from bantz.proactive.rule_engine import _free_slot_suggestion
        from bantz.proactive.signals import (CalendarSignal, DailySignals,
                                             FreeSlot, TaskSignal)

        sig = DailySignals(
            calendar=CalendarSignal(free_slots=[FreeSlot("09:00", "10:00")]),
            tasks=TaskSignal(active_tasks=[{"title": "T"}]),
        )
        assert _free_slot_suggestion(sig) is True

    def test_urgent_mail(self):
        from bantz.proactive.rule_engine import _urgent_mail
        from bantz.proactive.signals import DailySignals, EmailSignal

        sig = DailySignals(emails=EmailSignal(urgent=[{"id": "1"}]))
        assert _urgent_mail(sig) is True

    def test_high_unread(self):
        from bantz.proactive.rule_engine import _high_unread
        from bantz.proactive.signals import DailySignals, EmailSignal

        assert _high_unread(DailySignals(emails=EmailSignal(unread_count=20))) is True
        assert _high_unread(DailySignals(emails=EmailSignal(unread_count=5))) is False

    def test_overdue_tasks(self):
        from bantz.proactive.rule_engine import _overdue_tasks
        from bantz.proactive.signals import DailySignals, TaskSignal

        sig = DailySignals(tasks=TaskSignal(overdue=[{"title": "X"}]))
        assert _overdue_tasks(sig) is True
