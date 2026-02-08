#!/usr/bin/env python3
"""Bantz resume handler — called by systemd after suspend/hibernate (Issue #300).

This script runs the RecoveryManager to re-initialize audio,
check vLLM health, and reset the FSM to a safe state.

Usage::

    python scripts/bantz_resume.py
    python scripts/bantz_resume.py --vllm-url http://localhost:8001/health
    python scripts/bantz_resume.py --timeout 60
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("bantz.resume")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Bantz post-resume recovery")
    parser.add_argument(
        "--vllm-url",
        default="http://127.0.0.1:8001/health",
        help="vLLM health endpoint (default: http://127.0.0.1:8001/health)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Max seconds to wait for vLLM warm-up (default: 30)",
    )
    args = parser.parse_args(argv)

    try:
        from bantz.voice.resume import RecoveryManager

        mgr = RecoveryManager(
            vllm_url=args.vllm_url,
            warmup_timeout_s=args.timeout,
        )
        result = mgr.run()
        print(result.summary())
        return 0 if result.success else 1

    except Exception as exc:
        logger.error("Resume recovery failed: %s", exc, exc_info=True)
        print(f"❌ Recovery hatası: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
