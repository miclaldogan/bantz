from __future__ import annotations

import os
from typing import List, Optional

# Import base interface (new abstraction)
from bantz.llm.base import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMTimeoutError,
    LLMInvalidResponseError,
)


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5:3b-instruct",
        timeout_seconds: float = 120.0,
    ):
        env_url = (os.environ.get("BANTZ_OLLAMA_URL") or "").strip()
        env_model = (os.environ.get("BANTZ_OLLAMA_MODEL") or "").strip()

        base_url = (base_url or "").strip() or env_url or "http://127.0.0.1:11434"
        model = (model or "").strip() or env_model or "qwen2.5:3b-instruct"

        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.timeout_seconds = float(timeout_seconds)

    def is_available(self, *, timeout_seconds: float = 1.5) -> bool:
        """Return True if Ollama is reachable."""
        try:
            import requests
        except ModuleNotFoundError:
            return False

        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=float(timeout_seconds))
            return r.status_code == 200
        except Exception:
            return False

    def list_models(self, *, timeout_seconds: float = 2.0) -> list[str]:
        """List locally available model names from Ollama."""
        try:
            import requests
        except ModuleNotFoundError as e:
            raise RuntimeError("requests yüklü değil. Kurulum: pip install 'bantz[llm]'") from e

        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=float(timeout_seconds))
            r.raise_for_status()
            data = r.json() or {}
            models = data.get("models") or []
            out: list[str] = []
            for item in models:
                if isinstance(item, dict) and item.get("name"):
                    out.append(str(item["name"]))
            return out
        except Exception as e:
            raise RuntimeError(
                f"Ollama'ya bağlanamadım ({self.base_url}). Başlat: ollama serve"
            ) from e

    def _ensure_model_selected(self) -> None:
        if (self.model or "").strip():
            return
        models = self.list_models(timeout_seconds=2.0)
        if not models:
            raise RuntimeError(
                "Ollama çalışıyor ama model bulunamadı. Örn: ollama pull qwen2.5:3b-instruct"
            )
        self.model = models[0]

    def chat(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
    ) -> str:
        try:
            import requests
        except ModuleNotFoundError as e:
            raise RuntimeError(
                "requests yüklü değil. Kurulum: pip install 'bantz[llm]'"
            ) from e

        self._ensure_model_selected()

        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {
                "temperature": float(temperature),
                "num_predict": int(max_tokens),
            },
        }

        try:
            r = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout_seconds,
            )
        except Exception as e:
            raise RuntimeError(
                f"Ollama'ya bağlanamadım ({self.base_url}). Başlat: ollama serve"
            ) from e

        # Prefer JSON error if present.
        if r.status_code >= 400:
            err_text = ""
            try:
                data = r.json() or {}
                err_text = str(data.get("error") or "").strip()
            except Exception:
                err_text = (r.text or "").strip()

            if "model" in err_text.lower() and "not found" in err_text.lower():
                raise RuntimeError(
                    f"Ollama model bulunamadı: '{self.model}'. Kur: ollama pull {self.model}"
                )
            raise RuntimeError(f"Ollama hata ({r.status_code}): {err_text or 'unknown_error'}")

        data = r.json() or {}
        return (data.get("message") or {}).get("content", "").strip()


class OllamaClientAdapter(LLMClient):
    """Adapter that makes OllamaClient conform to LLMClient interface.
    
    This allows existing code to work unchanged while enabling backend abstraction.
    """
    
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5:3b-instruct",
        timeout_seconds: float = 120.0,
    ):
        self._client = OllamaClient(
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    
    def is_available(self, *, timeout_seconds: float = 1.5) -> bool:
        return self._client.is_available(timeout_seconds=timeout_seconds)
    
    def chat(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
    ) -> str:
        try:
            return self._client.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except RuntimeError as e:
            msg = str(e).lower()
            if "model" in msg and "not found" in msg:
                raise LLMModelNotFoundError(str(e)) from e
            elif "bağlanamadım" in msg or "connection" in msg:
                raise LLMConnectionError(str(e)) from e
            elif "timeout" in msg:
                raise LLMTimeoutError(str(e)) from e
            else:
                raise LLMInvalidResponseError(str(e)) from e
    
    def chat_detailed(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
        seed: Optional[int] = None,
    ) -> LLMResponse:
        # Ollama doesn't return detailed metadata by default
        # We'll just wrap the simple response
        content = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return LLMResponse(
            content=content,
            model=self._client.model,
            tokens_used=-1,  # Ollama doesn't expose this easily
            finish_reason="stop",
        )
    
    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
        """Simple text completion (used by Router)."""
        messages = [LLMMessage(role="user", content=prompt)]
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)
    
    @property
    def model_name(self) -> str:
        return self._client.model
    
    @property
    def backend_name(self) -> str:
        return "ollama"
