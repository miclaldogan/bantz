# SPDX-License-Identifier: MIT
"""
Language Bridge — TR↔EN translation layer for brain-level routing (Issue #1241).

The 3B/7B router models produce significantly more accurate route/plan
output when the input is in English.  This module transparently translates
Turkish user input into canonical English for the router while preserving
the original text and protected entities (proper nouns, JSON, CLI commands).

Architecture
~~~~~~~~~~~~

    User (TR) ──► LanguageBridge.to_en() ──► canonical_en ──► Router (EN)
                                           ├─ protected_spans
                                           └─ original (TR)

    Finalizer (EN/TR) ──► LanguageBridge.to_tr() ──► User (TR)

Design principles:
  - Feature-flag gated (``BANTZ_BRIDGE_ENABLED``)
  - Local NMT only — no cloud calls, no 429 risk
  - Lazy model loading (first use)
  - Protected span mechanism preserves entities, JSON, CLI commands
  - < 100 ms per translation (MarianMT on CPU)
  - Graceful degradation: import/model errors → bridge disabled
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = [
    "BridgeResult",
    "LanguageBridge",
    "get_bridge",
]


# ============================================================================
# Result dataclass
# ============================================================================


@dataclass(frozen=True, slots=True)
class BridgeResult:
    """Result of a translation operation.

    Attributes:
        canonical: Translated text (EN for to_en, TR for to_tr).
        detected_lang: Detected source language ("tr", "en", "unknown").
        protected_spans: Entity strings that were shielded from translation.
        original: Original untranslated text.
    """

    canonical: str
    detected_lang: str
    protected_spans: tuple[str, ...] = ()
    original: str = ""


# ============================================================================
# Constants
# ============================================================================

# CLI commands that must never be translated
_CLI_COMMANDS = frozenset({
    "exit", "quit", "clear", "help", "status",
    "history", "reset", "config", "version",
})

# Prefixes for CLI commands (e.g. "agent: ...")
_CLI_PREFIXES = ("agent:", "agent ", "ses:", "voice:")

# Regex to detect JSON blocks
_JSON_BLOCK_RE = re.compile(r"\{[^{}]*\}")

# Placeholder template for protected spans
_PLACEHOLDER = "<PROT_{i}>"

# Turkish-specific characters for language detection
_TURKISH_CHARS = set("ıİğĞüÜşŞöÖçÇâÂîÎûÛ")

# Common Turkish words (lightweight detection — no LLM needed)
_TR_MARKERS = re.compile(
    r"\b(bir|ve|bu|için|ile|var|yok|değil|evet|hayır|tamam|"
    r"nasıl|nerede|ne|şey|çok|sonra|şimdi|yarın|bugün|"
    r"bak|aç|kapat|oku|göster|listele|kontrol|ekle|sil|"
    r"lütfen|bana|benim|benim|senin|onun|"
    r"merhaba|günaydın|selam|efendim|dostum|"
    r"mail|posta|takvim|etkinlik|toplantı|"
    r"gelen|giden|gönder|al|ver|yap|git|gel|"
    r"kahvaltı|öğle|akşam|sabah)\b",
    re.IGNORECASE,
)

# Common English words for detection
_EN_MARKERS = re.compile(
    r"\b(the|is|are|was|were|have|has|had|will|would|"
    r"can|could|should|shall|may|might|"
    r"what|where|when|who|how|why|"
    r"this|that|these|those|"
    r"my|your|his|her|its|our|their|"
    r"check|open|read|show|list|send|get|"
    r"please|yes|no|okay|hello|hi|hey|"
    r"mail|email|calendar|event|meeting|"
    r"tomorrow|today|yesterday|morning|afternoon)\b",
    re.IGNORECASE,
)

# Entity patterns — things to protect from translation
# Uppercase words (likely proper nouns/acronyms): TÜBİTAK, NASA, etc.
_PROPER_NOUN_RE = re.compile(r"\b[A-ZÇĞIİÖŞÜ][A-ZÇĞIİÖŞÜa-zçğıiöşü]*(?:\s+[A-ZÇĞIİÖŞÜ][A-ZÇĞIİÖŞÜa-zçğıiöşü]*)*\b")

# Email addresses
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")

# Quoted strings
_QUOTED_RE = re.compile(r'"[^"]*"|\'[^\']*\'')

# MarianMT model names
_MARIAN_TR_EN = "Helsinki-NLP/opus-mt-tr-en"
_MARIAN_EN_TR = "Helsinki-NLP/opus-mt-tc-big-en-tr"


# ============================================================================
# LanguageBridge
# ============================================================================


class LanguageBridge:
    """Translates between Turkish and English using local NMT models.

    The bridge is feature-flag gated via ``BANTZ_BRIDGE_ENABLED``.
    Models are loaded lazily on first use.

    Usage::

        bridge = LanguageBridge()
        result = bridge.to_en("yarın takvimime bak")
        # result.canonical  → "look at my calendar tomorrow"
        # result.detected_lang → "tr"

        tr_text = bridge.to_tr("Your calendar has 3 events tomorrow.")
        # → "Yarın takviminizde 3 etkinlik var."

    Thread safety: NOT thread-safe (model loading). Create one per process.
    """

    def __init__(self, *, engine: str = "") -> None:
        self._engine = engine or os.getenv("BANTZ_BRIDGE_ENGINE", "marianmt")
        self._log_translations = os.getenv("BANTZ_BRIDGE_LOG", "0") == "1"
        self._cache_ttl = int(os.getenv("BANTZ_BRIDGE_CACHE_TTL", "300"))

        # Lazy-loaded models
        self._tr_en_model = None
        self._tr_en_tokenizer = None
        self._en_tr_model = None
        self._en_tr_tokenizer = None

        # Simple LRU cache {text: (translation, timestamp)}
        self._cache_tr_en: dict[str, tuple[str, float]] = {}
        self._cache_en_tr: dict[str, tuple[str, float]] = {}
        self._cache_max = 256

        self._available: Optional[bool] = None  # None = not yet checked

    # ── Public API ──────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """Check if translation models can be loaded."""
        if self._available is None:
            try:
                import transformers  # noqa: F401
                import sentencepiece  # noqa: F401
                self._available = True
            except ImportError:
                self._available = False
                logger.warning(
                    "[BRIDGE] transformers/sentencepiece not installed — "
                    "bridge disabled"
                )
        return self._available

    def detect(self, text: str) -> str:
        """Detect the language of *text*.

        Returns ``"tr"``, ``"en"``, or ``"unknown"``.
        Uses lightweight heuristics — no model calls.
        """
        if not text or len(text.strip()) < 2:
            return "unknown"

        text_lower = text.lower()

        # Check for Turkish-specific characters
        has_turkish = any(c in _TURKISH_CHARS for c in text)

        # Count marker hits
        tr_hits = len(_TR_MARKERS.findall(text_lower))
        en_hits = len(_EN_MARKERS.findall(text_lower))

        # Turkish chars are a strong signal
        if has_turkish and tr_hits >= en_hits:
            return "tr"
        if has_turkish and tr_hits > 0:
            return "tr"

        # Pure marker comparison
        if tr_hits > en_hits:
            return "tr"
        if en_hits > tr_hits:
            return "en"

        # If has Turkish chars but no markers, still likely Turkish
        if has_turkish:
            return "tr"

        return "unknown"

    def to_en(self, text: str) -> BridgeResult:
        """Translate Turkish text to English.

        Protected entities (proper nouns, JSON, CLI commands, quoted strings)
        are extracted before translation and restored after.

        If input is already English or the bridge is unavailable,
        returns the original text as canonical.
        """
        original = text
        stripped = text.strip()

        # ── Bypass checks ───────────────────────────────────────────
        if not stripped:
            return BridgeResult(
                canonical=stripped, detected_lang="unknown",
                original=original,
            )

        # CLI commands → never translate
        if self._is_cli_command(stripped):
            return BridgeResult(
                canonical=stripped, detected_lang="unknown",
                original=original,
            )

        lang = self.detect(stripped)

        # Already English → pass through
        if lang == "en":
            return BridgeResult(
                canonical=stripped, detected_lang="en",
                original=original,
            )

        # Bridge unavailable → pass through
        if not self.available:
            return BridgeResult(
                canonical=stripped, detected_lang=lang,
                original=original,
            )

        # ── Extract protected spans ─────────────────────────────────
        clean_text, protected = self._extract_protected_spans(stripped)

        # ── Translate ───────────────────────────────────────────────
        translated = self._translate_tr_en(clean_text)

        # ── Restore protected spans ─────────────────────────────────
        translated = self._restore_protected_spans(translated, protected)

        result = BridgeResult(
            canonical=translated,
            detected_lang=lang,
            protected_spans=tuple(protected.values()),
            original=original,
        )

        if self._log_translations:
            logger.info(
                "[BRIDGE] TR→EN lang=%s canonical=%r protected=%s",
                lang, translated, list(protected.values()),
            )

        return result

    def to_tr(self, text: str) -> str:
        """Translate English text to Turkish.

        Returns the translated text, or the original if bridge is unavailable
        or text is already Turkish.
        """
        if not text or not text.strip():
            return text

        lang = self.detect(text)
        if lang == "tr":
            return text

        if not self.available:
            return text

        translated = self._translate_en_tr(text.strip())

        if self._log_translations:
            logger.info("[BRIDGE] EN→TR original=%r translated=%r", text, translated)

        return translated

    # ── Protected span handling ─────────────────────────────────────

    def _is_cli_command(self, text: str) -> bool:
        """Check if text is a CLI command that should not be translated."""
        text_lower = text.lower().strip()

        # Exact CLI commands
        if text_lower in _CLI_COMMANDS:
            return True

        # CLI prefixes
        if any(text_lower.startswith(p) for p in _CLI_PREFIXES):
            return True

        return False

    def _extract_protected_spans(self, text: str) -> tuple[str, dict[str, str]]:
        """Extract entities that should not be translated.

        Returns (cleaned_text, {placeholder: original_span}).
        """
        protected: dict[str, str] = {}
        counter = 0

        def _protect(match_text: str) -> str:
            nonlocal counter
            ph = _PLACEHOLDER.format(i=counter)
            protected[ph] = match_text
            counter += 1
            return ph

        result = text

        # 1) JSON blocks
        for m in _JSON_BLOCK_RE.finditer(result):
            result = result.replace(m.group(), _protect(m.group()), 1)

        # 2) Email addresses
        for m in _EMAIL_RE.finditer(result):
            result = result.replace(m.group(), _protect(m.group()), 1)

        # 3) Quoted strings
        for m in _QUOTED_RE.finditer(result):
            result = result.replace(m.group(), _protect(m.group()), 1)

        # 4) Proper nouns / acronyms (2+ uppercase chars, not common words)
        _common_tr_upper = {
            "Ben", "Sen", "Biz", "Siz", "Benim", "Senin",
            "Yarın", "Bugün", "Hayır", "Evet", "Tamam",
        }
        for m in _PROPER_NOUN_RE.finditer(result):
            span = m.group()
            # Only protect if it's truly a proper noun (all caps or not common)
            if len(span) >= 2 and span not in _common_tr_upper:
                # All uppercase = acronym → protect
                if span.isupper() and len(span) >= 2:
                    result = result.replace(span, _protect(span), 1)
                # Mixed case multi-word = likely person/org name
                elif " " in span and not span.lower() in {"bir şey", "ne zaman"}:
                    result = result.replace(span, _protect(span), 1)

        return result, protected

    def _restore_protected_spans(
        self, text: str, protected: dict[str, str]
    ) -> str:
        """Restore protected spans in translated text."""
        result = text
        for placeholder, original in protected.items():
            result = result.replace(placeholder, original)
        return result

    # ── Translation engine ──────────────────────────────────────────

    def _ensure_tr_en_model(self) -> None:
        """Lazy-load TR→EN MarianMT model."""
        if self._tr_en_model is not None:
            return

        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        logger.info("[BRIDGE] Loading TR→EN model: %s", _MARIAN_TR_EN)
        self._tr_en_tokenizer = AutoTokenizer.from_pretrained(_MARIAN_TR_EN)
        self._tr_en_model = AutoModelForSeq2SeqLM.from_pretrained(_MARIAN_TR_EN)
        self._tr_en_model.eval()
        logger.info("[BRIDGE] TR→EN model ready")

    def _ensure_en_tr_model(self) -> None:
        """Lazy-load EN→TR MarianMT model."""
        if self._en_tr_model is not None:
            return

        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        logger.info("[BRIDGE] Loading EN→TR model: %s", _MARIAN_EN_TR)
        self._en_tr_tokenizer = AutoTokenizer.from_pretrained(_MARIAN_EN_TR)
        self._en_tr_model = AutoModelForSeq2SeqLM.from_pretrained(_MARIAN_EN_TR)
        self._en_tr_model.eval()
        logger.info("[BRIDGE] EN→TR model ready")

    def _translate_tr_en(self, text: str) -> str:
        """Translate Turkish text to English using MarianMT."""
        import time

        # Check cache
        cached = self._cache_tr_en.get(text)
        if cached:
            translation, ts = cached
            if time.time() - ts < self._cache_ttl:
                return translation
            del self._cache_tr_en[text]

        try:
            self._ensure_tr_en_model()

            inputs = self._tr_en_tokenizer(
                text, return_tensors="pt", padding=True, truncation=True,
                max_length=512,
            )
            outputs = self._tr_en_model.generate(**inputs, max_new_tokens=512)
            translated = self._tr_en_tokenizer.decode(
                outputs[0], skip_special_tokens=True
            )

            # Update cache
            self._cache_tr_en[text] = (translated, time.time())
            if len(self._cache_tr_en) > self._cache_max:
                # Evict oldest
                oldest = next(iter(self._cache_tr_en))
                del self._cache_tr_en[oldest]

            return translated

        except Exception as e:
            logger.warning("[BRIDGE] TR→EN translation failed: %s", e)
            return text  # fallback to original

    def _translate_en_tr(self, text: str) -> str:
        """Translate English text to Turkish using MarianMT."""
        import time

        # Check cache
        cached = self._cache_en_tr.get(text)
        if cached:
            translation, ts = cached
            if time.time() - ts < self._cache_ttl:
                return translation
            del self._cache_en_tr[text]

        try:
            self._ensure_en_tr_model()

            inputs = self._en_tr_tokenizer(
                text, return_tensors="pt", padding=True, truncation=True,
                max_length=512,
            )
            outputs = self._en_tr_model.generate(**inputs, max_new_tokens=512)
            translated = self._en_tr_tokenizer.decode(
                outputs[0], skip_special_tokens=True
            )

            # Update cache
            self._cache_en_tr[text] = (translated, time.time())
            if len(self._cache_en_tr) > self._cache_max:
                oldest = next(iter(self._cache_en_tr))
                del self._cache_en_tr[oldest]

            return translated

        except Exception as e:
            logger.warning("[BRIDGE] EN→TR translation failed: %s", e)
            return text  # fallback to original


# ============================================================================
# Singleton accessor
# ============================================================================

_bridge_instance: Optional[LanguageBridge] = None


def get_bridge() -> Optional[LanguageBridge]:
    """Return the singleton LanguageBridge if enabled, else None.

    Reads ``BANTZ_BRIDGE_ENABLED`` on first call.  If the env var is
    falsy (``0``, ``false``, ``no``, empty), returns ``None`` and the
    caller should skip all bridge logic.

    Usage::

        bridge = get_bridge()
        if bridge:
            result = bridge.to_en(user_input)
            canonical = result.canonical
        else:
            canonical = user_input
    """
    global _bridge_instance

    if _bridge_instance is not None:
        return _bridge_instance

    enabled_raw = os.getenv("BANTZ_BRIDGE_ENABLED", "0").strip().lower()
    if enabled_raw not in ("1", "true", "yes", "on"):
        return None

    try:
        _bridge_instance = LanguageBridge()
        if _bridge_instance.available:
            logger.info("[BRIDGE] LanguageBridge initialized (engine=%s)", _bridge_instance._engine)
        else:
            logger.warning("[BRIDGE] LanguageBridge unavailable — dependencies missing")
            _bridge_instance = None
    except Exception as e:
        logger.warning("[BRIDGE] LanguageBridge init failed: %s", e)
        _bridge_instance = None

    return _bridge_instance
