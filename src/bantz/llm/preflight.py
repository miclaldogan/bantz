"""LLM warmup pipeline — vLLM ready gate + Gemini preflight (Issue #289).

Ensures LLM backends are ready before voice service starts active listening.
Writes a readiness file (~/.cache/bantz/ready.json) that voice service polls.

Usage::

    from bantz.llm.preflight import run_warmup, is_ready, WarmupResult
    result = run_warmup()
    if result.ready:
        print("LLM backends ready!")
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = [
    "WarmupResult",
    "BackendStatus",
    "run_warmup",
    "is_ready",
    "check_vllm_health",
    "warmup_vllm",
    "check_gemini_preflight",
    "READY_FILE",
]

READY_FILE = Path(os.getenv(
    "BANTZ_READY_FILE",
    os.path.expanduser("~/.cache/bantz/ready.json"),
))


@dataclass
class BackendStatus:
    """Status of a single LLM backend."""

    status: str = "unknown"  # ready, error, skipped
    model: str = ""
    warmup_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class WarmupResult:
    """Complete warmup pipeline result."""

    ready: bool = False
    timestamp: str = ""
    backends: dict = field(default_factory=dict)
    boot_duration_ms: float = 0.0


# ─────────────────────────────────────────────────────────────────
# vLLM health + warmup
# ─────────────────────────────────────────────────────────────────


def check_vllm_health(
    url: str = "",
    timeout: float = 30.0,
    retry_interval: float = 2.0,
) -> BackendStatus:
    """Check vLLM /v1/models endpoint until ready or timeout.

    Parameters
    ----------
    url:
        vLLM base URL. Defaults to BANTZ_VLLM_URL env var.
    timeout:
        Max seconds to wait.
    retry_interval:
        Seconds between retries.
    """
    import requests  # type: ignore[import-untyped]

    base = url or os.getenv("BANTZ_VLLM_URL", "http://localhost:8001")
    endpoint = f"{base}/v1/models"
    deadline = time.monotonic() + timeout

    logger.debug("[warmup] checking vLLM health at %s", endpoint)

    while time.monotonic() < deadline:
        try:
            resp = requests.get(endpoint, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                model_id = models[0]["id"] if models else "unknown"
                logger.debug("[warmup] vLLM healthy, model=%s", model_id)
                return BackendStatus(status="ready", model=model_id)
        except Exception as exc:
            logger.debug("[warmup] vLLM not ready: %s", exc)
        time.sleep(retry_interval)

    return BackendStatus(status="error", error="vLLM health check timeout")


def warmup_vllm(
    url: str = "",
    timeout: float = 10.0,
) -> BackendStatus:
    """Send a tiny warmup request to vLLM to prime the model cache.

    Parameters
    ----------
    url:
        vLLM base URL.
    timeout:
        Request timeout in seconds.
    """
    import requests  # type: ignore[import-untyped]

    base = url or os.getenv("BANTZ_VLLM_URL", "http://localhost:8001")
    endpoint = f"{base}/v1/chat/completions"
    model = os.getenv("BANTZ_VLLM_MODEL", "Qwen/Qwen2.5-3B-Instruct-AWQ")

    logger.debug("[warmup] sending warmup request to vLLM")
    t0 = time.monotonic()

    try:
        resp = requests.post(
            endpoint,
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Merhaba"}],
                "max_tokens": 5,
                "temperature": 0.0,
            },
            timeout=timeout,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000

        if resp.status_code == 200:
            logger.debug("[warmup] vLLM warmup OK in %.0fms", elapsed_ms)
            return BackendStatus(status="ready", model=model, warmup_ms=elapsed_ms)

        return BackendStatus(
            status="error",
            model=model,
            error=f"HTTP {resp.status_code}",
        )
    except Exception as exc:
        elapsed_ms = (time.monotonic() - t0) * 1000
        return BackendStatus(
            status="error",
            model=model,
            warmup_ms=elapsed_ms,
            error=str(exc),
        )


# ─────────────────────────────────────────────────────────────────
# Gemini preflight
# ─────────────────────────────────────────────────────────────────


def check_gemini_preflight() -> BackendStatus:
    """Validate Gemini API key and basic connectivity.

    Skipped if GEMINI_API_KEY not set or cloud mode disabled.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    cloud_enabled = os.getenv("BANTZ_CLOUD_ENABLED", "false").lower() in {
        "1", "true", "yes",
    }

    if not api_key or not cloud_enabled:
        logger.debug("[warmup] Gemini skipped (no key or cloud disabled)")
        return BackendStatus(status="skipped")

    model = os.getenv("BANTZ_GEMINI_MODEL", "gemini-1.5-flash")
    logger.debug("[warmup] checking Gemini preflight for %s", model)

    try:
        import requests  # type: ignore[import-untyped]

        # Simple models list check
        resp = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
            timeout=10,
        )
        if resp.status_code == 200:
            logger.debug("[warmup] Gemini preflight OK")
            return BackendStatus(status="ready", model=model)

        return BackendStatus(
            status="error",
            model=model,
            error=f"HTTP {resp.status_code}",
        )
    except Exception as exc:
        return BackendStatus(status="error", model=model, error=str(exc))


# ─────────────────────────────────────────────────────────────────
# Ready file
# ─────────────────────────────────────────────────────────────────


def _write_ready(result: WarmupResult) -> None:
    """Write readiness file to disk."""
    READY_FILE.parent.mkdir(parents=True, exist_ok=True)
    READY_FILE.write_text(json.dumps(asdict(result), indent=2, default=str))
    logger.debug("[warmup] wrote ready file: %s", READY_FILE)


def is_ready() -> bool:
    """Check if the readiness file exists and indicates ready.

    Voice service polls this to know when LLM backends are available.
    """
    try:
        if not READY_FILE.exists():
            return False
        data = json.loads(READY_FILE.read_text())
        return data.get("ready", False)
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────
# Main warmup pipeline
# ─────────────────────────────────────────────────────────────────


def run_warmup(
    vllm_url: str = "",
    vllm_timeout: float = 30.0,
) -> WarmupResult:
    """Execute the full warmup pipeline.

    1. vLLM healthcheck (GET /v1/models) — retry until timeout
    2. vLLM warmup (POST tiny chat completion)
    3. Gemini preflight (if configured)
    4. Write ready.json

    Returns
    -------
    WarmupResult
        Overall readiness status.
    """
    t0 = time.monotonic()
    logger.info("[warmup] starting LLM warmup pipeline")

    backends = {}

    # Step 1 + 2: vLLM
    vllm_health = check_vllm_health(vllm_url, timeout=vllm_timeout)
    if vllm_health.status == "ready":
        vllm_warm = warmup_vllm(vllm_url)
        backends["vllm"] = asdict(vllm_warm)
    else:
        backends["vllm"] = asdict(vllm_health)

    # Step 3: Gemini
    gemini = check_gemini_preflight()
    backends["gemini"] = asdict(gemini)

    # Determine overall readiness
    vllm_ok = backends["vllm"].get("status") == "ready"
    elapsed = (time.monotonic() - t0) * 1000

    result = WarmupResult(
        ready=vllm_ok,
        timestamp=datetime.datetime.now().isoformat(),
        backends=backends,
        boot_duration_ms=elapsed,
    )

    # Step 4: Write ready file
    _write_ready(result)
    logger.info(
        "[warmup] pipeline complete: ready=%s, duration=%.0fms",
        result.ready,
        elapsed,
    )

    return result
