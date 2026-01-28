from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from bantz.agent.builtin_tools import build_default_registry  # noqa: E402
from bantz.time_windows import evening_window  # noqa: E402


try:  # noqa: E402
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


@dataclass(frozen=True)
class DemoConfig:
    run: bool
    calendar_id: Optional[str]
    tz_name: str
    d: date


def _local_tzinfo(name: str):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo


def _rfc3339(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _mask_params(params: dict[str, Any]) -> dict[str, Any]:
    masked: dict[str, Any] = {}
    for k, v in params.items():
        lk = str(k).lower()
        if any(x in lk for x in ("token", "secret", "password")):
            masked[k] = "***"
            continue
        masked[k] = v
    return masked


def _print_tool_call(name: str, params: dict[str, Any]) -> None:
    payload = {"tool": name, "params": _mask_params(params)}
    print("CALL_TOOL", json.dumps(payload, ensure_ascii=False))


def _format_hhmm(iso_dt: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_dt.replace("Z", "+00:00"))
        local = dt.astimezone(datetime.now().astimezone().tzinfo)
        return local.strftime("%H:%M")
    except Exception:
        return iso_dt


def _ask_confirm(prompt: str) -> bool:
    reply = input(prompt).strip().lower()
    return reply in {"tamam", "evet", "ok", "yes", "y"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic Jarvis Calendar demo (no LLM)")
    ap.add_argument("--evening", action="store_true", help="Use the 'evening' window")
    ap.add_argument("--date", type=str, default=None, help="Date YYYY-MM-DD (default: today)")
    ap.add_argument("--tz", type=str, default="Europe/Istanbul", help="Timezone name (default: Europe/Istanbul)")
    ap.add_argument("--calendar-id", type=str, default=None, help="Calendar ID (default: env or primary)")
    ap.add_argument("--dry-run", action="store_true", help="Do not create events; just print what would happen")
    ap.add_argument("--run", action="store_true", help="Actually call write tools (will prompt for confirmation)")
    ap.add_argument("--debug", action="store_true", help="Print debug info")
    args = ap.parse_args()

    if args.dry_run and args.run:
        raise SystemExit("Choose only one: --dry-run or --run")

    run_mode = bool(args.run)
    if not args.dry_run and not args.run:
        # Default safe behavior.
        run_mode = False

    if args.date:
        d = date.fromisoformat(args.date)
    else:
        d = datetime.now().date()

    cfg = DemoConfig(run=run_mode, calendar_id=args.calendar_id, tz_name=str(args.tz), d=d)
    tz = _local_tzinfo(cfg.tz_name)

    reg = build_default_registry()

    if args.debug:
        print("[debug] date:", cfg.d.isoformat())
        print("[debug] tz:", cfg.tz_name)
        print("[debug] tzinfo:", str(tz))
        print("[debug] calendar_id:", cfg.calendar_id)
        print("[debug] run_mode:", cfg.run)
        print("[debug] dry_run:", bool(args.dry_run))
        print()

    print('USER: "Bu akşam planım var mı?"')
    print("BANTZ: Kontrol etmeme izin verin efendim…")

    # 1) list_events (evening)
    if args.evening:
        time_min, time_max = evening_window(cfg.d, tz)
    else:
        now = datetime.now(tz)
        time_min = _rfc3339(now)
        time_max = _rfc3339(now + timedelta(hours=6))

    if args.debug:
        print("[debug] list_events time_min:", time_min)
        print("[debug] list_events time_max:", time_max)
        print()

    tool1 = reg.get("calendar.list_events")
    if not tool1 or not tool1.function:
        raise SystemExit("calendar.list_events tool not available")

    params1: dict[str, Any] = {"time_min": time_min, "time_max": time_max, "max_results": 20}
    if cfg.calendar_id:
        params1["calendar_id"] = cfg.calendar_id

    _print_tool_call("calendar.list_events", params1)
    out1 = tool1.function(**params1)
    events = (out1 or {}).get("events") or []
    if args.debug:
        print("[debug] list_events count:", len(events) if isinstance(events, list) else "?")
    if not events:
        print("BANTZ: Bu akşam takviminizde bir etkinlik görünmüyor efendim.")
    else:
        print("BANTZ: Bu akşamki planlarınız efendim:")
        for ev in events:
            s = (ev or {}).get("start")
            e = (ev or {}).get("end")
            summary = (ev or {}).get("summary") or "(no title)"
            if isinstance(s, str) and isinstance(e, str):
                print(f"- {_format_hhmm(s)}–{_format_hhmm(e)} | {summary}")

    print()
    print('USER: "8\'den önce 2 saat koşu koy"')
    print("BANTZ: Uygun bir boşluk arıyorum efendim…")

    # 2) find_free_slots (until 20:00)
    tool2 = reg.get("calendar.find_free_slots")
    if not tool2 or not tool2.function:
        raise SystemExit("calendar.find_free_slots tool not available")

    # Deterministic: search the whole day up to 20:00 (not "from now").
    window_start = datetime.combine(cfg.d, time(0, 0), tzinfo=tz)
    window_end = datetime.combine(cfg.d, time(20, 0), tzinfo=tz)

    if window_end <= window_start:
        print("BANTZ: 20:00\'ye kadar uygun bir pencere tanımlayamadım efendim.")
        return 1

    if args.debug:
        print("[debug] find_free_slots time_min:", _rfc3339(window_start))
        print("[debug] find_free_slots time_max:", _rfc3339(window_end))
        print("[debug] find_free_slots duration_minutes:", 120)
        print()

    params2: dict[str, Any] = {
        "time_min": _rfc3339(window_start),
        "time_max": _rfc3339(window_end),
        "duration_minutes": 120,
        "suggestions": 3,
    }
    if cfg.calendar_id:
        params2["calendar_id"] = cfg.calendar_id

    _print_tool_call("calendar.find_free_slots", params2)
    out2 = tool2.function(**params2)
    slots = (out2 or {}).get("slots") or []
    if args.debug:
        print("[debug] find_free_slots count:", len(slots) if isinstance(slots, list) else "?")
    if not slots:
        print("BANTZ: Maalesef 20:00\'den önce 2 saatlik boşluk bulamadım efendim.")
    else:
        print("BANTZ: Şu boşlukları buldum efendim:")
        for i, sl in enumerate(slots, start=1):
            s = sl.get("start")
            e = sl.get("end")
            if isinstance(s, str) and isinstance(e, str):
                print(f"  {i}) {_format_hhmm(s)}–{_format_hhmm(e)}")

    print()
    print('USER: "3:45 yap"')

    # 3) create_event (MED + confirmation)
    tool3 = reg.get("calendar.create_event")
    if not tool3 or not tool3.function:
        raise SystemExit("calendar.create_event tool not available")

    start_dt = datetime.combine(cfg.d, time(15, 45), tzinfo=tz)
    end_dt = start_dt + timedelta(minutes=120)

    params3: dict[str, Any] = {
        "summary": "Bantz Demo: Koşu",
        "start": _rfc3339(start_dt),
        "end": _rfc3339(end_dt),
    }
    if cfg.calendar_id:
        params3["calendar_id"] = cfg.calendar_id

    preview = f"{_format_hhmm(params3['start'])}–{_format_hhmm(params3['end'])} | {params3['summary']}"

    if args.debug:
        print("[debug] create_event start:", params3["start"])
        print("[debug] create_event end:", params3["end"])
        print("[debug] create_event summary:", params3["summary"])
        print("[debug] requires_confirmation:", bool(tool3.requires_confirmation))
        print()

    if tool3.requires_confirmation:
        print(f"BANTZ: Efendim, takvime şu etkinliği eklememi onaylıyor musunuz? ({preview})")
        if not cfg.run:
            print("BANTZ: (dry-run) Onay alınsaydı ekleyecektim efendim.")
            _print_tool_call("calendar.create_event", params3)
            return 0

        if not _ask_confirm("USER (tamam/iptal): "):
            print("BANTZ: İptal ediyorum efendim.")
            return 2

    print("BANTZ: Anlaşıldı… takviminize ekliyorum efendim.")
    _print_tool_call("calendar.create_event", params3)
    out3 = tool3.function(**params3)

    if isinstance(out3, dict) and out3.get("ok"):
        print("BANTZ: Tamamdır efendim.")
        if out3.get("htmlLink"):
            print("- link:", out3.get("htmlLink"))
        return 0

    print("BANTZ: Bir hata oldu efendim.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
