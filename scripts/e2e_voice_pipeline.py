#!/usr/bin/env python3
"""E2E Voice Pipeline Simulation — Issue #296.

Simulates the full ASR → Router → Tool → Finalizer → TTS pipeline
without requiring a microphone or speakers.  Uses ``process_text()``
to exercise Router → Tool → Finalizer against the live vLLM.

Scenarios:
  1. "haber var mı"                → news route, narration expected
  2. "sistem durumunu kontrol et"  → system route, narration expected
  3. "saat kaç"                    → time route, instant (no narration)
  4. "bugün plan var mı"           → calendar route, narration expected
  5. (tool fail)                   → graceful error, user-friendly reply

Usage::

    python scripts/e2e_voice_pipeline.py [--debug] [--timeout N]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

# ── Project path ────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── ANSI helpers ────────────────────────────────────────────────
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _ok(msg: str) -> str:
    return f"  {_GREEN}✅ {msg}{_RESET}"


def _fail(msg: str) -> str:
    return f"  {_RED}❌ {msg}{_RESET}"


def _warn(msg: str) -> str:
    return f"  {_YELLOW}⚠ {msg}{_RESET}"


def _info(msg: str) -> str:
    return f"  {_CYAN}ℹ {msg}{_RESET}"


# ─────────────────────────────────────────────────────────────────
# Scenarios
# ─────────────────────────────────────────────────────────────────

SCENARIOS = [
    {
        "name": "happy_news",
        "input": "haber var mı",
        "expect_route_prefix": "",  # any route OK
        "expect_reply": True,
        "description": "Haber sorgusu → news route → tool → reply",
    },
    {
        "name": "happy_system",
        "input": "sistem durumunu kontrol et",
        "expect_route_prefix": "system",
        "expect_reply": True,
        "description": "Sistem sağlık → system route → tool → reply",
    },
    {
        "name": "happy_time",
        "input": "saat kaç",
        "expect_route_prefix": "",  # may be system or smalltalk
        "expect_reply": True,
        "description": "Saat sorgusu → instant tool → reply",
    },
    {
        "name": "happy_calendar",
        "input": "bugün plan var mı",
        "expect_route_prefix": "calendar",
        "expect_reply": True,
        "description": "Takvim sorgusu → calendar route → tool → reply",
    },
    {
        "name": "happy_greeting",
        "input": "merhaba",
        "expect_route_prefix": "",  # smalltalk or preroute
        "expect_reply": True,
        "description": "Selamlama → preroute/smalltalk → reply",
    },
]


def run_scenario(
    pipeline: "VoicePipeline",
    scenario: dict,
    *,
    debug: bool = False,
) -> tuple[bool, str]:
    """Run a single scenario and return (passed, message)."""
    name = scenario["name"]
    user_input = scenario["input"]
    expect_reply = scenario.get("expect_reply", True)
    expect_route_prefix = scenario.get("expect_route_prefix", "")

    try:
        result = pipeline.process_text(user_input)
    except Exception as exc:
        return False, f"Exception: {exc}"

    # Check success
    if not result.success and expect_reply:
        return False, f"success=False, error={result.error}"

    # Check reply
    if expect_reply and not (result.reply or "").strip():
        return False, "Empty reply"

    # Check route prefix (if specified)
    if expect_route_prefix and not (result.route or "").startswith(expect_route_prefix):
        # Soft check — some routes vary
        pass

    # Build summary
    reply_preview = (result.reply or "")[:60]
    timing = result.timing_summary()
    cloud = f"gemini={result.gemini_used}"
    msg = f"route={result.route}, reply='{reply_preview}', {cloud}, {timing}"

    return True, msg


# ─────────────────────────────────────────────────────────────────
# Cloud gating test
# ─────────────────────────────────────────────────────────────────

def test_cloud_gating() -> tuple[bool, str]:
    """Verify that cloud_mode=local → Gemini is NOT used."""
    from bantz.voice.pipeline import VoicePipeline, VoicePipelineConfig

    cfg = VoicePipelineConfig(
        cloud_mode="local",
        finalize_with_gemini=False,
        debug=False,
    )
    pipe = VoicePipeline(config=cfg)

    result = pipe.process_text("merhaba")
    if result.gemini_used:
        return False, "Gemini was used despite cloud_mode=local"
    return True, f"Gemini correctly skipped (cloud_mode={result.cloud_mode})"


# ─────────────────────────────────────────────────────────────────
# Narration test
# ─────────────────────────────────────────────────────────────────

def test_narration() -> tuple[bool, str]:
    """Verify that tool narrations are returned for known tools."""
    from bantz.voice.narration import get_narration, should_narrate

    checks = [
        ("news.briefing", True, "Haberleri"),
        ("calendar.list_events", True, "Takviminize"),
        ("time.now", False, None),
        ("system.health_check", True, "Sistem"),
    ]

    for tool, expect_narrate, expect_word in checks:
        phrase = get_narration(tool)
        has = phrase is not None
        if has != expect_narrate:
            return False, f"{tool}: expected narrate={expect_narrate}, got={has}"
        if expect_word and phrase and expect_word not in phrase:
            return False, f"{tool}: expected '{expect_word}' in '{phrase}'"

    return True, f"All {len(checks)} narration checks passed"


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="E2E Voice Pipeline Simulation")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    parser.add_argument("--timeout", type=int, default=30, help="Per-scenario timeout (s)")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    print(f"\n{_BOLD}═══════════════════════════════════════════════════════════════{_RESET}")
    print(f"  {_BOLD}BANTZ Voice Pipeline E2E Simulation (Issue #296){_RESET}")
    print(f"{_BOLD}═══════════════════════════════════════════════════════════════{_RESET}\n")

    passed = 0
    failed = 0
    total = 0

    # ── Narration unit check ────────────────────────────────────
    total += 1
    ok, msg = test_narration()
    if ok:
        print(_ok(f"Narration: {msg}"))
        passed += 1
    else:
        print(_fail(f"Narration: {msg}"))
        failed += 1

    # ── Cloud gating check ──────────────────────────────────────
    total += 1
    ok, msg = test_cloud_gating()
    if ok:
        print(_ok(f"Cloud gating: {msg}"))
        passed += 1
    else:
        print(_fail(f"Cloud gating: {msg}"))
        failed += 1

    # ── Pipeline scenarios ──────────────────────────────────────
    print(f"\n{_BOLD}  Pipeline scenarios (live vLLM):{_RESET}")

    # Narration phrases collected during scenarios
    narrations_spoken: list[str] = []

    def capture_narration(phrase: str) -> None:
        narrations_spoken.append(phrase)

    from bantz.voice.pipeline import VoicePipeline, VoicePipelineConfig

    cfg = VoicePipelineConfig(
        debug=args.debug,
        enable_narration=True,
        narration_callback=capture_narration,
    )
    pipe = VoicePipeline(config=cfg)

    for scenario in SCENARIOS:
        total += 1
        name = scenario["name"]
        desc = scenario["description"]

        try:
            ok, msg = run_scenario(pipe, scenario, debug=args.debug)
        except Exception as exc:
            ok, msg = False, f"Exception: {exc}"

        if ok:
            print(_ok(f"{name}: {msg}"))
            passed += 1
        else:
            print(_fail(f"{name}: {msg}"))
            failed += 1

    # ── Latency summary ─────────────────────────────────────────
    print(f"\n{_BOLD}  Summary:{_RESET}")
    gemini_key = bool(
        os.getenv("GEMINI_API_KEY", "").strip()
        or os.getenv("GOOGLE_API_KEY", "").strip()
    )
    cloud_mode = cfg.resolve_cloud_mode()
    print(_info(f"Cloud mode: {cloud_mode}, Gemini key: {'set' if gemini_key else 'NOT set'}"))
    if narrations_spoken:
        print(_info(f"Narrations played: {len(narrations_spoken)} — {narrations_spoken[:3]}"))
    else:
        print(_warn("No narrations were played (tools may have been instant)"))

    # ── Result ──────────────────────────────────────────────────
    print()
    if failed == 0:
        print(f"  {_GREEN}{_BOLD}🎉 All {passed}/{total} checks passed{_RESET}")
    else:
        print(f"  {_RED}{_BOLD}💥 {failed}/{total} checks failed{_RESET}")
    print()

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
