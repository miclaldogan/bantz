from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False))


def _default_gmail_token_path() -> str:
    return os.path.expanduser(os.getenv("BANTZ_GOOGLE_GMAIL_TOKEN_PATH", "~/.config/bantz/google/gmail_token.json"))


def _require_yes(args: argparse.Namespace, *, action: str) -> None:
    if getattr(args, "yes", False):
        return
    raise SystemExit(
        f"Refusing to {action} without --yes. "
        "(This is a safety guard for write operations.)"
    )


def cmd_env(_args: argparse.Namespace) -> int:
    from bantz.google.auth import get_google_auth_config

    cfg = get_google_auth_config()
    out = {
        "client_secret_path": str(cfg.client_secret_path),
        "client_secret_exists": cfg.client_secret_path.exists(),
        "token_path": str(cfg.token_path),
        "token_exists": cfg.token_path.exists(),
        "calendar_id": os.getenv("BANTZ_GOOGLE_CALENDAR_ID") or None,
        "gmail_token_path": _default_gmail_token_path(),
        "env": {
            "BANTZ_GOOGLE_CLIENT_SECRET": os.getenv("BANTZ_GOOGLE_CLIENT_SECRET") or None,
            "BANTZ_GOOGLE_TOKEN_PATH": os.getenv("BANTZ_GOOGLE_TOKEN_PATH") or None,
            "BANTZ_GOOGLE_CALENDAR_ID": os.getenv("BANTZ_GOOGLE_CALENDAR_ID") or None,
            "BANTZ_GOOGLE_GMAIL_TOKEN_PATH": os.getenv("BANTZ_GOOGLE_GMAIL_TOKEN_PATH") or None,
        },
    }
    _print_json(out)
    return 0


def cmd_auth_calendar(args: argparse.Namespace) -> int:
    from bantz.google.auth import get_credentials
    from bantz.google.calendar import READONLY_SCOPES, WRITE_SCOPES

    scopes = WRITE_SCOPES if args.write else READONLY_SCOPES
    creds = get_credentials(
        scopes=scopes,
        client_secret_path=args.client_secret,
        token_path=args.token_path,
    )

    out = {
        "ok": True,
        "scopes": list(scopes),
        "client_secret_path": str(args.client_secret) if args.client_secret else None,
        "token_path": str(args.token_path) if args.token_path else None,
        "granted_scopes": getattr(creds, "scopes", None),
        "note": "Token written (or refreshed) successfully.",
    }
    _print_json(out)
    return 0


def cmd_auth_gmail(args: argparse.Namespace) -> int:
    from bantz.google.auth import get_credentials

    scopes_by_mode = {
        "readonly": ["https://www.googleapis.com/auth/gmail.readonly"],
        "send": ["https://www.googleapis.com/auth/gmail.send"],
        "modify": ["https://www.googleapis.com/auth/gmail.modify"],
    }
    scopes = scopes_by_mode[args.scope]

    token_path = args.token_path or _default_gmail_token_path()
    creds = get_credentials(
        scopes=scopes,
        client_secret_path=args.client_secret,
        token_path=token_path,
    )

    out = {
        "ok": True,
        "scopes": list(scopes),
        "token_path": str(token_path),
        "granted_scopes": getattr(creds, "scopes", None),
        "note": "Gmail token written (or refreshed) successfully.",
    }
    _print_json(out)
    return 0


