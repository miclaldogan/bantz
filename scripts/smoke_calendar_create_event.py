from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
import os
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from bantz.google.auth import DEFAULT_CLIENT_SECRET_PATH, DEFAULT_TOKEN_PATH  # noqa: E402
from bantz.google.calendar import DEFAULT_CALENDAR_ID, create_event  # noqa: E402


@dataclass(frozen=True)
class Plan:
    summary: str
    start: str
    end: str
    calendar_id: str
    description: Optional[str]
    location: Optional[str]


def _local_tz() -> Any:
    return datetime.now().astimezone().tzinfo


def _iso(dt: datetime) -> str:
    return dt.astimezone().isoformat()


def _print_setup_help() -> None:
    print("Google Calendar OAuth (write) setup required.")
    print()
    print("1) Install Google deps:")
    print("   pip install -e '.[calendar]'")
    print()
    print("2) Place your OAuth client secret file:")
    print(f"   Default: {DEFAULT_CLIENT_SECRET_PATH}")
    print("   export BANTZ_GOOGLE_CLIENT_SECRET=~/.config/bantz/google/client_secret.json")
    print()
    print("3) Token cache path (optional):")
    print(f"   Default: {DEFAULT_TOKEN_PATH}")
    print("   export BANTZ_GOOGLE_TOKEN_PATH=~/.config/bantz/google/token.json")
    print()
    print("4) Calendar ID (optional):")
    print(f"   Default: {DEFAULT_CALENDAR_ID}")
    print("   export BANTZ_GOOGLE_CALENDAR_ID=primary"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke test: Google Calendar create event")
    ap.add_argument("--dry-run", action="store_true", help="Only print payload; do not create")
    ap.add_argument("--summary", type=str, default="Bantz Test Event", help="Event summary")
    ap.add_argument("--minutes-from-now", type=int, default=5, help="Start minutes from now")
    ap.add_argument("--duration-minutes", type=int, default=10, help="Duration minutes")
    ap.add_argument("--calendar-id", type=str, default=None, help="Calendar ID (default: env or primary)")
    ap.add_argument("--description", type=str, default=None, help="Optional description")
    ap.add_argument("--location", type=str, default=None, help="Optional location")
    ap.add_argument("--debug", action="store_true", help="Print debug info")
    args = ap.parse_args()

    secret_path = os.path.expanduser(os.getenv("BANTZ_GOOGLE_CLIENT_SECRET", DEFAULT_CLIENT_SECRET_PATH))
    if not Path(secret_path).exists():
        _print_setup_help()
        print()
        print(f"Error: client_secret.json not found: {secret_path}")
        return 2

    tz = _local_tz()
    start_dt = datetime.now(tz) + timedelta(minutes=int(args.minutes_from_now))
    end_dt = start_dt + timedelta(minutes=int(args.duration_minutes))

    cal_id = args.calendar_id or os.getenv("BANTZ_GOOGLE_CALENDAR_ID") or DEFAULT_CALENDAR_ID

    plan = Plan(
        summary=str(args.summary),
        start=_iso(start_dt),
        end=_iso(end_dt),
        calendar_id=str(cal_id),
        description=args.description,
        location=args.location,
    )

    payload: dict[str, Any] = {
        "summary": plan.summary,
        "start": plan.start,
        "end": plan.end,
        "calendar_id": plan.calendar_id,
        "description": plan.description,
        "location": plan.location,
    }

    if args.debug:
        print("[debug] client_secret:", secret_path)
        print("[debug] token_path:", os.path.expanduser(os.getenv("BANTZ_GOOGLE_TOKEN_PATH", DEFAULT_TOKEN_PATH)))
        print("[debug] calendar_id:", plan.calendar_id)
        print("[debug] start:", plan.start)
        print("[debug] end:", plan.end)
        print("[debug] dry_run:", bool(args.dry_run))
        print()

    if args.dry_run:
        print("Dry-run payload:")
        for k, v in payload.items():
            if v is None:
                continue
            print(f"- {k}: {v}")
        return 0

    try:
        out = create_event(
            summary=plan.summary,
            start=plan.start,
            end=plan.end,
            calendar_id=plan.calendar_id,
            description=plan.description,
            location=plan.location,
        )
    except RuntimeError as e:
        _print_setup_help()
        print()
        print("Hata:", str(e))
        return 2
    except Exception as e:
        print("Hata:", str(e))
        return 1

    print("Created:")
    print("- id:", out.get("id"))
    print("- summary:", out.get("summary"))
    print("- start:", out.get("start"))
    print("- end:", out.get("end"))
    if out.get("htmlLink"):
        print("- link:", out.get("htmlLink"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
