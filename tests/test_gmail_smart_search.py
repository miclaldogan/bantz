from __future__ import annotations

from datetime import date
from unittest.mock import Mock

import os

from bantz.google.gmail_query import nl_to_gmail_query
from bantz.google.gmail_search_templates import templates_delete, templates_get, templates_list, templates_upsert
from bantz.google.gmail_smart_search import gmail_smart_search


def test_nl_to_query_gecen_hafta_matches_example_date_offset():
    # Matches the issue example logic: date.today() - timedelta(7)
    res = nl_to_gmail_query("geçen hafta", reference_date=date(2026, 1, 31), inbox_only=False)
    assert res.ok is True
    assert "after:2026-01-24" in res.parts


def test_nl_to_query_from_pattern():
    res = nl_to_gmail_query("Ali'den gelen mailleri bul", reference_date=date(2026, 2, 4))
    assert res.ok is True
    assert any(p.lower().startswith("from:") for p in res.parts)


def test_nl_to_query_to_pattern():
    res = nl_to_gmail_query("Ali'ye giden mailleri bul", reference_date=date(2026, 2, 4))
    assert res.ok is True
    assert any(p.lower().startswith("to:") for p in res.parts)


def test_nl_to_query_subject_konu_colon():
    res = nl_to_gmail_query("konu: Proje Update", reference_date=date(2026, 2, 4), inbox_only=False)
    assert res.ok is True
    assert "subject:\"Proje Update\"" in res.query


def test_nl_to_query_subject_hakkinda():
    res = nl_to_gmail_query("proje hakkında gelen mailler", reference_date=date(2026, 2, 4), inbox_only=False)
    assert res.ok is True
    assert any(p.lower().startswith("subject:") for p in res.parts)


def test_nl_to_query_has_attachment():
    res = nl_to_gmail_query("attachment'lı tüm mailler", reference_date=date(2026, 2, 4), inbox_only=False)
    assert res.ok is True
    assert "has:attachment" in res.parts


def test_nl_to_query_multi_criteria_composes():
    res = nl_to_gmail_query("Ali'den geçen hafta attachment", reference_date=date(2026, 2, 4), inbox_only=False)
    assert res.ok is True
    assert any(p.lower().startswith("from:") for p in res.parts)
    assert any(p.lower().startswith("after:") for p in res.parts)
    assert "has:attachment" in res.parts


def test_nl_to_query_preserves_existing_tokens():
    res = nl_to_gmail_query("from:a@example.com has:attachment", reference_date=date(2026, 2, 4), inbox_only=False)
    assert res.ok is True
    assert "from:a@example.com" in res.parts
    assert "has:attachment" in res.parts


def test_templates_crud(tmp_path, monkeypatch):
    p = tmp_path / "templates.json"
    monkeypatch.setenv("BANTZ_GMAIL_TEMPLATES_PATH", str(p))

    out = templates_upsert(name="Ali", query="from:ali@example.com")
    assert out["ok"] is True

    got = templates_get(name="ali")
    assert got["ok"] is True
    assert got["template"]["query"] == "from:ali@example.com"

    lst = templates_list()
    assert lst["ok"] is True
    assert any(t["key"] == "ali" for t in lst["templates"])

    deleted = templates_delete(name="ALI")
    assert deleted["ok"] is True
    assert deleted["deleted"] is True


def _mock_gmail_search_service(*, list_execute: dict, get_execute_by_id: dict[str, dict]) -> Mock:
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


def test_gmail_smart_search_uses_q_and_fetches_metadata(tmp_path, monkeypatch):
    # Ensure templates are isolated.
    monkeypatch.setenv("BANTZ_GMAIL_TEMPLATES_PATH", str(tmp_path / "templates.json"))
    templates_upsert(name="ali", query="from:ali@example.com")

    service = _mock_gmail_search_service(
        list_execute={
            "messages": [{"id": "m1"}],
            "resultSizeEstimate": 1,
        },
        get_execute_by_id={
            "m1": {
                "id": "m1",
                "snippet": "snip",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Ali <ali@example.com>"},
                        {"name": "To", "value": "Me <me@example.com>"},
                        {"name": "Subject", "value": "Hello"},
                        {"name": "Date", "value": "Mon, 1 Jan 2024 10:00:00 +0000"},
                    ]
                },
            }
        },
    )

    out = gmail_smart_search(query_nl="geçen hafta attachment", template_name="Ali", reference_date="2026-01-31", service=service)
    assert out["ok"] is True
    assert "q" in service.users.return_value.messages.return_value.list.call_args.kwargs
    q = service.users.return_value.messages.return_value.list.call_args.kwargs["q"]
    assert "from:ali@example.com" in q
    assert "after:2026-01-24" in q
    assert "has:attachment" in q

    assert out["messages"][0]["id"] == "m1"
    assert out["messages"][0]["subject"] == "Hello"
