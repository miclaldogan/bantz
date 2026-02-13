"""Tests for Issue #230: Write-Confirmation UX v2.

Tests for preview normalization, edit path, and idempotency.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from bantz.brain.confirmation_ux import (
    ConfirmationPreview,
    EditPath,
    IdempotencyKey,
    IdempotencyTracker,
    PreviewNormalization,
    build_confirmation_prompt,
)


class TestPreviewNormalization:
    """Tests for PreviewNormalization class."""

    def test_normalize_title_basic(self) -> None:
        """Basic title normalization."""
        assert PreviewNormalization.normalize_title("toplantı") == "Toplantı"
        assert PreviewNormalization.normalize_title(" test ") == "Test"

    def test_normalize_title_strip_quotes(self) -> None:
        """Quotes should be stripped."""
        assert PreviewNormalization.normalize_title('"test"') == "Test"
        assert PreviewNormalization.normalize_title("'test'") == "Test"
        assert PreviewNormalization.normalize_title("'Toplantı'") == "Toplantı"

    def test_normalize_title_strip_punctuation(self) -> None:
        """Trailing punctuation should be stripped."""
        assert PreviewNormalization.normalize_title("test...") == "Test"
        assert PreviewNormalization.normalize_title("test!!!") == "Test"

    def test_normalize_title_truncate(self) -> None:
        """Long titles should be truncated."""
        long_title = "a" * 100
        result = PreviewNormalization.normalize_title(long_title)
        assert len(result) <= 50
        assert result.endswith("...")

    def test_normalize_title_empty(self) -> None:
        """Empty title should return empty."""
        assert PreviewNormalization.normalize_title("") == ""
        assert PreviewNormalization.normalize_title(None) == ""  # type: ignore

    def test_format_time_hhmm(self) -> None:
        """HH:MM format should be preserved."""
        assert PreviewNormalization.format_time("14:00") == "14:00"
        assert PreviewNormalization.format_time("9:30") == "09:30"

    def test_format_time_ampm(self) -> None:
        """AM/PM format should be converted."""
        assert PreviewNormalization.format_time("2:00 PM") == "14:00"
        assert PreviewNormalization.format_time("9:00 AM") == "09:00"
        assert PreviewNormalization.format_time("12:00 PM") == "12:00"
        assert PreviewNormalization.format_time("12:00 AM") == "00:00"

    def test_format_time_empty(self) -> None:
        """Empty time should return empty."""
        assert PreviewNormalization.format_time("") == ""

    def test_format_date_today_tomorrow(self) -> None:
        """Today and tomorrow should be recognized."""
        today = datetime.now().strftime("%Y-%m-%d")
        result = PreviewNormalization.format_date(today)
        assert result == "Bugün"

    def test_format_date_turkish_month(self) -> None:
        """Dates should use Turkish month names."""
        result = PreviewNormalization.format_date("2024-01-15")
        assert "Ocak" in result
        assert "15" in result

    def test_format_duration_minutes(self) -> None:
        """Minutes should format correctly."""
        assert PreviewNormalization.format_duration(30) == "30 dakika"
        assert PreviewNormalization.format_duration(45) == "45 dakika"

    def test_format_duration_hours(self) -> None:
        """Hours should format correctly."""
        assert PreviewNormalization.format_duration(60) == "1 saat"
        assert PreviewNormalization.format_duration(120) == "2 saat"

    def test_format_duration_mixed(self) -> None:
        """Mixed hours and minutes should format correctly."""
        assert PreviewNormalization.format_duration(90) == "1 buçuk saat"
        assert PreviewNormalization.format_duration(75) == "1 saat 15 dakika"


class TestConfirmationPreview:
    """Tests for ConfirmationPreview class."""

    def test_calendar_create_basic(self) -> None:
        """Basic calendar create prompt."""
        preview = ConfirmationPreview(
            action_type="create",
            target="calendar",
            title="Toplantı",
            time="14:00",
        )
        result = preview.to_turkish()
        assert "Toplantı" in result
        assert "14:00" in result
        assert "eklensin mi" in result

    def test_calendar_create_with_date(self) -> None:
        """Calendar create with date."""
        preview = ConfirmationPreview(
            action_type="create",
            target="calendar",
            title="Toplantı",
            time="15:00",
            date="2024-01-15",
        )
        result = preview.to_turkish()
        assert "Toplantı" in result
        assert "eklensin mi" in result

    def test_calendar_create_with_duration(self) -> None:
        """Calendar create with duration."""
        preview = ConfirmationPreview(
            action_type="create",
            target="calendar",
            title="Toplantı",
            time="14:00",
            duration=60,
        )
        result = preview.to_turkish()
        assert "1 saat" in result

    def test_calendar_delete(self) -> None:
        """Calendar delete prompt."""
        preview = ConfirmationPreview(
            action_type="delete",
            target="calendar",
            title="Toplantı",
        )
        result = preview.to_turkish()
        assert "silinsin mi" in result

    def test_gmail_send(self) -> None:
        """Gmail send prompt."""
        preview = ConfirmationPreview(
            action_type="send",
            target="gmail",
            title="Merhaba",
            recipient="test@example.com",
        )
        result = preview.to_turkish()
        assert "test@example.com" in result
        assert "gönderilsin mi" in result


class TestEditPath:
    """Tests for EditPath class."""

    def test_detect_time_edit(self) -> None:
        """Time edit should be detected."""
        edit = EditPath.detect_edit("14:30 olsun")
        assert edit is not None
        assert edit["field"] == "time"
        assert edit["value"] == "14:30"

    def test_detect_time_with_saat(self) -> None:
        """Time with 'saat' prefix should be detected."""
        edit = EditPath.detect_edit("saat 15:00")
        assert edit is not None
        assert edit["field"] == "time"
        assert edit["value"] == "15:00"

    def test_detect_hour_only(self) -> None:
        """Hour-only edit should be detected."""
        edit = EditPath.detect_edit("15 olsun")
        assert edit is not None
        assert edit["field"] == "time"
        assert edit["value"] == "15:00"

    def test_detect_duration_hours(self) -> None:
        """Duration in hours should be detected."""
        edit = EditPath.detect_edit("2 saat olsun")
        assert edit is not None
        assert edit["field"] == "duration"
        assert edit["value"] == "120"

    def test_detect_duration_minutes(self) -> None:
        """Duration in minutes should be detected."""
        edit = EditPath.detect_edit("30 dakika olsun")
        assert edit is not None
        assert edit["field"] == "duration"
        assert edit["value"] == "30"

    def test_detect_date_hint(self) -> None:
        """Date hint should be detected."""
        edit = EditPath.detect_edit("yarın olsun")
        assert edit is not None
        assert edit["field"] == "date_hint"
        assert edit["value"] == "yarın"

    def test_detect_no_edit(self) -> None:
        """Non-edit text should return None."""
        assert EditPath.detect_edit("evet") is None
        assert EditPath.detect_edit("hayır") is None
        assert EditPath.detect_edit("merhaba") is None

    def test_apply_edit_time(self) -> None:
        """Apply time edit should update slots."""
        slots = {"title": "Toplantı", "time": "14:00"}
        edit = {"field": "time", "value": "15:00"}
        result = EditPath.apply_edit(slots, edit)
        assert result["time"] == "15:00"
        assert result["title"] == "Toplantı"

    def test_apply_edit_duration(self) -> None:
        """Apply duration edit should update slots."""
        slots = {"title": "Toplantı", "duration": 60}
        edit = {"field": "duration", "value": "90"}
        result = EditPath.apply_edit(slots, edit)
        assert result["duration"] == 90


class TestIdempotencyKey:
    """Tests for IdempotencyKey class."""

    def test_generate_key(self) -> None:
        """Key should be generated."""
        key = IdempotencyKey.generate(
            action_type="create",
            target="calendar",
            title="Toplantı",
            time="14:00",
        )
        assert key.key is not None
        assert len(key.key) == 16

    def test_same_params_same_key(self) -> None:
        """Same parameters should generate same key."""
        key1 = IdempotencyKey.generate(
            action_type="create",
            target="calendar",
            title="Toplantı",
        )
        key2 = IdempotencyKey.generate(
            action_type="create",
            target="calendar",
            title="Toplantı",
        )
        assert key1.key == key2.key

    def test_different_params_different_key(self) -> None:
        """Different parameters should generate different key."""
        key1 = IdempotencyKey.generate(
            action_type="create",
            target="calendar",
            title="Toplantı",
        )
        key2 = IdempotencyKey.generate(
            action_type="create",
            target="calendar",
            title="Görüşme",
        )
        assert key1.key != key2.key

    def test_to_dict(self) -> None:
        """Key should convert to dict."""
        key = IdempotencyKey.generate(
            action_type="create",
            target="calendar",
        )
        d = key.to_dict()
        assert "key" in d
        assert "created_at" in d


class TestIdempotencyTracker:
    """Tests for IdempotencyTracker class."""

    def test_first_operation_allowed(self) -> None:
        """First operation should be allowed."""
        tracker = IdempotencyTracker()
        key = IdempotencyKey.generate(
            action_type="create",
            target="calendar",
            title="Toplantı",
        )
        assert tracker.check_and_mark(key) is True

    def test_duplicate_blocked(self) -> None:
        """Duplicate operation should be blocked."""
        tracker = IdempotencyTracker()
        key = IdempotencyKey.generate(
            action_type="create",
            target="calendar",
            title="Toplantı",
        )
        assert tracker.check_and_mark(key) is True
        assert tracker.check_and_mark(key) is False

    def test_different_operations_allowed(self) -> None:
        """Different operations should both be allowed."""
        tracker = IdempotencyTracker()
        key1 = IdempotencyKey.generate(
            action_type="create",
            target="calendar",
            title="Toplantı",
        )
        key2 = IdempotencyKey.generate(
            action_type="create",
            target="calendar",
            title="Görüşme",
        )
        assert tracker.check_and_mark(key1) is True
        assert tracker.check_and_mark(key2) is True


class TestBuildConfirmationPrompt:
    """Tests for build_confirmation_prompt helper."""

    def test_calendar_create(self) -> None:
        """Calendar create prompt should be built."""
        slots = {"title": "Toplantı", "time": "14:00"}
        result = build_confirmation_prompt(slots, "create", "calendar")
        assert "Toplantı" in result
        assert "14:00" in result

    def test_gmail_send(self) -> None:
        """Gmail send prompt should be built."""
        slots = {"title": "Merhaba", "to": "test@example.com"}
        result = build_confirmation_prompt(slots, "send", "gmail")
        assert "Merhaba" in result
        assert "test@example.com" in result

    def test_default_title(self) -> None:
        """Missing title should use default."""
        slots = {"time": "14:00"}
        result = build_confirmation_prompt(slots, "create", "calendar")
        assert "Etkinlik" in result  # Default title
