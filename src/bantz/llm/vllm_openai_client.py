"""vLLM OpenAI-compatible client for fast GPU inference.

Issue #133: Backend Abstraction
Issue #158: TTFT Monitoring & Optimization

This client uses vLLM's OpenAI-compatible API endpoint to run local models with GPU acceleration.
vLLM provides 10-20x throughput compared to standard inference.

Features:
- Streaming support with TTFT measurement
- Automatic TTFT monitoring integration
- Performance regression detection

Usage:
    >>> client = VLLMOpenAIClient(base_url='http://localhost:8001')
    >>> response = client.chat([LLMMessage(role='user', content='Hello')])
    
    >>> # Streaming with TTFT
    >>> for chunk in client.chat_stream([LLMMessage(role='user', content='Hello')]):
    ...     print(chunk, end='', flush=True)
    
Requirements:
    pip install openai
    
vLLM server must be running:
    python -m vllm.entrypoints.openai.api_server --model Qwen/Qwen2.5-3B-Instruct-AWQ --port 8001
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import List, Optional, Iterator, Any
from dataclasses import dataclass

from bantz.llm.base import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMTimeoutError,
    LLMInvalidResponseError,
)

logger = logging.getLogger(__name__)


@dataclass
class StreamChunk:
    """Streaming response chunk."""
    content: str
    is_first_token: bool = False
    ttft_ms: Optional[int] = None
    finish_reason: Optional[str] = None


class VLLMOpenAIClient(LLMClient):
    """vLLM client using OpenAI-compatible API.
    
    This client connects to a local vLLM server (or remote endpoint) that exposes
    an OpenAI-compatible /v1/chat/completions endpoint.
    
    Features (Issue #158):
    - Streaming support with TTFT measurement
    - Automatic TTFT monitoring integration
    - Performance tracking
    
    Attributes:
        base_url: vLLM server URL (e.g., http://localhost:8001)
        model: Model name (e.g., Qwen/Qwen2.5-3B-Instruct-AWQ)
        timeout_seconds: Request timeout
        track_ttft: Enable TTFT tracking (default: True)
        ttft_phase: Phase name for TTFT tracking ("router" | "finalizer")
    """
    
    def __init__(
        self,
        base_url: str = "",
        model: str = "",
        timeout_seconds: float = 120.0,
        track_ttft: bool = True,
        ttft_phase: str = "router",
    ):
        # Issue #1020: Read from env vars with sensible fallbacks
        self.base_url = (
            base_url or os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8001")
        ).rstrip("/")
        self.model = (
            model or os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-3B-Instruct-AWQ")
        ).strip()
        self.timeout_seconds = float(timeout_seconds)
        self.track_ttft = track_ttft
        self.ttft_phase = ttft_phase

        # Cache for /v1/models capabilities.
        self._cached_model_context_len: Optional[int] = None
        
        # Issue #1016: Lock for thread-safe lazy init of _client and model auto-resolve.
        self._lock = threading.Lock()
        
        # Lazy-import OpenAI client
        self._client: Optional[object] = None

    def get_model_context_length(self, *, timeout_seconds: float = 1.5) -> Optional[int]:
        """Best-effort discovery of the served model's context length.

        Uses vLLM's OpenAI-compatible `/v1/models` endpoint when available.
        Returns `None` if unavailable or if the server doesn't report it.
        """

        if self._cached_model_context_len is not None:
            return int(self._cached_model_context_len)

        try:
            import requests
        except ModuleNotFoundError:
            return None

        try:
            r = requests.get(
                f"{self.base_url}/v1/models",
                timeout=float(timeout_seconds),
            )
            if r.status_code != 200:
                return None

            data = r.json() or {}
            models_list = data.get("data", [])
            if not isinstance(models_list, list) or not models_list:
                return None

            chosen = None
            wanted = str(self.model or "").strip()
            for item in models_list:
                if not isinstance(item, dict):
                    continue
                if wanted and str(item.get("id") or "").strip() == wanted:
                    chosen = item
                    break
            if chosen is None:
                # Fallback: first entry.
                chosen = models_list[0] if isinstance(models_list[0], dict) else None

            context_len = _extract_context_len(chosen) if isinstance(chosen, dict) else None
            if context_len is not None and context_len > 0:
                self._cached_model_context_len = int(context_len)
                return int(context_len)
            return None
        except Exception:
            return None
    
    def _get_client(self):
        """Lazy-initialize OpenAI client (thread-safe)."""
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                from openai import OpenAI
            except ModuleNotFoundError as e:
                raise RuntimeError(
                    "openai kütüphanesi yüklü değil. Kurulum: pip install openai"
                ) from e
            
            # OpenAI client expects base_url to point to API root.
            # self.base_url might already include /v1 or not.
            _api_base = self.base_url.rstrip("/")
            if not _api_base.endswith("/v1"):
                _api_base = f"{_api_base}/v1"
            
            self._client = OpenAI(
                base_url=_api_base,
                api_key=os.getenv("VLLM_API_KEY", "EMPTY"),
                timeout=self.timeout_seconds,
            )
        
        return self._client
    
    def _resolve_auto_model(self) -> None:
        """Thread-safe auto-resolution of model name from /v1/models.

        Issue #1016: Called when self.model == "auto". Uses a lock to
        prevent concurrent threads from racing on the assignment.
        """
        if (self.model or "").strip().lower() != "auto":
            return
        with self._lock:
            # Double-check after acquiring lock (another thread may have resolved).
            if (self.model or "").strip().lower() != "auto":
                return
            models = self.list_available_models(timeout_seconds=2.0)
            if not models:
                raise LLMModelNotFoundError(
                    f"vLLM ({self.base_url}) did not report any models via /v1/models"
                )
            self.model = str(models[0]).strip()

    def is_available(self, *, timeout_seconds: float = 1.5) -> bool:
        """Check if vLLM server is reachable."""
        try:
            import requests
        except ModuleNotFoundError:
            return False
        
        try:
            # Issue #996: self.base_url is the raw URL (e.g. http://localhost:8001).
            # vLLM serves /v1/models, not /models.  Must mirror _get_client()'s
            # /v1 suffix logic.
            _api_base = self.base_url.rstrip("/")
            if not _api_base.endswith("/v1"):
                _api_base = f"{_api_base}/v1"
            health_url = f"{_api_base}/models"
            r = requests.get(
                health_url,
                timeout=float(timeout_seconds),
            )
            return r.status_code == 200
        except Exception:
            return False
    
    def chat(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
        response_format: Optional[dict[str, Any]] = None,
        stop: Optional[List[str]] = None,
    ) -> str:
        """Chat completion (simple string response)."""
        response = self.chat_detailed(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            stop=stop,
        )
        return response.content
    
    def chat_detailed(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
        seed: Optional[int] = None,
        response_format: Optional[dict[str, Any]] = None,
        stop: Optional[List[str]] = None,
    ) -> LLMResponse:
        """Chat completion with detailed metadata."""
        client = self._get_client()

        # Issue #1016: Thread-safe auto model resolution.
        self._resolve_auto_model()
        
        # Convert to OpenAI message format
        openai_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]
        
        t0 = time.perf_counter()
        try:
            # Call OpenAI-compatible API
            kwargs: dict[str, Any] = {}
            if response_format is not None:
                kwargs["response_format"] = response_format
            if stop is not None:
                kwargs["stop"] = stop

            completion = client.chat.completions.create(
                model=self.model,
                messages=openai_messages,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
                seed=seed,
                **kwargs,
            )

            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            
            # Extract response
            choice = completion.choices[0]
            content = choice.message.content or ""
            
            usage_dict: dict[str, Any] | None = None
            try:
                if completion.usage is not None:
                    usage_obj = completion.usage
                    usage_dict = {
                        "prompt_tokens": getattr(usage_obj, "prompt_tokens", None),
                        "completion_tokens": getattr(usage_obj, "completion_tokens", None),
                        "total_tokens": getattr(usage_obj, "total_tokens", None),
                    }
            except Exception:
                usage_dict = None

            total_tokens = -1
            if isinstance(usage_dict, dict) and usage_dict.get("total_tokens") is not None:
                try:
                    total_tokens = int(usage_dict["total_tokens"])
                except Exception:
                    total_tokens = -1

            resp = LLMResponse(
                content=content.strip(),
                model=completion.model,
                tokens_used=total_tokens,
                finish_reason=choice.finish_reason or "stop",
                usage=usage_dict,
            )

            # Track TTFT (approximate for non-streaming)
            if self.track_ttft:
                try:
                    from bantz.llm.ttft_monitor import record_ttft
                    record_ttft(
                        ttft_ms=elapsed_ms,  # Approximate: total time for non-streaming
                        phase=self.ttft_phase,
                        model=self.model_name,
                        backend=self.backend_name,
                        total_tokens=resp.tokens_used,
                    )
                except Exception as e:
                    logger.debug(f"TTFT tracking failed: {e}")

            if _metrics_enabled():
                logging.getLogger("bantz.llm.metrics").info(
                    "llm_call backend=%s model=%s latency_ms=%s total_tokens=%s",
                    self.backend_name,
                    self.model_name,
                    elapsed_ms,
                    resp.tokens_used,
                )

            return resp
        
        except Exception as e:
            error_msg = str(e).lower()
            
            # Classify error type
            if "connection" in error_msg or "refused" in error_msg or "unreachable" in error_msg:
                raise LLMConnectionError(
                    f"vLLM sunucusuna bağlanamadım ({self.base_url}). "
                    f"Başlat: python -m vllm.entrypoints.openai.api_server --model {self.model}"
                ) from e
            
            elif "timeout" in error_msg:
                raise LLMTimeoutError(
                    f"vLLM request timeout ({self.timeout_seconds}s). Model yüklenirken zaman aşımı?"
                ) from e
            
            elif "model" in error_msg and ("not found" in error_msg or "404" in error_msg):
                raise LLMModelNotFoundError(
                    f"vLLM model bulunamadı: '{self.model}'. "
                    f"Sunucu başka model kullanıyor olabilir."
                ) from e
            
            else:
                raise LLMInvalidResponseError(
                    f"vLLM response parsing failed: {e}"
                ) from e
    
    def chat_stream(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
        seed: Optional[int] = None,
    ) -> Iterator[StreamChunk]:
        """Chat completion with streaming (Issue #158).
        
        This enables TTFT measurement and real-time response display.
        
        Args:
            messages: Chat messages
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            seed: Random seed
            
        Yields:
            StreamChunk with content and TTFT metadata
            
        Example:
            >>> for chunk in client.chat_stream(messages):
            ...     if chunk.is_first_token:
            ...         print(f"[TTFT: {chunk.ttft_ms}ms]")
            ...     print(chunk.content, end='', flush=True)
        """
        client = self._get_client()
        
        # Issue #1016: Thread-safe auto model resolution.
        self._resolve_auto_model()
        
        # Convert to OpenAI message format
        openai_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]
        
        t0 = time.perf_counter()
        ttft_measured = False
        ttft_ms = None
        total_tokens = 0
        total_content_chars = 0  # Issue #1013: accumulate content length
        chunk_count = 0
        
        try:
            # Call OpenAI-compatible streaming API
            stream = client.chat.completions.create(
                model=self.model,
                messages=openai_messages,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
                seed=seed,
                stream=True,
            )
            
            for chunk_data in stream:
                # First token timing
                if not ttft_measured:
                    ttft_ms = int((time.perf_counter() - t0) * 1000)
                    ttft_measured = True
                    
                    # Track TTFT
                    if self.track_ttft:
                        try:
                            from bantz.llm.ttft_monitor import record_ttft
                            record_ttft(
                                ttft_ms=ttft_ms,
                                phase=self.ttft_phase,
                                model=self.model_name,
                                backend=self.backend_name,
                            )
                        except Exception as e:
                            logger.debug(f"TTFT tracking failed: {e}")

                # Issue #1013: Try to extract usage from final chunk (vLLM sends
                # usage stats in the last streaming chunk when available)
                if hasattr(chunk_data, "usage") and chunk_data.usage:
                    usage = chunk_data.usage
                    if hasattr(usage, "completion_tokens") and usage.completion_tokens:
                        total_tokens = int(usage.completion_tokens)

                # Extract content
                if not chunk_data.choices:
                    continue
                
                choice = chunk_data.choices[0]
                delta = choice.delta
                
                content = delta.content or ""
                finish_reason = choice.finish_reason
                
                if content:
                    chunk_count += 1
                    total_content_chars += len(content)
                    
                    yield StreamChunk(
                        content=content,
                        is_first_token=(chunk_count == 1),
                        ttft_ms=ttft_ms if chunk_count == 1 else None,
                        finish_reason=finish_reason,
                    )
                
                if finish_reason:
                    break

            # Issue #1013: If usage stats weren't available from stream,
            # estimate tokens from accumulated content length (chars/4)
            if total_tokens == 0 and total_content_chars > 0:
                total_tokens = max(1, total_content_chars // 4)
            
            # Log final metrics
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            
            if _metrics_enabled():
                logging.getLogger("bantz.llm.metrics").info(
                    "llm_stream backend=%s model=%s ttft_ms=%s total_ms=%s total_tokens=%s",
                    self.backend_name,
                    self.model_name,
                    ttft_ms or -1,
                    elapsed_ms,
                    total_tokens,
                )
        
        except Exception as e:
            error_msg = str(e).lower()
            
            # Classify error type
            if "connection" in error_msg or "refused" in error_msg:
                raise LLMConnectionError(
                    f"vLLM sunucusuna bağlanamadım ({self.base_url})"
                ) from e
            
            elif "timeout" in error_msg:
                raise LLMTimeoutError(
                    f"vLLM stream timeout ({self.timeout_seconds}s)"
                ) from e
            
            else:
                raise LLMInvalidResponseError(
                    f"vLLM stream failed: {e}"
                ) from e
    
    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200, stop: Optional[List[str]] = None, system_prompt: Optional[str] = None) -> str:
        """Simple text completion (used by Router).

        Issue #1050: When system_prompt is provided it is sent as a proper
        system message instead of being crammed into the user message.
        """
        messages: List[LLMMessage] = []
        if system_prompt:
            messages.append(LLMMessage(role="system", content=system_prompt))
        messages.append(LLMMessage(role="user", content=prompt))
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens, stop=stop)
    
    @property
    def model_name(self) -> str:
        return self.model
    
    @property
    def backend_name(self) -> str:
        return "vllm"
    
    def list_available_models(self, *, timeout_seconds: float = 2.0) -> List[str]:
        """List models available on vLLM server.
        
        Returns:
            List of model names (usually just one model per vLLM instance)
        """
        try:
            import requests
        except ModuleNotFoundError as e:
            raise RuntimeError("requests yüklü değil. Kurulum: pip install requests") from e
        
        try:
            r = requests.get(
                f"{self.base_url}/v1/models",
                timeout=float(timeout_seconds),
            )
            r.raise_for_status()
            
            data = r.json() or {}
            models_list = data.get("data", [])
            
            return [item["id"] for item in models_list if isinstance(item, dict) and "id" in item]
        
        except Exception as e:
            raise RuntimeError(
                f"vLLM sunucusundan model listesi alınamadı ({self.base_url})"
            ) from e


def _metrics_enabled() -> bool:
    raw = str(os.environ.get("BANTZ_LLM_METRICS", "")).strip().lower()
    if not raw:
        return False
    return raw in {"1", "true", "yes", "y", "on"}


def _extract_context_len(model_item: dict[str, Any]) -> Optional[int]:
    """Extract context length from a `/v1/models` entry.

    vLLM deployments sometimes include fields like `max_model_len`. We keep the
    parsing best-effort and conservative.
    """

    if not isinstance(model_item, dict):
        return None

    candidates: list[Any] = []
    for key in (
        "max_model_len",
        "max_context_length",
        "context_length",
        "max_position_embeddings",
    ):
        if key in model_item:
            candidates.append(model_item.get(key))

    meta = model_item.get("metadata")
    if isinstance(meta, dict):
        for key in (
            "max_model_len",
            "max_context_length",
            "context_length",
            "max_position_embeddings",
        ):
            if key in meta:
                candidates.append(meta.get(key))

    # If the server stashes capabilities in a nested structure, try a small recursive walk.
    def walk(obj: Any, depth: int = 0) -> None:
        if depth > 3:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                lk = str(k).lower()
                if lk in {
                    "max_model_len",
                    "max_context_length",
                    "context_length",
                    "max_position_embeddings",
                }:
                    candidates.append(v)
                else:
                    walk(v, depth + 1)
        elif isinstance(obj, list):
            for v in obj[:10]:
                walk(v, depth + 1)

    walk(model_item)

    best: Optional[int] = None
    for v in candidates:
        try:
            iv = int(v)
        except Exception:
            continue
        if iv <= 0:
            continue
        if best is None or iv > best:
            best = iv

    # Sanity bounds.
    if best is None:
        return None
    if best < 256:
        return None
    if best > 262144:
        return None
    return int(best)
