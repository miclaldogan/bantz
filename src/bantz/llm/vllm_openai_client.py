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
    python -m vllm.entrypoints.openai.api_server --model Qwen/Qwen2.5-3B-Instruct --port 8001
"""

from __future__ import annotations

import json
import logging
import os
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
        model: Model name (e.g., Qwen/Qwen2.5-3B-Instruct)
        timeout_seconds: Request timeout
        track_ttft: Enable TTFT tracking (default: True)
        ttft_phase: Phase name for TTFT tracking ("router" | "finalizer")
    """
    
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8001",
        model: str = "Qwen/Qwen2.5-3B-Instruct",
        timeout_seconds: float = 120.0,
        track_ttft: bool = True,
        ttft_phase: str = "router",
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.timeout_seconds = float(timeout_seconds)
        self.track_ttft = track_ttft
        self.ttft_phase = ttft_phase

        # Cache for /v1/models capabilities.
        self._cached_model_context_len: Optional[int] = None
        
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
        """Lazy-initialize OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI
            except ModuleNotFoundError as e:
                raise RuntimeError(
                    "openai kütüphanesi yüklü değil. Kurulum: pip install openai"
                ) from e
            
            self._client = OpenAI(
                base_url=f"{self.base_url}/v1",
                api_key="EMPTY",  # vLLM doesn't require API key for local usage
                timeout=self.timeout_seconds,
            )
        
        return self._client
    
    def is_available(self, *, timeout_seconds: float = 1.5) -> bool:
        """Check if vLLM server is reachable."""
        try:
            import requests
        except ModuleNotFoundError:
            return False
        
        try:
            r = requests.get(
                f"{self.base_url}/v1/models",
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
    ) -> str:
        """Chat completion (simple string response)."""
        response = self.chat_detailed(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
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
    ) -> LLMResponse:
        """Chat completion with detailed metadata."""
        client = self._get_client()

        # Allow "auto" model selection (use the first model reported by /v1/models).
        # This is helpful when scripts pass --served-model-name or when the exact
        # model id differs between machines.
        if (self.model or "").strip().lower() == "auto":
            models = self.list_available_models(timeout_seconds=2.0)
            if not models:
                raise LLMModelNotFoundError(
                    f"vLLM ({self.base_url}) did not report any models via /v1/models"
                )
            self.model = str(models[0]).strip()
        
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
        
        # Model auto-selection
        if (self.model or "").strip().lower() == "auto":
            models = self.list_available_models(timeout_seconds=2.0)
            if not models:
                raise LLMModelNotFoundError(
                    f"vLLM ({self.base_url}) did not report any models via /v1/models"
                )
            self.model = str(models[0]).strip()
        
        # Convert to OpenAI message format
        openai_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]
        
        t0 = time.perf_counter()
        ttft_measured = False
        ttft_ms = None
        total_tokens = 0
        
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
                
                # Extract content
                if not chunk_data.choices:
                    continue
                
                choice = chunk_data.choices[0]
                delta = choice.delta
                
                content = delta.content or ""
                finish_reason = choice.finish_reason
                
                if content:
                    total_tokens += 1
                    
                    yield StreamChunk(
                        content=content,
                        is_first_token=(total_tokens == 1),
                        ttft_ms=ttft_ms if total_tokens == 1 else None,
                        finish_reason=finish_reason,
                    )
                
                if finish_reason:
                    break
            
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
    
    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
        """Simple text completion (used by Router)."""
        messages = [LLMMessage(role="user", content=prompt)]
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)
    
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
