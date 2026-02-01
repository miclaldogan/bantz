"""Helpers for rendering memory snippets into LLM prompt blocks."""

from __future__ import annotations

from collections.abc import Sequence

from bantz.memory.snippet import MemorySnippet, SnippetType


def snippets_to_prompt_block(
    snippets: Sequence[MemorySnippet],
    *,
    max_chars: int = 1200,
) -> str:
    """Format snippets into a compact prompt block.

    The block is intended for injection into LLM prompts (router/finalizer) and
    should remain short and high-signal.
    """
    if not snippets:
        return ""

    def _label(st: SnippetType) -> str:
        if st == SnippetType.PROFILE:
            return "PROFILE"
        if st == SnippetType.EPISODIC:
            return "EPISODIC"
        return "SESSION"

    # Keep stable ordering: profile -> episodic -> session
    priority = {
        SnippetType.PROFILE: 0,
        SnippetType.EPISODIC: 1,
        SnippetType.SESSION: 2,
    }

    sorted_snippets = sorted(
        snippets,
        key=lambda s: (priority.get(s.snippet_type, 9), -(s.confidence or 0.0), s.timestamp),
        reverse=False,
    )

    lines: list[str] = []
    for snip in sorted_snippets:
        content = str(snip.content or "").strip()
        if not content:
            continue
        # Single-line, avoid runaway length.
        content = " ".join(content.split())
        if len(content) > 240:
            content = content[:239] + "…"
        lines.append(f"- [{_label(snip.snippet_type)}] {content}")

        if max_chars and sum(len(l) + 1 for l in lines) >= max_chars:
            break

    # Ensure we don't exceed the budget.
    block = "\n".join(lines).strip()
    if max_chars and len(block) > max_chars:
        block = block[: max_chars - 1] + "…"
    return block
