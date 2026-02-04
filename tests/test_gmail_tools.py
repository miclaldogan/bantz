from __future__ import annotations

from unittest.mock import Mock

import base64

from bantz.google.gmail import gmail_get_message, gmail_list_messages, gmail_unread_count, gmail_send
from bantz.google.gmail import (
    gmail_create_draft,
    gmail_delete_draft,
    gmail_list_drafts,
    gmail_send_draft,
    gmail_update_draft,
)


def _make_get_response(
    *,
    msg_id: str,
    from_value: str | None = None,
    subject_value: str | None = None,
    date_value: str | None = None,
    snippet: str = "",
) -> dict:
    headers = []
    if from_value is not None:
        headers.append({"name": "From", "value": from_value})
    if subject_value is not None:
        headers.append({"name": "Subject", "value": subject_value})
    if date_value is not None:
        headers.append({"name": "Date", "value": date_value})

    return {
        "id": msg_id,
        "snippet": snippet,
        "payload": {"headers": headers},
    }


def _mock_gmail_service(*, list_execute: dict, get_execute_by_id: dict[str, dict]) -> Mock:
    """Build a chained mock that supports users().messages().list/get().execute()."""

    service = Mock(name="gmail_service")
    users = service.users.return_value
    messages = users.messages.return_value

    list_req = Mock(name="list_req")
    list_req.execute.return_value = list_execute
    messages.list.return_value = list_req

    def _get_side_effect(*, userId, id, format, metadataHeaders):  # noqa: A002
        _ = (userId, format, metadataHeaders)
        req = Mock(name=f"get_req_{id}")
        req.execute.return_value = get_execute_by_id[str(id)]
        return req

    messages.get.side_effect = _get_side_effect

    return service


def test_gmail_list_messages_inbox_defaults_and_pagination():
    service = _mock_gmail_service(
        list_execute={
            "messages": [{"id": "m1"}, {"id": "m2"}],
            "nextPageToken": "tok123",
            "resultSizeEstimate": 42,
        },
        get_execute_by_id={
            "m1": _make_get_response(
                msg_id="m1",
                from_value="a@example.com",
                subject_value="Hello",
                date_value="Mon, 1 Jan 2024 10:00:00 +0000",
                snippet="Snippet 1",
            ),
            "m2": _make_get_response(
                msg_id="m2",
                from_value="b@example.com",
                subject_value="World",
                date_value="Mon, 1 Jan 2024 11:00:00 +0000",
                snippet="Snippet 2",
            ),
        },
    )

    out = gmail_list_messages(max_results=2, service=service, page_token="p1")
    assert out["ok"] is True
    assert out["query"] == "in:inbox"
    assert out["estimated_count"] == 42
    assert out["next_page_token"] == "tok123"
    assert [m["id"] for m in out["messages"]] == ["m1", "m2"]
    assert out["messages"][0]["from"] == "a@example.com"
    assert out["messages"][0]["subject"] == "Hello"

    # Ensure query/pagination wired correctly
    service.users.return_value.messages.return_value.list.assert_called_once()
    _, kwargs = service.users.return_value.messages.return_value.list.call_args
    assert kwargs["labelIds"] == ["INBOX"]
    assert kwargs["maxResults"] == 2
    assert kwargs["pageToken"] == "p1"


def test_gmail_list_messages_unread_only_query():
    service = _mock_gmail_service(
        list_execute={"messages": [{"id": "m1"}], "resultSizeEstimate": 1},
        get_execute_by_id={
            "m1": _make_get_response(msg_id="m1", snippet="hi"),
        },
    )

    out = gmail_list_messages(max_results=1, unread_only=True, service=service)
    assert out["ok"] is True
    assert out["query"] == "is:unread"

    _, kwargs = service.users.return_value.messages.return_value.list.call_args
    assert kwargs["labelIds"] == ["INBOX", "UNREAD"]


def test_gmail_unread_count_uses_unread_label():
    service = Mock(name="gmail_service")
    users = service.users.return_value
    messages = users.messages.return_value

    list_req = Mock(name="list_req")
    list_req.execute.return_value = {"resultSizeEstimate": 7}
    messages.list.return_value = list_req

    out = gmail_unread_count(service=service)
    assert out == {"ok": True, "unread_count_estimate": 7}

    messages.list.assert_called_once()
    _, kwargs = messages.list.call_args
    assert kwargs["labelIds"] == ["UNREAD"]


def _b64url(s: str) -> str:
    raw = base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii")
    return raw.rstrip("=")


