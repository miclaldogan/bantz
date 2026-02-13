from __future__ import annotations

import json
import logging
import time
import os
from typing import Iterator, List, Optional

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
from bantz.llm.quota_tracker import (
    QuotaTracker,
    QuotaExceeded,
    CircuitBreaker,
    CircuitOpen,
)


logger = logging.getLogger(__name__)
metrics_logger = logging.getLogger("bantz.llm.metrics")

# Module-level defaults (shared across instances unless overridden)
_default_quota_tracker: Optional[QuotaTracker] = None
_default_circuit_breaker: Optional[CircuitBreaker] = None


def get_default_quota_tracker() -> QuotaTracker:
    """Get or create the module-level default QuotaTracker."""
    global _default_quota_tracker
    if _default_quota_tracker is None:
        _default_quota_tracker = QuotaTracker()
    return _default_quota_tracker


def get_default_circuit_breaker() -> CircuitBreaker:
    """Get or create the module-level default CircuitBreaker."""
    global _default_circuit_breaker
    if _default_circuit_breaker is None:
        _default_circuit_breaker = CircuitBreaker()
    return _default_circuit_breaker


# Retry configuration constants
RETRY_MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.0  # seconds
RETRY_MAX_DELAY = 30.0  # seconds
RETRY_BACKOFF_FACTOR = 2.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503}


from dataclasses import dataclass


@dataclass
class GeminiStreamChunk:
    """A chunk from Gemini streaming response.

    Attributes:
        content: Text content of this chunk.
        is_first_token: True for the very first content chunk.
        ttft_ms: Time-to-first-token in ms (set only on first chunk).
        finish_reason: If this is the final chunk, the finish reason.
    """

    content: str
    is_first_token: bool = False
    ttft_ms: Optional[int] = None
    finish_reason: Optional[str] = None


