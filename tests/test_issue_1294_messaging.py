"""Tests for Issue #1294 — Kontrollü Mesajlaşma Pipeline.

Covers: models, channel interface, GmailChannel adapter,
        MessagingPipeline, ThreadTracker, BatchDraftManager,
        and tool registration.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from bantz.messaging.batch import BatchDraftManager, _default_draft_generator
from bantz.messaging.channel import ChannelConnector
from bantz.messaging.gmail_channel import GmailChannel
from bantz.messaging.models import (ChannelType, Conversation, Draft,
                                    DraftBatch, DraftDecision, Message,
                                    SendResult)
from bantz.messaging.pipeline import MessagingPipeline
from bantz.messaging.thread_tracker import ThreadTracker, _default_summariser


def _make_message(
    *,
    id: str = "m1",
    sender: str = "ali@test.com",
    subject: str = "Test",
    body: str = "Hello",
    channel: ChannelType = ChannelType.EMAIL,
    thread_id: str | None = None,
    is_read: bool = False,
    timestamp: datetime | None = None,
) -> Message:
    return Message(
        id=id,
        channel=channel,
        sender=sender,
        recipients=["user@test.com"],
        subject=subject,
        body=body,
        timestamp=timestamp or datetime.now(),
        thread_id=thread_id,
        is_read=is_read,
    )


class TestMessage:
    def test_preview_short(self):
        msg = _make_message(body="short text")
        assert msg.preview == "short text"

    def test_preview_truncated(self):
        long_body = "x" * 200
        msg = _make_message(body=long_body)
        assert len(msg.preview) <= 121
        assert msg.preview.endswith("…")

    def test_channel_type_values(self):
        assert ChannelType.EMAIL.value == "email"
        assert ChannelType.TELEGRAM.value == "telegram"
        assert ChannelType.SLACK.value == "slack"
        assert ChannelType.WHATSAPP.value == "whatsapp"


class TestDraft:
    def test_as_display(self):
        d = Draft(to="ali@x.com", subject="Hello", body="Hi there")
        display = d.as_display()
        assert display["to"] == "ali@x.com"
        assert display["subject"] == "Hello"
        assert display["body"] == "Hi there"
        assert display["channel"] == "email"
        assert "id" in display

    def test_default_channel(self):
        d = Draft()
        assert d.channel == ChannelType.EMAIL


class TestDraftBatch:
    def test_empty_batch(self):
        b = DraftBatch()
        assert b.total == 0
        assert b.approved_count == 0
        assert b.pending_count == 0

    def test_approve_and_skip(self):
        d1 = Draft(to="a@x.com", subject="S1", body="B1")
        d2 = Draft(to="b@x.com", subject="S2", body="B2")
        d3 = Draft(to="c@x.com", subject="S3", body="B3")
        batch = DraftBatch(drafts=[d1, d2, d3])

        assert batch.total == 3
        assert batch.pending_count == 3

        batch.approve(d1.id)
        batch.skip(d2.id)

        assert batch.approved_count == 1
        assert batch.pending_count == 1

    def test_get_approved_drafts(self):
        d1 = Draft(to="a@x.com", subject="S1", body="B1")
        d2 = Draft(to="b@x.com", subject="S2", body="B2")
        batch = DraftBatch(drafts=[d1, d2])
        batch.approve(d1.id)
        batch.skip(d2.id)

        approved = batch.get_approved_drafts()
        assert len(approved) == 1
        assert approved[0].to == "a@x.com"


class TestSendResult:
    def test_ok_result(self):
        r = SendResult(ok=True, channel=ChannelType.EMAIL, message_id="123")
        assert r.ok
        assert r.message_id == "123"
        assert r.error is None

    def test_error_result(self):
        r = SendResult(ok=False, channel=ChannelType.EMAIL, error="fail")
        assert not r.ok
        assert r.error == "fail"


class TestConversation:
    def test_empty_conversation(self):
        c = Conversation(contact="ali@x.com")
        assert c.message_count == 0
        assert c.last_message is None

    def test_conversation_with_messages(self):
        m1 = _make_message(id="1")
        m2 = _make_message(id="2")
        c = Conversation(contact="ali@x.com", messages=[m1, m2])
        assert c.message_count == 2
        assert c.last_message is m2


# ── ChannelConnector ─────────────────────────────────────────────────


class DummyChannel(ChannelConnector):
    """Minimal channel implementation for testing."""

    def __init__(self, msgs: list[Message] | None = None):
        self._msgs = msgs or []

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.EMAIL

    async def read_inbox(self, *, filter_query=None, max_results=10, unread_only=False):
        result = self._msgs[:max_results]
        if unread_only:
            result = [m for m in result if not m.is_read]
        if filter_query:
            result = [m for m in result if filter_query.lower() in m.body.lower()
                      or filter_query.lower() in m.subject.lower()
                      or filter_query.lower() in m.sender.lower()]
        return result

    async def send(self, draft):
        return SendResult(ok=True, channel=self.channel_type, message_id="sent-1")

    async def get_thread(self, thread_id):
        return [m for m in self._msgs if m.thread_id == thread_id]


class TestChannelConnector:
    def test_dummy_implements_interface(self):
        ch = DummyChannel()
        assert ch.channel_type == ChannelType.EMAIL

    @pytest.mark.asyncio
    async def test_read_inbox(self):
        msgs = [_make_message(id=str(i)) for i in range(5)]
        ch = DummyChannel(msgs)
        result = await ch.read_inbox(max_results=3)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_send(self):
        ch = DummyChannel()
        draft = Draft(to="x@x.com", subject="S", body="B")
        result = await ch.send(draft)
        assert result.ok

    @pytest.mark.asyncio
    async def test_search_by_contact_default(self):
        msgs = [_make_message(id="1", sender="ali@x.com")]
        ch = DummyChannel(msgs)
        result = await ch.search_by_contact("ali@x.com")
        assert len(result) == 1


# ── GmailChannel ────────────────────────────────────────────────────


class TestGmailChannel:
    def test_channel_type(self):
        ch = GmailChannel()
        assert ch.channel_type == ChannelType.EMAIL

    @pytest.mark.asyncio
    async def test_read_inbox_success(self):
        mock_result = {
            "ok": True,
            "messages": [
                {
                    "id": "msg1",
                    "from": "ali@x.com",
                    "to": "user@x.com",
                    "subject": "Test",
                    "body": "Hello",
                    "date": "2025-01-15T10:00:00",
                    "unread": True,
                },
            ],
        }
        with patch("bantz.google.gmail.gmail_list_messages", return_value=mock_result):
            ch = GmailChannel()
            msgs = await ch.read_inbox(max_results=5)
            assert len(msgs) == 1
            assert msgs[0].sender == "ali@x.com"
            assert msgs[0].subject == "Test"
            assert not msgs[0].is_read

    @pytest.mark.asyncio
    async def test_read_inbox_error(self):
        with patch("bantz.google.gmail.gmail_list_messages", side_effect=RuntimeError("fail")):
            ch = GmailChannel()
            msgs = await ch.read_inbox()
            assert msgs == []

    @pytest.mark.asyncio
    async def test_send_success(self):
        mock_result = {"ok": True, "id": "sent-123"}
        with patch("bantz.google.gmail.gmail_send", return_value=mock_result):
            ch = GmailChannel()
            draft = Draft(to="x@x.com", subject="S", body="B")
            result = await ch.send(draft)
            assert result.ok
            assert result.message_id == "sent-123"

    @pytest.mark.asyncio
    async def test_send_failure(self):
        mock_result = {"ok": False, "error": "Auth failed"}
        with patch("bantz.google.gmail.gmail_send", return_value=mock_result):
            ch = GmailChannel()
            draft = Draft(to="x@x.com", subject="S", body="B")
            result = await ch.send(draft)
            assert not result.ok
            assert "Auth failed" in result.error

    @pytest.mark.asyncio
    async def test_send_exception(self):
        with patch("bantz.google.gmail.gmail_send", side_effect=Exception("boom")):
            ch = GmailChannel()
            draft = Draft(to="x@x.com", subject="S", body="B")
            result = await ch.send(draft)
            assert not result.ok
            assert "boom" in result.error

    def test_raw_to_message_iso_date(self):
        raw = {
            "id": "m1",
            "from": "ali@x.com",
            "to": "user@x.com",
            "subject": "Hello",
            "body": "World",
            "date": "2025-06-15T12:00:00",
            "unread": False,
        }
        msg = GmailChannel._raw_to_message(raw)
        assert msg.id == "m1"
        assert msg.sender == "ali@x.com"
        assert msg.subject == "Hello"
        assert msg.is_read  # unread=False → is_read=True

    def test_raw_to_message_bad_date(self):
        raw = {
            "id": "m2",
            "from": "ali@x.com",
            "to": "",
            "subject": "No date",
            "snippet": "Just a snippet",
            "date": "invalid",
        }
        msg = GmailChannel._raw_to_message(raw)
        assert msg.body == "Just a snippet"
        assert isinstance(msg.timestamp, datetime)

    def test_raw_to_message_list_recipients(self):
        raw = {
            "id": "m3",
            "from": "ali@x.com",
            "to": ["a@x.com", "b@x.com"],
            "subject": "Multi",
            "body": "",
            "date": "2025-01-01T00:00:00",
        }
        msg = GmailChannel._raw_to_message(raw)
        assert msg.recipients == ["a@x.com", "b@x.com"]


# ── ThreadTracker ────────────────────────────────────────────────────


class TestThreadTracker:
    @pytest.mark.asyncio
    async def test_default_summariser_empty(self):
        summary = await _default_summariser([])
        assert "bulunamadı" in summary.lower()

    @pytest.mark.asyncio
    async def test_default_summariser_with_messages(self):
        m1 = _make_message(id="1", timestamp=datetime(2025, 1, 1))
        m2 = _make_message(id="2", timestamp=datetime(2025, 1, 5))
        summary = await _default_summariser([m1, m2])
        assert "2 mesaj" in summary
        assert "01.01.2025" in summary
        assert "05.01.2025" in summary

    @pytest.mark.asyncio
    async def test_get_conversation_single_channel(self):
        msgs = [
            _make_message(id="1", sender="ali@x.com", thread_id="t1"),
            _make_message(id="2", sender="ali@x.com", thread_id="t1"),
        ]
        ch = DummyChannel(msgs)
        tracker = ThreadTracker(channels=[ch])
        conv = await tracker.get_conversation("ali@x.com")
        assert conv.contact == "ali@x.com"
        assert conv.message_count == 2
        assert "t1" in conv.thread_ids

    @pytest.mark.asyncio
    async def test_get_conversation_deduplicates(self):
        msg = _make_message(id="same-id", sender="ali@x.com")
        ch1 = DummyChannel([msg])
        ch2 = DummyChannel([msg])
        tracker = ThreadTracker(channels=[ch1, ch2])
        conv = await tracker.get_conversation("ali@x.com")
        assert conv.message_count == 1  # deduped

    @pytest.mark.asyncio
    async def test_get_conversation_channel_filter(self):
        msgs = [_make_message(id="1", sender="ali@x.com")]
        ch = DummyChannel(msgs)
        tracker = ThreadTracker(channels=[ch])
        conv = await tracker.get_conversation("ali@x.com", channel_filter="telegram")
        assert conv.message_count == 0  # email channel filtered out

    @pytest.mark.asyncio
    async def test_get_thread(self):
        msgs = [
            _make_message(id="1", thread_id="t1"),
            _make_message(id="2", thread_id="t2"),
        ]
        ch = DummyChannel(msgs)
        tracker = ThreadTracker(channels=[ch])
        result = await tracker.get_thread("t1")
        assert len(result) == 1
        assert result[0].id == "1"

    @pytest.mark.asyncio
    async def test_summarise_thread_not_found(self):
        ch = DummyChannel([])
        tracker = ThreadTracker(channels=[ch])
        summary = await tracker.summarise_thread("nonexistent")
        assert "bulunamadı" in summary.lower()

    @pytest.mark.asyncio
    async def test_custom_summariser(self):
        async def custom_sum(msgs):
            return f"Özel özet: {len(msgs)} msg"

        msgs = [_make_message(id="1", sender="ali@x.com")]
        ch = DummyChannel(msgs)
        tracker = ThreadTracker(channels=[ch], summariser=custom_sum)
        conv = await tracker.get_conversation("ali@x.com")
        assert "Özel özet" in conv.summary

    @pytest.mark.asyncio
    async def test_channel_error_handled(self):
        """Channel that raises should not crash the tracker."""

        class FailChannel(ChannelConnector):
            @property
            def channel_type(self):
                return ChannelType.TELEGRAM

            async def read_inbox(self, **kw):
                raise RuntimeError("fail")

            async def send(self, draft):
                raise RuntimeError("fail")

            async def get_thread(self, thread_id):
                raise RuntimeError("fail")

            async def search_by_contact(self, contact, **kw):
                raise RuntimeError("fail")

        tracker = ThreadTracker(channels=[FailChannel()])
        conv = await tracker.get_conversation("ali@x.com")
        assert conv.message_count == 0


# ── BatchDraftManager ────────────────────────────────────────────────


class TestBatchDraftManager:
    @pytest.mark.asyncio
    async def test_default_draft_generator(self):
        msg = _make_message(subject="Test Mail")
        text = await _default_draft_generator(msg, "Short reply")
        assert "Test Mail" in text

    @pytest.mark.asyncio
    async def test_generate_drafts(self):
        msgs = [
            _make_message(id="1", sender="a@x.com", subject="Sub1"),
            _make_message(id="2", sender="b@x.com", subject="Sub2"),
        ]
        ch = DummyChannel()
        mgr = BatchDraftManager(ch)
        batch = await mgr.generate_drafts(msgs)
        assert batch.total == 2
        assert all(d.to in ["a@x.com", "b@x.com"] for d in batch.drafts)

    @pytest.mark.asyncio
    async def test_generate_drafts_with_custom_generator(self):
        async def custom_gen(msg, instr):
            return f"Custom reply to {msg.sender}"

        msgs = [_make_message(id="1", sender="ali@x.com")]
        ch = DummyChannel()
        mgr = BatchDraftManager(ch, draft_generator=custom_gen)
        batch = await mgr.generate_drafts(msgs)
        assert "Custom reply to ali@x.com" in batch.drafts[0].body

    @pytest.mark.asyncio
    async def test_generate_drafts_generator_fails_uses_fallback(self):
        async def bad_gen(msg, instr):
            raise RuntimeError("LLM down")

        msgs = [_make_message(id="1", sender="ali@x.com", subject="Help")]
        ch = DummyChannel()
        mgr = BatchDraftManager(ch, draft_generator=bad_gen)
        batch = await mgr.generate_drafts(msgs)
        assert batch.total == 1
        assert "Help" in batch.drafts[0].body  # fallback

    def test_approve_and_skip(self):
        d1 = Draft(to="a@x.com", subject="S1", body="B1")
        batch = DraftBatch(drafts=[d1])
        ch = DummyChannel()
        mgr = BatchDraftManager(ch)

        assert mgr.approve(batch, d1.id)
        assert batch.approved_count == 1

    def test_skip(self):
        d1 = Draft(to="a@x.com", subject="S1", body="B1")
        batch = DraftBatch(drafts=[d1])
        ch = DummyChannel()
        mgr = BatchDraftManager(ch)

        assert mgr.skip(batch, d1.id)
        assert batch.decisions[d1.id] == DraftDecision.SKIP

    def test_approve_nonexistent(self):
        batch = DraftBatch()
        ch = DummyChannel()
        mgr = BatchDraftManager(ch)
        assert not mgr.approve(batch, "nonexistent")

    def test_edit_draft(self):
        d1 = Draft(to="a@x.com", subject="S1", body="old")
        batch = DraftBatch(drafts=[d1])
        ch = DummyChannel()
        mgr = BatchDraftManager(ch)

        assert mgr.edit_draft(batch, d1.id, body="new body")
        assert d1.body == "new body"

    def test_approve_all(self):
        d1 = Draft(to="a@x.com", subject="S1", body="B1")
        d2 = Draft(to="b@x.com", subject="S2", body="B2")
        batch = DraftBatch(drafts=[d1, d2])
        ch = DummyChannel()
        mgr = BatchDraftManager(ch)

        count = mgr.approve_all(batch)
        assert count == 2
        assert batch.approved_count == 2

    @pytest.mark.asyncio
    async def test_send_approved(self):
        d1 = Draft(to="a@x.com", subject="S1", body="B1")
        d2 = Draft(to="b@x.com", subject="S2", body="B2")
        batch = DraftBatch(drafts=[d1, d2])
        batch.approve(d1.id)
        batch.skip(d2.id)

        ch = DummyChannel()
        mgr = BatchDraftManager(ch)
        results = await mgr.send_approved(batch)
        assert len(results) == 1
        assert results[0].ok

    @pytest.mark.asyncio
    async def test_send_approved_error_handling(self):
        """Channel send failure should not crash batch."""

        class FailSendChannel(DummyChannel):
            async def send(self, draft):
                raise RuntimeError("network error")

        d1 = Draft(to="a@x.com", subject="S1", body="B1")
        batch = DraftBatch(drafts=[d1])
        batch.approve(d1.id)

        ch = FailSendChannel()
        mgr = BatchDraftManager(ch)
        results = await mgr.send_approved(batch)
        assert len(results) == 1
        assert not results[0].ok
        assert "network error" in results[0].error

    def test_format_batch_display(self):
        d1 = Draft(to="ali@x.com", subject="Sub1", body="Body1")
        d2 = Draft(to="veli@x.com", subject="Sub2", body="Body2")
        batch = DraftBatch(drafts=[d1, d2])
        batch.approve(d1.id)

        display = BatchDraftManager.format_batch_display(batch)
        assert "ali@x.com" in display
        assert "veli@x.com" in display
        assert "2 taslak" in display

    def test_format_batch_display_empty(self):
        batch = DraftBatch()
        display = BatchDraftManager.format_batch_display(batch)
        assert "bulunamadı" in display.lower()


# ── MessagingPipeline ────────────────────────────────────────────────


class TestMessagingPipeline:
    def test_register_channel(self):
        pipeline = MessagingPipeline()
        ch = DummyChannel()
        pipeline.register_channel(ch)
        assert "email" in pipeline.available_channels

    def test_get_channel(self):
        pipeline = MessagingPipeline()
        ch = DummyChannel()
        pipeline.register_channel(ch)
        assert pipeline.get_channel("email") is ch
        assert pipeline.get_channel("telegram") is None

    @pytest.mark.asyncio
    async def test_read_inbox_single_channel(self):
        msgs = [_make_message(id=str(i)) for i in range(3)]
        ch = DummyChannel(msgs)
        pipeline = MessagingPipeline()
        pipeline.register_channel(ch)

        result = await pipeline.read_inbox("email", max_results=2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_read_inbox_all_channels(self):
        msgs = [_make_message(id=str(i)) for i in range(3)]
        ch = DummyChannel(msgs)
        pipeline = MessagingPipeline()
        pipeline.register_channel(ch)

        result = await pipeline.read_inbox("all")
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_read_inbox_unknown_channel(self):
        pipeline = MessagingPipeline()
        result = await pipeline.read_inbox("telegram")
        assert result == []

    @pytest.mark.asyncio
    async def test_draft_reply(self):
        msgs = [_make_message(id="1", sender="ali@x.com", subject="Hi")]
        ch = DummyChannel(msgs)
        pipeline = MessagingPipeline()
        pipeline.register_channel(ch)

        draft = await pipeline.draft_reply(msgs[0])
        assert draft.to == "ali@x.com"
        assert "Re:" in draft.subject

    @pytest.mark.asyncio
    async def test_draft_replies_batch(self):
        msgs = [
            _make_message(id="1", sender="a@x.com", subject="A"),
            _make_message(id="2", sender="b@x.com", subject="B"),
        ]
        ch = DummyChannel()
        pipeline = MessagingPipeline()
        pipeline.register_channel(ch)

        batch = await pipeline.draft_replies(msgs)
        assert batch.total == 2

    @pytest.mark.asyncio
    async def test_draft_replies_empty(self):
        pipeline = MessagingPipeline()
        batch = await pipeline.draft_replies([])
        assert batch.total == 0

    @pytest.mark.asyncio
    async def test_confirm_and_send(self):
        ch = DummyChannel()
        pipeline = MessagingPipeline()
        pipeline.register_channel(ch)

        d1 = Draft(to="a@x.com", subject="S1", body="B1")
        batch = DraftBatch(drafts=[d1])
        batch.approve(d1.id)

        results = await pipeline.confirm_and_send(batch)
        assert len(results) == 1
        assert results[0].ok

    @pytest.mark.asyncio
    async def test_confirm_and_send_policy_deny(self):
        async def deny_policy(tool_name, params):
            return {"action": "deny", "reason": "Not allowed"}

        ch = DummyChannel()
        pipeline = MessagingPipeline(policy_fn=deny_policy)
        pipeline.register_channel(ch)

        d1 = Draft(to="a@x.com", subject="S1", body="B1")
        batch = DraftBatch(drafts=[d1])
        batch.approve(d1.id)

        results = await pipeline.confirm_and_send(batch)
        assert len(results) == 1
        assert not results[0].ok
        assert "Not allowed" in results[0].error

    @pytest.mark.asyncio
    async def test_confirm_and_send_policy_allow(self):
        async def allow_policy(tool_name, params):
            return {"action": "allow"}

        ch = DummyChannel()
        pipeline = MessagingPipeline(policy_fn=allow_policy)
        pipeline.register_channel(ch)

        d1 = Draft(to="a@x.com", subject="S1", body="B1")
        batch = DraftBatch(drafts=[d1])
        batch.approve(d1.id)

        results = await pipeline.confirm_and_send(batch)
        assert len(results) == 1
        assert results[0].ok

    @pytest.mark.asyncio
    async def test_send_single(self):
        ch = DummyChannel()
        pipeline = MessagingPipeline()
        pipeline.register_channel(ch)

        draft = Draft(to="a@x.com", subject="S", body="B")
        result = await pipeline.send_single(draft)
        assert result.ok

    @pytest.mark.asyncio
    async def test_get_conversation(self):
        msgs = [_make_message(id="1", sender="ali@x.com")]
        ch = DummyChannel(msgs)
        pipeline = MessagingPipeline()
        pipeline.register_channel(ch)

        conv = await pipeline.get_conversation("ali@x.com")
        assert conv.contact == "ali@x.com"
        assert conv.message_count >= 1

    def test_get_status(self):
        pipeline = MessagingPipeline()
        ch = DummyChannel()
        pipeline.register_channel(ch)

        status = pipeline.get_status()
        assert "email" in status["channels"]
        assert status["channel_count"] == 1


# ── Tool Registration ───────────────────────────────────────────────

class TestToolRegistration:
    def test_register_messaging_tools(self):
        """Verify messaging tools can be registered."""
        from bantz.agent.tools import ToolRegistry
        from bantz.tools.register_all import _register_messaging

        registry = ToolRegistry()
        count = _register_messaging(registry)
        assert count >= 5

        # Check all 5 tools registered
        names = registry.names()
        assert "messaging.read_inbox" in names
        assert "messaging.draft_reply" in names
        assert "messaging.send" in names
        assert "messaging.thread" in names
        assert "messaging.status" in names

    def test_messaging_status_tool(self):
        """The status tool should work without any external deps."""
        from bantz.agent.tools import ToolRegistry
        from bantz.tools.register_all import _register_messaging

        registry = ToolRegistry()
        _register_messaging(registry)

        tool = registry.get("messaging.status")
        assert tool is not None
        result = tool.function()
        assert result["ok"] is True
        assert "email" in result["available_channels"]


# ── Integration: Pipeline + GmailChannel ─────────────────────────────

class TestPipelineGmailIntegration:
    @pytest.mark.asyncio
    async def test_full_read_draft_send_flow(self):
        """End-to-end: read → draft → approve → send with mocked Gmail."""
        mock_list = {
            "ok": True,
            "messages": [
                {
                    "id": "msg-1",
                    "from": "ali@test.com",
                    "to": "user@test.com",
                    "subject": "Toplantı ne zaman?",
                    "body": "Yarınki toplantının saatini onaylar mısın?",
                    "date": "2025-06-15T09:00:00",
                    "unread": True,
                },
            ],
        }
        mock_send = {"ok": True, "id": "sent-99"}

        with patch("bantz.google.gmail.gmail_list_messages", return_value=mock_list), \
             patch("bantz.google.gmail.gmail_send", return_value=mock_send):

            pipeline = MessagingPipeline()
            pipeline.register_channel(GmailChannel())

            # READ
            msgs = await pipeline.read_inbox("email", unread_only=True)
            assert len(msgs) == 1
            assert msgs[0].sender == "ali@test.com"

            # DRAFT
            batch = await pipeline.draft_replies(msgs)
            assert batch.total == 1
            assert batch.drafts[0].to == "ali@test.com"

            # APPROVE
            batch.approve(batch.drafts[0].id)
            assert batch.approved_count == 1

            # SEND
            results = await pipeline.confirm_and_send(batch)
            assert len(results) == 1
            assert results[0].ok
            assert results[0].message_id == "sent-99"

    @pytest.mark.asyncio
    async def test_batch_with_multiple_messages(self):
        """Batch draft mode with 3 messages."""
        mock_list = {
            "ok": True,
            "messages": [
                {"id": f"msg-{i}", "from": f"user{i}@test.com",
                 "to": "me@test.com", "subject": f"Sub {i}",
                 "body": f"Body {i}", "date": "2025-06-15T09:00:00", "unread": True}
                for i in range(3)
            ],
        }
        mock_send = {"ok": True, "id": "sent-x"}

        with patch("bantz.google.gmail.gmail_list_messages", return_value=mock_list), \
             patch("bantz.google.gmail.gmail_send", return_value=mock_send):

            pipeline = MessagingPipeline()
            pipeline.register_channel(GmailChannel())

            msgs = await pipeline.read_inbox("email")
            assert len(msgs) == 3

            batch = await pipeline.draft_replies(msgs)
            assert batch.total == 3

            # Approve first two, skip third
            batch.approve(batch.drafts[0].id)
            batch.approve(batch.drafts[1].id)
            batch.skip(batch.drafts[2].id)

            results = await pipeline.confirm_and_send(batch)
            assert len(results) == 2  # only approved
            assert all(r.ok for r in results)
