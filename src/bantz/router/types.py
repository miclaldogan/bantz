from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

Intent = Literal[
    "agent_run",
    "agent_history",
    "agent_status",
    "agent_retry",
    "agent_preview",
    "agent_confirm_plan",
    "open_browser",
    "google_search",
    "open_path",
    "open_url",
    "notify",
    "open_btop",
    "dev_task",
    "enter_dev_mode",
    "exit_dev_mode",
    "confirm_yes",
    "confirm_no",
    "cancel",
    "queue_pause",
    "queue_resume",
    "queue_abort",
    "queue_skip",
    "queue_status",
    "debug_tail_logs",
    # Browser Agent intents
    "browser_open",
    "browser_scan",
    "browser_click",
    "browser_type",
    "browser_scroll_down",
    "browser_scroll_up",
    "browser_back",
    "browser_info",
    "browser_detail",
    "browser_wait",
    "browser_search",
    # News Briefing intents
    "news_briefing",
    "news_open_result",
    "news_open_current",
    "news_more",
    # Page Summarization intents
    "page_summarize",
    "page_summarize_detailed",
    "page_question",
    # Jarvis Panel control intents
    "panel_move",
    "panel_hide",
    "panel_minimize",
    "panel_maximize",
    "panel_next_page",
    "panel_prev_page",
    "panel_select_item",
    # Advanced desktop input
    "pc_mouse_move",
    "pc_mouse_click",
    "pc_mouse_scroll",
    "pc_hotkey",
    "clipboard_set",
    "clipboard_get",
    # Coding Agent intents (Issue #4)
    "file_read",
    "file_write",
    "file_edit",
    "file_create",
    "file_delete",
    "file_undo",
    "file_list",
    "file_search",
    "terminal_run",
    "terminal_background",
    "terminal_background_output",
    "terminal_background_kill",
    "terminal_background_list",
    "code_apply_diff",
    "code_replace_function",
    "code_replace_class",
    "code_insert_lines",
    "code_delete_lines",
    "code_format",
    "code_search_replace",
    "project_info",
    "project_tree",
    "project_symbols",
    "project_search_symbol",
    "project_related_files",
    "project_imports",
    # Overlay control intents
    "overlay_move",
    "overlay_hide",
    # Query clarification intents (Issue #21)
    "vague_search",           # Belirsiz arama: "şurada kaza olmuş"
    "clarification_response", # Clarification yanıtı
    "unknown",
]


PolicyDecision = Literal["allow", "confirm", "deny"]

@dataclass(frozen=True)
class RouterResult:
    ok: bool
    intent: Intent
    user_text: str
    needs_confirmation: bool = False
    confirmation_prompt: Optional[str] = None
    data: dict | None = None
