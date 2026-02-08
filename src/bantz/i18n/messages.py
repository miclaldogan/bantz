"""
Turkish Error Messages — Issue #440.

All user-facing error messages in Turkish. Maps internal error codes
to human-friendly Turkish text, preventing English leakage to end users.

Usage::

    from bantz.i18n.messages import tr, ErrorCode

    # Get Turkish error message
    msg = tr(ErrorCode.LLM_TIMEOUT)
    # → "Yapay zekâ yanıt vermedi. Lütfen tekrar deneyin."

    # With format arguments
    msg = tr(ErrorCode.TOOL_FAILED, tool_name="takvim")
    # → "takvim aracı çalışırken bir hata oluştu."

    # Fallback for unknown codes
    msg = tr("unknown_code")
    # → "Bir hata oluştu. Lütfen tekrar deneyin."
"""

from __future__ import annotations

import logging
from enum import Enum, unique
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Error Codes
# ─────────────────────────────────────────────────────────────────


@unique
class ErrorCode(str, Enum):
    """Internal error codes for all Bantz subsystems."""

    # ── LLM / Model ────────────────────────────────────────────
    LLM_TIMEOUT = "llm_timeout"
    LLM_OVERLOADED = "llm_overloaded"
    LLM_INVALID_RESPONSE = "llm_invalid_response"
    LLM_CONNECTION_ERROR = "llm_connection_error"
    LLM_JSON_PARSE_ERROR = "llm_json_parse_error"
    LLM_CONTEXT_TOO_LONG = "llm_context_too_long"

    # ── Gemini ─────────────────────────────────────────────────
    GEMINI_UNAVAILABLE = "gemini_unavailable"
    GEMINI_QUOTA_EXCEEDED = "gemini_quota_exceeded"
    GEMINI_SAFETY_BLOCK = "gemini_safety_block"
    GEMINI_TIMEOUT = "gemini_timeout"

    # ── vLLM ───────────────────────────────────────────────────
    VLLM_DOWN = "vllm_down"
    VLLM_RESTART_FAILED = "vllm_restart_failed"
    VLLM_HEALTH_CHECK_FAILED = "vllm_health_check_failed"

    # ── Router ─────────────────────────────────────────────────
    ROUTER_NO_MATCH = "router_no_match"
    ROUTER_LOW_CONFIDENCE = "router_low_confidence"

    # ── Tools ──────────────────────────────────────────────────
    TOOL_FAILED = "tool_failed"
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_AUTH_ERROR = "tool_auth_error"

    # ── Calendar ───────────────────────────────────────────────
    CALENDAR_AUTH_EXPIRED = "calendar_auth_expired"
    CALENDAR_NOT_FOUND = "calendar_not_found"
    CALENDAR_CONFLICT = "calendar_conflict"
    CALENDAR_API_ERROR = "calendar_api_error"

    # ── Gmail ──────────────────────────────────────────────────
    GMAIL_AUTH_EXPIRED = "gmail_auth_expired"
    GMAIL_SEND_FAILED = "gmail_send_failed"
    GMAIL_NOT_FOUND = "gmail_not_found"
    GMAIL_API_ERROR = "gmail_api_error"

    # ── Security ───────────────────────────────────────────────
    SECURITY_POLICY_BLOCKED = "security_policy_blocked"
    SECURITY_CONFIRMATION_REQUIRED = "security_confirmation_required"
    SECURITY_INJECTION_DETECTED = "security_injection_detected"
    SECURITY_RATE_LIMITED = "security_rate_limited"

    # ── Voice ──────────────────────────────────────────────────
    VOICE_RECOGNITION_FAILED = "voice_recognition_failed"
    VOICE_NO_SPEECH = "voice_no_speech"
    VOICE_TOO_NOISY = "voice_too_noisy"
    VOICE_MIC_ERROR = "voice_mic_error"

    # ── System ─────────────────────────────────────────────────
    SYSTEM_ERROR = "system_error"
    SYSTEM_CONFIG_ERROR = "system_config_error"
    SYSTEM_MEMORY_LOW = "system_memory_low"

    # ── Quality Gating ─────────────────────────────────────────
    QUALITY_RATE_LIMITED = "quality_rate_limited"
    QUALITY_FALLBACK = "quality_fallback"

    # ── Generic ────────────────────────────────────────────────
    UNKNOWN = "unknown"


# ─────────────────────────────────────────────────────────────────
# Turkish Message Registry
# ─────────────────────────────────────────────────────────────────

