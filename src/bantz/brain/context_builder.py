"""Context builder for orchestrator LLM planning phase (Issue #1010).

Extracted from orchestrator_loop.py._llm_planning_phase to reduce
complexity.  Assembles the ``enhanced_summary`` from multiple sources:

* Dialog summary (memory-lite)
* PII redaction + token-budget trimming
* User profile (persistent memory)
* Personality block (Jarvis / Friday / Alfred)
* Recent conversation history
* Last tool results
* Anaphora reference table
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ContextBuildResult:
    """Value returned by :meth:`ContextBuilder.build`."""

    enhanced_summary: str | None = None
    dialog_summary: str | None = None   # For event-bus preview
    turns_count: int = 0


class ContextBuilder:
    """Assembles enhanced context for the LLM router.

    Replaces ~160 inline lines in ``_llm_planning_phase``.
    Each source is optional — missing components are silently skipped.

    Usage::

        builder = ContextBuilder(
            memory=self.memory,
            user_memory=self.user_memory,
            personality_injector=self.personality_injector,
            pii_filter=self.config.memory_pii_filter,
            memory_max_tokens=self.config.memory_max_tokens,
        )
        result = builder.build(
            user_input=user_input,
            conversation_history=conversation_history,
            tool_results=tool_results,
            state=state,
            is_smalltalk=is_smalltalk,
            memory_tracer=self._memory_tracer,
        )
        enhanced_summary = result.enhanced_summary
    """

    def __init__(
        self,
        *,
        memory: Any,
        user_memory: Any = None,
        personality_injector: Any = None,
        pii_filter: bool = False,
        memory_max_tokens: int = 2048,
    ):
        self._memory = memory
        self._user_memory = user_memory
        self._personality_injector = personality_injector
        self._pii_filter = pii_filter
        self._memory_max_tokens = memory_max_tokens

        # PII redaction cache (Issue #942)
        self._cached_pii_summary: str | None = None
        self._cached_pii_summary_key: int | None = None

        # Personality cache (Issue #942)
        self._cached_personality_block: str | None = None
        self._personality_block_built: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        *,
        user_input: str,
        conversation_history: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
        state: Any,
        is_smalltalk: bool = False,
        memory_tracer: Any = None,
    ) -> ContextBuildResult:
        """Build the enhanced summary string for the LLM router.

        The caller is responsible for calling ``memory_tracer.end_turn()``
        and publishing the resulting record on the event bus.
        """
        context_parts: list[str] = []
        result = ContextBuildResult()

        # 1. Dialog summary (memory-lite)
        dialog_summary, turns_count = self._build_dialog_summary(memory_tracer)
        result.dialog_summary = dialog_summary
        result.turns_count = turns_count
        if dialog_summary:
            context_parts.append(dialog_summary)

        # 2. User profile + long-term memory
        um_facts = self._inject_user_profile(
            user_input, context_parts, is_smalltalk,
        )

        # 3. Personality block
        self._inject_personality(context_parts, um_facts)

        # 4. Recent conversation (adaptive compaction, PII-redacted) — Issue #1278
        self._inject_conversation_history(conversation_history, context_parts)

        # 5. Recent tool results
        self._inject_tool_results(tool_results, context_parts)

        # 6. Anaphora reference table
        self._inject_reference_table(tool_results, context_parts, state)

        result.enhanced_summary = (
            "\n\n".join(context_parts) if context_parts else None
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_dialog_summary(
        self, memory_tracer: Any = None,
    ) -> tuple[str | None, int]:
        """Retrieve and process dialog summary from memory-lite.

        Returns ``(dialog_summary, turns_count)``.
        """
        dialog_summary = self._memory.to_prompt_block()
        turns_count = (
            len(self._memory) if hasattr(self._memory, "__len__") else 0
        )

        if not dialog_summary:
            return None, turns_count

        if memory_tracer is not None:
            try:
                memory_tracer.begin_turn(
                    int(getattr(self._memory, "turn_count", 0)) + 1
                )
            except Exception:
                pass

        # PII redaction with caching (Issue #942)
        _raw_hash = hash(dialog_summary)

        if self._pii_filter:
            if (
                _raw_hash == self._cached_pii_summary_key
                and self._cached_pii_summary is not None
            ):
                dialog_summary = self._cached_pii_summary
            else:
                try:
                    from bantz.privacy.redaction import redact_pii

                    dialog_summary = redact_pii(dialog_summary)
                    self._cached_pii_summary = dialog_summary
                    self._cached_pii_summary_key = _raw_hash
                except Exception:
                    pass

        # Token budget trimming  (Issue #599)
        from bantz.llm.token_utils import estimate_tokens as _estimate_tokens

        # Use tracer budget if available, else constructor default
        try:
            budget_tokens = int(memory_tracer.budget.max_tokens)  # type: ignore[union-attr]
        except Exception:
            budget_tokens = int(self._memory_max_tokens)
        budget_tokens = max(1, budget_tokens)

        original_tokens = _estimate_tokens(dialog_summary)

        if original_tokens > budget_tokens:
            budget_chars = budget_tokens * 4
            trimmed = dialog_summary[-budget_chars:]
            nl = trimmed.find("\n")
            if 0 < nl < 80:
                trimmed = trimmed[nl + 1:]
            if memory_tracer is not None:
                try:
                    memory_tracer.record_trim(
                        original_tokens,
                        _estimate_tokens(trimmed),
                        reason="token_budget",
                    )
                except Exception:
                    pass
            dialog_summary = trimmed

        if memory_tracer is not None:
            try:
                memory_tracer.record_injection(
                    dialog_summary,
                    turns_count,
                    token_estimator=_estimate_tokens,
                )
            except Exception:
                pass

        return dialog_summary, turns_count

    def _inject_user_profile(
        self,
        user_input: str,
        context_parts: list[str],
        is_smalltalk: bool,
    ) -> dict[str, str]:
        """Inject user profile + long-term memory.  Returns facts dict."""
        um_facts: dict[str, str] = {}

        if self._user_memory is None or is_smalltalk:
            return um_facts

        try:
            um_result = self._user_memory.on_turn_start(user_input)
            profile_ctx = um_result.get("profile_context", "")
            um_facts = um_result.get("facts", {})

            if profile_ctx:
                context_parts.append(f"USER_PROFILE:\n{profile_ctx}")

            memory_snippets = um_result.get("memories", [])
            if memory_snippets:
                mem_block = "LONG_TERM_MEMORY:\n" + "\n".join(
                    f"  - {s}" for s in memory_snippets[:5]
                )
                context_parts.append(mem_block)

            # Update personality injector with user name
            # Issue #1178: Invalidate personality cache when name changes
            if self._personality_injector is not None:
                pname = um_facts.get("name", "")
                if pname:
                    old_name = getattr(
                        getattr(self._personality_injector, "config", None),
                        "user_name", "",
                    ) or ""
                    self._personality_injector.update_user_name(pname)
                    if pname != old_name:
                        self._personality_block_built = False

        except Exception as exc:
            logger.debug("[CONTEXT_BUILDER] user_memory failed: %s", exc)

        return um_facts

    def _inject_personality(
        self,
        context_parts: list[str],
        um_facts: dict[str, str],
    ) -> None:
        """Inject personality block (cached per session)."""
        if self._personality_injector is None:
            return

        try:
            if not self._personality_block_built:
                pi_block = self._personality_injector.build_router_block(
                    facts=um_facts,
                    preferences={},
                )
                self._cached_personality_block = pi_block
                self._personality_block_built = True
            else:
                pi_block = self._cached_personality_block

            if pi_block:
                context_parts.append(f"PERSONALITY:\n{pi_block}")
        except Exception as exc:
            logger.debug("[CONTEXT_BUILDER] personality injection failed: %s", exc)

    def _inject_conversation_history(
        self,
        conversation_history: list[dict[str, Any]],
        context_parts: list[str],
    ) -> None:
        """Add conversation history with adaptive compaction (Issue #1278).

        Last 3 turns are included verbatim; older turns are shown as
        compact one-line summaries.  PII redaction is applied to all.
        Previously hardcoded to ``[-2:]``.
        """
        if not conversation_history:
            return

        # Issue #1278: Split into compacted (older) and raw (recent) turns
        raw_tail = 3
        n = len(conversation_history)
        tail_start = max(0, n - raw_tail)

        conv_lines = ["RECENT_CONVERSATION:"]

        # Older turns — compact summaries
        for turn in conversation_history[:tail_start]:
            user_text = str(turn.get("user", ""))[:100]
            asst_text = str(turn.get("assistant", ""))[:80]

            if self._pii_filter:
                try:
                    from bantz.privacy.redaction import redact_pii
                    user_text = redact_pii(user_text)
                    asst_text = redact_pii(asst_text)
                except Exception:
                    pass

            conv_lines.append(f"  [past] U: {user_text} → A: {asst_text}")

        # Recent turns — full detail
        for turn in conversation_history[tail_start:]:
            user_text = str(turn.get("user", ""))[:200]
            asst_text = str(turn.get("assistant", ""))[:300]

            if self._pii_filter:
                try:
                    from bantz.privacy.redaction import redact_pii
                    user_text = redact_pii(user_text)
                    asst_text = redact_pii(asst_text)
                except Exception:
                    pass

            conv_lines.append(f"  U: {user_text}")
            conv_lines.append(f"  A: {asst_text}")

        context_parts.append("\n".join(conv_lines))

    def _inject_tool_results(
        self,
        tool_results: list[dict[str, Any]],
        context_parts: list[str],
    ) -> None:
        """Add last 2 tool results for context continuity."""
        if not tool_results:
            return

        result_lines = ["LAST_TOOL_RESULTS:"]
        for tr in tool_results[-2:]:
            tool_name = str(tr.get("tool", ""))
            result_str = str(tr.get("result_summary", ""))[:200]

            if self._pii_filter:
                try:
                    from bantz.privacy.redaction import redact_pii

                    result_str = redact_pii(result_str)
                except Exception:
                    pass

            success = tr.get("success", True)
            status = "ok" if success else "fail"
            result_lines.append(f"  {tool_name} ({status}): {result_str}")

        context_parts.append("\n".join(result_lines))

    def _inject_reference_table(
        self,
        tool_results: list[dict[str, Any]],
        context_parts: list[str],
        state: Any,
    ) -> None:
        """Inject REFERENCE_TABLE for anaphora resolution (Issue #416)."""
        if not tool_results:
            return

        try:
            from bantz.brain.anaphora import ReferenceTable

            ref_table = ReferenceTable.from_tool_results(tool_results)
            ref_block = ref_table.to_prompt_block()
            if ref_block:
                context_parts.append(ref_block)
                state.reference_table = ref_table
        except Exception as exc:
            logger.debug("[CONTEXT_BUILDER] reference table failed: %s", exc)
