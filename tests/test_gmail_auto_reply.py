from __future__ import annotations

import base64
from email import message_from_bytes
from typing import Any
from unittest.mock import Mock

import pytest

from bantz.google.gmail_reply import gmail_generate_reply


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("utf-8").rstrip("=")


def _decode_raw_email(raw_b64url: str) -> Any:
    raw = raw_b64url
    pad = (-len(raw)) % 4
    if pad:
        raw += "=" * pad
    data = base64.urlsafe_b64decode(raw.encode("ascii"))
    return message_from_bytes(data)


class MockLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls = []

    def chat(self, messages, *, temperature: float = 0.4, max_tokens: int = 512) -> str:
        self.calls.append({"messages": messages, "temperature": temperature, "max_tokens": max_tokens})
        return self.response

    @property
    def backend_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-model"


def _make_service(*, full_message: dict[str, Any], profile_email: str = "me@example.com") -> Mock:
    service = Mock(name="gmail_service")

    users = service.users.return_value

    # messages.get(...).execute()
    messages = users.messages.return_value
    get_req = Mock(name="msg_get_req")
    get_req.execute.return_value = full_message
    messages.get.return_value = get_req

    # profile
    prof_req = Mock(name="profile_req")
    prof_req.execute.return_value = {"emailAddress": profile_email}
    users.getProfile.return_value = prof_req

    # drafts.create(...).execute()
    drafts = users.drafts.return_value
    create_req = Mock(name="draft_create_req")
    create_req.execute.return_value = {"id": "d1", "message": {"id": "m_d", "threadId": full_message.get("threadId")}}
    drafts.create.return_value = create_req

    return service


def test_generate_reply_autodetects_reply_all_and_creates_threaded_draft():
    full_message = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "snip",
        "payload": {
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "To", "value": "me@example.com, bob@example.com"},
                {"name": "Cc", "value": "carol@example.com"},
                {"name": "Subject", "value": "Toplantı"},
                {"name": "Date", "value": "Mon, 1 Jan 2024 10:00:00 +0000"},
                {"name": "Message-ID", "value": "<msg123@example.com>"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64url("Merhaba"), "size": 7},
        },
    }

    llm = MockLLM(
        '{"short":{"subject":"Re: Toplantı","body":"Kısa."},'
        '"medium":{"subject":"Re: Toplantı","body":"Orta."},'
        '"detailed":{"subject":"Re: Toplantı","body":"Detay."}}'
    )
    service = _make_service(full_message=full_message)

    out = gmail_generate_reply(message_id="m1", user_intent="toplantı tamam", llm=llm, service=service)
    assert out["ok"] is True
    assert out["draft_id"] == "d1"
    assert out["reply_all"] is True
    assert out["to"] == ["alice@example.com"]
    assert out["cc"] == ["bob@example.com", "carol@example.com"]

    drafts = service.users.return_value.drafts.return_value
    drafts.create.assert_called_once()
    _, kwargs = drafts.create.call_args
    assert kwargs["userId"] == "me"
    assert kwargs["body"]["message"]["threadId"] == "t1"

    raw = kwargs["body"]["message"]["raw"]
    msg = _decode_raw_email(raw)
    assert msg.get("To") == "alice@example.com"
    assert "bob@example.com" in (msg.get("Cc") or "")
    assert "carol@example.com" in (msg.get("Cc") or "")
    assert msg.get("In-Reply-To") == "<msg123@example.com>"
    assert "<msg123@example.com>" in (msg.get("References") or "")


def test_generate_reply_override_reply_all_false_creates_single_recipient_draft():
    full_message = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "snip",
        "payload": {
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "To", "value": "me@example.com, bob@example.com"},
                {"name": "Cc", "value": "carol@example.com"},
                {"name": "Subject", "value": "Toplantı"},
                {"name": "Date", "value": "Mon, 1 Jan 2024 10:00:00 +0000"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64url("Merhaba"), "size": 7},
        },
    }

    llm = MockLLM('{"short":{"subject":"Re: Toplantı","body":"Kısa."},"medium":{"subject":"Re: Toplantı","body":"Orta."},"detailed":{"subject":"Re: Toplantı","body":"Detay."}}')
    service = _make_service(full_message=full_message)

    out = gmail_generate_reply(message_id="m1", user_intent="ok", reply_all=False, llm=llm, service=service)
    assert out["ok"] is True
    assert out["reply_all"] is False
    assert out["to"] == ["alice@example.com"]
    assert out["cc"] is None

    drafts = service.users.return_value.drafts.return_value
    _, kwargs = drafts.create.call_args
    msg = _decode_raw_email(kwargs["body"]["message"]["raw"])
    assert msg.get("To") == "alice@example.com"
    assert msg.get("Cc") is None


def test_generate_reply_include_quote_appends_quote_even_if_llm_omits_it():
    full_message = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "snip",
        "payload": {
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": "Toplantı"},
                {"name": "Date", "value": "Mon, 1 Jan 2024 10:00:00 +0000"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64url("Orijinal içerik"), "size": 15},
        },
    }

    llm = MockLLM('{"short":{"subject":"Re: Toplantı","body":"OK"},"medium":{"subject":"Re: Toplantı","body":"OK"},"detailed":{"subject":"Re: Toplantı","body":"OK"}}')
    service = _make_service(full_message=full_message)

    out = gmail_generate_reply(message_id="m1", user_intent="ok", include_quote=True, llm=llm, service=service)
    assert out["ok"] is True
    assert out["include_quote"] is True
    assert "----- Orijinal Mesaj -----" in out["preview"]

    drafts = service.users.return_value.drafts.return_value
    _, kwargs = drafts.create.call_args
    msg = _decode_raw_email(kwargs["body"]["message"]["raw"])
    body = msg.get_payload()
    assert "----- Orijinal Mesaj -----" in body
    assert "> Orijinal içerik" in body


def test_generate_reply_llm_non_json_falls_back_to_medium_body():
    full_message = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "snip",
        "payload": {
            "headers": [
                {"name": "From", "value": "Alice <alice@example.com>"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Subject", "value": "Toplantı"},
                {"name": "Date", "value": "Mon, 1 Jan 2024 10:00:00 +0000"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64url("Merhaba"), "size": 7},
        },
    }

    llm = MockLLM("Sadece text output")
    service = _make_service(full_message=full_message)

    out = gmail_generate_reply(message_id="m1", user_intent="ok", llm=llm, service=service)
    assert out["ok"] is True

    drafts = service.users.return_value.drafts.return_value
    _, kwargs = drafts.create.call_args
    msg = _decode_raw_email(kwargs["body"]["message"]["raw"])
    assert "Sadece text output" in msg.get_payload()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
