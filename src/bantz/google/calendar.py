from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
import os

from bantz.google.auth import get_credentials


DEFAULT_CALENDAR_ID = "primary"
READONLY_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_events(
    *,
    calendar_id: Optional[str] = None,
    max_results: int = 10,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    query: Optional[str] = None,
    single_events: bool = True,
    show_deleted: bool = False,
    order_by: str = "startTime",
) -> dict[str, Any]:
    """List upcoming events from Google Calendar.

    Notes:
    - Requires OAuth client_secret.json and a cached token.
    - Returns a JSON-serializable dict.
    """

    cal_id = (
        calendar_id
        or os.getenv("BANTZ_GOOGLE_CALENDAR_ID")
        or DEFAULT_CALENDAR_ID
    )

    # Get creds first (this will also validate secret file presence).
    creds = get_credentials(scopes=READONLY_SCOPES)

    # Lazy import to keep base installs light.
    try:
        from googleapiclient.discovery import build  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Google calendar dependencies are not installed. Install with: "
            "pip install -e '.[calendar]'"
        ) from e

    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    tmn = time_min or _now_rfc3339()
    params: dict[str, Any] = {
        "calendarId": cal_id,
        "timeMin": tmn,
        "maxResults": int(max_results),
        "singleEvents": bool(single_events),
        "showDeleted": bool(show_deleted),
        "orderBy": order_by,
    }
    if time_max:
        params["timeMax"] = time_max
    if query:
        params["q"] = query

    resp = service.events().list(**params).execute()
    items = resp.get("items") or []

    events: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        start = (it.get("start") or {}) if isinstance(it.get("start"), dict) else {}
        end = (it.get("end") or {}) if isinstance(it.get("end"), dict) else {}

        events.append(
            {
                "id": it.get("id"),
                "summary": it.get("summary"),
                "start": start.get("dateTime") or start.get("date"),
                "end": end.get("dateTime") or end.get("date"),
                "location": it.get("location"),
                "htmlLink": it.get("htmlLink"),
                "status": it.get("status"),
            }
        )

    return {
        "ok": True,
        "calendar_id": cal_id,
        "count": len(events),
        "events": events,
    }
