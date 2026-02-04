#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys

from bantz.google.gmail import gmail_get_message, gmail_list_messages
from bantz.google.gmail_auth import GMAIL_READONLY_SCOPES, authenticate_gmail


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Smoke test: list latest Gmail messages and read one.")
    p.add_argument("--max", type=int, default=5, help="Max messages to list (default: 5)")
    p.add_argument("--unread-only", action="store_true", help="List only unread messages")
    p.add_argument("--expand-thread", action="store_true", help="Expand the thread when reading the first message")
    p.add_argument(
        "--secret",
        default=None,
        help="Override client secret path (e.g. ~/.config/bantz/google/client_secret.json)",
    )
    p.add_argument(
        "--token",
        default=None,
        help="Override token path (e.g. ~/.config/bantz/google/token.json)",
    )

    args = p.parse_args(argv)

    try:
        service = authenticate_gmail(scopes=GMAIL_READONLY_SCOPES, secret_path=args.secret, token_path=args.token)
    except Exception as e:
        print(f"[AUTH ERROR] {e}", file=sys.stderr)
        return 2

    out = gmail_list_messages(max_results=args.max, unread_only=bool(args.unread_only), service=service)
    print("\n=== gmail.list_messages ===")
    print(json.dumps(out, ensure_ascii=False, indent=2)[:5000])

    if not out.get("ok"):
        return 3

    msgs = out.get("messages") or []
    if not msgs:
        print("No messages returned.")
        return 0

    first_id = msgs[0].get("id")
    if not first_id:
        print("First message has no id.")
        return 4

    detail = gmail_get_message(
        message_id=str(first_id),
        expand_thread=bool(args.expand_thread),
        service=service,
    )

    print("\n=== gmail.get_message (first) ===")
    print(json.dumps(detail, ensure_ascii=False, indent=2)[:5000])

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
