"""Coding Agent Intent Handlers (Issue #420).

Extracted from Router._dispatch() — handles all coding/file/terminal intents (Issue #4).
"""

from __future__ import annotations

from bantz.router.context import ConversationContext
from bantz.router.handler_registry import register_handlers
from bantz.router.types import RouterResult


_CODING_INTENTS = [
    "file_read", "file_write", "file_edit", "file_create", "file_delete",
    "file_undo", "file_list", "file_search",
    "terminal_run", "terminal_background", "terminal_background_output",
    "terminal_background_kill", "terminal_background_list",
    "code_apply_diff", "code_replace_function", "code_replace_class",
    "code_insert_lines", "code_delete_lines", "code_format", "code_search_replace",
    "project_info", "project_tree", "project_symbols", "project_search_symbol",
    "project_related_files", "project_imports",
]

# Shared executor instance (lazy init)
_executor = None


def handle_coding(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    follow_up = "" if in_queue else " Başka ne yapayım?"
    try:
        from bantz.coding import CodingToolExecutor

        global _executor
        if _executor is None:
            from pathlib import Path
            workspace = Path.cwd()
            _executor = CodingToolExecutor(workspace_root=workspace)

        import asyncio
        loop = asyncio.new_event_loop()
        try:
            ok, result_text = loop.run_until_complete(
                _executor.execute(intent, slots)
            )
        finally:
            loop.close()

        ctx.last_intent = intent
        return RouterResult(ok=ok, intent=intent, user_text=result_text + follow_up)

    except Exception as e:
        ctx.last_intent = intent
        return RouterResult(ok=False, intent=intent, user_text=f"❌ Coding agent hatası: {e}" + follow_up)


# ── Registration ──────────────────────────────────────────────────────────

def register_all() -> None:
    """Register all coding agent intent handlers."""
    register_handlers(_CODING_INTENTS, handle_coding)
