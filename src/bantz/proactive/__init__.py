"""Bantz Proactive Intelligence Engine — Scheduler + Cross-Analysis + Notifications.

The Proactive Engine allows Bantz to act autonomously by periodically running
checks (morning briefing, weather×calendar cross-analysis, email digest),
combining results from multiple tools, and notifying the user with actionable
suggestions.

Issue #835
"""
from __future__ import annotations

from bantz.proactive.models import (
    ProactiveCheck,
    CheckSchedule,
    CheckResult,
    CrossAnalysis,
    Insight,
    InsightSeverity,
    Suggestion,
    NotificationPolicy,
    ProactiveNotification,
)
from bantz.proactive.engine import ProactiveEngine
from bantz.proactive.cross_analyzer import CrossAnalyzer
from bantz.proactive.notification_queue import NotificationQueue

__all__ = [
    "ProactiveCheck",
    "CheckSchedule",
    "CheckResult",
    "CrossAnalysis",
    "Insight",
    "InsightSeverity",
    "Suggestion",
    "NotificationPolicy",
    "ProactiveNotification",
    "ProactiveEngine",
    "CrossAnalyzer",
    "NotificationQueue",
]
