"""Tests for Issue #1299 — Gelecek Yetenekler (Future Capabilities).

Covers all 6 planned skills with ABC contracts, data models,
and placeholder implementations.
"""

from __future__ import annotations

from skills.file_search import (SUPPORTED_TYPES, FileResult, IndexStats,
                                PlaceholderFileSearch)
from skills.health_reminder import (HealthLog, Medication,
                                    PlaceholderHealthReminder, WaterConfig)
from skills.secret_manager import (PlaceholderSecretManager, SecretEntry,
                                   generate_password)

from skills.finance import (BudgetAlert, Expense, ExpenseCategory,
                            PlaceholderFinanceTracker)
from skills.reporter import (PlaceholderReportGenerator, ProductivityMetric,
                             Report, ToolUsageStat)
from skills.travel import Booking, PlaceholderTravelAssistant, Trip

# ─── Finance ─────────────────────────────────────────────────────────


class TestExpenseCategory:
    def test_values(self):
        assert ExpenseCategory.FOOD == "yemek"
        assert ExpenseCategory.TRANSPORT == "ulaşım"
        assert ExpenseCategory.OTHER == "diğer"


class TestExpense:
    def test_to_dict(self):
        e = Expense(amount=150.0, category=ExpenseCategory.FOOD, merchant="Migros")
        d = e.to_dict()
        assert d["amount"] == 150.0
        assert d["category"] == "yemek"
        assert d["merchant"] == "Migros"
        assert d["currency"] == "TRY"


class TestBudgetAlert:
    def test_to_dict(self):
        alert = BudgetAlert(
            category="yemek",
            budget=2000.0,
            spent=2500.0,
            remaining=-500.0,
            exceeded=True,
        )
        d = alert.to_dict()
        assert d["exceeded"] is True
        assert d["remaining"] == -500.0


class TestPlaceholderFinance:
    def test_parse_expenses_empty(self):
        tracker = PlaceholderFinanceTracker()
        assert tracker.parse_expenses() == []

    def test_monthly_summary_stub(self):
        tracker = PlaceholderFinanceTracker()
        result = tracker.monthly_summary()
        assert result["status"] == "planned"

    def test_check_budget_empty(self):
        tracker = PlaceholderFinanceTracker()
        assert tracker.check_budget() == []

    def test_categorize_returns_other(self):
        tracker = PlaceholderFinanceTracker()
        cat = tracker.categorize("test", 100.0)
        assert cat == ExpenseCategory.OTHER


# ─── File Search ─────────────────────────────────────────────────────


class TestFileResult:
    def test_to_dict(self):
        r = FileResult(
            path="/home/user/doc.pdf",
            filename="doc.pdf",
            score=0.92345,
            snippet="relevant text here",
            file_type=".pdf",
            size_bytes=1024000,
        )
        d = r.to_dict()
        assert d["score"] == 0.923
        assert d["size_kb"] == 1000.0
        assert d["file_type"] == ".pdf"

    def test_to_dict_minimal(self):
        r = FileResult(path="/x", filename="x", score=0.5)
        d = r.to_dict()
        assert "snippet" not in d
        assert "size_kb" not in d


class TestIndexStats:
    def test_to_dict(self):
        stats = IndexStats(total_files=100, indexed_files=80, total_size_mb=250.0)
        d = stats.to_dict()
        assert d["total_files"] == 100
        assert d["indexed_files"] == 80


class TestPlaceholderFileSearch:
    def test_search_empty(self):
        s = PlaceholderFileSearch()
        assert s.search("sunum") == []

    def test_index_directory(self):
        s = PlaceholderFileSearch()
        stats = s.index_directory("/home/user/Documents")
        assert "/home/user/Documents" in stats.directories

    def test_get_stats(self):
        s = PlaceholderFileSearch()
        assert s.get_stats().total_files == 0

    def test_supported_types(self):
        assert ".pdf" in SUPPORTED_TYPES
        assert ".docx" in SUPPORTED_TYPES
        assert ".exe" not in SUPPORTED_TYPES


# ─── Secret Manager ─────────────────────────────────────────────────


class TestSecretEntry:
    def test_to_dict_no_values(self):
        entry = SecretEntry(name="aws-key", vault="work", username="admin")
        d = entry.to_dict()
        assert d["name"] == "aws-key"
        assert d["vault"] == "work"
        assert d["username"] == "admin"
        # Must NOT contain any secret value
        assert "password" not in d
        assert "secret" not in d


class TestGeneratePassword:
    def test_default_length(self):
        pw = generate_password()
        assert len(pw) == 20

    def test_custom_length(self):
        pw = generate_password(length=32)
        assert len(pw) == 32

    def test_min_length_enforced(self):
        pw = generate_password(length=2)
        assert len(pw) == 8

    def test_max_length_enforced(self):
        pw = generate_password(length=500)
        assert len(pw) == 128

    def test_pin_charset(self):
        pw = generate_password(length=10, charset="pin")
        assert pw.isdigit()

    def test_alphanumeric_charset(self):
        pw = generate_password(length=50, charset="alphanumeric")
        assert pw.isalnum()

    def test_uniqueness(self):
        passwords = {generate_password() for _ in range(10)}
        assert len(passwords) == 10  # All should be unique


class TestPlaceholderSecretManager:
    def test_retrieve_returns_none(self):
        sm = PlaceholderSecretManager()
        assert sm.retrieve("test") is None

    def test_list_entries_empty(self):
        sm = PlaceholderSecretManager()
        assert sm.list_entries() == []

    def test_generate_password_works(self):
        sm = PlaceholderSecretManager()
        pw = sm.generate_password(16, "alphanumeric")
        assert len(pw) == 16
        assert pw.isalnum()