def test_gmail_get_message_plain_text_decoding_and_attachments_and_truncation():
    service = Mock(name="gmail_service")
    users = service.users.return_value

    # messages().get(...).execute()
    msg_get_req = Mock(name="msg_get_req")
    users.messages.return_value.get.return_value = msg_get_req

    long_text = "x" * 6000
    msg_get_req.execute.return_value = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "snip",
        "payload": {
            "headers": [
                {"name": "From", "value": "Ali <ali@example.com>"},
                {"name": "Subject", "value": "Konu"},
                {"name": "Date", "value": "Mon, 1 Jan 2024 10:00:00 +0000"},
            ],
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "filename": "",
                    "body": {"data": _b64url(long_text), "size": len(long_text)},
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "file.pdf",
                    "body": {"attachmentId": "att1", "size": 12345},
                },
            ],
        },
    }

    out = gmail_get_message(message_id="m1", service=service)
    assert out["ok"] is True
    assert out["message"]["id"] == "m1"
    assert out["message"]["threadId"] == "t1"
    assert out["message"]["from"] == "Ali <ali@example.com>"
    assert out["message"]["subject"] == "Konu"
    assert out["message"]["truncated"] is True
    assert len(out["message"]["body_text"]) == 5000

    atts = out["message"]["attachments"]
    assert any(a.get("filename") == "file.pdf" for a in atts)

    users.messages.return_value.get.assert_called_once()
    _, kwargs = users.messages.return_value.get.call_args
    assert kwargs["format"] == "full"


def test_gmail_get_message_html_fallback_when_no_plain():
    service = Mock(name="gmail_service")
    users = service.users.return_value
    msg_get_req = Mock(name="msg_get_req")
    users.messages.return_value.get.return_value = msg_get_req

    html = "<div>Merhaba <b>dunya</b></div>"
    msg_get_req.execute.return_value = {
        "id": "m2",
        "threadId": "t2",
        "snippet": "snip",
        "payload": {
            "headers": [{"name": "Subject", "value": "HTML"}],
            "mimeType": "text/html",
            "body": {"data": _b64url(html), "size": len(html)},
        },
    }

    out = gmail_get_message(message_id="m2", service=service)
    assert out["ok"] is True
    assert out["message"]["body_html"] is not None
    assert "Merhaba" in out["message"]["body_text"]
    assert "dunya" in out["message"]["body_text"]


def test_gmail_get_message_thread_expansion():
    service = Mock(name="gmail_service")
    users = service.users.return_value

    msg_get_req = Mock(name="msg_get_req")
    users.messages.return_value.get.return_value = msg_get_req
    msg_get_req.execute.return_value = {
        "id": "m3",
        "threadId": "t3",
        "snippet": "snip",
        "payload": {
            "headers": [{"name": "Subject", "value": "Thread"}],
            "mimeType": "text/plain",
            "body": {"data": _b64url("hi"), "size": 2},
        },
    }

    thread_get_req = Mock(name="thread_get_req")
    users.threads.return_value.get.return_value = thread_get_req
    thread_get_req.execute.return_value = {
        "id": "t3",
        "messages": [
            {
                "id": "m3",
                "threadId": "t3",
                "snippet": "snip",
                "payload": {
                    "headers": [{"name": "Subject", "value": "Thread"}],
                    "mimeType": "text/plain",
                    "body": {"data": _b64url("hi"), "size": 2},
                },
            },
            {
                "id": "m4",
                "threadId": "t3",
                "snippet": "snip2",
                "payload": {
                    "headers": [{"name": "Subject", "value": "Thread"}],
                    "mimeType": "text/plain",
                    "body": {"data": _b64url("hello"), "size": 5},
                },
            },
        ],
    }

    out = gmail_get_message(message_id="m3", expand_thread=True, service=service)
    assert out["ok"] is True
    assert out["thread"]["id"] == "t3"
    assert [m["id"] for m in out["thread"]["messages"]] == ["m3", "m4"]


def test_gmail_create_draft_calls_gmail_drafts_create_with_raw_message():
    service = Mock(name="gmail_service")
    drafts = service.users.return_value.drafts.return_value

    create_req = Mock(name="create_req")
    create_req.execute.return_value = {"id": "d1", "message": {"id": "m1", "threadId": "t1"}}
    drafts.create.return_value = create_req

    out = gmail_create_draft(to="a@example.com", subject="Hello", body="Hi", service=service)
    assert out["ok"] is True
    assert out["draft_id"] == "d1"
    assert out["message_id"] == "m1"
    assert out["thread_id"] == "t1"

    drafts.create.assert_called_once()
    _, kwargs = drafts.create.call_args
    assert kwargs["userId"] == "me"
    assert isinstance(kwargs["body"]["message"]["raw"], str)
    assert kwargs["body"]["message"]["raw"]


