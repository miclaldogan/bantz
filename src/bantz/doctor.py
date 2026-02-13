"""bantz doctor — system health diagnostics (Issue #1223).

Checks:
- Python version and key dependencies
- Environment variables (.env / BANTZ_ENV_FILE)
- OAuth credentials (Google token existence + validity)
- LLM endpoint reachability (vLLM / Ollama)
- Tool registry consistency
- Dangerous mode warnings

Each check returns a :class:`CheckResult` and the overall status is
printed with actionable suggestions.

Usage::

    $ bantz doctor
    $ python -m bantz.cli doctor
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["run_doctor", "CheckResult"]


@dataclass
class CheckResult:
    """Outcome of a single diagnostic check."""

    name: str
    status: str        # "ok" | "warn" | "fail"
    message: str = ""
    action: str = ""   # Suggested fix (empty if ok)

    @property
    def icon(self) -> str:
        return {"ok": "✓", "warn": "⚠", "fail": "✗"}.get(self.status, "?")


# ============================================================================
# Individual checks
# ============================================================================

def _check_python_version() -> CheckResult:
    v = sys.version_info
    if v >= (3, 10):
        return CheckResult("Python version", "ok", f"Python {v.major}.{v.minor}.{v.micro}")
    return CheckResult(
        "Python version", "fail",
        f"Python {v.major}.{v.minor} — 3.10+ required",
        action="Install Python 3.10 or later",
    )


def _check_key_dependencies() -> List[CheckResult]:
    results = []
    deps = [
        ("torch", "PyTorch"),
        ("transformers", "Transformers"),
        ("google.auth", "Google Auth"),
        ("googleapiclient", "Google API Client"),
    ]
    for module, name in deps:
        try:
            importlib.import_module(module)
            results.append(CheckResult(name, "ok", "installed"))
        except ImportError:
            results.append(CheckResult(
                name, "warn", "not installed",
                action=f"pip install {module.split('.')[0]}",
            ))
    return results


def _check_env_file() -> CheckResult:
    env_file = os.getenv("BANTZ_ENV_FILE", ".env")
    if Path(env_file).exists():
        return CheckResult("Env file", "ok", f"{env_file} found")
    return CheckResult(
        "Env file", "warn",
        f"{env_file} not found",
        action="Copy config/bantz-env.example to .env and fill in secrets",
    )


def _check_env_vars() -> List[CheckResult]:
    results = []
    critical = [
        ("BANTZ_LLM_BACKEND", "LLM backend"),
    ]
    optional = [
        ("BANTZ_VLLM_URL", "vLLM URL"),
        ("GOOGLE_APPLICATION_CREDENTIALS", "Google credentials"),
        ("BANTZ_BRIDGE_ENABLED", "Language bridge"),
    ]
    for var, label in critical:
        val = os.getenv(var)
        if val:
            results.append(CheckResult(f"Env: {label}", "ok", f"{var}={val[:20]}…" if len(val or "") > 20 else f"{var}={val}"))
        else:
            results.append(CheckResult(
                f"Env: {label}", "warn", f"{var} not set",
                action=f"Set {var} in .env",
            ))
    for var, label in optional:
        val = os.getenv(var)
        if val:
            results.append(CheckResult(f"Env: {label}", "ok", "set"))
    return results


def _check_google_token() -> CheckResult:
    token_path = Path.home() / ".config" / "bantz" / "token.json"
    alt_path = Path("token.json")
    for p in (token_path, alt_path):
        if p.exists():
            try:
                data = json.loads(p.read_text())
                has_refresh = bool(data.get("refresh_token"))
                if has_refresh:
                    return CheckResult("Google OAuth", "ok", f"Token at {p} (has refresh_token)")
                return CheckResult(
                    "Google OAuth", "warn",
                    f"Token at {p} — no refresh_token",
                    action="Re-run: bantz google auth",
                )
            except (json.JSONDecodeError, OSError):
                return CheckResult(
                    "Google OAuth", "fail", f"Corrupted token at {p}",
                    action="Delete and re-auth: bantz google auth",
                )
    return CheckResult(
        "Google OAuth", "warn",
        "No token.json found",
        action="Run: bantz google auth",
    )


def _check_llm_endpoint() -> CheckResult:
    vllm_url = os.getenv("BANTZ_VLLM_URL") or os.getenv("VLLM_URL")
    if not vllm_url:
        return CheckResult(
            "LLM endpoint", "warn",
            "No vLLM/Ollama URL configured",
            action="Set BANTZ_VLLM_URL in .env",
        )
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{vllm_url.rstrip('/')}/health",
            method="GET",
        )
        req.add_header("User-Agent", "bantz-doctor/1.0")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return CheckResult("LLM endpoint", "ok", f"{vllm_url} reachable")
    except Exception as exc:
        return CheckResult(
            "LLM endpoint", "fail",
            f"{vllm_url} unreachable: {exc}",
            action="Check vLLM/Ollama is running",
        )
    return CheckResult(
        "LLM endpoint", "warn",
        f"{vllm_url} — unexpected response",
        action="Verify endpoint manually",
    )


def _check_tool_registry() -> CheckResult:
    try:
        from bantz.tools.metadata import load_policy_json
        registry, _, _ = load_policy_json()
        return CheckResult(
            "Tool registry", "ok", f"{len(registry)} tools in policy.json",
        )
    except Exception as exc:
        return CheckResult(
            "Tool registry", "fail", f"Load failed: {exc}",
            action="Check config/policy.json",
        )


def _check_dangerous_mode() -> CheckResult:
    dangerous = os.getenv("BANTZ_DANGEROUS_MODE", "").strip().lower()
    if dangerous in ("1", "true", "yes"):
        return CheckResult(
            "Dangerous mode", "warn",
            "BANTZ_DANGEROUS_MODE=true — safety guards disabled!",
            action="Unset BANTZ_DANGEROUS_MODE for production",
        )
    return CheckResult("Dangerous mode", "ok", "disabled (safe)")


# ============================================================================
# Run all checks
# ============================================================================

def run_doctor(*, verbose: bool = False) -> int:
    """Run all diagnostic checks and print results.

    Returns exit code: 0 if all ok/warn, 1 if any fail.
    """
    checks: List[CheckResult] = []

    checks.append(_check_python_version())
    checks.extend(_check_key_dependencies())
    checks.append(_check_env_file())
    checks.extend(_check_env_vars())
    checks.append(_check_google_token())
    checks.append(_check_llm_endpoint())
    checks.append(_check_tool_registry())
    checks.append(_check_dangerous_mode())

    # Print results
    print("\n╔══════════════════════════════════════╗")
    print("║        🏥 Bantz Doctor Report        ║")
    print("╚══════════════════════════════════════╝\n")

    fail_count = 0
    warn_count = 0
    ok_count = 0

    for check in checks:
        status_color = {
            "ok": "\033[32m",     # green
            "warn": "\033[33m",   # yellow
            "fail": "\033[31m",   # red
        }.get(check.status, "")
        reset = "\033[0m"

        print(f"  {status_color}{check.icon}{reset} {check.name}: {check.message}")
        if check.action and (verbose or check.status != "ok"):
            print(f"    → {check.action}")

        if check.status == "fail":
            fail_count += 1
        elif check.status == "warn":
            warn_count += 1
        else:
            ok_count += 1

    print(f"\n  Summary: {ok_count} ok, {warn_count} warnings, {fail_count} failures")

    if fail_count:
        print("\n  ❌ Some checks failed. Fix the issues above and re-run: bantz doctor")
        return 1
    if warn_count:
        print("\n  ⚠️  Some warnings. Review and fix if needed.")
    else:
        print("\n  ✅ All checks passed!")
    return 0
