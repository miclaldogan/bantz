from __future__ import annotations

from unittest.mock import Mock

from bantz.google.gmail import gmail_list_messages, gmail_unread_count


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
    assert kwargs["q"] == "in:inbox"
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
    assert kwargs["q"] == "is:unread"


def test_gmail_unread_count_uses_is_unread_query():
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
    assert kwargs["q"] == "is:unread"
