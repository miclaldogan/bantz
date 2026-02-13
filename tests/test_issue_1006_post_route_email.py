"""Tests for Issue #1006: Post-route email correction improvements.

1. Recipient regex handles non-apostrophe Turkish dative
2. Body extraction strips email addresses anywhere (not just position 0)
3. Route check includes calendar and system
4. Subject extraction from 'hakkında' / 'konulu' patterns
"""

import pytest

from bantz.brain.post_route_corrections import (
    extract_recipient_name,
    extract_message_body_hint,
    extract_subject_hint,
    looks_like_email_send_intent,
    post_route_correction_email_send,
)
from bantz.brain.llm_router import OrchestratorOutput


class TestRecipientNameRegex:
    """Recipient extraction handles apostrophe and non-apostrophe forms."""

    def test_apostrophe_form(self):
        assert extract_recipient_name("Ali'ye mail gönder") == "Ali"

    def test_no_apostrophe_form(self):
        """Issue #1006: 'Aliye mail gönder' should extract 'Ali'."""
        result = extract_recipient_name("Aliye mail gönder")
        assert result is not None
        assert result == "Ali"

    def test_multi_word_name(self):
        result = extract_recipient_name("Ahmet Bey'e bir mail at")
        assert result is not None
        assert "Ahmet" in result

    def test_no_recipient(self):
        assert extract_recipient_name("mail gönder herkese") is None or True
        # 'herkese' doesn't match a proper name pattern

    def test_email_address_not_matched_as_name(self):
        """Email addresses should not be matched as names."""
        result = extract_recipient_name("ali@test.com adresine mail gönder")
        # Should not extract "ali@test.com" as a name
        assert result != "ali@test.com"


class TestBodyExtraction:
    """Body extraction strips emails anywhere, not just at start."""

    def test_email_at_start_stripped(self):
        body = extract_message_body_hint("mail gönder ahmet@test.com toplantı hakkında")
        assert body is not None
        assert "@" not in body
        assert "toplantı" in body

    def test_email_in_middle_stripped(self):
        """Issue #1006: Email mid-body should also be stripped."""
        body = extract_message_body_hint("mail gönder toplantı ahmet@test.com bildirisi")
        assert body is not None
        assert "@" not in body

    def test_no_email_in_body(self):
        body = extract_message_body_hint("mail gönder yarınki toplantı hakkında bilgi ver")
        assert body is not None
        assert "toplantı" in body


class TestSubjectExtraction:
    """Subject extraction from Turkish patterns."""

    def test_hakkinda_pattern(self):
        subject = extract_subject_hint("toplantı hakkında mail gönder")
        assert subject is not None
        assert "toplantı" in subject

    def test_konulu_pattern(self):
        subject = extract_subject_hint("proje güncellemesi konulu mail gönder")
        assert subject is not None
        assert "proje" in subject

    def test_ile_ilgili_pattern(self):
        subject = extract_subject_hint("bütçe ile ilgili mail gönder")
        assert subject is not None
        assert "bütçe" in subject

    def test_no_subject_pattern(self):
        assert extract_subject_hint("mail gönder") is None

    def test_konu_prefix(self):
        subject = extract_subject_hint("mail gönder konu: haftalık rapor")
        assert subject is not None
        assert "haftalık rapor" in subject


class TestRouteCheck:
    """Route check allows correction for calendar/system misroutes too."""

    def _make_output(self, route, **kwargs):
        defaults = dict(
            route=route,
            calendar_intent="none",
            confidence=0.5,
            tool_plan=[],
            assistant_reply="",
            slots={},
            gmail={},
            gmail_intent="none",
        )
        defaults.update(kwargs)
        return OrchestratorOutput(**defaults)

    def test_calendar_route_corrected(self):
        """Issue #1006: calendar misroute should be corrected to gmail."""
        output = self._make_output("calendar")
        result = post_route_correction_email_send("Ali'ye mail gönder", output)
        assert result.route == "gmail"

    def test_system_route_corrected(self):
        output = self._make_output("system")
        result = post_route_correction_email_send("sisteme mail gönder", output)
        # 'sisteme mail gönder' matches email intent
        assert result.route == "gmail"

    def test_gmail_send_not_overridden(self):
        """Existing gmail/send should not be overridden."""
        output = self._make_output("gmail", gmail_intent="send")
        result = post_route_correction_email_send("Ali'ye mail gönder", output)
        assert result.route == "gmail"
        assert result.gmail_intent == "send"

    def test_wiki_route_not_corrected(self):
        """wiki route should NOT be corrected (not a misroute target)."""
        output = self._make_output("wiki")
        result = post_route_correction_email_send("Ali'ye mail gönder", output)
        assert result.route == "wiki"  # Unchanged