def test_gmail_list_drafts_fetches_metadata_for_each_draft():
    service = Mock(name="gmail_service")
    drafts = service.users.return_value.drafts.return_value

    list_req = Mock(name="list_req")
    list_req.execute.return_value = {
        "drafts": [{"id": "d1"}, {"id": "d2"}],
        "resultSizeEstimate": 2,
        "nextPageToken": "tok",
    }
    drafts.list.return_value = list_req

    def _get_side_effect(*, userId, id, format, metadataHeaders):  # noqa: A002
        _ = (userId, format, metadataHeaders)
        req = Mock(name=f"get_req_{id}")
        req.execute.return_value = {
            "id": str(id),
            "message": {
                "id": f"m_{id}",
                "snippet": f"snip_{id}",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "me@example.com"},
                        {"name": "To", "value": "you@example.com"},
                        {"name": "Subject", "value": f"Subj_{id}"},
                        {"name": "Date", "value": "Mon, 1 Jan 2024 10:00:00 +0000"},
                    ]
                },
            },
        }
        return req

    drafts.get.side_effect = _get_side_effect

    out = gmail_list_drafts(max_results=2, service=service)
    assert out["ok"] is True
    assert out["estimated_count"] == 2
    assert out["next_page_token"] == "tok"
    assert [d["draft_id"] for d in out["drafts"]] == ["d1", "d2"]
    assert out["drafts"][0]["subject"] == "Subj_d1"


def test_gmail_update_draft_partial_fetches_existing_and_updates_raw():
    service = Mock(name="gmail_service")
    drafts = service.users.return_value.drafts.return_value

    get_req = Mock(name="get_req")
    get_req.execute.return_value = {
        "id": "d1",
        "message": {
            "id": "m1",
            "threadId": "t1",
            "payload": {
                "headers": [
                    {"name": "To", "value": "a@example.com"},
                    {"name": "Subject", "value": "Old subject"},
                ],
                "mimeType": "text/plain",
                "body": {"data": _b64url("old body"), "size": 8},
            },
        },
    }
    drafts.get.return_value = get_req

    update_req = Mock(name="update_req")
    update_req.execute.return_value = {"id": "d1", "message": {"id": "m2", "threadId": "t2"}}
    drafts.update.return_value = update_req

    out = gmail_update_draft(draft_id="d1", updates={"subject": "New subject"}, service=service)
    assert out["ok"] is True
    assert out["draft_id"] == "d1"
    assert out["message_id"] == "m2"

    drafts.get.assert_called_once()
    drafts.update.assert_called_once()
    _, kwargs = drafts.update.call_args
    raw = kwargs["body"]["message"]["raw"]
    decoded = base64.urlsafe_b64decode(raw.encode("utf-8")).decode("utf-8", errors="ignore")
    assert "Subject: New subject" in decoded
    assert "To: a@example.com" in decoded


def test_gmail_send_draft_calls_gmail_drafts_send():
    service = Mock(name="gmail_service")
    drafts = service.users.return_value.drafts.return_value

    send_req = Mock(name="send_req")
    send_req.execute.return_value = {"id": "m9", "threadId": "t9", "labelIds": ["SENT"]}
    drafts.send.return_value = send_req

    out = gmail_send_draft(draft_id="d9", service=service)
    assert out["ok"] is True
    assert out["draft_id"] == "d9"
    assert out["message_id"] == "m9"
    assert out["thread_id"] == "t9"
    assert out["label_ids"] == ["SENT"]

    drafts.send.assert_called_once()


def test_gmail_delete_draft_calls_gmail_drafts_delete():
    service = Mock(name="gmail_service")
    drafts = service.users.return_value.drafts.return_value

    delete_req = Mock(name="delete_req")
    delete_req.execute.return_value = {}
    drafts.delete.return_value = delete_req

    out = gmail_delete_draft(draft_id="d7", service=service)
    assert out == {"ok": True, "draft_id": "d7"}
    drafts.delete.assert_called_once()


def test_gmail_send_builds_rfc2822_and_calls_gmail_api_send():
    service = Mock(name="gmail_service")
    users = service.users.return_value
    messages = users.messages.return_value

    send_req = Mock(name="send_req")
    send_req.execute.return_value = {"id": "msg123", "threadId": "thr456", "labelIds": ["SENT"]}
    messages.send.return_value = send_req

    out = gmail_send(
        to="a@example.com, b@example.com",
        subject="Hello",
        body="Body text",
        cc="c@example.com",
        bcc="d@example.com; e@example.com",
        service=service,
    )

    assert out["ok"] is True
    assert out["message_id"] == "msg123"
    assert out["thread_id"] == "thr456"
    assert out["label_ids"] == ["SENT"]
    assert out["to"] == ["a@example.com", "b@example.com"]
    assert out["cc"] == ["c@example.com"]
    assert out["bcc"] == ["d@example.com", "e@example.com"]

    messages.send.assert_called_once()
    _, kwargs = messages.send.call_args
    assert kwargs["userId"] == "me"
    assert "raw" in kwargs["body"]
    assert isinstance(kwargs["body"]["raw"], str)
