"""Tests for Issue #526: Router output strict schema validation + auto-repair.

Tests cover:
1. Field-level validation (route, intent, confidence, tool_plan, slots)
2. Repair pipeline: missing → default, invalid → fuzzy-match
3. Broken JSON → repair → valid output scenario
4. RepairMetrics rolling window + /status formatting
5. Edge cases (None input, empty dict, type coercion)
"""

from __future__ import annotations

import threading

import pytest

from bantz.brain.router_validation import (
    FIELD_DEFAULTS,
    REQUIRED_FIELDS,
    VALID_CALENDAR_INTENTS,
    VALID_GMAIL_INTENTS,
    VALID_ROUTES,
    FieldValidation,
    RepairMetrics,
    RepairReport,
    repair_router_output,
    validate_router_output,
)


# ── validate_router_output ────────────────────────────────────


class TestValidateRouterOutput:
    """Field-level validation tests."""

    def test_valid_minimal_output(self) -> None:
        """Tüm zorunlu alan doğru → valid."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": 0.9,
            "tool_plan": ["calendar.create_event"],
            "assistant_reply": "Takvime ekliyorum.",
        }
        is_valid, validations = validate_router_output(parsed)
        assert is_valid is True

    def test_missing_required_field(self) -> None:
        """Zorunlu alan eksikse invalid."""
        parsed = {"route": "calendar", "confidence": 0.9}
        is_valid, validations = validate_router_output(parsed)
        assert is_valid is False
        missing_names = [v.field_name for v in validations if v.error == "missing"]
        assert "calendar_intent" in missing_names
        assert "tool_plan" in missing_names
        assert "assistant_reply" in missing_names

    def test_invalid_route(self) -> None:
        """Geçersiz route enum → invalid."""
        parsed = {
            "route": "weather",
            "calendar_intent": "none",
            "confidence": 0.5,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        is_valid, validations = validate_router_output(parsed)
        assert is_valid is False
        route_v = next(v for v in validations if v.field_name == "route")
        assert "invalid route" in route_v.error

    def test_invalid_calendar_intent(self) -> None:
        """Geçersiz takvim intent'i → invalid."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "delete",
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        is_valid, validations = validate_router_output(parsed)
        assert is_valid is False

    def test_confidence_out_of_range(self) -> None:
        """Confidence > 1.0 → invalid."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": 1.5,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        is_valid, validations = validate_router_output(parsed)
        assert is_valid is False

    def test_confidence_negative(self) -> None:
        """Confidence < 0 → invalid."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": -0.5,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        is_valid, _ = validate_router_output(parsed)
        assert is_valid is False

    def test_confidence_not_a_number(self) -> None:
        """Confidence string (sayıya dönüştürülemeyen) → invalid."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": "yüksek",
            "tool_plan": [],
            "assistant_reply": "test",
        }
        is_valid, _ = validate_router_output(parsed)
        assert is_valid is False

    def test_tool_plan_not_list(self) -> None:
        """tool_plan string → invalid."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": 0.9,
            "tool_plan": "calendar.create_event",
            "assistant_reply": "test",
        }
        is_valid, _ = validate_router_output(parsed)
        assert is_valid is False

    def test_assistant_reply_not_string(self) -> None:
        """assistant_reply integer → invalid."""
        parsed = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "confidence": 0.8,
            "tool_plan": [],
            "assistant_reply": 42,
        }
        is_valid, _ = validate_router_output(parsed)
        assert is_valid is False

    def test_slots_not_dict(self) -> None:
        """slots list → invalid."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "test",
            "slots": ["date", "time"],
        }
        is_valid, _ = validate_router_output(parsed)
        assert is_valid is False

    def test_gmail_intent_invalid(self) -> None:
        """Geçersiz gmail_intent → invalid."""
        parsed = {
            "route": "gmail",
            "calendar_intent": "none",
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "test",
            "gmail_intent": "delete",
        }
        is_valid, _ = validate_router_output(parsed)
        assert is_valid is False

    def test_not_a_dict(self) -> None:
        """Input dict değilse → invalid."""
        is_valid, validations = validate_router_output("not a dict")
        assert is_valid is False
        assert validations[0].field_name == "_root"

    def test_empty_dict(self) -> None:
        """Boş dict → tüm zorunlu alanlar eksik."""
        is_valid, validations = validate_router_output({})
        assert is_valid is False
        missing = [v.field_name for v in validations if v.error == "missing"]
        assert set(missing) == set(REQUIRED_FIELDS)

    def test_valid_with_optional_fields(self) -> None:
        """Opsiyonel alanlar doğruysa sorun yok."""
        parsed = {
            "route": "gmail",
            "calendar_intent": "none",
            "confidence": 0.7,
            "tool_plan": ["gmail.list"],
            "assistant_reply": "Maillerine bakıyorum.",
            "slots": {"query": "toplantı"},
            "gmail_intent": "list",
        }
        is_valid, _ = validate_router_output(parsed)
        assert is_valid is True


# ── repair_router_output ──────────────────────────────────────


class TestRepairRouterOutput:
    """Repair pipeline tests."""

    def test_already_valid_no_repair(self) -> None:
        """Zaten geçerli → repair yapılmaz."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": 0.9,
            "tool_plan": ["calendar.create_event"],
            "assistant_reply": "Ekliyorum.",
        }
        repaired, report = repair_router_output(parsed)
        assert report.is_valid_before is True
        assert report.is_valid_after is True
        assert report.fields_repaired == []
        assert report.needed_repair is False

    def test_missing_fields_filled(self) -> None:
        """Eksik alanlar default ile doldurulur."""
        parsed = {"route": "smalltalk"}
        repaired, report = repair_router_output(parsed)
        assert report.is_valid_before is False
        assert report.is_valid_after is True
        assert "calendar_intent" in report.fields_repaired
        assert "confidence" in report.fields_repaired
        assert "tool_plan" in report.fields_repaired
        assert "assistant_reply" in report.fields_repaired
        assert repaired["calendar_intent"] == "none"
        assert repaired["confidence"] == 0.0
        assert repaired["tool_plan"] == []
        assert repaired["assistant_reply"] == ""

    def test_fuzzy_route_repair(self) -> None:
        """Yakın yazım hatası düzeltilir: calender → calendar."""
        parsed = {
            "route": "calender",
            "calendar_intent": "create",
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        repaired, report = repair_router_output(parsed)
        assert repaired["route"] == "calendar"
        assert "route" in report.fields_repaired

    def test_fuzzy_intent_repair(self) -> None:
        """Yakın intent düzeltmesi: creat → create."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "creat",
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        repaired, report = repair_router_output(parsed)
        assert repaired["calendar_intent"] == "create"

    def test_confidence_string_coercion(self) -> None:
        """Confidence string → float dönüşümü."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": "0.85",
            "tool_plan": [],
            "assistant_reply": "test",
        }
        # "0.85" geçerli bir float string — validate aşamasında float() yapılır
        is_valid, _ = validate_router_output(parsed)
        assert is_valid is True  # Çünkü float("0.85") geçerli

    def test_confidence_clamp_high(self) -> None:
        """Confidence > 1 → 1.0 clamp."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": 2.5,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        repaired, report = repair_router_output(parsed)
        assert repaired["confidence"] == 1.0
        assert "confidence" in report.fields_repaired

    def test_confidence_clamp_negative(self) -> None:
        """Confidence < 0 → 0.0 clamp."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": -1.0,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        repaired, report = repair_router_output(parsed)
        assert repaired["confidence"] == 0.0

    def test_tool_plan_string_to_list(self) -> None:
        """tool_plan string → list'e dönüştürülür."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": 0.9,
            "tool_plan": "calendar.create_event",
            "assistant_reply": "test",
        }
        repaired, report = repair_router_output(parsed)
        assert repaired["tool_plan"] == ["calendar.create_event"]
        assert "tool_plan" in report.fields_repaired

    def test_tool_plan_comma_separated(self) -> None:
        """tool_plan virgüllü string → list split."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "query",
            "confidence": 0.8,
            "tool_plan": "calendar.list_events, calendar.create_event",
            "assistant_reply": "test",
        }
        repaired, report = repair_router_output(parsed)
        assert repaired["tool_plan"] == ["calendar.list_events", "calendar.create_event"]

    def test_slots_non_dict_repair(self) -> None:
        """slots list → {} repair."""
        parsed = {
            "route": "calendar",
            "calendar_intent": "create",
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "test",
            "slots": ["date"],
        }
        repaired, report = repair_router_output(parsed)
        assert repaired["slots"] == {}

    def test_none_input_full_defaults(self) -> None:
        """None input → tüm alanlar default."""
        repaired, report = repair_router_output(None)
        assert report.is_valid_before is False
        assert report.is_valid_after is True
        assert repaired["route"] == "unknown"
        assert repaired["confidence"] == 0.0

    def test_completely_broken_still_produces_output(self) -> None:
        """Tamamen bozuk input bile valid output üretir."""
        repaired, report = repair_router_output(
            {"route": 123, "confidence": "xxx", "tool_plan": True}
        )
        assert report.is_valid_after is True
        assert repaired["route"] == "unknown"
        assert repaired["confidence"] == 0.0
        assert repaired["tool_plan"] == []

    def test_unknown_route_no_fuzzy_match(self) -> None:
        """Hiç yakın olmayan route → unknown."""
        parsed = {
            "route": "zzzzzz",
            "calendar_intent": "none",
            "confidence": 0.5,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        repaired, report = repair_router_output(parsed)
        assert repaired["route"] == "unknown"

    def test_route_case_normalization(self) -> None:
        """Route büyük harf → küçük harf normalizasyonu."""
        parsed = {
            "route": "CALENDAR",
            "calendar_intent": "create",
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        # "CALENDAR" → "calendar" geçerli mi? validate eder
        is_valid, validations = validate_router_output(parsed)
        # _validate_route normalizes lowercase
        assert is_valid is True

    def test_route_whitespace_stripped(self) -> None:
        """Route boşluklu → strip edilir."""
        parsed = {
            "route": "  calendar  ",
            "calendar_intent": "create",
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "test",
        }
        is_valid, _ = validate_router_output(parsed)
        assert is_valid is True


# ── RepairReport ──────────────────────────────────────────────


class TestRepairReport:
    """RepairReport properties and trace_line."""

    def test_trace_line_valid(self) -> None:
        report = RepairReport(is_valid_before=True, is_valid_after=True)
        assert "valid=true" in report.to_trace_line()

    def test_trace_line_repaired(self) -> None:
        report = RepairReport(
            is_valid_before=False,
            is_valid_after=True,
            fields_repaired=["route", "confidence"],
        )
        line = report.to_trace_line()
        assert "valid_before=False" in line
        assert "route,confidence" in line

    def test_needed_repair_property(self) -> None:
        report = RepairReport(is_valid_before=False, is_valid_after=True)
        assert report.needed_repair is True

    def test_repair_succeeded_property(self) -> None:
        report = RepairReport(is_valid_before=False, is_valid_after=True)
        assert report.repair_succeeded is True

    def test_no_repair_needed(self) -> None:
        report = RepairReport(is_valid_before=True)
        assert report.needed_repair is False


# ── RepairMetrics ─────────────────────────────────────────────


class TestRepairMetrics:
    """Rolling-window repair metrics."""

    def test_empty_metrics(self) -> None:
        """Boş metrik → 0 repair rate."""
        m = RepairMetrics(window_size=10)
        assert m.total == 0
        assert m.repair_rate == 0.0
        assert m.repair_success_rate == 100.0

    def test_all_valid_no_repair(self) -> None:
        """Hiç repair gerekmemiş → %0 repair rate."""
        m = RepairMetrics(window_size=10)
        for _ in range(5):
            m.record(RepairReport(is_valid_before=True, is_valid_after=True))
        assert m.total == 5
        assert m.repair_rate == 0.0
        assert m.repair_success_rate == 100.0

    def test_some_repairs(self) -> None:
        """3/10 repair → %30 rate."""
        m = RepairMetrics(window_size=10)
        for _ in range(7):
            m.record(RepairReport(is_valid_before=True, is_valid_after=True))
        for _ in range(3):
            m.record(RepairReport(is_valid_before=False, is_valid_after=True))
        assert m.total == 10
        assert m.repair_rate == 30.0
        assert m.repair_success_rate == 100.0

    def test_failed_repair(self) -> None:
        """Başarısız repair → success rate düşer."""
        m = RepairMetrics(window_size=10)
        m.record(RepairReport(is_valid_before=False, is_valid_after=True))
        m.record(RepairReport(is_valid_before=False, is_valid_after=False))
        assert m.repair_count == 2
        assert m.repair_success_count == 1
        assert m.repair_success_rate == 50.0

    def test_rolling_window(self) -> None:
        """Window dolunca eski kayıtlar düşer."""
        m = RepairMetrics(window_size=3)
        m.record(RepairReport(is_valid_before=False, is_valid_after=True))
        m.record(RepairReport(is_valid_before=True, is_valid_after=True))
        m.record(RepairReport(is_valid_before=True, is_valid_after=True))
        # Window: [repair, ok, ok] → repair_rate = 33.3%
        assert m.total == 3
        assert m.repair_count == 1

        # 4th record → ilk kayıt (repair) düşer
        m.record(RepairReport(is_valid_before=True, is_valid_after=True))
        assert m.total == 3
        assert m.repair_count == 0
        assert m.repair_rate == 0.0

    def test_summary_dict(self) -> None:
        """summary() doğru format döner."""
        m = RepairMetrics(window_size=100)
        m.record(RepairReport(is_valid_before=False, is_valid_after=True))
        m.record(RepairReport(is_valid_before=True, is_valid_after=True))
        s = m.summary()
        assert s["window_size"] == 100
        assert s["total_turns"] == 2
        assert s["repairs_needed"] == 1
        assert s["repairs_succeeded"] == 1
        assert s["repair_rate_pct"] == 50.0
        assert s["repair_success_rate_pct"] == 100.0

    def test_format_status(self) -> None:
        """/status çıktısı emoji ve metin içerir."""
        m = RepairMetrics(window_size=100)
        m.record(RepairReport(is_valid_before=False, is_valid_after=True))
        status = m.format_status()
        assert "📊" in status
        assert "Router Schema Repair" in status
        assert "1/100" in status

    def test_clear(self) -> None:
        """clear() tüm kayıtları siler."""
        m = RepairMetrics(window_size=10)
        m.record(RepairReport(is_valid_before=False, is_valid_after=True))
        assert m.total == 1
        m.clear()
        assert m.total == 0

    def test_thread_safety(self) -> None:
        """Concurrent erişimde veri kaybı olmaz."""
        m = RepairMetrics(window_size=1000)
        errors = []

        def writer(n: int) -> None:
            try:
                for _ in range(n):
                    m.record(RepairReport(is_valid_before=False, is_valid_after=True))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(50,)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert m.total == 500


# ── End-to-end: Broken JSON → repair → valid ─────────────────


class TestEndToEndBrokenJsonRepair:
    """Issue #526 kabul senaryosu: bozuk JSON → repair → valid output."""

    def test_llm_returns_typo_route(self) -> None:
        """LLM 'calender' yazsa bile → 'calendar' düzeltilir."""
        raw = {
            "route": "calender",
            "calendar_intent": "creat",
            "confidence": "0.9",
            "tool_plan": "calendar.create_event",
            "assistant_reply": "Toplantıyı ekliyorum.",
            "slots": {"date": "yarın"},
        }
        repaired, report = repair_router_output(raw)
        assert report.needed_repair is True
        assert report.repair_succeeded is True
        assert repaired["route"] == "calendar"
        assert repaired["calendar_intent"] == "create"
        assert repaired["tool_plan"] == ["calendar.create_event"]

    def test_llm_returns_extra_fields(self) -> None:
        """Extra alanlar korunur, sorun çıkmaz."""
        raw = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "confidence": 0.8,
            "tool_plan": [],
            "assistant_reply": "Merhaba!",
            "extra_field": "value",
        }
        repaired, report = repair_router_output(raw)
        assert report.is_valid_before is True
        assert repaired.get("extra_field") == "value"

    def test_llm_returns_only_route(self) -> None:
        """Sadece route geldi → geri kalan default."""
        raw = {"route": "gmail"}
        repaired, report = repair_router_output(raw)
        assert report.needed_repair is True
        assert repaired["route"] == "gmail"
        assert repaired["confidence"] == 0.0
        assert repaired["tool_plan"] == []
        assert repaired["assistant_reply"] == ""

    def test_metrics_track_e2e(self) -> None:
        """End-to-end metrics: validation → repair → record."""
        metrics = RepairMetrics(window_size=100)

        # Valid turn
        valid = {
            "route": "smalltalk",
            "calendar_intent": "none",
            "confidence": 0.9,
            "tool_plan": [],
            "assistant_reply": "Merhaba!",
        }
        _, report_ok = repair_router_output(valid)
        metrics.record(report_ok)

        # Broken turn
        broken = {"route": "calender", "confidence": "xxx"}
        _, report_bad = repair_router_output(broken)
        metrics.record(report_bad)

        assert metrics.total == 2
        assert metrics.repair_rate == 50.0
        assert metrics.repair_success_rate == 100.0

    def test_completely_empty_input_recovers(self) -> None:
        """Boş dict → tüm defaults doldu, valid output."""
        repaired, report = repair_router_output({})
        assert report.needed_repair is True
        assert report.repair_succeeded is True
        assert repaired["route"] == "unknown"
        assert repaired["calendar_intent"] == "none"
        assert repaired["confidence"] == 0.0
        assert repaired["tool_plan"] == []
        assert isinstance(repaired["slots"], dict)

    def test_report_trace_line_in_e2e(self) -> None:
        """Trace line doğru formatlanır."""
        raw = {"route": "calender"}
        _, report = repair_router_output(raw)
        line = report.to_trace_line()
        assert "[schema]" in line
        assert "valid_before=False" in line
        assert "valid_after=True" in line


# ── Constants ─────────────────────────────────────────────────


class TestConstants:
    """Doğru constant kümelerini kontrol et."""

    def test_valid_routes(self) -> None:
        assert VALID_ROUTES == {"calendar", "gmail", "smalltalk", "system", "unknown"}

    def test_valid_calendar_intents(self) -> None:
        assert VALID_CALENDAR_INTENTS == {"create", "modify", "cancel", "query", "none"}

    def test_valid_gmail_intents(self) -> None:
        assert VALID_GMAIL_INTENTS == {"list", "search", "read", "send", "none"}

    def test_required_fields(self) -> None:
        assert "route" in REQUIRED_FIELDS
        assert "confidence" in REQUIRED_FIELDS
        assert "assistant_reply" in REQUIRED_FIELDS

    def test_field_defaults_cover_required(self) -> None:
        for f in REQUIRED_FIELDS:
            assert f in FIELD_DEFAULTS, f"FIELD_DEFAULTS missing: {f}"