# ─── Travel ──────────────────────────────────────────────────────────


class TestBooking:
    def test_to_dict(self):
        b = Booking(
            booking_type="flight",
            provider="THY",
            confirmation="ABC123",
            details={"flight_no": "TK1234"},
        )
        d = b.to_dict()
        assert d["type"] == "flight"
        assert d["provider"] == "THY"
        assert d["confirmation"] == "ABC123"

    def test_to_dict_minimal(self):
        b = Booking(booking_type="hotel")
        d = b.to_dict()
        assert d["type"] == "hotel"
        assert "confirmation" not in d


class TestTrip:
    def test_to_dict(self):
        trip = Trip(
            name="İstanbul gezisi",
            destination="İstanbul",
            bookings=[Booking(booking_type="flight", provider="THY")],
        )
        d = trip.to_dict()
        assert d["name"] == "İstanbul gezisi"
        assert len(d["bookings"]) == 1


class TestPlaceholderTravel:
    def test_parse_bookings_empty(self):
        ta = PlaceholderTravelAssistant()
        assert ta.parse_bookings() == []

    def test_create_itinerary(self):
        ta = PlaceholderTravelAssistant()
        trip = ta.create_itinerary("Test Trip")
        assert trip.name == "Test Trip"

    def test_set_reminders(self):
        ta = PlaceholderTravelAssistant()
        trip = Trip(name="x")
        assert ta.set_reminders(trip) == 0


# ─── Health Reminder ─────────────────────────────────────────────────


class TestMedication:
    def test_to_dict(self):
        med = Medication(name="Vitamin D", dose="1000IU", schedule="sabah")
        d = med.to_dict()
        assert d["name"] == "Vitamin D"
        assert d["schedule"] == "sabah"
        assert d["active"] is True


class TestHealthLog:
    def test_to_dict(self):
        log = HealthLog(action="medication_taken", details="Vitamin D")
        d = log.to_dict()
        assert d["action"] == "medication_taken"
        assert "timestamp" in d


class TestWaterConfig:
    def test_remaining(self):
        wc = WaterConfig(daily_goal_ml=2500, consumed_ml=1000)
        assert wc.remaining_ml == 1500

    def test_remaining_capped(self):
        wc = WaterConfig(daily_goal_ml=2500, consumed_ml=3000)
        assert wc.remaining_ml == 0

    def test_to_dict(self):
        wc = WaterConfig()
        d = wc.to_dict()
        assert d["daily_goal_ml"] == 2500
        assert d["remaining_ml"] == 2500


class TestPlaceholderHealthReminder:
    def test_add_medication(self):
        hr = PlaceholderHealthReminder()
        med = hr.add_medication("Aspirin", "akşam", "100mg")
        assert med.name == "Aspirin"
        assert med.schedule == "akşam"

    def test_setup_water_reminder(self):
        hr = PlaceholderHealthReminder()
        wc = hr.setup_water_reminder(30, 3000)
        assert wc.interval_minutes == 30
        assert wc.daily_goal_ml == 3000

    def test_setup_ergonomics(self):
        hr = PlaceholderHealthReminder()
        result = hr.setup_ergonomics(60)
        assert result["max_sitting_minutes"] == 60

    def test_log_action(self):
        hr = PlaceholderHealthReminder()
        log = hr.log_action("water_drunk", "250ml")
        assert log.action == "water_drunk"

    def test_daily_summary_stub(self):
        hr = PlaceholderHealthReminder()
        result = hr.get_daily_summary()
        assert result["status"] == "planned"


# ─── Reporter ────────────────────────────────────────────────────────


class TestToolUsageStat:
    def test_to_dict(self):
        stat = ToolUsageStat(
            tool_name="gmail.send", call_count=42, success_count=40, avg_latency_ms=150.3
        )
        d = stat.to_dict()
        assert d["tool"] == "gmail.send"
        assert d["calls"] == 42


class TestProductivityMetric:
    def test_to_dict(self):
        pm = ProductivityMetric(
            period="this_week",
            total_meetings_h=8.5,
            total_work_h=32.0,
            focus_ratio=0.79,
            tool_interactions=150,
            tasks_completed=12,
        )
        d = pm.to_dict()
        assert d["focus_ratio"] == 0.79
        assert d["tasks_completed"] == 12


class TestReport:
    def test_to_dict(self):
        report = Report(
            report_type="weekly",
            title="Haftalık Rapor",
            period="2026-W07",
            content="Rapor içeriği...",
        )
        d = report.to_dict()
        assert d["type"] == "weekly"
        assert d["title"] == "Haftalık Rapor"

    def test_to_dict_with_stats(self):
        report = Report(
            report_type="weekly",
            title="Test",
            tool_stats=[
                ToolUsageStat(tool_name="test", call_count=5, success_count=5),
            ],
        )
        d = report.to_dict()
        assert len(d["tool_stats"]) == 1


class TestPlaceholderReporter:
    def test_weekly_report(self):
        rg = PlaceholderReportGenerator()
        report = rg.weekly_report()
        assert report.report_type == "weekly"
        assert "aktif değil" in report.content

    def test_monthly_report(self):
        rg = PlaceholderReportGenerator()
        report = rg.monthly_report()
        assert report.report_type == "monthly"

    def test_productivity_analysis(self):
        rg = PlaceholderReportGenerator()
        pm = rg.productivity_analysis("this_week")
        assert pm.period == "this_week"

    def test_export_stub(self):
        rg = PlaceholderReportGenerator()
        report = Report(report_type="weekly", title="Test")
        result = rg.export(report, "markdown")
        assert result == ""
