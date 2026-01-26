from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

Intent = Literal[
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