def cmd_calendar_list(args: argparse.Namespace) -> int:
    from bantz.google.calendar import list_events

    resp = list_events(
        calendar_id=args.calendar_id,
        max_results=int(args.max_results),
        time_min=args.time_min,
        time_max=args.time_max,
        query=args.query,
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 1


def cmd_calendar_free(args: argparse.Namespace) -> int:
    from bantz.google.calendar import find_free_slots

    resp = find_free_slots(
        calendar_id=args.calendar_id,
        time_min=str(args.time_min),
        time_max=str(args.time_max),
        duration_minutes=int(args.duration_minutes),
        suggestions=int(args.suggestions),
        preferred_start=args.preferred_start,
        preferred_end=args.preferred_end,
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 1


def cmd_calendar_create(args: argparse.Namespace) -> int:
    _require_yes(args, action="create an event")

    from bantz.google.calendar import create_event

    resp = create_event(
        calendar_id=args.calendar_id,
        summary=str(args.summary),
        start=str(args.start),
        end=args.end,
        duration_minutes=args.duration_minutes,
        description=args.description,
        location=args.location,
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 1


def cmd_calendar_update(args: argparse.Namespace) -> int:
    _require_yes(args, action="update an event")

    from bantz.google.calendar import update_event

    resp = update_event(
        calendar_id=args.calendar_id,
        event_id=str(args.event_id),
        start=str(args.start),
        end=str(args.end),
        summary=args.summary,
        description=args.description,
        location=args.location,
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 1


def cmd_calendar_delete(args: argparse.Namespace) -> int:
    _require_yes(args, action="delete an event")

    from bantz.google.calendar import delete_event

    resp = delete_event(
        calendar_id=args.calendar_id,
        event_id=str(args.event_id),
    )
    _print_json(resp)
    return 0 if resp.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bantz google",
        description="Google OAuth + Calendar/Gmail utilities for Bantz",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_env = sub.add_parser("env", help="Print resolved Google OAuth config/env")
    p_env.set_defaults(func=cmd_env)

    p_auth = sub.add_parser("auth", help="Run OAuth flows and write token files")
    auth_sub = p_auth.add_subparsers(dest="auth_command", required=True)

    p_auth_cal = auth_sub.add_parser("calendar", help="Create/refresh Calendar token")
    p_auth_cal.add_argument("--write", action="store_true", help="Request write scope (calendar.events)")
    p_auth_cal.add_argument(
        "--client-secret",
        default=None,
        help="Path to client_secret.json (overrides BANTZ_GOOGLE_CLIENT_SECRET)",
    )
    p_auth_cal.add_argument(
        "--token-path",
        default=None,
        help="Path to token.json (overrides BANTZ_GOOGLE_TOKEN_PATH)",
    )
    p_auth_cal.set_defaults(func=cmd_auth_calendar)

    p_auth_gm = auth_sub.add_parser("gmail", help="Create/refresh Gmail token")
    p_auth_gm.add_argument(
        "--scope",
        choices=["readonly", "send", "modify"],
        default="readonly",
        help="Requested Gmail scope",
    )
    p_auth_gm.add_argument(
        "--client-secret",
        default=None,
        help="Path to client_secret.json (overrides BANTZ_GOOGLE_CLIENT_SECRET)",
    )
    p_auth_gm.add_argument(
        "--token-path",
        default=None,
        help="Path to Gmail token (default: ~/.config/bantz/google/gmail_token.json or BANTZ_GOOGLE_GMAIL_TOKEN_PATH)",
    )
    p_auth_gm.set_defaults(func=cmd_auth_gmail)

    p_cal = sub.add_parser("calendar", help="Calendar operations")
    cal_sub = p_cal.add_subparsers(dest="calendar_command", required=True)

    def add_calendar_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--calendar-id",
            default=None,
            help="Calendar ID (overrides BANTZ_GOOGLE_CALENDAR_ID; default is 'primary')",
        )

    p_list = cal_sub.add_parser("list", help="List events")
    add_calendar_common(p_list)
    p_list.add_argument("--max-results", type=int, default=10, help="Max results")
    p_list.add_argument("--time-min", default=None, help="RFC3339 datetime (default: now)")
    p_list.add_argument("--time-max", default=None, help="RFC3339 datetime")
    p_list.add_argument("--query", default=None, help="Full-text search query")
    p_list.set_defaults(func=cmd_calendar_list)

    p_free = cal_sub.add_parser("free", help="Find free slots")
    add_calendar_common(p_free)
    p_free.add_argument("--time-min", required=True, help="RFC3339 datetime")
    p_free.add_argument("--time-max", required=True, help="RFC3339 datetime")
    p_free.add_argument("--duration-minutes", type=int, required=True, help="Slot duration in minutes")
    p_free.add_argument("--suggestions", type=int, default=3, help="Number of suggestions")
    p_free.add_argument("--preferred-start", default=None, help="HH:MM (local in window tz), default 09:00")
    p_free.add_argument("--preferred-end", default=None, help="HH:MM or 24:00, default 18:00")
    p_free.set_defaults(func=cmd_calendar_free)

    p_create = cal_sub.add_parser("create", help="Create an event (write)")
    add_calendar_common(p_create)
    p_create.add_argument("--summary", required=True, help="Event summary/title")
    p_create.add_argument("--start", required=True, help="RFC3339 datetime")
    p_create.add_argument("--end", default=None, help="RFC3339 datetime")
    p_create.add_argument("--duration-minutes", type=int, default=None, help="Used if --end is missing")
    p_create.add_argument("--description", default=None)
    p_create.add_argument("--location", default=None)
    p_create.add_argument("--yes", action="store_true", help="Confirm write operation")
    p_create.set_defaults(func=cmd_calendar_create)

    p_update = cal_sub.add_parser("update", help="Update an event (write)")
    add_calendar_common(p_update)
    p_update.add_argument("--event-id", required=True, help="Google Calendar event id")
    p_update.add_argument("--start", required=True, help="RFC3339 datetime")
    p_update.add_argument("--end", required=True, help="RFC3339 datetime")
    p_update.add_argument("--summary", default=None)
    p_update.add_argument("--description", default=None)
    p_update.add_argument("--location", default=None)
    p_update.add_argument("--yes", action="store_true", help="Confirm write operation")
    p_update.set_defaults(func=cmd_calendar_update)

    p_delete = cal_sub.add_parser("delete", help="Delete an event (write)")
    add_calendar_common(p_delete)
    p_delete.add_argument("--event-id", required=True, help="Google Calendar event id")
    p_delete.add_argument("--yes", action="store_true", help="Confirm write operation")
    p_delete.set_defaults(func=cmd_calendar_delete)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        fn = getattr(args, "func")
    except AttributeError:
        parser.print_help(sys.stderr)
        return 2

    try:
        return int(fn(args))
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        msg = str(e)
        if "dependencies" in msg.lower() and "google" in msg.lower():
            print(f"❌ {e}", file=sys.stderr)
            print("\n💡 Install Google deps: pip install -e '.[calendar]'", file=sys.stderr)
            return 2
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
