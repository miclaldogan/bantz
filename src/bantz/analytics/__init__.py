"""
Analytics & Learning Module.

Track usage patterns, learn from corrections, and provide insights.
"""

from bantz.analytics.tracker import (
    CommandEvent,
    UsageAnalytics,
    MockUsageAnalytics,
)
from bantz.analytics.learner import (
    ASRLearner,
    Correction,
    MockASRLearner,
)
from bantz.analytics.performance import (
    PerformanceTracker,
    OperationStats,
    MockPerformanceTracker,
)
from bantz.analytics.suggestions import (
    SmartSuggestions,
    Suggestion,
    MockSmartSuggestions,
)
from bantz.analytics.dashboard import (
    AnalyticsDashboard,
    DailyReport,
    WeeklyReport,
    MockAnalyticsDashboard,
)

__all__ = [
    # Tracker
    "CommandEvent",
    "UsageAnalytics",
    "MockUsageAnalytics",
    # Learner
    "ASRLearner",
    "Correction",
    "MockASRLearner",
    # Performance
    "PerformanceTracker",
    "OperationStats",
    "MockPerformanceTracker",
    # Suggestions
    "SmartSuggestions",
    "Suggestion",
    "MockSmartSuggestions",
    # Dashboard
    "AnalyticsDashboard",
    "DailyReport",
    "WeeklyReport",
    "MockAnalyticsDashboard",
]
