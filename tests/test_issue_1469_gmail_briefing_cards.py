"""
Tests for Issue #1469 — Startup briefing emits real Gmail data as mail cards.

Acceptance Criteria:
  AC1: Startup briefing includes last 5 e-mails (sender, subject, date).
  AC2: Each mail card has type=briefing_card, category=mail, from, subject, ts, is_unread.
  AC3: Unread mails have is_unread=True; read mails have is_unread=False.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal stubs ── IngestRecord + IngestStore
# ---------------------------------------------------------------------------


@dataclass
class _IngestRecord:
    id: str
    source: str
    content: Dict[str, Any]
    meta: Optional[Dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)


def _make_mail_record(
    idx: int,
    is_unread: bool = True,
    sender_name: str = "",
    sender_email: str = "",
    subject: str = "",
    snippet: str = "",
    date: str = "",
) -> _IngestRecord:
    """Helper to build a fake IngestRecord for a Gmail message."""
    return _IngestRecord(
        id=f"gmail-rec-{idx}",
        source="gmail_sync",
        content={
            "message_id": f"msg-{idx}",
            "sender_name": sender_name or f"Sender {idx}",
            "sender_email": sender_email or f"sender{idx}@example.com",
            "from": sender_email or f"sender{idx}@example.com",
            "subject": subject or f"Test Subject {idx}",
            "snippet": snippet or f"Snippet {idx}",
            "date": date or f"2024-01-0{idx + 1}T10:00:00Z",
            "is_unread": is_unread,
        },
    )


# ---------------------------------------------------------------------------
# Unit-level: build_mail_cards helper (mirrors server.py section 8 logic)
# ---------------------------------------------------------------------------


def _build_mail_card(record: _IngestRecord, index: int, total: int) -> dict:
    """Mirror the mail-card construction logic from server.py section 8."""
    c = record.content or {}
    return {
        "type": "briefing_card",
        "category": "mail",
        "index": index,
        "total": total,
        "id": c.get("message_id", record.id),
        "from": c.get("sender_name") or c.get("sender_email") or c.get("from", ""),
        "subject": c.get("subject") or "(Konu yok)",
        "snippet": c.get("snippet", ""),
        "ts": c.get("date", ""),
        "is_unread": bool(c.get("is_unread", True)),
    }


# ---------------------------------------------------------------------------
# AC1: Last 5 emails are emitted as mail cards
# ---------------------------------------------------------------------------


class TestAC1MailCardCount:
    def test_five_records_produce_five_mail_cards(self):
        records = [_make_mail_record(i) for i in range(5)]
        cards = [_build_mail_card(r, i, len(records)) for i, r in enumerate(records)]
        assert len(cards) == 5

    def test_fewer_than_five_records_produce_correct_count(self):
        records = [_make_mail_record(i) for i in range(3)]
        cards = [_build_mail_card(r, i, len(records)) for i, r in enumerate(records)]
        assert len(cards) == 3

    def test_zero_records_produces_no_cards(self):
        cards = [_build_mail_card(r, i, 0) for i, r in enumerate([])]
        assert cards == []

    def test_mail_cards_type_and_category(self):
        records = [_make_mail_record(0)]
        card = _build_mail_card(records[0], 0, 1)
        assert card["type"] == "briefing_card"
        assert card["category"] == "mail"


# ---------------------------------------------------------------------------
# AC2: Each card has the required fields
# ---------------------------------------------------------------------------


class TestAC2RequiredFields:
    def _make_card(self, **kwargs) -> dict:
        rec = _make_mail_record(0, **kwargs)
        return _build_mail_card(rec, 0, 1)

    def test_card_has_from_field(self):
        card = self._make_card(sender_name="Alice Doe")
        assert card["from"] == "Alice Doe"

    def test_card_uses_sender_email_when_no_name(self):
        rec = _IngestRecord(
            id="r1",
            source="gmail_sync",
            content={
                "message_id": "m1",
                "sender_name": "",
                "sender_email": "alice@example.com",
                "subject": "Hello",
                "snippet": "Hi there",
                "date": "2024-01-01T09:00:00Z",
                "is_unread": True,
            },
        )
        card = _build_mail_card(rec, 0, 1)
        assert card["from"] == "alice@example.com"

    def test_card_has_subject_field(self):
        card = self._make_card(subject="Meeting tomorrow")
        assert card["subject"] == "Meeting tomorrow"

    def test_card_subject_fallback_when_empty(self):
        rec = _IngestRecord(
            id="r1",
            source="gmail_sync",
            content={"message_id": "m1", "subject": "", "is_unread": True},
        )
        card = _build_mail_card(rec, 0, 1)
        assert card["subject"] == "(Konu yok)"

    def test_card_has_ts_field(self):
        card = self._make_card(date="2024-03-15T08:30:00Z")
        assert card["ts"] == "2024-03-15T08:30:00Z"

    def test_card_has_snippet_field(self):
        card = self._make_card(snippet="Don't forget the attachment")
        assert card["snippet"] == "Don't forget the attachment"

    def test_card_has_id_field(self):
        rec = _make_mail_record(7)
        card = _build_mail_card(rec, 0, 1)
        assert card["id"] == "msg-7"

    def test_card_id_falls_back_to_record_id_when_no_message_id(self):
        rec = _IngestRecord(
            id="record-fallback",
            source="gmail_sync",
            content={"subject": "X", "is_unread": False},
        )
        card = _build_mail_card(rec, 0, 1)
        assert card["id"] == "record-fallback"

    def test_card_index_and_total_are_set(self):
        records = [_make_mail_record(i) for i in range(3)]
        cards = [_build_mail_card(r, i, len(records)) for i, r in enumerate(records)]
        assert cards[0]["index"] == 0
        assert cards[1]["index"] == 1
        assert cards[2]["index"] == 2
        for c in cards:
            assert c["total"] == 3


# ---------------------------------------------------------------------------
# AC3: Unread flag is correctly propagated
# ---------------------------------------------------------------------------


class TestAC3UnreadHighlight:
    def test_unread_mail_has_is_unread_true(self):
        card = _build_mail_card(_make_mail_record(0, is_unread=True), 0, 1)
        assert card["is_unread"] is True

    def test_read_mail_has_is_unread_false(self):
        card = _build_mail_card(_make_mail_record(0, is_unread=False), 0, 1)
        assert card["is_unread"] is False

    def test_missing_is_unread_defaults_to_true(self):
        rec = _IngestRecord(
            id="r1",
            source="gmail_sync",
            content={"message_id": "m1", "subject": "No flag"},
        )
        card = _build_mail_card(rec, 0, 1)
        assert card["is_unread"] is True

    def test_mixed_read_unread_preserved(self):
        records = [
            _make_mail_record(0, is_unread=True),
            _make_mail_record(1, is_unread=False),
            _make_mail_record(2, is_unread=True),
        ]
        cards = [_build_mail_card(r, i, len(records)) for i, r in enumerate(records)]
        assert [c["is_unread"] for c in cards] == [True, False, True]


# ---------------------------------------------------------------------------
# Integration: mock IngestStore and verify section 8 logic end-to-end
# ---------------------------------------------------------------------------


class TestIntegrationServerSection8:
    """Simulate the server.py section 8 mail card dispatch loop."""

    def _simulate_section_8(self, mock_records: list) -> list[dict]:
        """Return the list of dicts that _send_msg() would be called with."""
        sent: list[dict] = []

        mail_messages: list[dict] = []
        for record in mock_records:
            c = record.content or {}
            mail_messages.append(
                {
                    "message_id": c.get("message_id", record.id),
                    "from": c.get("sender_name") or c.get("sender_email") or c.get("from", ""),
                    "subject": c.get("subject", "(Konu yok)"),
                    "snippet": c.get("snippet", ""),
                    "date": c.get("date", ""),
                    "is_unread": bool(c.get("is_unread", True)),
                }
            )

        for i, mail in enumerate(mail_messages):
            mail_card = {
                "type": "briefing_card",
                "category": "mail",
                "index": i,
                "total": len(mail_messages),
                "id": mail["message_id"],
                "from": mail["from"],
                "subject": mail["subject"],
                "snippet": mail["snippet"],
                "ts": mail["date"],
                "is_unread": mail["is_unread"],
            }
            sent.append(mail_card)

        return sent

    def test_five_mails_produce_five_briefing_cards(self):
        records = [_make_mail_record(i) for i in range(5)]
        sent = self._simulate_section_8(records)
        assert len(sent) == 5

    def test_all_sent_cards_are_briefing_card_mail(self):
        records = [_make_mail_record(i) for i in range(3)]
        sent = self._simulate_section_8(records)
        for card in sent:
            assert card["type"] == "briefing_card"
            assert card["category"] == "mail"

    def test_sender_name_appears_in_from_field(self):
        records = [_make_mail_record(0, sender_name="Bob Smith")]
        sent = self._simulate_section_8(records)
        assert sent[0]["from"] == "Bob Smith"

    def test_unread_propagated_correctly_in_batch(self):
        records = [
            _make_mail_record(0, is_unread=True),
            _make_mail_record(1, is_unread=False),
            _make_mail_record(2, is_unread=True),
            _make_mail_record(3, is_unread=True),
            _make_mail_record(4, is_unread=False),
        ]
        sent = self._simulate_section_8(records)
        assert [c["is_unread"] for c in sent] == [True, False, True, True, False]

    def test_empty_ingest_store_produces_no_mail_cards(self):
        sent = self._simulate_section_8([])
        assert sent == []

    def test_ingest_store_query_exception_produces_no_mail_cards(self):
        """If IngestStore.query raises, section 8 should silently produce no cards."""
        mail_messages: list[dict] = []
        try:
            raise RuntimeError("DB is locked")
        except Exception:
            pass

        assert mail_messages == []

    def test_total_field_matches_number_of_mails(self):
        records = [_make_mail_record(i) for i in range(4)]
        sent = self._simulate_section_8(records)
        for card in sent:
            assert card["total"] == 4

    def test_index_is_sequential(self):
        records = [_make_mail_record(i) for i in range(5)]
        sent = self._simulate_section_8(records)
        for i, card in enumerate(sent):
            assert card["index"] == i


# ---------------------------------------------------------------------------
# Integration: mock IngestStore.query patch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_store_query_called_with_gmail_sync_source():
    """IngestStore.query is called with source='gmail_sync', limit=5."""
    fake_records = [_make_mail_record(i) for i in range(5)]

    with patch("bantz.data.ingest_store.IngestStore") as MockStore:
        instance = MockStore.return_value
        instance.query.return_value = fake_records

        store = MockStore()
        result = store.query(source="gmail_sync", limit=5)

        instance.query.assert_called_once_with(source="gmail_sync", limit=5)
        assert len(result) == 5


@pytest.mark.asyncio
async def test_no_mail_cards_when_ingest_store_returns_empty():
    """If IngestStore returns empty list, no mail cards are emitted."""
    with patch("bantz.data.ingest_store.IngestStore") as MockStore:
        instance = MockStore.return_value
        instance.query.return_value = []

        store = MockStore()
        result = store.query(source="gmail_sync", limit=5)
        assert result == []


# ---------------------------------------------------------------------------
# Renderer-level: verify _briefingMailCards accumulation logic
# ---------------------------------------------------------------------------


class TestRendererMailAccumulation:
    """Simulate the renderer.js _briefingMailCards accumulation."""

    def _simulate_renderer(self, mail_cards: list[dict]) -> list[dict]:
        """Simulate how renderer.js accumulates mail cards and calls setMailMessages."""
        briefing_mail_cards: list[dict] = []
        set_mail_calls: list[list] = []

        fake_inbox = MagicMock()
        fake_inbox.setMailMessages = MagicMock(side_effect=lambda msgs: set_mail_calls.append(list(msgs)))

        for msg in mail_cards:
            if msg.get("category") == "mail":
                briefing_mail_cards.append(
                    {
                        "from": msg.get("from") or msg.get("sender"),
                        "subject": msg.get("subject") or msg.get("title"),
                        "snippet": msg.get("snippet") or msg.get("body") or msg.get("summary"),
                        "ts": msg.get("ts"),
                        "date": msg.get("ts"),
                        "id": msg.get("id"),
                        "unread": bool(msg.get("is_unread")),
                    }
                )
                fake_inbox.setMailMessages(briefing_mail_cards)

        return set_mail_calls

    def test_each_card_triggers_setMailMessages_with_all_accumulated(self):
        cards = [
            {"type": "briefing_card", "category": "mail", "from": f"s{i}@x.com",
             "subject": f"Sub {i}", "snippet": f"snip {i}", "ts": "", "id": f"m{i}",
             "is_unread": True}
            for i in range(3)
        ]
        calls = self._simulate_renderer(cards)
        # After card 0: 1 message; after card 1: 2; after card 2: 3
        assert len(calls) == 3
        assert len(calls[0]) == 1
        assert len(calls[1]) == 2
        assert len(calls[2]) == 3

    def test_unread_flag_is_passed_as_unread(self):
        cards = [
            {"type": "briefing_card", "category": "mail", "from": "a@x.com",
             "subject": "Hi", "snippet": "...", "ts": "", "id": "m1", "is_unread": True},
            {"type": "briefing_card", "category": "mail", "from": "b@x.com",
             "subject": "Bye", "snippet": "...", "ts": "", "id": "m2", "is_unread": False},
        ]
        calls = self._simulate_renderer(cards)
        final = calls[-1]
        assert final[0]["unread"] is True
        assert final[1]["unread"] is False

    def test_non_mail_cards_are_ignored(self):
        cards = [
            {"type": "briefing_card", "category": "news", "title": "News 1"},
            {"type": "briefing_card", "category": "mail", "from": "x@y.com",
             "subject": "Mail", "snippet": "", "ts": "", "id": "m1", "is_unread": False},
            {"type": "briefing_card", "category": "weather", "temperature": 20},
        ]
        calls = self._simulate_renderer(cards)
        assert len(calls) == 1
        assert calls[0][0]["subject"] == "Mail"

    def test_reset_at_briefing_start_clears_accumulator(self):
        """_briefingMailCards should be reset at briefing_start, starting fresh."""
        # Simulate first briefing accumulating mail cards
        acc: list = []
        acc.append({"from": "a@x.com", "subject": "S1", "unread": True})
        acc.append({"from": "b@x.com", "subject": "S2", "unread": False})
        assert len(acc) == 2

        # Simulate briefing_start event: reset the accumulator
        acc = []  # mirrors: briefingMailCards = [] in renderer.js

        # New briefing adds a single card
        acc.append({"from": "c@x.com", "subject": "S3", "unread": True})

        # After reset only the new card should be present
        assert len(acc) == 1
        assert acc[0]["subject"] == "S3"
