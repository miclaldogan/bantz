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


from bantz.agent.builtin_tools import build_planner_registry  # noqa: E402


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


def _parse_rfc3339(value: str, default_tz) -> Optional[datetime]:
    v = (value or "").strip()
    if not v:
        return None
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=default_tz)
    return dt


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        s = ev.get("start")
        e = ev.get("end")
        summary = ev.get("summary") or ""
        if not isinstance(s, str) or not isinstance(e, str):
            continue
        key = (s, e, str(summary))
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    return out


def _normalize_choice(reply: str, overrides: Optional[dict[str, str]] = None) -> str:
    r = (reply or "").strip().lower()
    # Normalize a few common Turkish phrases for deterministic demo UX.
    aliases: dict[str, str] = {
        "evet": "1",
        "tamam": "1",
        "ok": "1",
        "onay": "1",
        "onayla": "1",
        "onaylıyorum": "1",
        "yap": "1",
        "yapalım": "1",
        "yapalim": "1",
        "hayır": "0",
        "hayir": "0",
        "iptal": "0",
        "vazgeç": "0",
        "vazgec": "0",
        "vazgeçtim": "0",
        "vazgectim": "0",
        "cancel": "0",
        "en erken": "2",
        "en erkeni": "2",
        "en erken uygun": "2",
    }
    if overrides and r in overrides:
        return overrides[r]
    return aliases.get(r, r)


def _ask_choice(prompt: str, allowed: set[str], *, overrides: Optional[dict[str, str]] = None) -> str:
    default = "0" if "0" in allowed else next(iter(sorted(allowed)))

    # Non-interactive robustness: if input is piped (heredoc/CI), don't loop and
    # don't spam the prompt. One attempt; invalid/empty/EOF => default.
    if not sys.stdin.isatty():
        try:
            raw = input(prompt)
        except EOFError:
            return default
        if not (raw or "").strip():
            return default
        reply = _normalize_choice(raw, overrides=overrides)
        return reply if reply in allowed else default

    while True:
        try:
            raw = input(prompt)
        except EOFError:
            return default
        if not (raw or "").strip():
            return default
        reply = _normalize_choice(raw, overrides=overrides)
        if reply in allowed:
            return reply


