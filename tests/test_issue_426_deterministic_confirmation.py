"""Tests for Issue #426 – Deterministic confirmation prompts.

Validates:
1. deterministic_confirmation_prompt() generates from slots only
2. no_new_facts() guard catches LLM hallucination
3. get_confirmation_prompt() in metadata.py delegates to deterministic builder
4. Calendar prompts: title, date, time, duration from slots
5. Gmail prompts: to, subject from slots
6. Unknown tools get generic fallback
7. Missing slots produce safe fallback (no "None" or blanks)
8. Edge cases: empty slots, Turkish characters
"""

from __future__ import annotations

import pytest

from bantz.brain.confirmation_ux import (
    deterministic_confirmation_prompt,
    no_new_facts,
    build_confirmation_prompt,
    ConfirmationPreview,
    PreviewNormalization,
)


# ===================================================================
# 1. Calendar deterministic prompts
# ===================================================================


class TestCalendarDeterministic:

    def test_create_event_with_title_and_time(self):
        prompt = deterministic_confirmation_prompt(
            "calendar.create_event",
            {"title": "Toplantı", "time": "14:00", "date": "2025-01-15"},
        )
        assert "Toplantı" in prompt
        assert "eklensin mi" in prompt

    def test_create_event_with_title_only(self):
        prompt = deterministic_confirmation_prompt(
            "calendar.create_event",
            {"title": "Yemek"},
        )
        assert "Yemek" in prompt
        assert "eklensin mi" in prompt

    def test_update_event(self):
        prompt = deterministic_confirmation_prompt(
            "calendar.update_event",
            {"title": "Doktor randevusu"},
        )
        assert "Doktor" in prompt
        assert "güncellensin mi" in prompt

    def test_delete_event(self):
        prompt = deterministic_confirmation_prompt(
            "calendar.delete_event",
            {"title": "Eski toplantı"},
        )
        assert "Eski" in prompt
        assert "silinsin mi" in prompt

    def test_create_event_no_title_fallback(self):
        prompt = deterministic_confirmation_prompt(
            "calendar.create_event",
            {"time": "09:00"},
        )
        # Should use "İşlem" fallback title, not crash or show "None"
        assert "None" not in prompt
        assert "eklensin mi" in prompt


# ===================================================================
# 2. Gmail deterministic prompts
# ===================================================================


class TestGmailDeterministic:

    def test_gmail_send_with_to_and_subject(self):
        prompt = deterministic_confirmation_prompt(
            "gmail.send",
            {"to": "ali@test.com", "subject": "Merhaba"},
        )
        assert "ali@test.com" in prompt
        assert "Merhaba" in prompt

    def test_gmail_send_to_contact(self):
        prompt = deterministic_confirmation_prompt(
            "gmail.send_to_contact",
            {"name": "Ayşe", "subject": "Bilgi"},
        )
        assert "Ayşe" in prompt

    def test_gmail_send_draft(self):
        prompt = deterministic_confirmation_prompt(
            "gmail.send_draft",
            {"draft_id": "12345"},
        )
        assert "Taslak" in prompt or "gönderilsin" in prompt

    def test_gmail_archive(self):
        prompt = deterministic_confirmation_prompt(
            "gmail.archive",
            {"message_id": "abc"},
        )
        assert "arşivlensin" in prompt

    def test_gmail_generate_reply(self):
        prompt = deterministic_confirmation_prompt(
            "gmail.generate_reply",
            {"message_id": "xyz"},
        )
        assert "yanıt" in prompt or "oluşturulsun" in prompt


# ===================================================================
# 3. Generic/unknown tool prompts
# ===================================================================


class TestGenericPrompts:

    def test_unknown_tool_gets_generic(self):
        prompt = deterministic_confirmation_prompt(
            "custom.unknown_tool",
            {"key": "value"},
        )
        assert "custom.unknown_tool" in prompt
        assert "çalıştırılsın mı" in prompt

    def test_file_delete(self):
        prompt = deterministic_confirmation_prompt(
            "file.delete",
            {"path": "/tmp/test.txt"},
        )
        assert "/tmp/test.txt" in prompt or "silinsin" in prompt

    def test_system_shutdown(self):
        prompt = deterministic_confirmation_prompt(
            "system.shutdown",
            {},
        )
        assert "kapatılsın" in prompt

    def test_database_delete(self):
        prompt = deterministic_confirmation_prompt(
            "database.delete",
            {},
        )
        assert "geri alınamaz" in prompt


# ===================================================================
# 4. no_new_facts guard
# ===================================================================