class GeminiClient(LLMClient):
    """Gemini (Google Generative Language API) client.

    This implementation uses the public REST API so we don't need extra deps.

    Env (recommended to set via create_quality_client):
      - GEMINI_API_KEY / GOOGLE_API_KEY / BANTZ_GEMINI_API_KEY
      - model: e.g. gemini-2.0-flash

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
        quota_tracker: Optional[QuotaTracker] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        max_retries: int = RETRY_MAX_ATTEMPTS,
        use_default_gates: bool = True,
    ):
        self._api_key = (api_key or "").strip()
        self._model = (model or "").strip()
        self._timeout_seconds = float(timeout_seconds)
        self._base_url = base_url.rstrip("/")

        # Issue #593: default gates (quota + circuit) were implemented but not wired.
        # If the caller doesn't pass explicit trackers, use shared module-level
        # defaults to keep the system safe/stable under quota pressure.
        self._quota_tracker = (
            quota_tracker
            if quota_tracker is not None
            else (get_default_quota_tracker() if use_default_gates else None)
        )
        self._circuit_breaker = (
            circuit_breaker
            if circuit_breaker is not None
            else (get_default_circuit_breaker() if use_default_gates else None)
        )
        self._max_retries = max_retries

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

        # --- Pre-flight: circuit breaker & quota ---
        if self._circuit_breaker is not None:
            try:
                self._circuit_breaker.check()
            except CircuitOpen:
                logger.warning("[GEMINI] Circuit breaker OPEN — skipping call")
                raise LLMConnectionError(
                    "Gemini circuit_open reason=circuit_open — "
                    "Gemini geçici olarak devre dışı, yerel model kullanılıyor"
                )

        if self._quota_tracker is not None:
            try:
                self._quota_tracker.check()
            except QuotaExceeded as exc:
                logger.warning("[GEMINI] Quota exceeded: %s", exc)
                raise LLMConnectionError(
                    "Gemini quota_exceeded reason=quota_exceeded — "
                    "Gemini quota aşıldı, yerel model kullanılıyor"
                )

        url = f"{self._base_url}/v1beta/models/{self._model}:generateContent"

        # --- Build payload ---
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

        prompt_tokens_est = _estimate_prompt_tokens(payload)

        # --- Retry loop with exponential backoff ---
        last_exception: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            t0 = time.perf_counter()
            try:
                r = requests.post(
                    url,
                    params={"key": self._api_key},
                    headers={"Content-Type": "application/json"},
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    timeout=self._timeout_seconds,
                )
                elapsed_ms = int((time.perf_counter() - t0) * 1000)

                # --- Parse rate-limit headers ---
                resp_headers = getattr(r, "headers", {}) or {}
                rate_limit_remaining = _parse_rate_limit_remaining(resp_headers)
                retry_after_header = _parse_retry_after(resp_headers)

                if rate_limit_remaining is not None and rate_limit_remaining <= 5:
                    logger.warning(
                        "[GEMINI] Rate limit nearly exhausted: %d remaining",
                        rate_limit_remaining,
                    )

                # --- Retryable status codes ---
                if r.status_code in RETRYABLE_STATUS_CODES:
                    delay = _calculate_backoff(attempt, retry_after_header)
                    logger.warning(
                        "[GEMINI] Retryable error status=%d attempt=%d/%d backoff=%.1fs",
                        r.status_code,
                        attempt,
                        self._max_retries,
                        delay,
                    )
                    if attempt < self._max_retries:
                        time.sleep(delay)
                        continue
                    # Last attempt — fall through to error handling

                # --- Non-retryable errors ---
                if r.status_code >= 500:
                    self._record_failure()
                    raise LLMConnectionError(
                        f"Gemini server_error status={r.status_code} reason=server_error"
                    )
                if r.status_code in {401, 403}:
                    raise LLMConnectionError(
                        f"Gemini auth_error status={r.status_code} reason=auth_error"
                    )
                if r.status_code == 429:
                    self._record_failure()
                    raise LLMConnectionError(
                        "Gemini rate_limited status=429 reason=rate_limited"
                    )
                if r.status_code == 404:
                    raise LLMModelNotFoundError(
                        "Gemini model_not_found status=404 reason=model_not_found"
                    )
                if r.status_code >= 400:
                    raise LLMInvalidResponseError(
                        f"Gemini invalid_request status={r.status_code} reason=invalid_request"
                    )

                # --- Success: parse response ---
                data = r.json() or {}
                candidates = data.get("candidates") or []
                text_out = ""
                finish_reason = "stop"
                if candidates and isinstance(candidates[0], dict):
                    cand = candidates[0]
                    finish_reason = str(cand.get("finishReason") or "stop")
                    content_data = cand.get("content") or {}
                    parts = content_data.get("parts") or []
                    if parts and isinstance(parts[0], dict):
                        text_out = str(parts[0].get("text") or "")

                usage = data.get("usageMetadata") or {}
                prompt_tokens = int(usage.get("promptTokenCount") or -1)
                completion_tokens = int(usage.get("candidatesTokenCount") or -1)
                total_tokens = int(usage.get("totalTokenCount") or -1)

                if prompt_tokens < 0:
                    prompt_tokens = int(prompt_tokens_est)

                # --- Record success ---
                self._record_success(total_tokens if total_tokens > 0 else 0)

                if _metrics_enabled():
                    metrics_logger.info(
                        "llm_call backend=%s model=%s latency_ms=%s prompt_tokens=%s "
                        "completion_tokens=%s total_tokens=%s attempt=%s",
                        self.backend_name,
                        self.model_name,
                        elapsed_ms,
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                        attempt,
                    )

                return LLMResponse(
                    content=str(text_out or "").strip(),
                    model=self._model,
                    tokens_used=total_tokens,
                    finish_reason=finish_reason,
                )

            except requests.Timeout as e:
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                last_exception = e
                if _metrics_enabled():
                    metrics_logger.info(
                        "llm_call_failed backend=%s model=%s latency_ms=%s "
                        "reason=%s prompt_tokens=%s attempt=%s",
                        self.backend_name,
                        self.model_name,
                        elapsed_ms,
                        "timeout",
                        int(prompt_tokens_est),
                        attempt,
                    )
                # Timeout is retryable
                if attempt < self._max_retries:
                    delay = _calculate_backoff(attempt)
                    logger.warning(
                        "[GEMINI] Timeout attempt=%d/%d backoff=%.1fs",
                        attempt,
                        self._max_retries,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                self._record_failure()
                raise LLMTimeoutError(
                    f"Gemini timeout reason=timeout timeout_s={self._timeout_seconds} "
                    f"attempts={self._max_retries}"
                ) from e

            except requests.RequestException as e:
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                last_exception = e
                if _metrics_enabled():
                    metrics_logger.info(
                        "llm_call_failed backend=%s model=%s latency_ms=%s "
                        "reason=%s prompt_tokens=%s attempt=%s",
                        self.backend_name,
                        self.model_name,
                        elapsed_ms,
                        "connection_error",
                        int(prompt_tokens_est),
                        attempt,
                    )
                # Connection errors are retryable
                if attempt < self._max_retries:
                    delay = _calculate_backoff(attempt)
                    logger.warning(
                        "[GEMINI] Connection error attempt=%d/%d backoff=%.1fs",
                        attempt,
                        self._max_retries,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                self._record_failure()
                raise LLMConnectionError(
                    f"Gemini connection_error reason=connection_error "
                    f"attempts={self._max_retries}"
                ) from e

            except (LLMConnectionError, LLMModelNotFoundError, LLMTimeoutError, LLMInvalidResponseError):
                raise

            except Exception as e:
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                if _metrics_enabled():
                    metrics_logger.info(
                        "llm_call_failed backend=%s model=%s latency_ms=%s "
                        "reason=%s prompt_tokens=%s attempt=%s",
                        self.backend_name,
                        self.model_name,
                        elapsed_ms,
                        "parse_error",
                        int(prompt_tokens_est),
                        attempt,
                    )
                raise LLMInvalidResponseError(
                    f"Gemini parse_error reason=parse_error"
                ) from e

        # Should not reach here, but safety net
        self._record_failure()
        raise LLMConnectionError(
            f"Gemini retries_exhausted reason=retries_exhausted attempts={self._max_retries}"
        )

    # -----------------------------------------------------------------------
    # Circuit breaker / quota helpers
    # -----------------------------------------------------------------------

    def _record_success(self, tokens_used: int = 0) -> None:
        """Record a successful API call to circuit breaker and quota tracker."""
        if self._circuit_breaker is not None:
            self._circuit_breaker.record_success()
        if self._quota_tracker is not None:
            self._quota_tracker.record(tokens_used)

    def _record_failure(self) -> None:
        """Record a failed API call to circuit breaker."""
        if self._circuit_breaker is not None:
            self._circuit_breaker.record_failure()

    # -----------------------------------------------------------------------
    # Streaming (Issue #411)
    # -----------------------------------------------------------------------

    def chat_stream(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
    ) -> Iterator[GeminiStreamChunk]:
        """Stream a chat completion via Gemini ``streamGenerateContent`` API.

        Yields ``GeminiStreamChunk`` objects as partial content arrives.
        The very first chunk has ``is_first_token=True`` and ``ttft_ms`` set.

        Circuit breaker and quota pre-flight checks are performed before the
        HTTP call, same as ``chat_detailed``.

        Args:
            messages: Chat messages.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.

        Yields:
            GeminiStreamChunk with incremental text and TTFT metadata.

        Example::

            for chunk in client.chat_stream(messages):
                if chunk.is_first_token:
                    print(f"[TTFT: {chunk.ttft_ms}ms]")
                print(chunk.content, end="", flush=True)
        """
        if not self._api_key:
            raise LLMConnectionError("Gemini API key missing")
        if not self._model:
            raise LLMInvalidResponseError("Gemini model not set")

        # Pre-flight: circuit breaker & quota
        if self._circuit_breaker is not None:
            try:
                self._circuit_breaker.check()
            except CircuitOpen:
                logger.warning("[GEMINI] Circuit breaker OPEN — skipping stream call")
                raise LLMConnectionError(
                    "Gemini circuit_open reason=circuit_open — "
                    "Gemini geçici olarak devre dışı, yerel model kullanılıyor"
                )

        if self._quota_tracker is not None:
            try:
                self._quota_tracker.check()
            except QuotaExceeded as exc:
                logger.warning("[GEMINI] Quota exceeded: %s", exc)
                raise LLMConnectionError(
                    "Gemini quota_exceeded reason=quota_exceeded — "
                    "Gemini quota aşıldı, yerel model kullanılıyor"
                )

        url = f"{self._base_url}/v1beta/models/{self._model}:streamGenerateContent"

        # Build payload (same as chat_detailed)
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

        t0 = time.perf_counter()
        ttft_measured = False
        ttft_ms: Optional[int] = None
        chunk_count = 0
        total_text = ""

        try:
            r = requests.post(
                url,
                params={"key": self._api_key},
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=self._timeout_seconds,
                stream=True,
            )

            if r.status_code != 200:
                self._record_failure()
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                if r.status_code == 429:
                    raise LLMConnectionError(
                        "Gemini rate_limited status=429 reason=rate_limited"
                    )
                if r.status_code in {401, 403}:
                    raise LLMConnectionError(
                        f"Gemini auth_error status={r.status_code} reason=auth_error"
                    )
                if r.status_code == 404:
                    raise LLMModelNotFoundError(
                        "Gemini model_not_found status=404 reason=model_not_found"
                    )
                if r.status_code >= 500:
                    raise LLMConnectionError(
                        f"Gemini server_error status={r.status_code} reason=server_error"
                    )
                raise LLMInvalidResponseError(
                    f"Gemini invalid_request status={r.status_code} reason=invalid_request"
                )

            # Gemini streamGenerateContent returns JSON array elements as
            # individual JSON objects separated by newlines (NDJSON-like).
            # We parse each chunk as it arrives.
            buffer = ""
            for raw_line in r.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue

                line = raw_line.strip()
                # Skip array delimiters
                if line in ("[", "]", ","):
                    continue
                # Strip leading comma if present
                if line.startswith(","):
                    line = line[1:].strip()

                # Accumulate lines that might be partial JSON
                buffer += line
                try:
                    chunk_data = json.loads(buffer)
                    buffer = ""
                except json.JSONDecodeError:
                    continue

                # Extract text from chunk
                candidates = chunk_data.get("candidates") or []
                if not candidates or not isinstance(candidates[0], dict):
                    continue

                cand = candidates[0]
                content_data = cand.get("content") or {}
                parts = content_data.get("parts") or []
                text_part = ""
                if parts and isinstance(parts[0], dict):
                    text_part = str(parts[0].get("text") or "")

                finish_reason = cand.get("finishReason")

                if text_part:
                    chunk_count += 1
                    total_text += text_part

                    if not ttft_measured:
                        ttft_ms = int((time.perf_counter() - t0) * 1000)
                        ttft_measured = True

                    yield GeminiStreamChunk(
                        content=text_part,
                        is_first_token=(chunk_count == 1),
                        ttft_ms=ttft_ms if chunk_count == 1 else None,
                        finish_reason=str(finish_reason) if finish_reason else None,
                    )

                elif finish_reason:
                    yield GeminiStreamChunk(
                        content="",
                        is_first_token=False,
                        ttft_ms=None,
                        finish_reason=str(finish_reason),
                    )

            # Record success
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            estimated_tokens = max(len(total_text) // 4, 1) if total_text else 0
            self._record_success(estimated_tokens)

            if _metrics_enabled():
                metrics_logger.info(
                    "llm_stream backend=%s model=%s latency_ms=%s ttft_ms=%s "
                    "chunks=%s total_chars=%s",
                    self.backend_name,
                    self.model_name,
                    elapsed_ms,
                    ttft_ms,
                    chunk_count,
                    len(total_text),
                )

        except requests.Timeout as e:
            self._record_failure()
            raise LLMTimeoutError(
                f"Gemini timeout reason=timeout timeout_s={self._timeout_seconds}"
            ) from e
        except requests.RequestException as e:
            self._record_failure()
            raise LLMConnectionError(
                "Gemini connection_error reason=connection_error"
            ) from e
        except (LLMConnectionError, LLMModelNotFoundError, LLMTimeoutError, LLMInvalidResponseError):
            raise
        except Exception as e:
            raise LLMInvalidResponseError(
                "Gemini parse_error reason=parse_error"
            ) from e

    def chat_stream_to_text(
        self,
        messages: List[LLMMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 512,
    ) -> tuple[str, Optional[int]]:
        """Stream then collect full text. Returns (text, ttft_ms).

        Convenience wrapper over ``chat_stream`` for callers that want the
        full text but also need the TTFT metric.
        """
        parts: list[str] = []
        ttft: Optional[int] = None
        for chunk in self.chat_stream(messages, temperature=temperature, max_tokens=max_tokens):
            parts.append(chunk.content)
            if chunk.is_first_token:
                ttft = chunk.ttft_ms
        return "".join(parts).strip(), ttft

    def complete_text(self, *, prompt: str, temperature: float = 0.0, max_tokens: int = 200, system_prompt: Optional[str] = None) -> str:
        messages: list[LLMMessage] = []
        if system_prompt:
            messages.append(LLMMessage(role="system", content=system_prompt))
        messages.append(LLMMessage(role="user", content=prompt))
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)


def _metrics_enabled() -> bool:
    # Keep this local to avoid import cycles; parse env here.
    raw = str(os.environ.get("BANTZ_LLM_METRICS", "")).strip().lower()
    if not raw:
        return False
    return raw in {"1", "true", "yes", "y", "on"}


def _calculate_backoff(
    attempt: int,
    retry_after_header: Optional[float] = None,
) -> float:
    """Calculate exponential backoff delay with jitter.

    If the server provided a Retry-After header, honour it (capped).
    Otherwise use exponential backoff: base * factor^(attempt-1).
    """
    if retry_after_header is not None and retry_after_header > 0:
        return min(retry_after_header, RETRY_MAX_DELAY)

    import random
    delay = RETRY_BASE_DELAY * (RETRY_BACKOFF_FACTOR ** (attempt - 1))
    # Add ±25 % jitter to avoid thundering herd
    jitter = delay * 0.25 * (2 * random.random() - 1)
    return min(delay + jitter, RETRY_MAX_DELAY)


def _parse_rate_limit_remaining(headers: dict) -> Optional[int]:
    """Parse X-RateLimit-Remaining from response headers."""
    for key in ("X-RateLimit-Remaining", "x-ratelimit-remaining"):
        val = headers.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
    return None


def _parse_retry_after(headers: dict) -> Optional[float]:
    """Parse Retry-After header (seconds) from response headers."""
    for key in ("Retry-After", "retry-after"):
        val = headers.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
    return None


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
