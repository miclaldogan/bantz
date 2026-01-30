"""
Analytics Dashboard.

Generate reports and summaries:
- Daily summary
- Weekly report
- HTML export
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from pathlib import Path
from datetime import datetime, timedelta
import logging
import json

if TYPE_CHECKING:
    from bantz.analytics.tracker import UsageAnalytics
    from bantz.analytics.learner import ASRLearner
    from bantz.analytics.performance import PerformanceTracker

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class DailyReport:
    """Daily analytics report."""
    
    date: datetime
    total_commands: int
    success_count: int
    failure_count: int
    success_rate: float
    avg_response_time_ms: float
    top_intents: Dict[str, int]
    top_errors: Dict[str, int]
    peak_hour: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "date": self.date.isoformat(),
            "total_commands": self.total_commands,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": round(self.success_rate, 4),
            "avg_response_time_ms": round(self.avg_response_time_ms, 2),
            "top_intents": self.top_intents,
            "top_errors": self.top_errors,
            "peak_hour": self.peak_hour,
        }


@dataclass
class WeeklyReport:
    """Weekly analytics report."""
    
    start_date: datetime
    end_date: datetime
    daily_reports: List[DailyReport]
    total_commands: int
    success_rate: float
    avg_commands_per_day: float
    trend: str  # "up", "down", "stable"
    top_intents: Dict[str, int]
    improvement_suggestions: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "daily_reports": [r.to_dict() for r in self.daily_reports],
            "total_commands": self.total_commands,
            "success_rate": round(self.success_rate, 4),
            "avg_commands_per_day": round(self.avg_commands_per_day, 2),
            "trend": self.trend,
            "top_intents": self.top_intents,
            "improvement_suggestions": self.improvement_suggestions,
        }


# =============================================================================
# Analytics Dashboard
# =============================================================================


class AnalyticsDashboard:
    """
    Generate analytics reports and summaries.
    
    Provides:
    - Daily usage summary
    - Weekly reports
    - HTML export
    - Performance insights
    
    Example:
        dashboard = AnalyticsDashboard(analytics, learner, perf)
        
        # Get daily summary
        summary = dashboard.daily_summary()
        print(summary)
        
        # Export weekly report
        dashboard.export_html(Path("report.html"))
    """
    
    def __init__(
        self,
        analytics: Optional["UsageAnalytics"] = None,
        learner: Optional["ASRLearner"] = None,
        performance: Optional["PerformanceTracker"] = None,
    ):
        """
        Initialize dashboard.
        
        Args:
            analytics: UsageAnalytics instance
            learner: ASRLearner instance
            performance: PerformanceTracker instance
        """
        self.analytics = analytics
        self.learner = learner
        self.performance = performance
    
    def daily_summary(self, date: Optional[datetime] = None) -> str:
        """
        Generate daily usage summary.
        
        Args:
            date: Date for summary (today if None)
            
        Returns:
            Formatted summary string
        """
        if date is None:
            date = datetime.now()
        
        if not self.analytics:
            return "📊 Analytics verisi yok"
        
        stats = self.analytics.get_stats(days=1)
        
        # Get top intent
        top_intent = "Yok"
        if stats.top_intents:
            top_intent = max(stats.top_intents.items(), key=lambda x: x[1])[0]
        
        # Get top error if any
        error_line = ""
        if stats.top_errors:
            top_error = max(stats.top_errors.items(), key=lambda x: x[1])
            error_line = f"\n⚠️ En Sık Hata: {top_error[0][:30]}... ({top_error[1]})"
        
        # Performance line
        perf_line = ""
        if self.performance:
            summary = self.performance.get_summary()
            if summary.get("total_measurements", 0) > 0:
                perf_line = f"\n⚡ En Yavaş: {summary.get('slowest_operation', 'N/A')} ({summary.get('slowest_avg_ms', 0):.0f}ms)"
        
        # Learner line
        learner_line = ""
        if self.learner:
            learner_stats = self.learner.get_stats()
            if learner_stats.get("active_corrections", 0) > 0:
                learner_line = f"\n📝 Aktif Düzeltmeler: {learner_stats['active_corrections']}"
        
        return f"""📊 Günlük Özet - {date.strftime('%d.%m.%Y')}