def _ask_confirm(prompt: str) -> bool:
    try:
        reply = input(prompt)
    except EOFError:
        return False
    reply = reply.strip().lower()
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
    now = datetime.now(tz)

    reg = build_planner_registry()

    if args.debug:
        print("[debug] date:", cfg.d.isoformat())
        print("[debug] tz:", cfg.tz_name)
        print("[debug] tzinfo:", str(tz))
        print("[debug] calendar_id:", cfg.calendar_id)
        print("[debug] run_mode:", cfg.run)
        print("[debug] dry_run:", bool(args.dry_run))
        print("[debug] now:", _rfc3339(now))
        print()

    print('USER: "Bu akşam planım var mı?"')
    print("BANTZ: Kontrol etmeme izin verin efendim…")

    # 1) list_events (evening)
    if args.evening:
        window_start = datetime.combine(cfg.d, time(18, 0), tzinfo=tz)
        window_end = datetime.combine(cfg.d + timedelta(days=1), time(0, 0), tzinfo=tz)
        if cfg.d == now.date():
            window_start = max(window_start, now)
        time_min = _rfc3339(window_start)
        time_max = _rfc3339(window_end)
    else:
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
    raw_events = (out1 or {}).get("events") or []
    events = _dedupe_events(raw_events) if isinstance(raw_events, list) else []
    if args.debug:
        print("[debug] list_events count:", len(events) if isinstance(events, list) else "?")

    if not events:
        print("BANTZ: Efendim bu akşam için şu andan sonra bir plan görünmüyor.")
    else:
        starts: list[tuple[datetime, dict[str, Any]]] = []
        for ev in events:
            s = ev.get("start")
            dt = _parse_rfc3339(s, tz) if isinstance(s, str) else None
            if dt is not None:
                starts.append((dt, ev))
        starts.sort(key=lambda x: x[0])

        first_time = _format_hhmm(starts[0][1]["start"]) if starts else _format_hhmm(events[0].get("start", ""))
        first_summary = (starts[0][1].get("summary") or "(no title)") if starts else (events[0].get("summary") or "(no title)")

        if starts:
            mins = int((starts[0][0] - now).total_seconds() // 60)
            if mins >= 0 and mins <= 90:
                print(f"BANTZ: Efendim bu akşam {len(events)} planınız görünüyor. İlk etkinlik {mins} dakika sonra: {first_summary}.")
            else:
                print(f"BANTZ: Efendim bu akşam {len(events)} planınız görünüyor. İlki {first_time} civarı: {first_summary}.")
        else:
            print(f"BANTZ: Efendim bu akşam {len(events)} planınız görünüyor. İlki {first_time} civarı: {first_summary}.")
        print("BANTZ: İsterseniz detaylarını listelerim efendim.")

        if args.debug:
            print("[debug] list_events details:")
            for ev in events:
                s = ev.get("start")
                e = ev.get("end")
                summary = ev.get("summary") or "(no title)"
                if isinstance(s, str) and isinstance(e, str):
                    print(f"- {_format_hhmm(s)}–{_format_hhmm(e)} | {summary}")

    print()
    print('USER: "8\'den önce 2 saat koşu koy"')
    print("BANTZ: Uygun bir boşluk arıyorum efendim…")

    # 2) find_free_slots (until 20:00)
    tool2 = reg.get("calendar.find_free_slots")
    if not tool2 or not tool2.function:
        raise SystemExit("calendar.find_free_slots tool not available")

    # Time-aware: only search from now (or day's start if querying another date) up to 20:00.
    base_start = datetime.combine(cfg.d, time(0, 0), tzinfo=tz)
    base_end = datetime.combine(cfg.d, time(20, 0), tzinfo=tz)
    window_start = base_start
    if cfg.d == now.date():
        window_start = max(base_start, now)
    window_end = base_end

    can_search_before_20 = window_end > window_start

    slots_today: list[dict[str, Any]] = []
    slots_tomorrow: list[dict[str, Any]] = []

    duration_minutes = 120

    if args.debug:
        print("[debug] find_free_slots time_min:", _rfc3339(window_start))
        print("[debug] find_free_slots time_max:", _rfc3339(window_end))
        print("[debug] find_free_slots duration_minutes:", duration_minutes)
        print("[debug] find_free_slots can_search_before_20:", can_search_before_20)
        print()

    params2: dict[str, Any] = {
        "time_min": _rfc3339(window_start),
        "time_max": _rfc3339(window_end),
        "duration_minutes": duration_minutes,
        "suggestions": 3,
        "preferred_start": "07:30",
        "preferred_end": "22:30",
    }
    if cfg.calendar_id:
        params2["calendar_id"] = cfg.calendar_id

    if can_search_before_20:
        _print_tool_call("calendar.find_free_slots", params2)
        out2 = tool2.function(**params2)
        slots = (out2 or {}).get("slots") or []
        slots_today = slots if isinstance(slots, list) else []
    else:
        print("BANTZ: Efendim saat 20:00'yi geçmiş; 20:00'den önce 2 saatlik bir koşu için bugün artık geç kaldık.")
        slots = []
    if args.debug:
        print("[debug] find_free_slots count:", len(slots) if isinstance(slots, list) else "?")
    if not slots:
        duration_desc = "2 saatlik" if duration_minutes == 120 else f"{duration_minutes} dakikalık"
        print(f"BANTZ: Maalesef 20:00'den önce {duration_desc} boşluk bulamadım efendim.")
        print(f"BANTZ: İsterseniz 20:00'den sonra ilk {duration_desc} boşluğu arayayım mı, yoksa yarın için mi bakayım efendim?")
        print("- 1) 20:00'den sonra bak")
        print("- 2) Yarın için bak")
        print("- 3) 60 dakika olsun")
        print("- 0) İptal")
        choice = _ask_choice(
            "USER (seçim): ",
            {"0", "1", "2", "3"},
            overrides={
                "yarın": "2",
                "yarina": "2",
                "yarına": "2",
                "yarın için": "2",
                "yarin icin": "2",
                "sonra": "1",
                "20": "1",
                "20:00": "1",
                "20den sonra": "1",
                "20'den sonra": "1",
                "1 saat": "3",
                "60": "3",
                "60 dk": "3",
                "60 dakika": "3",
            },
        )
        if choice == "0":
            print("BANTZ: İptal ediyorum efendim.")
            return 2

        if choice == "1":
            alt_start = datetime.combine(cfg.d, time(20, 0), tzinfo=tz)
            alt_end = datetime.combine(cfg.d + timedelta(days=1), time(0, 0), tzinfo=tz)
            if cfg.d == now.date():
                alt_start = max(alt_start, now)
            params2_alt = dict(params2)
            params2_alt["time_min"] = _rfc3339(alt_start)
            params2_alt["time_max"] = _rfc3339(alt_end)
            if args.debug:
                print("[debug] find_free_slots (after-20) time_min:", params2_alt["time_min"])
                print("[debug] find_free_slots (after-20) time_max:", params2_alt["time_max"])
            _print_tool_call("calendar.find_free_slots", params2_alt)
            out2_alt = tool2.function(**params2_alt)
            slots = (out2_alt or {}).get("slots") or []
            slots_today = slots if isinstance(slots, list) else []
        elif choice == "2":
            d2 = cfg.d + timedelta(days=1)
            alt_start = datetime.combine(d2, time(7, 30), tzinfo=tz)
            alt_end = datetime.combine(d2, time(20, 0), tzinfo=tz)
            params2_alt = dict(params2)
            params2_alt["time_min"] = _rfc3339(alt_start)
            params2_alt["time_max"] = _rfc3339(alt_end)
            if args.debug:
                print("[debug] find_free_slots (tomorrow) time_min:", params2_alt["time_min"])
                print("[debug] find_free_slots (tomorrow) time_max:", params2_alt["time_max"])
            _print_tool_call("calendar.find_free_slots", params2_alt)
            out2_alt = tool2.function(**params2_alt)
            slots = (out2_alt or {}).get("slots") or []
            slots_tomorrow = slots if isinstance(slots, list) else []
        elif choice == "3":
            duration_minutes = 60
            if can_search_before_20:
                params2_alt = dict(params2)
                params2_alt["duration_minutes"] = 60
                if args.debug:
                    print("[debug] find_free_slots (60min) time_min:", params2_alt["time_min"])
                    print("[debug] find_free_slots (60min) time_max:", params2_alt["time_max"])
                _print_tool_call("calendar.find_free_slots", params2_alt)
                out2_alt = tool2.function(**params2_alt)
                slots = (out2_alt or {}).get("slots") or []
                slots_today = slots if isinstance(slots, list) else []
            else:
                print("BANTZ: Efendim bugün için artık geç; 60 dakikayı yarın için arıyorum.")
                d2 = cfg.d + timedelta(days=1)
                params2_alt = dict(params2)
                params2_alt["time_min"] = _rfc3339(datetime.combine(d2, time(7, 30), tzinfo=tz))
                params2_alt["time_max"] = _rfc3339(datetime.combine(d2, time(22, 30), tzinfo=tz))
                params2_alt["duration_minutes"] = 60
                if args.debug:
                    print("[debug] find_free_slots (tomorrow 60min) time_min:", params2_alt["time_min"])
                    print("[debug] find_free_slots (tomorrow 60min) time_max:", params2_alt["time_max"])
                _print_tool_call("calendar.find_free_slots", params2_alt)
                out2_alt = tool2.function(**params2_alt)
                slots = (out2_alt or {}).get("slots") or []
                slots_tomorrow = slots if isinstance(slots, list) else []

        if not slots:
            duration_desc = "2 saatlik" if duration_minutes == 120 else f"{duration_minutes} dakikalık"
            print(f"BANTZ: Üzgünüm efendim, bu seçenekle de {duration_desc} boşluk bulamadım.")
        else:
            print("BANTZ: Şu boşlukları buldum efendim:")
            for i, sl in enumerate(slots, start=1):
                s = sl.get("start")
                e = sl.get("end")
                if isinstance(s, str) and isinstance(e, str):
                    print(f"  {i}) {_format_hhmm(s)}–{_format_hhmm(e)}")
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

    requested_time = time(15, 45)
    start_dt = datetime.combine(cfg.d, requested_time, tzinfo=tz)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    if cfg.d == now.date() and start_dt < now:
        print("BANTZ: Efendim bugün için bu saat geçti.")

        options: list[str] = ["1) Yarın 15:45 olarak ayarla", "2) Yarın en erken uygun saat"]
        has_slots_today = bool(slots_today)
        if has_slots_today:
            options.append("3) Bugün en erken uygun boşluğu kullan")
        options.append("4) Haftalık tekrar (P1)")
        options.append("0) İptal")

        print("BANTZ: Ne yapmamı istersiniz efendim?")
        for o in options:
            print("-", o)

        allowed = {"0", "1", "2", "4"} | ({"3"} if has_slots_today else set())
        choice = _ask_choice(
            "USER (seçim): ",
            allowed,
            overrides={
                "yarın": "1",
                "yarina": "1",
                "yarına": "1",
                "yarın yap": "1",
                "yarin yap": "1",
                "yarın en erken": "2",
                "yarin en erken": "2",
                "en erken": "3" if has_slots_today else "2",
                "en erkeni": "3" if has_slots_today else "2",
                "haftalık": "4",
                "haftalik": "4",
                "weekly": "4",
            },
        )

        if choice == "0":
            print("BANTZ: İptal ediyorum efendim.")
            return 2

        if choice == "1":
            start_dt = datetime.combine(cfg.d + timedelta(days=1), requested_time, tzinfo=tz)
            end_dt = start_dt + timedelta(minutes=duration_minutes)
        elif choice == "2":
            if not slots_tomorrow:
                d2 = cfg.d + timedelta(days=1)
                params_tomorrow: dict[str, Any] = {
                    "time_min": _rfc3339(datetime.combine(d2, time(7, 30), tzinfo=tz)),
                    "time_max": _rfc3339(datetime.combine(d2, time(22, 30), tzinfo=tz)),
                    "duration_minutes": duration_minutes,
                    "suggestions": 1,
                    "preferred_start": "07:30",
                    "preferred_end": "22:30",
                }
                if cfg.calendar_id:
                    params_tomorrow["calendar_id"] = cfg.calendar_id
                _print_tool_call("calendar.find_free_slots", params_tomorrow)
                out_t = tool2.function(**params_tomorrow)
                slots_tomorrow = (out_t or {}).get("slots") or []

            first = slots_tomorrow[0] if slots_tomorrow and isinstance(slots_tomorrow[0], dict) else None
            s = first.get("start") if first else None
            dt = _parse_rfc3339(s, tz) if isinstance(s, str) else None
            if dt is None:
                print("BANTZ: Üzgünüm efendim, yarın için uygun boşluğu okuyamadım.")
                return 1
            start_dt = dt
            end_dt = start_dt + timedelta(minutes=duration_minutes)
        elif choice == "3" and has_slots_today:
            first = slots_today[0] if isinstance(slots_today[0], dict) else None
            s = first.get("start") if first else None
            dt = _parse_rfc3339(s, tz) if isinstance(s, str) else None
            if dt is None:
                print("BANTZ: Üzgünüm efendim, uygun boşluğu okuyamadım.")
                return 1
            start_dt = dt
            end_dt = start_dt + timedelta(minutes=duration_minutes)
        elif choice == "4":
            print("BANTZ: Efendim, haftalık tekrar ekleme henüz bu demo sürümünde yok.")
            print("BANTZ: İsterseniz yarın olarak ayarlayayım efendim.")
            start_dt = datetime.combine(cfg.d + timedelta(days=1), requested_time, tzinfo=tz)
            end_dt = start_dt + timedelta(minutes=duration_minutes)

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
