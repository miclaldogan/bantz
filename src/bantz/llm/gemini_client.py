from __future__ import annotations

import json
import logging
import time
import os
from typing import List, Optional

import requests

from bantz.llm.base import (
    LLMClient,
    LLMMessage,
    LLMResponse,
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMTimeoutError,
    LLMInvalidResponseError,
)

from bantz.llm.privacy import redact_for_cloud, minimize_for_cloud


logger = logging.getLogger(__name__)
metrics_logger = logging.getLogger("bantz.llm.metrics")


class GeminiClient(LLMClient):
    """Gemini (Google Generative Language API) client.

    This implementation uses the public REST API so we don't need extra deps.

    Env (recommended to set via create_quality_client):
      - GEMINI_API_KEY / GOOGLE_API_KEY / BANTZ_GEMINI_API_KEY
      - model: e.g. gemini-1.5-flash

    Notes:
      - This client assumes *cloud mode* is already allowed by the caller.
      - It still applies redact+minimize helpers (best-effort) to reduce leakage.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 240.0,
        base_url: str = "https://generativelanguage.googleapis.com",
    ):
        self._api_key = (api_key or "").strip()
        self._model = (model or "").strip()
        self._timeout_seconds = float(timeout_seconds)
        self._base_url = base_url.rstrip("/")

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def backend_name(self) -> str:
        return "gemini"

    def is_available(self, *, timeout_seconds: float = 1.5) -> bool:
        if not self._api_key or not self._model:
            return False

        url = f"{self._base_url}/v1beta/models"
        try:
            r = requests.get(url, params={"key": self._api_key}, timeout=float(timeout_seconds))
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
        return self.chat_detailed(messages, temperature=temperature, max_tokens=max_tokens).content

    def chat_detailed(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
        seed: Optional[int] = None,
    ) -> LLMResponse:
        if not self._api_key:
            raise LLMConnectionError("Gemini API key missing")
        if not self._model:
            raise LLMInvalidResponseError("Gemini model not set")

        url = f"{self._base_url}/v1beta/models/{self._model}:generateContent"

        # Gemini roles are "user" and "model". We'll map system separately if present.
        system_lines: list[str] = []
        contents = []
        for m in messages:
            role = (m.role or "").strip().lower()
            content = str(m.content or "")
            if role == "system":
                system_lines.append(content)
                continue
            if role in {"assistant", "model"}:
                gemini_role = "model"
            else:
                gemini_role = "user"

            safe_text = minimize_for_cloud(redact_for_cloud(content))
            contents.append({"role": gemini_role, "parts": [{"text": safe_text}]})

        payload: dict = {
            "contents": contents or [{"role": "user", "parts": [{"text": ""}]}],
            "generationConfig": {
                "temperature": float(temperature),
                "maxOutputTokens": int(max_tokens),
            },
        }

        if system_lines:
            safe_sys = minimize_for_cloud(redact_for_cloud("\n\n".join(system_lines)))
            payload["systemInstruction"] = {"parts": [{"text": safe_sys}]}

        if seed is not None:
            payload.setdefault("generationConfig", {})["seed"] = int(seed)

        t0 = time.perf_counter()
        prompt_tokens_est = _estimate_prompt_tokens(payload)
        try:
            r = requests.post(
                url,
                params={"key": self._api_key},
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=self._timeout_seconds,
            )
            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            # Map HTTP errors to stable reason codes.
            if r.status_code >= 500:
                raise LLMConnectionError(f"Gemini server_error status={r.status_code} reason=server_error")
            if r.status_code in {401, 403}:
                raise LLMConnectionError(
                    f"Gemini auth_error status={r.status_code} reason=auth_error"
                )
            if r.status_code == 429:
                raise LLMConnectionError("Gemini rate_limited status=429 reason=rate_limited")
            if r.status_code == 404:
                raise LLMModelNotFoundError("Gemini model_not_found status=404 reason=model_not_found")
            if r.status_code >= 400:
                # Do not include response body (avoid accidentally logging user content).
                raise LLMInvalidResponseError(
                    f"Gemini invalid_request status={r.status_code} reason=invalid_request"
                )

            data = r.json() or {}
            candidates = data.get("candidates") or []
            text_out = ""
            finish_reason = "stop"
            if candidates and isinstance(candidates[0], dict):
                cand = candidates[0]
                finish_reason = str(cand.get("finishReason") or "stop")
                content = cand.get("content") or {}
                parts = content.get("parts") or []
                if parts and isinstance(parts[0], dict):
                    text_out = str(parts[0].get("text") or "")

            usage = data.get("usageMetadata") or {}
            prompt_tokens = int(usage.get("promptTokenCount") or -1)
            completion_tokens = int(usage.get("candidatesTokenCount") or -1)
            total_tokens = int(usage.get("totalTokenCount") or -1)

            if prompt_tokens < 0:
                prompt_tokens = int(prompt_tokens_est)

            if _metrics_enabled():
                metrics_logger.info(
                    "llm_call backend=%s model=%s latency_ms=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
                    self.backend_name,
                    self.model_name,
                    elapsed_ms,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                )

            return LLMResponse(
                content=str(text_out or "").strip(),
                model=self._model,
                tokens_used=total_tokens,
                finish_reason=finish_reason,
            )

        except requests.Timeout as e:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            if _metrics_enabled():
                metrics_logger.info(
                    "llm_call_failed backend=%s model=%s latency_ms=%s reason=%s prompt_tokens=%s",
                    self.backend_name,
                    self.model_name,
                    elapsed_ms,
                    "timeout",
                    int(prompt_tokens_est),
                )
            raise LLMTimeoutError(
                f"Gemini timeout reason=timeout timeout_s={self._timeout_seconds}"
            ) from e
        except requests.RequestException as e:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            if _metrics_enabled():
                metrics_logger.info(
                    "llm_call_failed backend=%s model=%s latency_ms=%s reason=%s prompt_tokens=%s",
                    self.backend_name,
                    self.model_name,
                    elapsed_ms,
                    "connection_error",
                    int(prompt_tokens_est),
                )
            raise LLMConnectionError(
                f"Gemini connection_error reason=connection_error"
            ) from e
        except (LLMConnectionError, LLMModelNotFoundError, LLMTimeoutError, LLMInvalidResponseError):
            # Preserve upstream reason codes.
            raise
        except Exception as e:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            if _metrics_enabled():
                metrics_logger.info(
                    "llm_call_failed backend=%s model=%s latency_ms=%s reason=%s prompt_tokens=%s",
                    self.backend_name,
                    self.model_name,
                    elapsed_ms,
                    "parse_error",
                    int(prompt_tokens_est),
                )
            raise LLMInvalidResponseError(f"Gemini parse_error reason=parse_error") from e

    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200) -> str:
        messages = [LLMMessage(role="user", content=prompt)]
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)


def _metrics_enabled() -> bool:
    # Keep this local to avoid import cycles; parse env here.
    raw = str(os.environ.get("BANTZ_LLM_METRICS", "")).strip().lower()
    if not raw:
        return False
    return raw in {"1", "true", "yes", "y", "on"}


def _estimate_prompt_tokens(payload: dict) -> int:
    """Best-effort token estimate for metrics when Gemini omits usageMetadata.

    Issue #406: Uses unified token estimator for the chars→tokens conversion,
    but still walks the Gemini payload structure to extract total chars.
    """
    from bantz.llm.token_utils import estimate_tokens

    try:
        parts_text: list[str] = []
        sys_inst = payload.get("systemInstruction") or {}
        for p in (sys_inst.get("parts") or []):
            if isinstance(p, dict):
                parts_text.append(str(p.get("text") or ""))

        for c in (payload.get("contents") or []):
            if not isinstance(c, dict):
                continue
            for p in (c.get("parts") or []):
                if isinstance(p, dict):
                    parts_text.append(str(p.get("text") or ""))

        return estimate_tokens(" ".join(parts_text))
    except Exception:
        return -1