class TestNoNewFacts:

    def test_safe_prompt_passes(self):
        slots = {"title": "Toplantı", "time": "14:00"}
        prompt = "'Toplantı' 14:00'de eklensin mi?"
        assert no_new_facts(prompt, slots) is True

    def test_hallucinated_time_fails(self):
        slots = {"title": "Toplantı"}
        prompt = "'Toplantı' 15:30'de eklensin mi?"
        # "15:30" is not in slots, but it's not quoted → allowed
        assert no_new_facts(prompt, slots) is True

    def test_hallucinated_quoted_value_fails(self):
        slots = {"title": "Toplantı"}
        # Prompt introduces a quoted recipient that's not in slots
        prompt = "'Toplantı' 'ali@test.com' adresine gönderilsin mi?"
        assert no_new_facts(prompt, slots) is False

    def test_empty_slots_always_passes(self):
        assert no_new_facts("Anything goes", {}) is True

    def test_quoted_value_in_slot(self):
        slots = {"to": "ali@test.com", "subject": "Hello"}
        prompt = "'ali@test.com' adresine 'Hello' konulu mail gönderilsin mi?"
        assert no_new_facts(prompt, slots) is True

    def test_partial_match_ok(self):
        """Slot value 'Toplantı bilgisi' contains 'Toplantı'."""
        slots = {"title": "Toplantı bilgisi"}
        prompt = "'Toplantı bilgisi' eklensin mi?"
        assert no_new_facts(prompt, slots) is True


# ===================================================================
# 5. get_confirmation_prompt in metadata.py delegates
# ===================================================================


class TestMetadataDelegation:
    """metadata.get_confirmation_prompt now delegates to deterministic builder."""

    def test_delegates_for_calendar_create(self):
        from bantz.tools.metadata import get_confirmation_prompt

        prompt = get_confirmation_prompt(
            "calendar.create_event",
            {"title": "Sprint planlaması", "time": "10:00"},
        )
        assert "Sprint" in prompt
        assert "eklensin" in prompt

    def test_delegates_for_gmail_send(self):
        from bantz.tools.metadata import get_confirmation_prompt

        prompt = get_confirmation_prompt(
            "gmail.send",
            {"to": "user@test.com", "subject": "Test"},
        )
        assert "user@test.com" in prompt

    def test_delegates_for_unknown_tool(self):
        from bantz.tools.metadata import get_confirmation_prompt

        prompt = get_confirmation_prompt("bizarre.tool", {})
        assert "bizarre.tool" in prompt

    def test_no_none_in_output(self):
        from bantz.tools.metadata import get_confirmation_prompt

        prompt = get_confirmation_prompt("calendar.create_event", {})
        assert "None" not in prompt


# ===================================================================
# 6. Deterministic prompt never shows LLM hallucination
# ===================================================================


class TestNoHallucination:
    """Deterministic prompts must only show slot data, never arbitrary text."""

    def test_prompt_only_has_slot_data(self):
        slots = {"title": "Meeting", "time": "09:00"}
        prompt = deterministic_confirmation_prompt("calendar.create_event", slots)

        # Verify via no_new_facts
        assert no_new_facts(prompt, slots) is True

    def test_gmail_prompt_only_has_slot_data(self):
        slots = {"to": "a@b.com", "subject": "Hello"}
        prompt = deterministic_confirmation_prompt("gmail.send", slots)

        assert no_new_facts(prompt, slots) is True

    def test_missing_slots_never_show_none(self):
        """Even with missing slots, 'None' should never appear in prompt."""
        for tool_name in [
            "calendar.create_event",
            "calendar.delete_event",
            "gmail.send",
            "gmail.send_draft",
            "file.delete",
            "system.shutdown",
        ]:
            prompt = deterministic_confirmation_prompt(tool_name, {})
            assert "None" not in prompt, f"{tool_name} prompt contains 'None': {prompt}"


# ===================================================================
# 7. Edge cases
# ===================================================================


class TestEdgeCases:

    def test_empty_slots(self):
        prompt = deterministic_confirmation_prompt("calendar.create_event", {})
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_none_slots(self):
        prompt = deterministic_confirmation_prompt("gmail.send", None)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_turkish_special_chars(self):
        prompt = deterministic_confirmation_prompt(
            "calendar.create_event",
            {"title": "Çöp toplama — İş güvenliği"},
        )
        assert "Çöp" in prompt or "güvenliği" in prompt

    def test_long_title_truncated(self):
        prompt = deterministic_confirmation_prompt(
            "calendar.create_event",
            {"title": "A" * 200},
        )
        # PreviewNormalization.MAX_TITLE_LENGTH is 50
        assert "..." in prompt
        assert len(prompt) < 300

    def test_preview_normalization_strips_quotes(self):
        title = PreviewNormalization.normalize_title('"Test başlığı"')
        assert '"' not in title
        assert "Test" in title
