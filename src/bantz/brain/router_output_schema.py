"""Router output schema management (Issue #418).

Problem: The full OrchestratorOutput JSON schema has ~15 fields requiring
~200+ tokens. The 3B model with 128 max_tokens frequently truncates the JSON,
triggering json_repair and lowering quality.

Solution: Two-tier schema:
  - **Slim (routing-only)**: route, calendar_intent, slots, confidence,
    tool_plan, gmail_intent — ~50 tokens output
  - **Extended**: adds assistant_reply, confirmation_prompt, memory_update,
    reasoning_summary, gmail, ask_user, question — used when budget allows

The slim schema is the default for 3B routing; extended fields are populated
by the finalization phase (Gemini or 3B fallback).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "RouterOutputSchema",
    "SLIM_SCHEMA_JSON",
    "EXTENDED_FIELDS_JSON",
    "FULL_SCHEMA_JSON",
    "slim_schema_instruction",
    "full_schema_instruction",
]


# ── Slim schema: ONLY routing-critical fields (~50 token output) ────────
SLIM_SCHEMA_JSON = (
    '{"route":"calendar|gmail|smalltalk|unknown",'
    '"calendar_intent":"create|modify|cancel|query|none",'
    '"slots":{"date":"YYYY-MM-DD|null","time":"HH:MM|null",'
    '"duration":"dk|null","title":"str|null",'
    '"window_hint":"evening|tomorrow|morning|today|week|null"},'
    '"confidence":0.0-1.0,'
    '"tool_plan":["tool_name"],'
    '"gmail_intent":"list|search|read|send|none",'
    '"requires_confirmation":false}'
)

# ── Extended fields: added when budget allows (~100 extra tokens) ───────
EXTENDED_FIELDS_JSON = (
    '"assistant_reply":"metin",'
    '"gmail":{},'
    '"ask_user":false,'
    '"question":"",'
    '"confirmation_prompt":"",'
    '"memory_update":"",'
    '"reasoning_summary":["madde"]'
)

# ── Full schema: slim + extended (backwards compatible) ─────────────────
FULL_SCHEMA_JSON = (
    '{"route":"calendar|gmail|smalltalk|unknown",'
    '"calendar_intent":"create|modify|cancel|query|none",'
    '"slots":{"date":"YYYY-MM-DD|null","time":"HH:MM|null",'
    '"duration":"dk|null","title":"str|null",'
    '"window_hint":"evening|tomorrow|morning|today|week|null"},'
    '"confidence":0.0-1.0,'
    '"tool_plan":["tool_name"],'
    '"assistant_reply":"metin",'
    '"gmail_intent":"list|search|read|send|none",'
    '"gmail":{},'
    '"ask_user":false,'
    '"question":"",'
    '"requires_confirmation":false,'
    '"confirmation_prompt":"",'
    '"memory_update":"",'
    '"reasoning_summary":["madde"]}'
)


# ── Prompt instruction templates ────────────────────────────────────────

def slim_schema_instruction() -> str:
    """Return the slim OUTPUT SCHEMA instruction for system prompt."""
    return (
        f"OUTPUT SCHEMA (tek JSON object döndür — SADECE bu alanlar):\n"
        f"{SLIM_SCHEMA_JSON}\n"
        f"\n"
        f"NOT: assistant_reply, memory_update, reasoning_summary alanları "
        f"gerekli DEĞİL — bunlar finalization fazında doldurulur."
    )


def full_schema_instruction() -> str:
    """Return the full OUTPUT SCHEMA instruction (backward compat)."""
    return (
        f"OUTPUT SCHEMA (tek JSON object döndür):\n"
        f"{FULL_SCHEMA_JSON}"
    )


@dataclass
class RouterOutputSchema:
    """Manages which schema tier to use based on budget/model capability.

    Attributes:
        use_slim: Whether to use the slim (routing-only) schema.
        max_tokens_hint: Suggested max_tokens for the LLM call.
    """

    use_slim: bool = True
    max_tokens_hint: int = 256

    @classmethod
    def for_budget(
        cls,
        *,
        available_completion_tokens: int,
        model_context_length: int = 2048,
    ) -> "RouterOutputSchema":
        """Select schema tier based on available completion budget.

        If completion budget is tight (< 200 tokens), use slim schema.
        Otherwise, use full schema for richer output.
        """
        if available_completion_tokens < 200:
            return cls(use_slim=True, max_tokens_hint=min(256, available_completion_tokens))
        return cls(use_slim=False, max_tokens_hint=min(512, available_completion_tokens))

    @classmethod
    def slim(cls) -> "RouterOutputSchema":
        """Create a slim schema (for 3B models)."""
        return cls(use_slim=True, max_tokens_hint=256)

    @classmethod
    def full(cls) -> "RouterOutputSchema":
        """Create a full schema (for larger models or Gemini)."""
        return cls(use_slim=False, max_tokens_hint=512)

    def get_schema_instruction(self) -> str:
        """Return the appropriate schema instruction for the system prompt."""
        if self.use_slim:
            return slim_schema_instruction()
        return full_schema_instruction()

    def get_schema_json(self) -> str:
        """Return the raw schema JSON string."""
        if self.use_slim:
            return SLIM_SCHEMA_JSON
        return FULL_SCHEMA_JSON

    @property
    def required_fields(self) -> set[str]:
        """Fields that MUST be present in the router output."""
        base = {"route", "calendar_intent", "slots", "confidence", "tool_plan"}
        if not self.use_slim:
            base.update({
                "assistant_reply", "gmail_intent", "gmail",
                "ask_user", "question", "requires_confirmation",
                "confirmation_prompt", "memory_update", "reasoning_summary",
            })
        else:
            base.add("gmail_intent")
            base.add("requires_confirmation")
        return base

    @property
    def optional_fields(self) -> set[str]:
        """Fields that MAY be present (populated by finalizer)."""
        if self.use_slim:
            return {
                "assistant_reply", "gmail", "ask_user", "question",
                "confirmation_prompt", "memory_update", "reasoning_summary",
            }
        return set()

    def validate_output(self, parsed: dict[str, Any]) -> list[str]:
        """Validate parsed router output against schema.

        Returns list of missing required fields (empty = valid).
        """
        missing = []
        for f in self.required_fields:
            if f not in parsed:
                missing.append(f)
        return missing

    def fill_defaults(self, parsed: dict[str, Any]) -> dict[str, Any]:
        """Fill missing optional fields with defaults.

        This ensures OrchestratorOutput can be constructed even from slim output.
        """
        defaults = {
            "route": "unknown",
            "calendar_intent": "none",
            "slots": {},
            "confidence": 0.0,
            "tool_plan": [],
            "assistant_reply": "",
            "gmail_intent": "none",
            "gmail": {},
            "ask_user": False,
            "question": "",
            "requires_confirmation": False,
            "confirmation_prompt": "",
            "memory_update": "",
            "reasoning_summary": [],
        }
        result = dict(defaults)
        result.update(parsed)
        return result
