"""
Issue #874: Personality Injection — 3-Layer Personality → LLM Prompt.

Builds compact, injection-ready prompt blocks from:
  Layer 1: Persona (Personality preset — Jarvis/Friday/Alfred)
  Layer 2: User Preferences (UserProfile facts + style)
  Layer 3: Behavior Rules (confirmation, verbosity, routing)

Token budget: persona(200) + prefs(150) + rules(100) = max ~450 tokens.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token budget constants
# ---------------------------------------------------------------------------

_PERSONA_MAX_CHARS = 800    # ~200 tokens
_PREFS_MAX_CHARS = 600      # ~150 tokens
_RULES_MAX_CHARS = 400      # ~100 tokens
_TOTAL_MAX_CHARS = 1800     # ~450 tokens


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class PersonalityConfig:
    """Configuration for personality injection."""

    # Which preset to use (jarvis, friday, alfred, cortana, hal)
    preset_name: str = "jarvis"

    # User name override (if known from profile)
    user_name: str = ""

    # Behavior rules
    confirmation_mode: str = "dangerous"   # always | dangerous | never
    verbosity: str = "short"               # short | normal | detailed
    response_language: str = "tr"          # tr | en | auto

    # Token budgets
    persona_max_chars: int = _PERSONA_MAX_CHARS
    prefs_max_chars: int = _PREFS_MAX_CHARS
    rules_max_chars: int = _RULES_MAX_CHARS

    @classmethod
    def from_env(cls) -> "PersonalityConfig":
        """Build config from environment variables."""
        return cls(
            preset_name=os.getenv("BANTZ_PERSONALITY", "jarvis").lower(),
            user_name=os.getenv("BANTZ_USER_NAME", ""),
            confirmation_mode=os.getenv("BANTZ_CONFIRMATION_MODE", "dangerous"),
            verbosity=os.getenv("BANTZ_VERBOSITY", "short"),
        )


# ---------------------------------------------------------------------------
# PersonalityInjector
# ---------------------------------------------------------------------------

class PersonalityInjector:
    """
    Builds injection-ready personality blocks for LLM prompts.

    Usage in orchestrator:
        injector = PersonalityInjector()
        block = injector.build_router_block()       # for Phase 1
        block = injector.build_finalizer_block()     # for Phase 3
        identity = injector.build_identity_lines()   # replaces hardcoded BANTZ identity
    """

    def __init__(self, config: Optional[PersonalityConfig] = None) -> None:
        self.config = config or PersonalityConfig.from_env()
        self._personality: Any = None
        self._init_personality()

    def _init_personality(self) -> None:
        """Load personality preset (best-effort)."""
        try:
            from bantz.memory.personality import get_personality

            self._personality = get_personality(self.config.preset_name)
        except Exception as exc:
            logger.warning("[PERSONALITY] Failed to load preset '%s': %s",
                           self.config.preset_name, exc)
            self._personality = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def personality(self) -> Any:
        """Underlying Personality instance (may be None)."""
        return self._personality

    @property
    def name(self) -> str:
        """Active personality name."""
        if self._personality is not None:
            return self._personality.name
        return "Bantz"

    @property
    def uses_honorifics(self) -> bool:
        """Whether the active personality uses honorifics."""
        if self._personality is not None:
            return self._personality.use_honorifics
        return True  # default Jarvis behavior

    # ------------------------------------------------------------------
    # Layer 1: Persona Block
    # ------------------------------------------------------------------

    def _build_persona_block(self, user_name: str = "") -> str:
        """Build Layer 1: Persona identity block."""
        name = user_name or self.config.user_name or "kullanıcı"
        p = self._personality

        if p is None:
            return f"Sen Bantz'sın, {name}'nın kişisel asistanısın."

        parts: list[str] = [
            f"Sen {p.name}'sin, {name}'nın kişisel asistanısın.",
        ]

        # Speaking style
        style_desc = getattr(p.speaking_style, "description_tr", "Samimi iletişim")
        parts.append(f"İletişim tarzın: {style_desc}.")

        # Honorifics
        if p.use_honorifics:
            parts.append("'Efendim' hitabını kullan (yanıt başına en fazla 1 kez).")
        else:
            parts.append("Samimi bir dil kullan, resmi hitaplardan kaçın.")

        # Humor
        if p.witty_remarks and p.sarcasm_level > 0:
            level = "hafif" if p.sarcasm_level < 0.3 else "orta"
            parts.append(f"Zaman zaman {level} espri yapabilirsin.")

        # Verbosity from config
        if self.config.verbosity == "short":
            parts.append("Kısa ve öz yanıtlar ver (1-3 cümle).")
        elif self.config.verbosity == "detailed":
            parts.append("Detaylı açıklamalar yap, adım adım anlat.")
        else:
            parts.append("Normal uzunlukta yanıtlar ver.")

        block = "\n".join(parts)
        return block[:self.config.persona_max_chars]

    # ------------------------------------------------------------------
    # Layer 2: User Preferences Block (from profile data)
    # ------------------------------------------------------------------

    def _build_prefs_block(
        self,
        facts: Optional[Dict[str, str]] = None,
        preferences: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build Layer 2: User preferences block."""
        parts: list[str] = []

        if facts:
            fact_lines = [f"- {k}: {v}" for k, v in list(facts.items())[:8]]
            if fact_lines:
                parts.append("Kullanıcı hakkında bildiklerin:")
                parts.extend(fact_lines)

        if preferences:
            pref_lines: list[str] = []
            for key, pref in list(preferences.items())[:6]:
                if hasattr(pref, "is_reliable") and pref.is_reliable:
                    pref_lines.append(f"- {key}: {pref.value}")
                elif isinstance(pref, dict) and pref.get("confidence", 0) >= 0.5:
                    pref_lines.append(f"- {key}: {pref.get('value', pref)}")
            if pref_lines:
                if parts:
                    parts.append("")
                parts.append("Tercihleri:")
                parts.extend(pref_lines)

        block = "\n".join(parts)
        return block[:self.config.prefs_max_chars]

    # ------------------------------------------------------------------
    # Layer 3: Behavior Rules Block
    # ------------------------------------------------------------------

    def _build_rules_block(self) -> str:
        """Build Layer 3: Behavior rules block."""
        rules: list[str] = ["Davranış kuralları:"]

        # Confirmation mode
        mode = self.config.confirmation_mode
        if mode == "always":
            rules.append("- Tüm işlemlerde onay iste.")
        elif mode == "never":
            rules.append("- Onay istemeden doğrudan yap.")
        else:  # dangerous
            rules.append("- Riskli işlemlerde (silme, güncelleme) onay iste.")

        # Language
        rules.append("- SADECE TÜRKÇE konuş. Çince, Korece, İngilizce YASAK.")

        # Output format
        rules.append("- Sadece kullanıcıya söyleyeceğin düz metin üret. JSON/Markdown yok.")

        # Honesty
        rules.append("- Bilmediğin konularda dürüst ol.")

        block = "\n".join(rules)
        return block[:self.config.rules_max_chars]

    # ------------------------------------------------------------------
    # Combined Blocks (for Router & Finalizer)
    # ------------------------------------------------------------------

    def build_router_block(
        self,
        user_name: str = "",
        facts: Optional[Dict[str, str]] = None,
        preferences: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Build full personality block for Phase 1 (router/planner) injection.

        Returns a multi-line string suitable for appending to context_parts.
        """
        sections: list[str] = []

        persona = self._build_persona_block(user_name)
        if persona:
            sections.append(persona)

        prefs = self._build_prefs_block(facts, preferences)
        if prefs:
            sections.append(prefs)

        combined = "\n\n".join(sections)

        # Enforce total budget
        if len(combined) > _TOTAL_MAX_CHARS:
            combined = combined[:_TOTAL_MAX_CHARS]
            nl = combined.rfind("\n")
            if nl > 0:
                combined = combined[:nl]

        return combined

    def build_finalizer_block(
        self,
        user_name: str = "",
        facts: Optional[Dict[str, str]] = None,
        preferences: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Build full personality block for Phase 3 (finalizer) injection.

        Includes all 3 layers: persona + prefs + rules.
        """
        sections: list[str] = []

        persona = self._build_persona_block(user_name)
        if persona:
            sections.append(persona)

        prefs = self._build_prefs_block(facts, preferences)
        if prefs:
            sections.append(prefs)

        rules = self._build_rules_block()
        if rules:
            sections.append(rules)

        combined = "\n\n".join(sections)

        # Enforce total budget
        if len(combined) > _TOTAL_MAX_CHARS:
            combined = combined[:_TOTAL_MAX_CHARS]
            nl = combined.rfind("\n")
            if nl > 0:
                combined = combined[:nl]

        return combined

    def build_identity_lines(self, user_name: str = "") -> str:
        """
        Build identity lines to replace hardcoded 'BANTZ' in _build_system_prompt.

        Returns compact identity string for PromptBuilder injection.
        """
        name = user_name or self.config.user_name or "USER"
        p = self._personality

        persona_name = p.name if p is not None else "Bantz"

        lines = [
            f"- Sen {persona_name}'sin. Kullanıcı {name}'dır.",
            "- SADECE TÜRKÇE konuş. Asla Çince, Korece, İngilizce veya başka dil kullanma!",
        ]

        if self.uses_honorifics:
            lines.append("- 'Efendim' hitabını kullan.")
        else:
            lines.append("- Samimi bir dil kullan.")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def switch_preset(self, preset_name: str) -> None:
        """Switch to a different personality preset."""
        self.config.preset_name = preset_name.lower()
        self._init_personality()
        logger.info("[PERSONALITY] Switched to preset: %s", self.name)

    def update_user_name(self, name: str) -> None:
        """Update the user name from profile."""
        self.config.user_name = name

    def __repr__(self) -> str:
        return (
            f"PersonalityInjector(preset={self.config.preset_name!r}, "
            f"name={self.name!r}, "
            f"honorifics={self.uses_honorifics})"
        )