━━━━━━━━━━━━━━━━━━━━━━━━━
📈 Toplam Komut: {stats.total_commands}
✅ Başarı Oranı: {stats.success_rate:.1%}
🎯 En Çok Kullanılan: {top_intent}
⏱️ Ortalama Yanıt: {stats.avg_execution_time_ms:.0f}ms{error_line}{perf_line}{learner_line}
━━━━━━━━━━━━━━━━━━━━━━━━━"""
    
    def get_daily_report(self, date: Optional[datetime] = None) -> DailyReport:
        """
        Get structured daily report.
        
        Args:
            date: Date for report
            
        Returns:
            DailyReport object
        """
        if date is None:
            date = datetime.now()
        
        if not self.analytics:
            return DailyReport(
                date=date,
                total_commands=0,
                success_count=0,
                failure_count=0,
                success_rate=0.0,
                avg_response_time_ms=0.0,
                top_intents={},
                top_errors={},
                peak_hour=0,
            )
        
        stats = self.analytics.get_stats(days=1)
        hourly = self.analytics.get_hourly_distribution(days=1)
        
        # Find peak hour
        peak_hour = max(hourly.items(), key=lambda x: x[1])[0] if hourly else 0
        
        return DailyReport(
            date=date,
            total_commands=stats.total_commands,
            success_count=stats.success_count,
            failure_count=stats.failure_count,
            success_rate=stats.success_rate,
            avg_response_time_ms=stats.avg_execution_time_ms,
            top_intents=stats.top_intents,
            top_errors=stats.top_errors,
            peak_hour=peak_hour,
        )
    
    def weekly_report(self, end_date: Optional[datetime] = None) -> WeeklyReport:
        """
        Generate weekly report.
        
        Args:
            end_date: End date of week (today if None)
            
        Returns:
            WeeklyReport object
        """
        if end_date is None:
            end_date = datetime.now()
        
        start_date = end_date - timedelta(days=7)
        
        if not self.analytics:
            return WeeklyReport(
                start_date=start_date,
                end_date=end_date,
                daily_reports=[],
                total_commands=0,
                success_rate=0.0,
                avg_commands_per_day=0.0,
                trend="stable",
                top_intents={},
                improvement_suggestions=[],
            )
        
        stats = self.analytics.get_stats(days=7)
        
        # Generate daily reports for the week
        daily_reports = []
        for i in range(7):
            day = end_date - timedelta(days=6-i)
            daily_reports.append(self.get_daily_report(day))
        
        # Calculate trend
        if len(daily_reports) >= 2:
            first_half = sum(r.total_commands for r in daily_reports[:3])
            second_half = sum(r.total_commands for r in daily_reports[4:])
            
            if second_half > first_half * 1.1:
                trend = "up"
            elif second_half < first_half * 0.9:
                trend = "down"
            else:
                trend = "stable"
        else:
            trend = "stable"
        
        # Generate improvement suggestions
        suggestions = self._generate_suggestions(stats, daily_reports)
        
        return WeeklyReport(
            start_date=start_date,
            end_date=end_date,
            daily_reports=daily_reports,
            total_commands=stats.total_commands,
            success_rate=stats.success_rate,
            avg_commands_per_day=stats.total_commands / 7,
            trend=trend,
            top_intents=stats.top_intents,
            improvement_suggestions=suggestions,
        )
    
    def _generate_suggestions(
        self,
        stats,
        daily_reports: List[DailyReport],
    ) -> List[str]:
        """Generate improvement suggestions."""
        suggestions = []
        
        # Low success rate
        if stats.success_rate < 0.8:
            suggestions.append(
                f"Başarı oranı düşük ({stats.success_rate:.1%}). "
                "Sık başarısız olan komutları kontrol edin."
            )
        
        # High response time
        if stats.avg_execution_time_ms > 500:
            suggestions.append(
                f"Ortalama yanıt süresi yüksek ({stats.avg_execution_time_ms:.0f}ms). "
                "Performans optimizasyonu yapılabilir."
            )
        
        # Repeated errors
        if stats.top_errors and len(stats.top_errors) > 0:
            top_error = list(stats.top_errors.items())[0]
            if top_error[1] >= 5:
                suggestions.append(
                    f"'{top_error[0][:20]}...' hatası {top_error[1]} kez tekrarlandı. "
                    "Bu hatanın kaynağını araştırın."
                )
        
        # Learner suggestions
        if self.learner:
            common_errors = self.learner.get_common_errors(min_count=5)
            if common_errors:
                suggestions.append(
                    f"{len(common_errors)} ASR düzeltmesi öğrenildi. "
                    "Bunları inceleyerek ASR modelini iyileştirebilirsiniz."
                )
        
        return suggestions
    
    def export_json(self, output_path: Path, days: int = 7) -> None:
        """
        Export analytics data as JSON.
        
        Args:
            output_path: Output file path
            days: Days to export
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "exported_at": datetime.now().isoformat(),
            "days": days,
        }
        
        if self.analytics:
            stats = self.analytics.get_stats(days=days)
            data["usage_stats"] = stats.to_dict()
            data["failure_patterns"] = [
                {
                    "intent": p.intent,
                    "error": p.error_message,
                    "count": p.count,
                }
                for p in self.analytics.get_failure_patterns()
            ]
        
        if self.learner:
            data["asr_learner"] = self.learner.get_stats()
        
        if self.performance:
            data["performance"] = self.performance.report_dict()
        
        output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info(f"Exported analytics to {output_path}")
    
    def export_html(self, output_path: Path, days: int = 7) -> None:
        """
        Export analytics as HTML report.
        
        Args:
            output_path: Output file path
            days: Days to include
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        weekly = self.weekly_report()
        
        # Generate HTML
        html = self._generate_html(weekly, days)
        
        output_path.write_text(html, encoding="utf-8")
        logger.info(f"Exported HTML report to {output_path}")
    
    def _generate_html(self, weekly: WeeklyReport, days: int) -> str:
        """Generate HTML report."""
        trend_emoji = {"up": "📈", "down": "📉", "stable": "➡️"}
        
        # Top intents table
        intents_rows = ""
        for intent, count in list(weekly.top_intents.items())[:10]:
            intents_rows += f"<tr><td>{intent}</td><td>{count}</td></tr>"
        
        # Suggestions list
        suggestions_html = ""
        for suggestion in weekly.improvement_suggestions:
            suggestions_html += f"<li>{suggestion}</li>"
        
        # Performance section
        perf_html = ""
        if self.performance:
            perf_html = "<h2>⚡ Performans</h2><table><tr><th>İşlem</th><th>Ortalama</th><th>P95</th><th>Sayı</th></tr>"
            for op, stats in self.performance.report().items():
                perf_html += f"<tr><td>{op}</td><td>{stats.avg_ms:.1f}ms</td><td>{stats.p95_ms:.1f}ms</td><td>{stats.count}</td></tr>"
            perf_html += "</table>"
        
        return f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bantz Analytics Report</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; border-bottom: 2px solid #ddd; padding-bottom: 10px; }}
        .card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
        }}
        .stat {{
            text-align: center;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 8px;
        }}
        .stat-value {{ font-size: 2em; font-weight: bold; color: #2196F3; }}
        .stat-label {{ color: #666; font-size: 0.9em; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
        }}
        th, td {{
            padding: 10px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{ background: #f5f5f5; }}
        .suggestion {{
            background: #fff3cd;
            padding: 10px 15px;
            border-radius: 5px;
            margin: 5px 0;
        }}
    </style>
</head>
<body>
    <h1>📊 Bantz Analytics Report</h1>
    <p>Dönem: {weekly.start_date.strftime('%d.%m.%Y')} - {weekly.end_date.strftime('%d.%m.%Y')}</p>
    
    <div class="card">
        <h2>📈 Özet</h2>
        <div class="stats">
            <div class="stat">
                <div class="stat-value">{weekly.total_commands}</div>
                <div class="stat-label">Toplam Komut</div>
            </div>
            <div class="stat">
                <div class="stat-value">{weekly.success_rate:.1%}</div>
                <div class="stat-label">Başarı Oranı</div>
            </div>
            <div class="stat">
                <div class="stat-value">{weekly.avg_commands_per_day:.1f}</div>
                <div class="stat-label">Günlük Ortalama</div>
            </div>
            <div class="stat">
                <div class="stat-value">{trend_emoji.get(weekly.trend, '➡️')}</div>
                <div class="stat-label">Trend</div>
            </div>
        </div>
    </div>
    
    <div class="card">
        <h2>🎯 En Çok Kullanılan Komutlar</h2>
        <table>
            <tr><th>Intent</th><th>Kullanım</th></tr>
            {intents_rows}
        </table>
    </div>
    
    {perf_html}
    
    <div class="card">
        <h2>💡 Öneriler</h2>
        <ul>
            {suggestions_html if suggestions_html else '<li>Şu an için öneri yok.</li>'}
        </ul>
    </div>
    
    <footer style="text-align: center; color: #999; margin-top: 30px;">
        Oluşturulma: {datetime.now().strftime('%d.%m.%Y %H:%M')}
    </footer>
</body>
</html>"""


# =============================================================================
# Mock Implementation
# =============================================================================


class MockAnalyticsDashboard(AnalyticsDashboard):
    """Mock analytics dashboard for testing."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mock_daily_summary: Optional[str] = None
        self._mock_weekly_report: Optional[WeeklyReport] = None
    
    def set_mock_daily_summary(self, summary: str) -> None:
        """Set mock daily summary."""
        self._mock_daily_summary = summary
    
    def set_mock_weekly_report(self, report: WeeklyReport) -> None:
        """Set mock weekly report."""
        self._mock_weekly_report = report
    
    def daily_summary(self, date: Optional[datetime] = None) -> str:
        """Return mock if set."""
        if self._mock_daily_summary:
            return self._mock_daily_summary
        return super().daily_summary(date)
    
    def weekly_report(self, end_date: Optional[datetime] = None) -> WeeklyReport:
        """Return mock if set."""
        if self._mock_weekly_report:
            return self._mock_weekly_report
        return super().weekly_report(end_date)