_MESSAGES_TR: Dict[str, str] = {
    # ── LLM / Model ──
    ErrorCode.LLM_TIMEOUT:
        "Yapay zekâ yanıt vermedi. Lütfen tekrar deneyin.",
    ErrorCode.LLM_OVERLOADED:
        "Sistem şu anda yoğun. Lütfen birkaç saniye bekleyin.",
    ErrorCode.LLM_INVALID_RESPONSE:
        "Yapay zekâdan geçersiz bir yanıt alındı. Tekrar deniyorum.",
    ErrorCode.LLM_CONNECTION_ERROR:
        "Yapay zekâ sunucusuna bağlanılamadı.",
    ErrorCode.LLM_JSON_PARSE_ERROR:
        "Yapay zekâ yanıtı ayrıştırılamadı. Tekrar deneniyor.",
    ErrorCode.LLM_CONTEXT_TOO_LONG:
        "Mesaj çok uzun. Lütfen daha kısa bir ifade deneyin.",

    # ── Gemini ──
    ErrorCode.GEMINI_UNAVAILABLE:
        "Gemini şu anda kullanılamıyor. Hızlı model ile devam ediyorum.",
    ErrorCode.GEMINI_QUOTA_EXCEEDED:
        "Gemini kullanım kotası aşıldı. Hızlı model ile devam ediyorum.",
    ErrorCode.GEMINI_SAFETY_BLOCK:
        "İçerik güvenlik filtresi tarafından engellendi.",
    ErrorCode.GEMINI_TIMEOUT:
        "Gemini yanıt vermedi. Hızlı model ile devam ediyorum.",

    # ── vLLM ──
    ErrorCode.VLLM_DOWN:
        "Yerel yapay zekâ sunucusu çalışmıyor. Yeniden başlatılıyor.",
    ErrorCode.VLLM_RESTART_FAILED:
        "Yapay zekâ sunucusu yeniden başlatılamadı.",
    ErrorCode.VLLM_HEALTH_CHECK_FAILED:
        "Yapay zekâ sunucusu sağlık kontrolünü geçemedi.",

    # ── Router ──
    ErrorCode.ROUTER_NO_MATCH:
        "Ne demek istediğinizi anlayamadım. Lütfen başka bir şekilde ifade edin.",
    ErrorCode.ROUTER_LOW_CONFIDENCE:
        "Tam olarak anlayamadım. Şunu mu demek istediniz?",

    # ── Tools ──
    ErrorCode.TOOL_FAILED:
        "{tool_name} aracı çalışırken bir hata oluştu.",
    ErrorCode.TOOL_NOT_FOUND:
        "İstenen araç bulunamadı: {tool_name}",
    ErrorCode.TOOL_TIMEOUT:
        "{tool_name} aracı zaman aşımına uğradı.",
    ErrorCode.TOOL_AUTH_ERROR:
        "{tool_name} için yetkilendirme hatası. Lütfen izinleri kontrol edin.",

    # ── Calendar ──
    ErrorCode.CALENDAR_AUTH_EXPIRED:
        "Google Takvim oturumunuz sona erdi. Lütfen tekrar giriş yapın.",
    ErrorCode.CALENDAR_NOT_FOUND:
        "Belirtilen etkinlik bulunamadı.",
    ErrorCode.CALENDAR_CONFLICT:
        "Bu zaman diliminde zaten bir etkinlik var.",
    ErrorCode.CALENDAR_API_ERROR:
        "Google Takvim'e erişirken bir sorun oluştu.",

    # ── Gmail ──
    ErrorCode.GMAIL_AUTH_EXPIRED:
        "Gmail oturumunuz sona erdi. Lütfen tekrar giriş yapın.",
    ErrorCode.GMAIL_SEND_FAILED:
        "E-posta gönderilemedi. Lütfen tekrar deneyin.",
    ErrorCode.GMAIL_NOT_FOUND:
        "Belirtilen e-posta bulunamadı.",
    ErrorCode.GMAIL_API_ERROR:
        "Gmail'e erişirken bir sorun oluştu.",

    # ── Security ──
    ErrorCode.SECURITY_POLICY_BLOCKED:
        "Bu işlem güvenlik politikası tarafından engellendi.",
    ErrorCode.SECURITY_CONFIRMATION_REQUIRED:
        "Bu işlem onay gerektiriyor. Devam etmek istiyor musunuz?",
    ErrorCode.SECURITY_INJECTION_DETECTED:
        "Güvenlik ihlali algılandı. İşlem reddedildi.",
    ErrorCode.SECURITY_RATE_LIMITED:
        "Çok fazla istek gönderildi. Lütfen biraz bekleyin.",

    # ── Voice ──
    ErrorCode.VOICE_RECOGNITION_FAILED:
        "Sesinizi anlayamadım. Lütfen tekrar söyleyin.",
    ErrorCode.VOICE_NO_SPEECH:
        "Herhangi bir konuşma algılanmadı.",
    ErrorCode.VOICE_TOO_NOISY:
        "Ortam çok gürültülü. Lütfen daha sessiz bir yerde deneyin.",
    ErrorCode.VOICE_MIC_ERROR:
        "Mikrofona erişilemiyor. Lütfen mikrofon ayarlarını kontrol edin.",

    # ── System ──
    ErrorCode.SYSTEM_ERROR:
        "Beklenmeyen bir hata oluştu. Lütfen tekrar deneyin.",
    ErrorCode.SYSTEM_CONFIG_ERROR:
        "Yapılandırma hatası algılandı. Lütfen ayarları kontrol edin.",
    ErrorCode.SYSTEM_MEMORY_LOW:
        "Sistem belleği düşük. Bazı işlemler yavaşlayabilir.",

    # ── Quality Gating ──
    ErrorCode.QUALITY_RATE_LIMITED:
        "Kalite modeli kullanım limiti aşıldı. Hızlı model ile devam ediyorum.",
    ErrorCode.QUALITY_FALLBACK:
        "Kalite modeline ulaşılamadı. Hızlı model ile devam ediyorum.",

    # ── Generic ──
    ErrorCode.UNKNOWN:
        "Bir hata oluştu. Lütfen tekrar deneyin.",
}

