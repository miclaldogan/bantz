#!/usr/bin/env python3
"""Boot-to-ready smoke test (Issue #305).

Validates that the BANTZ system is healthy and ready to serve:

1. vLLM endpoint reachable + model loaded
2. Gemini finalizer key present (or 3B fallback warning)
3. ToolRegistry loads with expected tools
4. Runtime factory (create_runtime) succeeds
5. Single turn ("saat kaç?") → success with valid output

Usage::

    python scripts/smoke_boot_ready.py
    python scripts/smoke_boot_ready.py --debug
    python scripts/smoke_boot_ready.py --timeout 10

Exit code 0 = all checks passed.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

# ── Ensure project root on path ──────────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if os.path.join(_PROJECT_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
if os.path.join(_PROJECT_ROOT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts"))

logger = logging.getLogger("bantz.smoke")

# ── ANSI helpers ─────────────────────────────────────────────────────
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    elapsed_ms: float = 0.0
    hint: str = ""


def _ok(name: str, msg: str, elapsed_ms: float = 0.0) -> CheckResult:
    return CheckResult(name=name, passed=True, message=msg, elapsed_ms=elapsed_ms)


def _fail(name: str, msg: str, hint: str = "", elapsed_ms: float = 0.0) -> CheckResult:
    return CheckResult(name=name, passed=False, message=msg, hint=hint, elapsed_ms=elapsed_ms)


# =====================================================================
# 1. vLLM Health Check
# =====================================================================
def check_vllm(timeout: float = 5.0) -> CheckResult:
    """Check that vLLM endpoint is reachable and has a model loaded."""
    vllm_url = os.getenv("BANTZ_VLLM_URL", "http://localhost:8001").rstrip("/")
    url = f"{vllm_url}/v1/models"

    t0 = time.perf_counter()
    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = (time.perf_counter() - t0) * 1000
            body = json.loads(resp.read().decode())

        items = body.get("data") or []
        if not items:
            return _fail(
                "vllm_health",
                f"vLLM reachable but no models loaded at {url}",
                hint="Check vLLM logs: docker logs bantz-vllm",
                elapsed_ms=elapsed,
            )

        model_id = items[0].get("id", "unknown")
        return _ok(
            "vllm_health",
            f"vLLM ready — model={model_id} ({elapsed:.0f}ms)",
            elapsed_ms=elapsed,
        )

    except urllib.error.URLError as e:
        elapsed = (time.perf_counter() - t0) * 1000
        return _fail(
            "vllm_health",
            f"vLLM not reachable at {url}: {e.reason}",
            hint="Start vLLM: ./scripts/vllm/start_3b.sh",
            elapsed_ms=elapsed,
        )
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        return _fail(
            "vllm_health",
            f"vLLM check error: {e}",
            hint="Check BANTZ_VLLM_URL env var",
            elapsed_ms=elapsed,
        )


# =====================================================================
# 2. Gemini Finalizer Check
# =====================================================================
def check_gemini_key() -> CheckResult:
    """Check if Gemini API key is configured."""
    for key_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "BANTZ_GEMINI_API_KEY"):
        val = os.getenv(key_name, "").strip()
        if val:
            masked = val[:4] + "..." + val[-4:] if len(val) > 8 else "****"
            model = os.getenv("BANTZ_GEMINI_MODEL", "gemini-1.5-flash")
            return _ok(
                "gemini_key",
                f"Finalizer: {model} ✓ (Gemini via {key_name}={masked})",
            )

    return CheckResult(
        name="gemini_key",
        passed=True,  # Not a hard failure — 3B fallback works
        message="Finalizer: 3B ⚠ (GEMINI_API_KEY not set — quality may be degraded)",
        hint="Set GEMINI_API_KEY for better response quality",
    )


# =====================================================================
# 3. ToolRegistry Load
# =====================================================================
def check_tool_registry() -> CheckResult:
    """Verify that ToolRegistry loads with expected core tools."""
    t0 = time.perf_counter()
    try:
        from terminal_jarvis import _build_registry

        reg = _build_registry()
        elapsed = (time.perf_counter() - t0) * 1000

        tool_names = set()
        if hasattr(reg, "_tools"):
            tool_names = set(reg._tools.keys())
        elif hasattr(reg, "tools"):
            tool_names = set(reg.tools.keys())
        elif hasattr(reg, "list_tools"):
            tool_names = {t.name for t in reg.list_tools()}

        # Minimum expected tools
        critical_tools = {"time.now", "calendar.list_events"}
        missing = critical_tools - tool_names

        if missing:
            return _fail(
                "tool_registry",
                f"ToolRegistry loaded ({len(tool_names)} tools) but missing: {missing}",
                hint="Check terminal_jarvis._build_registry()",
                elapsed_ms=elapsed,
            )

        return _ok(
            "tool_registry",
            f"ToolRegistry: {len(tool_names)} tools loaded ({elapsed:.0f}ms)",
            elapsed_ms=elapsed,
        )

    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        return _fail(
            "tool_registry",
            f"ToolRegistry load failed: {e}",
            hint="Check terminal_jarvis._build_registry() for import errors",
            elapsed_ms=elapsed,
        )


# =====================================================================
# 4. Runtime Factory
# =====================================================================
def check_runtime_factory() -> CheckResult:
    """Verify that create_runtime() succeeds."""
    t0 = time.perf_counter()
    try:
        from bantz.brain.runtime_factory import create_runtime

        runtime = create_runtime()
        elapsed = (time.perf_counter() - t0) * 1000

        finalizer = "Gemini" if runtime.finalizer_is_gemini else "3B"
        return _ok(
            "runtime_factory",
            f"create_runtime() ✓ — router={runtime.router_model}, finalizer={finalizer} ({elapsed:.0f}ms)",
            elapsed_ms=elapsed,
        )

    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        return _fail(
            "runtime_factory",
            f"create_runtime() failed: {e}",
            hint="Check env vars: BANTZ_VLLM_URL, BANTZ_VLLM_MODEL",
            elapsed_ms=elapsed,
        )


# =====================================================================
# 5. Single Turn Smoke ("saat kaç?")
# =====================================================================
def check_single_turn(timeout: float = 30.0) -> CheckResult:
    """Run a single turn through the brain and verify output."""
    t0 = time.perf_counter()
    try:
        from bantz.brain.runtime_factory import create_runtime
        from bantz.brain.orchestrator_state import OrchestratorState

        runtime = create_runtime()
        state = OrchestratorState()

        output, new_state = runtime.process_turn("saat kaç?", state)
        elapsed = (time.perf_counter() - t0) * 1000

        # Validate output
        route = getattr(output, "route", None) or "unknown"
        reply = str(getattr(output, "assistant_reply", "") or "").strip()
        finalizer_model = getattr(output, "finalizer_model", "") or ""

        details = [f"route={route}"]
        if reply:
            details.append(f"reply={reply[:60]}{'…' if len(reply) > 60 else ''}")
        if finalizer_model:
            details.append(f"finalizer={finalizer_model}")

        if not reply:
            # Check ask_user path
            question = str(getattr(output, "question", "") or "").strip()
            if question:
                details.append(f"question={question[:60]}")
                reply = question

        if route in ("system", "time", "unknown") or reply:
            return _ok(
                "single_turn",
                f"Turn ✓ — {', '.join(details)} ({elapsed:.0f}ms)",
                elapsed_ms=elapsed,
            )
        else:
            return _fail(
                "single_turn",
                f"Turn returned unexpected route: {route} ({elapsed:.0f}ms)",
                hint=f"Output: {details}",
                elapsed_ms=elapsed,
            )

    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        return _fail(
            "single_turn",
            f"Turn failed: {e}",
            hint="Is vLLM running? Check 'curl http://localhost:8001/v1/models'",
            elapsed_ms=elapsed,
        )


# =====================================================================
# 6. Systemd Services (optional)
# =====================================================================
def check_systemd_services() -> list[CheckResult]:
    """Check optional systemd user services (non-fatal)."""
    import subprocess

    results = []
    for svc in ("bantz-core", "bantz-voice"):
        try:
            proc = subprocess.run(
                ["systemctl", "--user", "is-active", svc],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if proc.returncode == 0:
                results.append(_ok(f"systemd:{svc}", f"{svc}: active"))
            else:
                results.append(CheckResult(
                    name=f"systemd:{svc}",
                    passed=True,  # Not a hard failure
                    message=f"{svc}: not active (optional)",
                    hint=f"systemctl --user start {svc}",
                ))
        except FileNotFoundError:
            results.append(CheckResult(
                name=f"systemd:{svc}",
                passed=True,
                message=f"{svc}: systemctl not found (skipped)",
            ))
        except Exception as e:
            results.append(CheckResult(
                name=f"systemd:{svc}",
                passed=True,
                message=f"{svc}: check error (skipped): {e}",
            ))

    return results


# =====================================================================
# Runner
# =====================================================================
def run_smoke(
    *,
    timeout: float = 10.0,
    include_turn: bool = True,
    include_systemd: bool = True,
    debug: bool = False,
) -> int:
    """Run all smoke checks and print a report.

    Returns exit code: 0 = all pass, 1 = hard failure.
    """
    boot_t0 = time.perf_counter()

    print(f"\n{BOLD}{'═' * 60}{RESET}")
    print(f"{BOLD}  🚀 BANTZ Boot-to-Ready Smoke Test{RESET}")
    print(f"{BOLD}{'═' * 60}{RESET}\n")

    results: list[CheckResult] = []

    # Core checks
    checks = [
        ("vLLM Endpoint", lambda: check_vllm(timeout=timeout)),
        ("Gemini Key", check_gemini_key),
        ("Tool Registry", check_tool_registry),
        ("Runtime Factory", check_runtime_factory),
    ]

    if include_turn:
        checks.append(("Single Turn", lambda: check_single_turn(timeout=timeout * 3)))

    for label, check_fn in checks:
        print(f"  {DIM}checking {label}...{RESET}", end="", flush=True)
        result = check_fn()
        results.append(result)
        _print_result(result)

    # Optional systemd checks
    if include_systemd:
        print(f"\n  {DIM}── optional: systemd services ──{RESET}")
        for result in check_systemd_services():
            results.append(result)
            _print_result(result, indent=2)

    # Summary
    boot_elapsed = (time.perf_counter() - boot_t0) * 1000
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    total = len(results)

    print(f"\n{BOLD}{'─' * 60}{RESET}")
    if failed == 0:
        print(f"  {GREEN}{BOLD}🎉 All {passed}/{total} checks passed ({boot_elapsed:.0f}ms){RESET}")
    else:
        print(f"  {RED}{BOLD}❌ {failed}/{total} checks FAILED ({boot_elapsed:.0f}ms){RESET}")
        for r in results:
            if not r.passed:
                print(f"     {RED}• {r.name}: {r.message}{RESET}")
                if r.hint:
                    print(f"       {DIM}Hint: {r.hint}{RESET}")

    print(f"{BOLD}{'─' * 60}{RESET}\n")

    # Debug trace
    if debug:
        print(f"  {CYAN}[debug] Detailed results:{RESET}")
        for r in results:
            status = f"{GREEN}PASS{RESET}" if r.passed else f"{RED}FAIL{RESET}"
            ms = f" ({r.elapsed_ms:.0f}ms)" if r.elapsed_ms else ""
            print(f"    {status} {r.name}{ms}: {r.message}")
            if r.hint:
                print(f"         {DIM}→ {r.hint}{RESET}")
        print()

    return 0 if failed == 0 else 1


def _print_result(result: CheckResult, indent: int = 0) -> None:
    pad = "  " * indent
    if result.passed:
        if "⚠" in result.message:
            icon = f"{YELLOW}⚠{RESET}"
        else:
            icon = f"{GREEN}✅{RESET}"
    else:
        icon = f"{RED}❌{RESET}"

    ms = f" {DIM}({result.elapsed_ms:.0f}ms){RESET}" if result.elapsed_ms else ""
    print(f"\r  {pad}{icon} {result.message}{ms}")

    if not result.passed and result.hint:
        print(f"  {pad}   {DIM}Hint: {result.hint}{RESET}")


# =====================================================================
# CLI
# =====================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="BANTZ boot-to-ready smoke test (Issue #305)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print detailed debug trace",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Timeout in seconds for network checks (default: 10)",
    )
    parser.add_argument(
        "--no-turn",
        action="store_true",
        help="Skip single-turn test (faster, for CI/health only)",
    )
    parser.add_argument(
        "--no-systemd",
        action="store_true",
        help="Skip systemd service checks",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )

    return run_smoke(
        timeout=args.timeout,
        include_turn=not args.no_turn,
        include_systemd=not args.no_systemd,
        debug=args.debug,
    )


if __name__ == "__main__":
    sys.exit(main())
