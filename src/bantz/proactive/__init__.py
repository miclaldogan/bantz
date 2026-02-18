"""Bantz Proactive Intelligence Engine — Scheduler + Cross-Analysis + Notifications.

The Proactive Engine allows Bantz to act autonomously by periodically running
checks (morning briefing, weather×calendar cross-analysis, email digest),
combining results from multiple tools, and notifying the user with actionable
suggestions.

The Proactive Secretary (Issue #1293) adds structured signal collection,
a hybrid rule + LLM reasoning engine, composable daily briefs, and
configurable delivery channels.

Issues #835, #1293
"""
from __future__ import annotations

from bantz.proactive.cross_analyzer import CrossAnalyzer
from bantz.proactive.daily_brief import DailyBriefGenerator
from bantz.proactive.delivery import (CallbackDelivery, DeliveryChannel,
                                      DesktopNotificationDelivery,
                                      EventBusDelivery, TerminalDelivery)
from bantz.proactive.engine import ProactiveEngine
from bantz.proactive.models import (CheckResult, CheckSchedule, CrossAnalysis,
                                    Insight, InsightSeverity,
                                    NotificationPolicy, ProactiveCheck,
                                    ProactiveNotification, Suggestion)
from bantz.proactive.notification_queue import NotificationQueue
from bantz.proactive.rule_engine import (DEFAULT_RULES, ProactiveRuleEngine,
                                         Rule, RuleSuggestion)
from bantz.proactive.signals import (CalendarSignal, DailySignals, EmailSignal,
                                     FreeSlot, NewsSignal, SignalCollector,
                                     TaskSignal, WeatherSignal)

__all__ = [
    # Models (Issue #835)
    "ProactiveCheck",
    "CheckSchedule",
    "CheckResult",
    "CrossAnalysis",
    "Insight",
    "InsightSeverity",
    "Suggestion",
    "NotificationPolicy",
    "ProactiveNotification",
    # Engine (Issue #835)
    "ProactiveEngine",
    "CrossAnalyzer",
    "NotificationQueue",
    # Signals (Issue #1293)
    "CalendarSignal",
    "DailySignals",
    "EmailSignal",
    "FreeSlot",
    "NewsSignal",
    "SignalCollector",
    "TaskSignal",
    "WeatherSignal",
    # Rule Engine (Issue #1293)
    "DEFAULT_RULES",
    "ProactiveRuleEngine",
    "Rule",
    "RuleSuggestion",
    # Daily Brief (Issue #1293)
    "DailyBriefGenerator",
    # Delivery (Issue #1293)
    "CallbackDelivery",
    "DeliveryChannel",
    "DesktopNotificationDelivery",
    "EventBusDelivery",
    "TerminalDelivery",
]
