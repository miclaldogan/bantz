from __future__ import annotations

from typing import Any, Optional

from bantz.google.gmail_auth import GMAIL_READONLY_SCOPES, authenticate_gmail
from bantz.google.gmail_query import nl_to_gmail_query
from bantz.google.gmail_search_templates import templates_get


def _get_header(payload: dict[str, Any], name: str) -> Optional[str]:
    headers = payload.get("headers") if isinstance(payload, dict) else None
    if not isinstance(headers, list):
        return None

    target = name.strip().lower()
    for h in headers:
        if not isinstance(h, dict):
            continue
        n = str(h.get("name") or "").strip().lower()
        if n == target:
            v = h.get("value")
            return str(v) if v is not None else None

    return None


def gmail_smart_search(
    *,
    query_nl: str,
    max_results: int = 10,
    page_token: str | None = None,
    inbox_only: bool = True,
    template_name: str | None = None,
    service: Any = None,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """Search Gmail with a natural-language query.

    - Converts NL → Gmail `q=` query.
    - Uses readonly scope.
    - SAFE (read-only).

    Args:
        query_nl: Natural language query (Turkish-ish supported).
        template_name: Optional saved template name; if present its query is prepended.
        reference_date: Optional ISO date string used for relative dates (tests).

    Returns:
        {ok, query, estimated_count, next_page_token, messages:[...]}
    """

    if not isinstance(max_results, int) or max_results <= 0:
        raise ValueError("max_results must be a positive integer")

    base_query = ""
    if template_name:
        got = templates_get(name=template_name)
        if not got.get("ok"):
            return {"ok": False, "error": "template_not_found", "query": "", "messages": [], "estimated_count": None, "next_page_token": None}
        tpl = got.get("template") or {}
        base_query = str(tpl.get("query") or "").strip()

    # Parse reference date.
    ref = None
    if reference_date:
        from datetime import date

        ref = date.fromisoformat(str(reference_date))

    built = nl_to_gmail_query(query_nl, reference_date=ref, inbox_only=inbox_only)
    if not built.ok:
        return {"ok": False, "error": built.error or "invalid_query", "query": "", "messages": [], "estimated_count": None, "next_page_token": None}

    query = (base_query + " " + built.query).strip() if base_query else built.query

    try:
        svc = service or authenticate_gmail(scopes=GMAIL_READONLY_SCOPES)

        list_kwargs: dict[str, Any] = {
            "userId": "me",
            "q": query,
            "maxResults": max_results,
        }
        if page_token:
            list_kwargs["pageToken"] = page_token

        list_resp = svc.users().messages().list(**list_kwargs).execute() or {}
        msg_refs = list_resp.get("messages")
        if not isinstance(msg_refs, list):
            msg_refs = []

        next_page_token = list_resp.get("nextPageToken")
        estimated_count = list_resp.get("resultSizeEstimate")
        if not isinstance(estimated_count, int):
            estimated_count = None

        out_messages: list[dict[str, Any]] = []
        for ref in msg_refs:
            if not isinstance(ref, dict):
                continue
            msg_id = ref.get("id")
            if not msg_id:
                continue

            msg = (
                svc.users()
                .messages()
                .get(
                    userId="me",
                    id=str(msg_id),
                    format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"],
                )
                .execute()
                or {}
            )

            payload = msg.get("payload")
            if not isinstance(payload, dict):
                payload = {}

            out_messages.append(
                {
                    "id": str(msg.get("id") or msg_id),
                    "from": _get_header(payload, "From"),
                    "to": _get_header(payload, "To"),
                    "subject": _get_header(payload, "Subject"),
                    "snippet": str(msg.get("snippet") or ""),
                    "date": _get_header(payload, "Date"),
                }
            )

        return {
            "ok": True,
            "query": query,
            "estimated_count": estimated_count,
            "next_page_token": str(next_page_token) if next_page_token else None,
            "messages": out_messages,
        }

    except Exception as e:  # pragma: no cover
        return {
            "ok": False,
            "error": str(e),
            "query": query,
            "messages": [],
            "estimated_count": None,
            "next_page_token": None,
        }
