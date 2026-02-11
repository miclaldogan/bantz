"""
Issue #873: Persistent User Memory — UserMemoryBridge.

Façade that wraps ProfileManager + MemoryStore + LearningEngine + ContextBuilder
into a single entry point for OrchestratorLoop.

Two hooks:
  1. on_turn_start(user_input) → dict with profile_context block for LLM prompt
  2. on_turn_end(user_input, reply, route, tool_results) → learn + persist

All operations are best-effort (never crashes the orchestrator).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class UserMemoryConfig:
    """Configuration for UserMemoryBridge."""

    profile_path: str = "~/.bantz/profile.json"
    db_path: str = "~/.bantz/memory.db"

    # How many memories to recall per turn
    max_recall: int = 5
    # Minimum importance for recalled memories
    min_importance: float = 0.1
    # Maximum chars for the profile context block injected into prompt
    max_context_chars: int = 600

    # Feature flags
    learn_facts: bool = True
    learn_preferences: bool = True
    store_conversations: bool = True

    # PII filtering (uses privacy.redaction if available)
    pii_filter: bool = True

    @classmethod
    def from_env(cls) -> "UserMemoryConfig":
        """Build config from environment variables (best-effort)."""
        return cls(
            profile_path=os.getenv("BANTZ_PROFILE_PATH", "~/.bantz/profile.json"),
            db_path=os.getenv("BANTZ_MEMORY_DB", "~/.bantz/memory.db"),
            max_recall=int(os.getenv("BANTZ_MEMORY_MAX_RECALL", "5")),
            pii_filter=os.getenv("BANTZ_MEMORY_PII_FILTER", "1") == "1",
        )


# ---------------------------------------------------------------------------
# UserMemoryBridge
# ---------------------------------------------------------------------------

class UserMemoryBridge:
    """
    Single entry point for persistent user memory in OrchestratorLoop.

    Wraps:
      - ProfileManager  (JSON — user facts, preferences, style)
      - MemoryStore      (SQLite — long-term episodic memory)
      - LearningEngine   (fact/preference extraction from text)

    Thread-safety: delegates to underlying thread-safe managers.
    """

    def __init__(self, config: Optional[UserMemoryConfig] = None) -> None:
        self.config = config or UserMemoryConfig.from_env()
        self._ready = False

        # Lazy-initialized references
        self._profile_manager: Any = None
        self._memory_store: Any = None
        self._learning_engine: Any = None

        self._init_components()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _init_components(self) -> None:
        """Initialize memory components (best-effort, non-fatal)."""
        try:
            from bantz.memory.profile import ProfileManager

            self._profile_manager = ProfileManager(
                profile_path=self.config.profile_path,
                auto_save=True,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("[USER_MEMORY] ProfileManager init failed: %s", exc)
            self._profile_manager = None

        try:
            from bantz.memory.store import MemoryStore

            self._memory_store = MemoryStore(
                db_path=self.config.db_path,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("[USER_MEMORY] MemoryStore init failed: %s", exc)
            self._memory_store = None

        try:
            if self._memory_store is not None and self._profile_manager is not None:
                from bantz.memory.learning import LearningEngine

                self._learning_engine = LearningEngine(
                    memory_store=self._memory_store,
                    profile_manager=self._profile_manager,
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("[USER_MEMORY] LearningEngine init failed: %s", exc)
            self._learning_engine = None

        self._ready = (
            self._profile_manager is not None
            or self._memory_store is not None
        )
        if self._ready:
            logger.info(
                "[USER_MEMORY] Initialized (profile=%s, store=%s, learning=%s)",
                self._profile_manager is not None,
                self._memory_store is not None,
                self._learning_engine is not None,
            )
        else:
            logger.warning("[USER_MEMORY] No components initialized — memory disabled")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def ready(self) -> bool:
        """Whether at least one memory component is available."""
        return self._ready

    @property
    def profile_manager(self) -> Any:
        """Underlying ProfileManager (may be None)."""
        return self._profile_manager

    @property
    def memory_store(self) -> Any:
        """Underlying MemoryStore (may be None)."""
        return self._memory_store

    # ------------------------------------------------------------------
    # Hook 1: Turn Start
    # ------------------------------------------------------------------

    def on_turn_start(self, user_input: str) -> Dict[str, Any]:
        """
        Called at the beginning of each turn.

        Returns a dict with:
          - "profile_context": str  — formatted block for LLM prompt injection
          - "facts": dict           — known user facts
          - "memories": list[str]   — recalled memory snippets relevant to input

        Never raises — returns empty dict on error.
        """
        result: Dict[str, Any] = {
            "profile_context": "",
            "facts": {},
            "memories": [],
        }

        if not self._ready:
            return result

        # 1. Load profile + build context block
        try:
            result.update(self._build_profile_context())
        except Exception as exc:
            logger.debug("[USER_MEMORY] profile context failed: %s", exc)

        # 2. Recall relevant memories
        try:
            result["memories"] = self._recall_memories(user_input)
        except Exception as exc:
            logger.debug("[USER_MEMORY] memory recall failed: %s", exc)

        # 3. PII filter on output
        if self.config.pii_filter:
            try:
                result["profile_context"] = self._filter_pii(
                    result.get("profile_context", "")
                )
            except Exception:
                pass

        return result

    def _build_profile_context(self) -> Dict[str, Any]:
        """Build profile context block for LLM prompt."""
        if self._profile_manager is None:
            return {"profile_context": "", "facts": {}}

        profile = self._profile_manager.profile

        parts: list[str] = []

        # User facts
        facts = dict(profile.facts) if profile.facts else {}
        if facts:
            fact_lines = [f"  • {k}: {v}" for k, v in facts.items()]
            parts.append("KULLANICI BİLGİLERİ:\n" + "\n".join(fact_lines))

        # Communication style
        style_prompt = ""
        if hasattr(profile, "get_communication_style_prompt"):
            style_prompt = profile.get_communication_style_prompt()
        elif hasattr(profile, "communication_style_prompt"):
            style_prompt = profile.communication_style_prompt
        if not style_prompt:
            # Fallback: build from attributes
            style_parts: list[str] = []
            if profile.name:
                style_parts.append(f"Kullanıcının adı: {profile.name}")
            if getattr(profile, "preferred_language", None):
                style_parts.append(
                    f"Tercih edilen dil: {profile.preferred_language}"
                )
            vp = getattr(profile, "verbosity_preference", 0.5)
            if vp < 0.3:
                style_parts.append("Kısa ve öz cevaplar ver")
            elif vp > 0.7:
                style_parts.append("Detaylı açıklamalar yap")
            tl = getattr(profile, "technical_level", 0.5)
            if tl > 0.7:
                style_parts.append("Teknik terimler kullanabilirsin")
            elif tl < 0.3:
                style_parts.append("Basit ve anlaşılır anlat")
            style_prompt = ". ".join(style_parts)

        if style_prompt:
            parts.append(f"İLETİŞİM TARZI: {style_prompt}")

        # Reliable preferences (confidence >= 0.5)
        pref_lines: list[str] = []
        prefs = getattr(profile, "preferences", {}) or {}
        for key, pref in prefs.items():
            if hasattr(pref, "is_reliable") and pref.is_reliable:
                pref_lines.append(f"  • {key}: {pref.value}")
            elif isinstance(pref, dict) and pref.get("confidence", 0) >= 0.5:
                pref_lines.append(f"  • {key}: {pref.get('value', pref)}")
        if pref_lines:
            parts.append("TERCİHLER:\n" + "\n".join(pref_lines))

        context_block = "\n".join(parts)

        # Truncate to budget
        if len(context_block) > self.config.max_context_chars:
            context_block = context_block[: self.config.max_context_chars]
            # Don't cut mid-line
            nl = context_block.rfind("\n")
            if nl > 0:
                context_block = context_block[:nl]

        return {"profile_context": context_block, "facts": facts}

    def _recall_memories(self, user_input: str) -> List[str]:
        """Recall relevant memories for user input."""
        if self._memory_store is None or not user_input.strip():
            return []

        memories = self._memory_store.recall(
            query=user_input,
            limit=self.config.max_recall,
            min_importance=self.config.min_importance,
        )

        snippets: list[str] = []
        for mem in memories:
            content = getattr(mem, "content", str(mem))
            if content:
                # Truncate individual snippets
                if len(content) > 150:
                    content = content[:147] + "..."
                snippets.append(content)
        return snippets

    # ------------------------------------------------------------------
    # Hook 2: Turn End
    # ------------------------------------------------------------------

    def on_turn_end(
        self,
        user_input: str,
        assistant_reply: str,
        route: str = "",
        tool_results: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Called at the end of each turn to learn from interaction.

        Returns a dict with:
          - "facts": list[dict]        — newly extracted facts
          - "preferences": list[dict]  — newly extracted preferences
          - "memory_id": str | None    — conversation memory ID

        Never raises — returns empty dict on error.
        """
        result: Dict[str, Any] = {
            "facts": [],
            "preferences": [],
            "memory_id": None,
        }

        if not self._ready:
            return result

        # Use LearningEngine if available
        if self._learning_engine is not None:
            try:
                from bantz.memory.learning import InteractionResult

                task_result = None
                if tool_results:
                    # Build InteractionResult from tool_results
                    success_count = sum(
                        1 for r in tool_results if r.get("success", False)
                    )
                    task_result = InteractionResult(
                        description=route or "unknown",
                        success=success_count > 0,
                        steps=[r.get("tool", "") for r in tool_results],
                        apps_used=[],
                    )

                learned = self._learning_engine.process_interaction(
                    user_input=user_input,
                    assistant_response=assistant_reply,
                    task_result=task_result,
                )
                result["facts"] = learned.get("facts", [])
                result["preferences"] = learned.get("preferences", [])
                result["memory_id"] = learned.get("memory_id")

                if result["facts"] or result["preferences"]:
                    logger.info(
                        "[USER_MEMORY] Learned: %d facts, %d preferences",
                        len(result["facts"]),
                        len(result["preferences"]),
                    )
            except Exception as exc:
                logger.debug("[USER_MEMORY] learning failed: %s", exc)
        else:
            # Fallback: at least try fact extraction from profile manager
            try:
                if self._profile_manager is not None:
                    self._profile_manager.record_interaction()
            except Exception:
                pass

        return result

    # ------------------------------------------------------------------
    # PII Filtering
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_pii(text: str) -> str:
        """Best-effort PII filtering."""
        if not text:
            return text
        try:
            from bantz.privacy.redaction import redact_pii

            return redact_pii(text)
        except ImportError:
            pass
        try:
            from bantz.memory.safety import mask_pii

            return mask_pii(text)
        except ImportError:
            pass
        return text

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def get_profile_summary(self) -> str:
        """Get a short summary of the user profile."""
        if self._profile_manager is None:
            return ""
        try:
            profile = self._profile_manager.profile
            return profile.get_facts_summary()
        except Exception:
            return ""

    def close(self) -> None:
        """Clean up resources."""
        if self._memory_store is not None:
            try:
                self._memory_store.close()
            except Exception:
                pass

    def __repr__(self) -> str:
        return (
            f"UserMemoryBridge(ready={self._ready}, "
            f"profile={self._profile_manager is not None}, "
            f"store={self._memory_store is not None}, "
            f"learning={self._learning_engine is not None})"
        )
