#!/usr/bin/env python3
"""Replay a JSON trace scenario and compare route/tool outputs (Issue #664).

Usage:
  python scripts/replay_scenario.py --trace artifacts/logs/traces/trace_0001_...json --mode live
  python scripts/replay_scenario.py --trace tests/golden/sample_trace.json --mode echo

Modes:
  echo  - do not execute; use expected trace as actual (for CI sanity)
  live  - run real runtime (requires vLLM/Gemini or local env)
  mock  - simple heuristic routing (no tools)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bantz.brain.trace_exporter import compare_traces


def _load_trace_file(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return [raw]
    return []


def _mock_plan(user_input: str) -> dict[str, Any]:
    t = (user_input or "").lower()
    if any(w in t for w in ["takvim", "etkinlik", "randevu", "toplantı", "yarın", "bugün"]):
        return {"route": "calendar", "tools": ["calendar.list_events"]}
    if any(w in t for w in ["mail", "e-posta", "email", "inbox"]):
        return {"route": "gmail", "tools": ["gmail.list_messages"]}
    if any(w in t for w in ["saat", "tarih", "sistem", "cpu"]):
        return {"route": "system", "tools": ["time.now"]}
    return {"route": "smalltalk", "tools": []}


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay scenario trace and compare route/tools")
    parser.add_argument("--trace", required=True, help="Path to trace JSON file")
    parser.add_argument("--mode", choices=["echo", "live", "mock"], default="echo")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of turns")
    parser.add_argument("--json", action="store_true", help="Output JSON diff")
    args = parser.parse_args()

    trace_path = Path(args.trace)
    turns = _load_trace_file(trace_path)
    if args.limit is not None:
        turns = turns[: args.limit]

    if not turns:
        print("No turns found in trace file.")
        return 1

    runtime = None
    runtime_state = None

    if args.mode == "live":
        from bantz.brain.runtime_factory import create_runtime
        runtime = create_runtime(debug=False)
        runtime_state = None

    diffs = []
    for idx, turn in enumerate(turns, start=1):
        expected = {
            "route": turn.get("route"),
            "tools": turn.get("tools", []),
        }

        if args.mode == "echo":
            actual = expected
        elif args.mode == "mock":
            plan = _mock_plan(turn.get("user_input") or "")
            actual = {"route": plan["route"], "tools": [{"name": t} for t in plan["tools"]]}
        else:
            user_input = turn.get("user_input") or ""
            output, runtime_state = runtime.process_turn(user_input, runtime_state)
            actual = {"route": output.route, "tools": [{"name": t} for t in (output.tool_plan or [])]}

        diff = compare_traces(expected, actual)
        if diff:
            diffs.append({"turn": idx, "diff": diff, "user_input": turn.get("user_input")})

    if args.json:
        print(json.dumps({"diffs": diffs, "total": len(diffs)}, indent=2, ensure_ascii=False))
    else:
        if not diffs:
            print("✅ Replay OK — no diffs")
        else:
            print(f"❌ Replay diffs: {len(diffs)}")
            for d in diffs:
                print(f"Turn {d['turn']}: {d['diff']}")

    return 0 if not diffs else 2


if __name__ == "__main__":
    raise SystemExit(main())
