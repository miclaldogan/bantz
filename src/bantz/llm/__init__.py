from __future__ import annotations

import os

from .base import LLMMessage, LLMClient, LLMClientProtocol, create_client
from .vllm_openai_client import VLLMOpenAIClient
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


def create_fast_client(
    *,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 120.0,
) -> LLMClientProtocol:
    """Create the default (fast) vLLM client.

    Env:
      - BANTZ_VLLM_URL (default: http://127.0.0.1:8001)
      - BANTZ_VLLM_MODEL (default: Qwen/Qwen2.5-3B-Instruct)

    Tip: set model to "auto" to pick the first /v1/models entry.
    """

    return create_client(
        "vllm",
        base_url=(base_url or os.getenv("BANTZ_VLLM_URL") or "http://127.0.0.1:8001"),
        model=(model or os.getenv("BANTZ_VLLM_MODEL") or "Qwen/Qwen2.5-3B-Instruct"),
        timeout=timeout,
    )


def create_quality_client(
    *,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = 240.0,
) -> LLMClientProtocol:
    """Create the "quality" vLLM client (usually a larger model on port 8002).

    Env:
      - BANTZ_VLLM_QUALITY_URL (default: http://127.0.0.1:8002)
      - BANTZ_VLLM_QUALITY_MODEL (default: Qwen/Qwen2.5-7B-Instruct-AWQ)

    If quality env vars are not set, this still works (falls back to defaults).
    Tip: set model to "auto" to pick the first /v1/models entry.
    """

    return create_client(
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

