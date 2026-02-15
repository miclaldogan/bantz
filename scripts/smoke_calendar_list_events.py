from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional
import os
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from bantz.google.auth import DEFAULT_CLIENT_SECRET_PATH, DEFAULT_TOKEN_PATH  # noqa: E402
from bantz.google.calendar import DEFAULT_CALENDAR_ID, list_events  # noqa: E402


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime


def _local_tz() -> Any:
    return datetime.now().astimezone().tzinfo


def _iso(dt: datetime) -> str:
    return dt.astimezone().isoformat()


def _parse_dt(value: str) -> datetime:
    # Accept RFC3339-ish strings; also accept trailing Z.
    v = (value or "").strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_local_tz())
    return dt


def _fmt_time(value: Optional[str]) -> str:
    if not value:
        return "?"
    v = value.strip()
    # All-day event: YYYY-MM-DD
    if len(v) == 10 and v[4] == "-" and v[7] == "-":
        return v
    try:
        dt = _parse_dt(v)
        return dt.astimezone(_local_tz()).strftime("%H:%M")
    except Exception:
        return v


def _window_today() -> TimeWindow:
    tz = _local_tz()
    now = datetime.now(tz)
    start = datetime.combine(now.date(), time(0, 0), tzinfo=tz)
    end = datetime.combine(now.date(), time(23, 59, 59), tzinfo=tz)
    return TimeWindow(start=start, end=end)


def _window_evening() -> TimeWindow:
    tz = _local_tz()
    now = datetime.now(tz)
    start = datetime.combine(now.date(), time(18, 0), tzinfo=tz)
    end = datetime.combine(now.date(), time(23, 59, 59), tzinfo=tz)
    return TimeWindow(start=start, end=end)


def _window_next(hours: int) -> TimeWindow:
    tz = _local_tz()
    start = datetime.now(tz)
    end = start + timedelta(hours=hours)
    return TimeWindow(start=start, end=end)


def _print_setup_help() -> None:
    print("Google Calendar OAuth setup required.")
    print()
    print("1) Install Google deps:")
    print("   pip install -e '.[calendar]'")
    print()
    print("2) Place your OAuth client secret file:")
    print(f"   Default: {DEFAULT_CLIENT_SECRET_PATH}")
    print("   or via env:")
    print("   export BANTZ_GOOGLE_CLIENT_SECRET=~/.config/bantz/google/client_secret.json")
    print()
    print("3) Token cache path (optional):")
    print(f"   Default: {DEFAULT_TOKEN_PATH}")
    print("   export BANTZ_GOOGLE_TOKEN_PATH=~/.config/bantz/google/token.json")
    print()
    print("4) Calendar ID (optional):")
    print(f"   Default: {DEFAULT_CALENDAR_ID}")
    print("   export BANTZ_GOOGLE_CALENDAR_ID=primary")


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke test: Google Calendar list events")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--today", action="store_true", help="List today's events")
    g.add_argument("--evening", action="store_true", help="List today's evening events (18:00-24:00)")

    ap.add_argument("--max-results", type=int, default=10, help="Max results")
    ap.add_argument("--calendar-id", type=str, default=None, help="Calendar ID (default: env or primary)")
    ap.add_argument("--query", type=str, default=None, help="Free-text search query")
    ap.add_argument("--time-min", type=str, default=None, help="RFC3339 timeMin override")
    ap.add_argument("--time-max", type=str, default=None, help="RFC3339 timeMax override")
    ap.add_argument("--next-hours", type=int, default=24, help="Default window when no flags: next N hours")
    ap.add_argument("--debug", action="store_true", help="Print debug info")

    args = ap.parse_args()

    secret_path = os.path.expanduser(os.getenv("BANTZ_GOOGLE_CLIENT_SECRET", DEFAULT_CLIENT_SECRET_PATH))
    if not Path(secret_path).exists():
        _print_setup_help()
        print()
        print(f"Error: client_secret.json not found: {secret_path}")
        return 2

    if args.time_min or args.time_max:
        tmn = args.time_min
        tmx = args.time_max
        if tmn is None:
            print("Error: --time-max requires --time-min (or use --today/--evening).")
            return 2
    else:
        if args.today:
            w = _window_today()
        elif args.evening:
            w = _window_evening()
        else:
            w = _window_next(int(args.next_hours))
        tmn = _iso(w.start)
        tmx = _iso(w.end)

    if args.debug:
        print("[debug] calendar_id:", args.calendar_id or os.getenv("BANTZ_GOOGLE_CALENDAR_ID") or DEFAULT_CALENDAR_ID)
        print("[debug] time_min:", tmn)
        print("[debug] time_max:", tmx)
        print("[debug] max_results:", args.max_results)
        print("[debug] query:", args.query)
        print("[debug] client_secret:", secret_path)
        print("[debug] token_path:", os.path.expanduser(os.getenv("BANTZ_GOOGLE_TOKEN_PATH", DEFAULT_TOKEN_PATH)))
        print()

    try:
        resp = list_events(
            calendar_id=args.calendar_id,
            max_results=int(args.max_results),
            time_min=tmn,
            time_max=tmx,
            query=args.query,
            single_events=True,
            show_deleted=False,
            order_by="startTime",
        )
    except RuntimeError as e:
        # Typically missing deps.
        _print_setup_help()
        print()
        print("Hata:", str(e))
        return 2
    except Exception as e:
        print("Hata:", str(e))
        return 1

    events = resp.get("events") if isinstance(resp, dict) else None
    if not isinstance(events, list) or not events:
        print("(no events)")
        return 0

    for ev in events:
        if not isinstance(ev, dict):
            continue
        start = _fmt_time(ev.get("start"))
        end = _fmt_time(ev.get("end"))
        summary = (ev.get("summary") or "(no title)")
        print(f"{start}–{end} | {summary}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
