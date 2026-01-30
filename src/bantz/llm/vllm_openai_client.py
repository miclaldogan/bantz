"""vLLM OpenAI-compatible client for fast GPU inference.

Issue #133: Backend Abstraction

This client uses vLLM's OpenAI-compatible API endpoint to run local models with GPU acceleration.
vLLM provides 10-20x throughput compared to standard inference.

Usage:
    >>> client = VLLMOpenAIClient(base_url='http://localhost:8000')
    >>> response = client.chat([LLMMessage(role='user', content='Hello')])
    
Requirements:
    pip install openai
    
vLLM server must be running:
    python -m vllm.entrypoints.openai.api_server --model Qwen/Qwen2.5-3B-Instruct --port 8000
"""

from __future__ import annotations

import json
from typing import List, Optional

from bantz.llm.base import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMTimeoutError,
    LLMInvalidResponseError,
)


class VLLMOpenAIClient(LLMClient):
    """vLLM client using OpenAI-compatible API.
    
    This client connects to a local vLLM server (or remote endpoint) that exposes
    an OpenAI-compatible /v1/chat/completions endpoint.
    
    Attributes:
        base_url: vLLM server URL (e.g., http://localhost:8000)
        model: Model name (e.g., Qwen/Qwen2.5-3B-Instruct)
        timeout_seconds: Request timeout
    """
    
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        model: str = "Qwen/Qwen2.5-3B-Instruct",
        timeout_seconds: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.timeout_seconds = float(timeout_seconds)
        
        # Lazy-import OpenAI client
        self._client: Optional[object] = None
    
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
    ) -> str:
        """Chat completion (simple string response)."""
        response = self.chat_detailed(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.content
    
    def chat_detailed(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
        seed: Optional[int] = None,
    ) -> LLMResponse:
        """Chat completion with detailed metadata."""
        client = self._get_client()
        
        # Convert to OpenAI message format
        openai_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]
        
        try:
            # Call OpenAI-compatible API
            completion = client.chat.completions.create(
                model=self.model,
                messages=openai_messages,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
                seed=seed,
            )
            
            # Extract response
            choice = completion.choices[0]
            content = choice.message.content or ""
            
            return LLMResponse(
                content=content.strip(),
                model=completion.model,
                tokens_used=completion.usage.total_tokens if completion.usage else -1,
                finish_reason=choice.finish_reason or "stop",
            )
        
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
