from __future__ import annotations

import os

from .base import LLMMessage, LLMClient, LLMClientProtocol, create_client
from .vllm_openai_client import VLLMOpenAIClient
from .privacy import get_cloud_privacy_config
from .persona import (
    JarvisPersona,
    ResponseBuilder,
    JARVIS_RESPONSES,
    JARVIS_CONTEXTUAL,
    get_persona,
    say,
    jarvis_greeting,
    jarvis_farewell,
)

__all__ = [
    "LLMMessage",
    "LLMClient",
    "LLMClientProtocol",
    "create_client",
    "VLLMOpenAIClient",
    "JarvisPersona",
    "ResponseBuilder",
    "JARVIS_RESPONSES",
    "JARVIS_CONTEXTUAL",
    "get_persona",
    "say",
    "jarvis_greeting",
    "jarvis_farewell",
    "create_fast_client",
    "create_quality_client",
]


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "y", "on", "enable", "enabled"}


def _env_str(*names: str, default: str = "") -> str:
    for n in names:
        v = str(os.getenv(n, "")).strip()
        if v:
            return v
    return default


def create_fast_client(
    *,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 120.0,
) -> LLMClientProtocol:
    """Create the default (fast) vLLM client.

    Env:
      - BANTZ_VLLM_URL (default: http://127.0.0.1:8001)
      - BANTZ_VLLM_MODEL (default: Qwen/Qwen2.5-3B-Instruct-AWQ)

    Tip: set model to "auto" to pick the first /v1/models entry.
    """

    return create_client(
        "vllm",
        base_url=(base_url or os.getenv("BANTZ_VLLM_URL") or "http://127.0.0.1:8001"),
        model=(model or os.getenv("BANTZ_VLLM_MODEL") or "Qwen/Qwen2.5-3B-Instruct-AWQ"),
        timeout=timeout,
    )


def create_quality_client(
    *,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 240.0,
) -> LLMClientProtocol:
    """Create the "quality" client.

    Default: vLLM on port 8002.
    Hybrid mode: route quality calls to Gemini (Flash) while keeping fast local vLLM.

    Provider selection env (supports both names):
      - QUALITY_PROVIDER / BANTZ_QUALITY_PROVIDER: vllm|gemini

    vLLM quality env:
      - BANTZ_VLLM_QUALITY_URL (default: http://127.0.0.1:8002)
      - BANTZ_VLLM_QUALITY_MODEL (default: Qwen/Qwen2.5-7B-Instruct-AWQ)

    Gemini env (cloud):
      - BANTZ_CLOUD_MODE=cloud (or CLOUD_MODE=cloud). Default is local (cloud disabled).
      - GEMINI_API_KEY / GOOGLE_API_KEY / BANTZ_GEMINI_API_KEY
      - QUALITY_MODEL / QUALITY_MODEL_NAME / BANTZ_QUALITY_MODEL / BANTZ_GEMINI_MODEL

    Fallback:
      - If the quality provider isn't usable, returns fast client (3B) by default.
        Disable via BANTZ_QUALITY_FALLBACK_TO_FAST=0.
    """

    provider = _env_str("QUALITY_PROVIDER", "BANTZ_QUALITY_PROVIDER", default="vllm").lower()
    fallback_to_fast = _env_flag("BANTZ_QUALITY_FALLBACK_TO_FAST", default=True)

    if provider in {"gemini", "google", "genai"}:
        privacy = get_cloud_privacy_config()
        if privacy.mode != "cloud":
            return create_fast_client(timeout=timeout)

        api_key = _env_str("GEMINI_API_KEY", "GOOGLE_API_KEY", "BANTZ_GEMINI_API_KEY", default="")
        if not api_key:
            return create_fast_client(timeout=timeout)

        gem_model = (
            model
            or _env_str(
                "QUALITY_MODEL",
                "QUALITY_MODEL_NAME",
                "BANTZ_QUALITY_MODEL",
                "BANTZ_GEMINI_MODEL",
                default="gemini-2.0-flash",
            )
        )

        from bantz.llm.gemini_client import GeminiClient

        return GeminiClient(api_key=api_key, model=gem_model, timeout_seconds=timeout)

    # Default: vLLM quality endpoint (8002)
    quality_client = create_client(
        "vllm",
        base_url=(
            base_url
            or os.getenv("BANTZ_VLLM_QUALITY_URL")
            or "http://127.0.0.1:8002"
        ),
        model=(
            model
            or os.getenv("BANTZ_VLLM_QUALITY_MODEL")
            or "Qwen/Qwen2.5-7B-Instruct-AWQ"
        ),
        timeout=timeout,
    )

    if not fallback_to_fast:
        return quality_client

    # If 8002 is down / not ready, keep the system stable by falling back to fast.
    try:
        probe_timeout = float(os.getenv("BANTZ_QUALITY_AVAIL_TIMEOUT", "1.0") or "1.0")
    except Exception:
        probe_timeout = 1.0

    try:
        if not quality_client.is_available(timeout_seconds=probe_timeout):
            return create_fast_client(timeout=timeout)
    except Exception:
        return create_fast_client(timeout=timeout)

    return quality_client

