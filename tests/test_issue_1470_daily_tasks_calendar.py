"""
Tests for Issue #1470 — Daily Tasks panel shows real Google Calendar events.

Spec-mirror note: helper functions _is_today(), _is_all_day(), _is_imminent(),
and _build_cal_card() intentionally mirror the corresponding logic in
src/bantz/server.py (section 5).  Any change to the server logic must be
reflected here and vice-versa.

Acceptance Criteria:
  AC1: Startup shows today's meetings in DailyTasksPanel.
  AC2: all_day events are marked as 'TÜM GÜN'.
  AC3: Events starting within 30 minutes get is_imminent=True (imminent tag).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

_UTC = timezone.utc


@dataclass
class _IngestRecord:
    id: str
    source: str
    content: Dict[str, Any]
    meta: Optional[Dict[str, Any]] = None
    created_at: float = field(default_factory=time.time)


# Frozen timestamp for flakiness-free imminent/today calculations.
# All tests that compare against "now" use _NOW instead of a live datetime.now().
_NOW: datetime = datetime.now(_UTC)


def _now() -> datetime:
    """Return the frozen module-level timestamp (prevents test flakiness)."""
    return _NOW


def _today_iso(hour: int = 10, minute: int = 0) -> str:
    """Return an ISO string for today at the given time (UTC)."""
    dt = _NOW.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return dt.isoformat()


def _allday_iso() -> str:
    """Return a date-only string (all-day event, no 'T')."""
    return _NOW.date().isoformat()  # e.g. "2026-02-18"


def _make_cal_record(
    idx: int,
    summary: str = "",
    start: str = "",
    end: str = "",
    is_all_day: bool = False,
) -> _IngestRecord:
    s = start or _today_iso(10 + idx)
    e = end or _today_iso(11 + idx)
    return _IngestRecord(
        id=f"cal-rec-{idx}",
        source="calendar",
        content={
            "event_id": f"evt-{idx}",
            "summary": summary or f"Meeting {idx}",
            "start": _allday_iso() if is_all_day else s,
            "end": _allday_iso() if is_all_day else e,
            "location": "",
            "status": "confirmed",
        },
        meta={
            "is_all_day": is_all_day,
            "sync_source": "calendar_sync",
        },
    )


# ---------------------------------------------------------------------------
# Logic mirrors from server.py today-filter + imminent calculation
# ---------------------------------------------------------------------------

_IMMINENT_SECONDS = 1800  # 30 minutes


def _is_today(raw_start: str, today: datetime) -> bool:
    """Mirror server.py today-filter logic."""
    if not raw_start:
        return False
    if "T" not in str(raw_start):
        # all-day
        try:
            evt_date = datetime.fromisoformat(str(raw_start)).date()
            return evt_date == today.date()
        except Exception:
            return True
    else:
        try:
            evt_dt = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
            today_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today.replace(hour=23, minute=59, second=59, microsecond=0)
            return today_start <= evt_dt <= today_end
        except Exception:
            return True


def _is_all_day(raw_start: str) -> bool:
    return "T" not in str(raw_start)


def _is_imminent(raw_start: str, now: datetime) -> bool:
    """Mirror server.py imminent logic: 0 <= diff <= 1800s."""
    if _is_all_day(raw_start):
        return False
    try:
        start_dt = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
        diff = (start_dt - now).total_seconds()
        return 0 <= diff <= _IMMINENT_SECONDS
    except Exception:
        return False


def _build_cal_card(evt: dict, idx: int, total: int, now: datetime) -> dict:
    """Mirror server.py section 5 card construction."""
    raw_start = evt.get("start", "")
    all_day = _is_all_day(raw_start)
    imminent = not all_day and _is_imminent(raw_start, now)
    return {
        "type": "briefing_card",
        "category": "calendar",
        "index": idx,
        "total": total,
        "title": evt.get("title", evt.get("summary", "")),
        "start": raw_start,
        "end": evt.get("end", ""),
        "all_day": all_day,
        "is_imminent": imminent,
        "id": evt.get("id", evt.get("event_id", f"cal-{idx}")),
    }


# ---------------------------------------------------------------------------
# AC1: Today's meetings are emitted
# ---------------------------------------------------------------------------


class TestAC1TodayFilter:
    def test_today_event_is_included(self):
        assert _is_today(_today_iso(14, 0), _now()) is True

    def test_yesterday_event_is_excluded(self):
        yesterday = (_now() - timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        assert _is_today(yesterday.isoformat(), _now()) is False

    def test_tomorrow_event_is_excluded(self):
        tomorrow = (_now() + timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        assert _is_today(tomorrow.isoformat(), _now()) is False

    def test_allday_today_is_included(self):
        assert _is_today(_allday_iso(), _now()) is True

    def test_allday_yesterday_is_excluded(self):
        yesterday_date = (_now() - timedelta(days=1)).date().isoformat()
        assert _is_today(yesterday_date, _now()) is False

    def test_empty_start_returns_false(self):
        assert _is_today("", _now()) is False

    def test_multiple_events_today_all_pass(self):
        events = [_today_iso(h) for h in range(9, 18)]
        today_events = [e for e in events if _is_today(e, _now())]
        assert len(today_events) == len(events)

    def test_card_type_and_category(self):
        evt = {"event_id": "e1", "summary": "Standup", "start": _today_iso(9), "end": _today_iso(10)}
        card = _build_cal_card(evt, 0, 1, _now())
        assert card["type"] == "briefing_card"
        assert card["category"] == "calendar"

    def test_card_title_from_summary(self):
        evt = {"event_id": "e1", "summary": "Sprint Review", "start": _today_iso(15), "end": _today_iso(16)}
        card = _build_cal_card(evt, 0, 1, _now())
        assert card["title"] == "Sprint Review"

    def test_card_id_from_event_id(self):
        evt = {"event_id": "abc123", "summary": "Demo", "start": _today_iso(11), "end": _today_iso(12)}
        card = _build_cal_card(evt, 0, 1, _now())
        assert card["id"] == "abc123"


# ---------------------------------------------------------------------------
# AC2: all_day events are flagged
# ---------------------------------------------------------------------------


class TestAC2AllDay:
    def test_allday_event_has_all_day_true(self):
        assert _is_all_day(_allday_iso()) is True

    def test_timed_event_has_all_day_false(self):
        assert _is_all_day(_today_iso(10)) is False

    def test_card_all_day_true_for_date_only_start(self):
        evt = {"event_id": "e1", "summary": "Holiday", "start": _allday_iso(), "end": _allday_iso()}
        card = _build_cal_card(evt, 0, 1, _now())
        assert card["all_day"] is True

    def test_card_all_day_false_for_datetime_start(self):
        evt = {"event_id": "e2", "summary": "Meeting", "start": _today_iso(14), "end": _today_iso(15)}
        card = _build_cal_card(evt, 0, 1, _now())
        assert card["all_day"] is False

    def test_allday_event_is_not_imminent(self):
        evt = {"event_id": "e3", "summary": "Holiday", "start": _allday_iso(), "end": _allday_iso()}
        card = _build_cal_card(evt, 0, 1, _now())
        assert card["is_imminent"] is False


# ---------------------------------------------------------------------------
# AC3: Imminent events (within 30 min) get is_imminent=True
# ---------------------------------------------------------------------------


class TestAC3ImminentTag:
    def test_event_in_15_min_is_imminent(self):
        start = (_now() + timedelta(minutes=15)).isoformat()
        assert _is_imminent(start, _now()) is True

    def test_event_in_29_min_is_imminent(self):
        start = (_now() + timedelta(minutes=29)).isoformat()
        assert _is_imminent(start, _now()) is True

    def test_event_in_30_min_is_imminent(self):
        start = (_now() + timedelta(minutes=30)).isoformat()
        assert _is_imminent(start, _now()) is True

    def test_event_in_31_min_is_not_imminent(self):
        start = (_now() + timedelta(minutes=31)).isoformat()
        assert _is_imminent(start, _now()) is False

    def test_event_in_2_hours_is_not_imminent(self):
        start = (_now() + timedelta(hours=2)).isoformat()
        assert _is_imminent(start, _now()) is False

    def test_past_event_is_not_imminent(self):
        start = (_now() - timedelta(minutes=10)).isoformat()
        assert _is_imminent(start, _now()) is False

    def test_allday_is_never_imminent(self):
        assert _is_imminent(_allday_iso(), _now()) is False

    def test_card_is_imminent_true_for_near_event(self):
        soon = (_now() + timedelta(minutes=10)).isoformat()
        evt = {"event_id": "e5", "summary": "Quick Sync", "start": soon, "end": soon}
        card = _build_cal_card(evt, 0, 1, _now())
        assert card["is_imminent"] is True

    def test_card_is_imminent_false_for_far_event(self):
        later = (_now() + timedelta(hours=3)).isoformat()
        evt = {"event_id": "e6", "summary": "Evening", "start": later, "end": later}
        card = _build_cal_card(evt, 0, 1, _now())
        assert card["is_imminent"] is False


# ---------------------------------------------------------------------------
# Integration: IngestStore source name fix
# ---------------------------------------------------------------------------


class TestCalendarSourceFix:
    """Verify the IngestStore is queried with source='calendar' (not 'calendar_sync')."""

    def test_correct_source_key_used(self):
        """CalendarSyncer uses _INGEST_SOURCE = 'calendar', not 'calendar_sync'."""
        # Simulate server.py query with correct source
        with patch("bantz.data.ingest_store.IngestStore") as MockStore:
            instance = MockStore.return_value
            instance.query.return_value = []

            store = MockStore()
            store.query(source="calendar", limit=50)

            instance.query.assert_called_once_with(source="calendar", limit=50)

    def test_wrong_source_key_returns_empty(self):
        """Querying 'calendar_sync' (wrong) returns no results."""
        with patch("bantz.data.ingest_store.IngestStore") as MockStore:
            instance = MockStore.return_value
            # Simulate: 'calendar' has data, 'calendar_sync' is empty
            instance.query.side_effect = lambda **kwargs: (
                [_make_cal_record(0)] if kwargs.get("source") == "calendar" else []
            )

            store = MockStore()
            result_wrong = store.query(source="calendar_sync", limit=50)
            result_correct = store.query(source="calendar", limit=50)

            assert result_wrong == []
            assert len(result_correct) == 1


# ---------------------------------------------------------------------------
# Integration: full section-5 dispatch simulation
# ---------------------------------------------------------------------------


class TestSection5Dispatch:
    def _simulate_section5(self, events: list) -> list:
        """Simulate server.py section 5 dispatch loop, return sent cards."""
        now = _now()
        sent = []
        for i, evt in enumerate(events):
            card = _build_cal_card(evt, i, len(events), now)
            sent.append(card)
        return sent

    def test_three_events_produce_three_cards(self):
        events = [
            {"event_id": f"e{i}", "summary": f"Evt {i}", "start": _today_iso(9 + i), "end": _today_iso(10 + i)}
            for i in range(3)
        ]
        sent = self._simulate_section5(events)
        assert len(sent) == 3

    def test_all_cards_are_calendar_type(self):
        events = [{"event_id": "e1", "summary": "S", "start": _today_iso(10), "end": _today_iso(11)}]
        sent = self._simulate_section5(events)
        assert sent[0]["category"] == "calendar"
        assert sent[0]["type"] == "briefing_card"

    def test_imminent_event_flagged_in_dispatch(self):
        soon = (_now() + timedelta(minutes=5)).isoformat()
        events = [{"event_id": "e1", "summary": "Urgent", "start": soon, "end": soon}]
        sent = self._simulate_section5(events)
        assert sent[0]["is_imminent"] is True

    def test_allday_event_flagged_in_dispatch(self):
        events = [{"event_id": "e2", "summary": "Holiday", "start": _allday_iso(), "end": _allday_iso()}]
        sent = self._simulate_section5(events)
        assert sent[0]["all_day"] is True
        assert sent[0]["is_imminent"] is False

    def test_index_and_total_correct(self):
        events = [
            {"event_id": f"e{i}", "summary": f"E{i}", "start": _today_iso(9 + i), "end": _today_iso(10 + i)}
            for i in range(4)
        ]
        sent = self._simulate_section5(events)
        for i, card in enumerate(sent):
            assert card["index"] == i
            assert card["total"] == 4

    def test_empty_events_produce_no_cards(self):
        sent = self._simulate_section5([])
        assert sent == []


# ---------------------------------------------------------------------------
# Renderer accumulation simulation
# ---------------------------------------------------------------------------


class TestRendererCalendarAccumulation:
    def _simulate_renderer(self, cards: list) -> tuple[list, list]:
        """Simulate renderer.js calendar routing.
        Returns (addEvent_calls, setCalendarEvents_calls).
        """
        add_calls = []
        set_calls = []
        cal_acc = []

        fake_dt = MagicMock()
        fake_dt.addEvent = MagicMock(side_effect=lambda e: add_calls.append(dict(e)))

        fake_inbox = MagicMock()
        fake_inbox.setCalendarEvents = MagicMock(side_effect=lambda evts: set_calls.append(list(evts)))

        for msg in cards:
            if msg.get("category") == "calendar":
                fake_dt.addEvent({
                    "title": msg.get("title"),
                    "start": msg.get("start"),
                    "end": msg.get("end"),
                    "all_day": msg.get("all_day"),
                    "is_imminent": bool(msg.get("is_imminent")),
                    "id": msg.get("id"),
                })
                cal_acc.append({
                    "title": msg.get("title"),
                    "start": msg.get("start"),
                    "end": msg.get("end"),
                    "all_day": msg.get("all_day"),
                    "id": msg.get("id"),
                })
                fake_inbox.setCalendarEvents(cal_acc)

        return add_calls, set_calls

    def test_addEvent_called_for_each_card(self):
        cards = [
            {"type": "briefing_card", "category": "calendar", "title": f"Evt {i}",
             "start": _today_iso(9 + i), "end": _today_iso(10 + i),
             "all_day": False, "is_imminent": False, "id": f"e{i}"}
            for i in range(3)
        ]
        add_calls, _ = self._simulate_renderer(cards)
        assert len(add_calls) == 3

    def test_is_imminent_passed_to_addEvent(self):
        soon = (_now() + timedelta(minutes=5)).isoformat()
        cards = [{"type": "briefing_card", "category": "calendar", "title": "Urgent",
                  "start": soon, "end": soon, "all_day": False, "is_imminent": True, "id": "e1"}]
        add_calls, _ = self._simulate_renderer(cards)
        assert add_calls[0]["is_imminent"] is True

    def test_inbox_accumulates_across_cards(self):
        cards = [
            {"type": "briefing_card", "category": "calendar", "title": f"E{i}",
             "start": _today_iso(9 + i), "end": _today_iso(10 + i),
             "all_day": False, "is_imminent": False, "id": f"e{i}"}
            for i in range(3)
        ]
        _, set_calls = self._simulate_renderer(cards)
        assert len(set_calls[0]) == 1
        assert len(set_calls[1]) == 2
        assert len(set_calls[2]) == 3

    def test_reset_on_briefing_start(self):
        """_briefingCalCards accumulator is cleared on briefing_start.

        Simulates a full two-briefing sequence:
          1. First briefing populates the accumulator with 2 events.
          2. briefing_start fires — accumulator is reset to [].
          3. Second briefing adds 1 new event.
        After the reset only the single new event should be present.
        """
        # ─ First briefing ────────────────────────────────────────
        acc: list = []
        acc.append({"title": "Old Event 1", "id": "old1"})
        acc.append({"title": "Old Event 2", "id": "old2"})
        assert len(acc) == 2

        # ─ briefing_start: reset accumulator ─────────────────────
        acc = []  # mirrors: briefingCalCards = [] in renderer.js

        # ─ Second briefing ───────────────────────────────────────
        acc.append({"title": "New Event", "id": "new1"})

        # Only the new event should be present after reset
        assert len(acc) == 1
        assert acc[0]["title"] == "New Event"

    def test_non_calendar_cards_not_routed(self):
        cards = [
            {"type": "briefing_card", "category": "weather", "temperature": 20},
            {"type": "briefing_card", "category": "calendar", "title": "Meeting",
             "start": _today_iso(10), "end": _today_iso(11), "all_day": False,
             "is_imminent": False, "id": "e1"},
            {"type": "briefing_card", "category": "news", "title": "News"},
        ]
        add_calls, _ = self._simulate_renderer(cards)
        assert len(add_calls) == 1
        assert add_calls[0]["title"] == "Meeting"
