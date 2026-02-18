"""
VLLMOpenAIClient stub — legacy compatibility shim.

The real vLLM OpenAI-compatible client was consolidated into the
tiered client (bantz.llm.tiered). This stub ensures imports don't
break during the migration period.

Issue #1463: Re-added as part of pre-existing import fix.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator, Optional

logger = logging.getLogger(__name__)


class VLLMOpenAIClient:
    """Stub that delegates to the real vLLM client from bantz.llm.base."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8001",
        model: str = "Qwen/Qwen2.5-3B-Instruct-AWQ",
        timeout: float = 120.0,
        **kwargs: Any,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._timeout = timeout
        try:
            from bantz.llm.base import create_client

            self._inner = create_client(
                "vllm",
                base_url=base_url,
                model=model,
                timeout=timeout,
            )
        except Exception as e:
            logger.warning("[VLLMOpenAIClient] Failed to init inner client: %s", e)
            self._inner = None

    # ── delegation ──────────────────────────────────────────────────────────

    def complete(self, messages: Any, **kwargs: Any) -> Any:
        if self._inner is None:
            raise RuntimeError("VLLMOpenAIClient: inner client not initialized")
        return self._inner.complete(messages, **kwargs)

    def stream(self, messages: Any, **kwargs: Any) -> Iterator[str]:
        if self._inner is None:
            raise RuntimeError("VLLMOpenAIClient: inner client not initialized")
        return self._inner.stream(messages, **kwargs)

    def is_available(self, timeout_seconds: float = 1.0) -> bool:
        if self._inner is None:
            return False
        try:
            return self._inner.is_available(timeout_seconds=timeout_seconds)
        except Exception:
            return False

    @property
    def model_name(self) -> str:
        return self._model