# Fallback message
_FALLBACK_TR = "Bir hata oluştu. Lütfen tekrar deneyin."


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────


def tr(code: str | ErrorCode, **kwargs: Any) -> str:
    """Get Turkish error message for the given code.

    Args:
        code: Error code (ErrorCode enum or string).
        **kwargs: Format arguments (e.g. tool_name="takvim").

    Returns:
        Turkish error message string.
    """
    # Normalize to string key
    key = code.value if isinstance(code, ErrorCode) else str(code)

    # Lookup by enum or string
    template: Optional[str] = None
    if isinstance(code, ErrorCode):
        template = _MESSAGES_TR.get(code)
    if template is None:
        # Try string lookup
        for ec, msg in _MESSAGES_TR.items():
            if ec.value == key:
                template = msg
                break

    if template is None:
        logger.warning("No Turkish message for error code: %s", key)
        template = _FALLBACK_TR

    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def get_all_messages() -> Dict[str, str]:
    """Return all Turkish error messages (for testing/export)."""
    return {ec.value: msg for ec, msg in _MESSAGES_TR.items()}


def get_error_code(code_str: str) -> ErrorCode:
    """Convert a string to an ErrorCode enum, or UNKNOWN if not found."""
    try:
        return ErrorCode(code_str)
    except ValueError:
        return ErrorCode.UNKNOWN


def is_retriable(code: str | ErrorCode) -> bool:
    """Check if an error is retriable (user can retry the action).

    Returns True for transient errors, False for permanent ones.
    """
    key = code.value if isinstance(code, ErrorCode) else str(code)
    retriable_codes = {
        ErrorCode.LLM_TIMEOUT.value,
        ErrorCode.LLM_OVERLOADED.value,
        ErrorCode.LLM_INVALID_RESPONSE.value,
        ErrorCode.LLM_CONNECTION_ERROR.value,
        ErrorCode.LLM_JSON_PARSE_ERROR.value,
        ErrorCode.GEMINI_UNAVAILABLE.value,
        ErrorCode.GEMINI_TIMEOUT.value,
        ErrorCode.VLLM_DOWN.value,
        ErrorCode.TOOL_FAILED.value,
        ErrorCode.TOOL_TIMEOUT.value,
        ErrorCode.VOICE_RECOGNITION_FAILED.value,
        ErrorCode.VOICE_TOO_NOISY.value,
        ErrorCode.GMAIL_SEND_FAILED.value,
        ErrorCode.CALENDAR_API_ERROR.value,
        ErrorCode.GMAIL_API_ERROR.value,
        ErrorCode.SYSTEM_ERROR.value,
        ErrorCode.QUALITY_RATE_LIMITED.value,
        ErrorCode.QUALITY_FALLBACK.value,
    }
    return key in retriable_codes
