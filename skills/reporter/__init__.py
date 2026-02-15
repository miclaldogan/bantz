"""Report Generator skill — activity reporting and productivity analysis.

Issue #1299: Gelecek Yetenekler — Faz G+

Status: PLANNED — skeleton only.
Dependencies: Observability (EPIC 3).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolUsageStat:
    """Tool usage statistics entry."""

    tool_name: str
    call_count: int = 0
    success_count: int = 0
    avg_latency_ms: float = 0.0
    last_used: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "tool": self.tool_name,
            "calls": self.call_count,
            "successes": self.success_count,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
        }
        if self.last_used:
            d["last_used"] = self.last_used.isoformat()
        return d


@dataclass
class ProductivityMetric:
    """Productivity analysis result."""

    period: str
    total_meetings_h: float = 0.0
    total_work_h: float = 0.0
    focus_ratio: float = 0.0  # work / (work + meetings)
    tool_interactions: int = 0
    tasks_completed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period": self.period,
            "meetings_hours": round(self.total_meetings_h, 1),
            "work_hours": round(self.total_work_h, 1),
            "focus_ratio": round(self.focus_ratio, 2),
            "tool_interactions": self.tool_interactions,
            "tasks_completed": self.tasks_completed,
        }


@dataclass
class Report:
    """Generated report."""

    report_type: str  # weekly | monthly | productivity
    title: str
    content: str = ""
    period: str = ""
    generated_at: datetime = field(default_factory=datetime.now)
    tool_stats: List[ToolUsageStat] = field(default_factory=list)
    productivity: Optional[ProductivityMetric] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": self.report_type,
            "title": self.title,
            "period": self.period,
            "generated_at": self.generated_at.isoformat(),
        }
        if self.content:
            d["content"] = self.content
        if self.tool_stats:
            d["tool_stats"] = [s.to_dict() for s in self.tool_stats]
        if self.productivity:
            d["productivity"] = self.productivity.to_dict()
        return d


class ReportGenerator(ABC):
    """Abstract base for report generation.

    Concrete implementation requires Observability EPIC.
    """

    @abstractmethod
    def weekly_report(
        self,
        week: Optional[str] = None,
        *,
        include_tools: bool = True,
    ) -> Report:
        """Generate weekly activity report."""
        ...

    @abstractmethod
    def monthly_report(
        self,
        month: Optional[str] = None,
    ) -> Report:
        """Generate monthly activity report."""
        ...

    @abstractmethod
    def productivity_analysis(
        self,
        period: str = "this_week",
    ) -> ProductivityMetric:
        """Analyze productivity (meeting/work ratio)."""
        ...

    @abstractmethod
    def export(
        self,
        report: Report,
        fmt: str = "markdown",
    ) -> str:
        """Export report to a file. Returns file path."""
        ...


class PlaceholderReportGenerator(ReportGenerator):
    """Placeholder — returns stub data."""

    def weekly_report(
        self,
        week: Optional[str] = None,
        *,
        include_tools: bool = True,
    ) -> Report:
        logger.info("[Reporter] weekly_report — stub mode")
        return Report(
            report_type="weekly",
            title="Haftalık Rapor",
            content="Rapor üretici henüz aktif değil. "
            "Observability EPIC'i tamamlandıktan sonra aktive edilecek.",
        )

    def monthly_report(
        self,
        month: Optional[str] = None,
    ) -> Report:
        return Report(
            report_type="monthly",
            title="Aylık Rapor",
            content="Rapor üretici henüz aktif değil.",
        )

    def productivity_analysis(
        self,
        period: str = "this_week",
    ) -> ProductivityMetric:
        return ProductivityMetric(period=period)

    def export(
        self,
        report: Report,
        fmt: str = "markdown",
    ) -> str:
        return ""
