"""Bantz Daemon - Background service mode.

Runs Bantz server as a persistent background daemon.
Accepts commands via Unix socket.
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from bantz.server import BantzServer, DEFAULT_SESSION


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    print(f"\n🛑 Signal {signum} received, shutting down...")
    sys.exit(0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bantz-daemon",
        description="Bantz background daemon service",
    )
    parser.add_argument("--session", default=DEFAULT_SESSION, help="Session name")
    parser.add_argument("--policy", default="config/policy.json", help="Policy file")
    parser.add_argument("--log", default="bantz.log.jsonl", help="Log file")
    parser.add_argument(
        "--init-browser",
        action="store_true",
        help="Eagerly initialize Playwright/browser on startup (default: lazy)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="(Deprecated) Kept for compatibility; browser is lazy by default.",
    )

    args = parser.parse_args(argv)

    # Setup signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    print(f"🚀 Bantz Daemon starting...")
    print(f"   Session: {args.session}")
    print(f"   Policy:  {args.policy}")
    print(f"   Log:     {args.log}")

    try:
        server = BantzServer(
            session_name=args.session,
            policy_path=args.policy,
            log_path=args.log,
        )

        # Browser is lazy by default.
        # Opt-in eager init for setups that rely on Playwright being ready immediately.
        if args.init_browser and not args.no_browser:
            print("   Browser: initializing...")
            server._init_browser()
            print("   Browser: ready ✓")

        # Run server (blocking)
        server.run()

    except KeyboardInterrupt:
        print("\n🛑 Interrupted, shutting down...")
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
