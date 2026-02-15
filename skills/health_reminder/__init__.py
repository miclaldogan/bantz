"""Health Reminder skill — medication, hydration, and ergonomics tracking.

Issue #1299: Future Capabilities — Phase G+

Status: PLANNED — skeleton only.
Dependencies: Scheduler (EPIC 6).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict

logger = logging.getLogger(__name__)


@dataclass
class Medication:
    """Medication/vitamin entry."""

    name: str
    dose: str = ""
    schedule: str = "morning"  # morning | noon | evening | cron expression
    active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "dose": self.dose,
            "schedule": self.schedule,
            "active": self.active,
        }


@dataclass
class HealthLog:
    """Single health action log entry."""

    action: str  # medication_taken | water_drunk | break_taken | exercise
    details: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class WaterConfig:
    """Water reminder configuration."""

    interval_minutes: int = 45
    daily_goal_ml: int = 2500
    consumed_ml: int = 0

    @property
    def remaining_ml(self) -> int:
        return max(0, self.daily_goal_ml - self.consumed_ml)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interval_minutes": self.interval_minutes,
            "daily_goal_ml": self.daily_goal_ml,
            "consumed_ml": self.consumed_ml,
            "remaining_ml": self.remaining_ml,
        }


class HealthReminder(ABC):
    """Abstract base for health reminder system.

    Concrete implementation requires Scheduler EPIC.
    """

    @abstractmethod
    def add_medication(
        self,
        name: str,
        schedule: str = "morning",
        dose: str = "",
    ) -> Medication:
        """Add a medication reminder."""
        ...

    @abstractmethod
    def setup_water_reminder(
        self,
        interval_minutes: int = 45,
        daily_goal_ml: int = 2500,
    ) -> WaterConfig:
        """Set up water drinking reminders."""
        ...

    @abstractmethod
    def setup_ergonomics(
        self,
        max_sitting_minutes: int = 90,
    ) -> Dict[str, Any]:
        """Set up ergonomics reminder."""
        ...

    @abstractmethod
    def log_action(
        self,
        action: str,
        details: str = "",
    ) -> HealthLog:
        """Log a health action."""
        ...

    @abstractmethod
    def get_daily_summary(self) -> Dict[str, Any]:
        """Get today's health activity summary."""
        ...


class PlaceholderHealthReminder(HealthReminder):
    """Placeholder — returns stub data."""

    def add_medication(
        self,
        name: str,
        schedule: str = "morning",
        dose: str = "",
    ) -> Medication:
        logger.info("[HealthReminder] add_medication — stub mode")
        return Medication(name=name, schedule=schedule, dose=dose)

    def setup_water_reminder(
        self,
        interval_minutes: int = 45,
        daily_goal_ml: int = 2500,
    ) -> WaterConfig:
        return WaterConfig(
            interval_minutes=interval_minutes,
            daily_goal_ml=daily_goal_ml,
        )

    def setup_ergonomics(
        self,
        max_sitting_minutes: int = 90,
    ) -> Dict[str, Any]:
        return {
            "status": "planned",
            "max_sitting_minutes": max_sitting_minutes,
            "message": "Ergonomics reminder is not yet active.",
        }

    def log_action(
        self,
        action: str,
        details: str = "",
    ) -> HealthLog:
        return HealthLog(action=action, details=details)

    def get_daily_summary(self) -> Dict[str, Any]:
        return {
            "status": "planned",
            "message": "Health tracking is not yet active. "
            "Will be activated after Scheduler EPIC is complete.",
        }
