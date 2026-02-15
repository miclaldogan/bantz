from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from bantz.router.types import Intent


@dataclass
class PendingAction:
    original_text: str
    intent: Intent
    slots: dict
    policy_decision: str
    created_at: float
    expires_at: float

    def expired(self) -> bool:
        return time.time() > self.expires_at


@dataclass
class QueueStep:
    """A single step in a multi-step task chain."""
    original_text: str
    intent: Intent
    slots: dict


@dataclass
class ConversationContext:
    timeout_seconds: int = 120
    pending_timeout_seconds: int = 90
    _last_updated: float = field(default_factory=lambda: time.time())

    # Mode state
    mode: str = "normal"  # "normal" | "dev"

    # Simple context: last intent and expected follow-up
    last_intent: Optional[str] = None
    awaiting: Optional[str] = None  # e.g. "search_query", "app_next_step"
    pending: Optional[PendingAction] = None

    # App session state (PC control)
    active_app: Optional[str] = None  # e.g. "discord", "firefox", "spotify"
    active_window_id: Optional[str] = None  # wmctrl window id (optional)

    # Queue state for multi-step task chains
    queue: list[QueueStep] = field(default_factory=list)
    queue_index: int = 0
    queue_paused: bool = False
    queue_source: str = "chain"  # "chain" | "agent"
    current_agent_task_id: Optional[str] = None

    def _expired(self) -> bool:
        return (time.time() - self._last_updated) > self.timeout_seconds

    def touch(self) -> None:
        self._last_updated = time.time()

    def reset_if_expired(self) -> None:
        if self._expired():
            self.last_intent = None
            self.awaiting = None
            self.pending = None
            self.touch()

    def reset_pending_if_expired(self) -> None:
        if self.pending and self.pending.expired():
            self.pending = None

    def set_pending(self, *, original_text: str, intent: Intent, slots: dict, policy_decision: str) -> None:
        now = time.time()
        self.pending = PendingAction(
            original_text=original_text,
            intent=intent,
            slots=slots,
            policy_decision=policy_decision,
            created_at=now,
            expires_at=now + self.pending_timeout_seconds,
        )

    def clear_pending(self) -> None:
        self.pending = None

    def cancel_all(self) -> None:
        self.awaiting = None
        self.pending = None
        self.clear_queue()

    # App session management
    def set_active_app(self, app_name: str, window_id: Optional[str] = None) -> None:
        """Set the currently active app for session-aware commands."""
        self.active_app = app_name.lower()
        self.active_window_id = window_id
        self.awaiting = "app_next_step"

    def clear_active_app(self) -> None:
        """Clear the active app session."""
        self.active_app = None
        self.active_window_id = None
        if self.awaiting == "app_next_step":
            self.awaiting = None

    def has_active_app(self) -> bool:
        """Check if there's an active app session."""
        return self.active_app is not None

    # Queue management
    def set_queue(self, steps: list[QueueStep], source: str = "chain", task_id: Optional[str] = None) -> None:
        self.queue = steps
        self.queue_index = 0
        self.queue_paused = False
        self.queue_source = source
        self.current_agent_task_id = task_id if source == "agent" else None

    def clear_queue(self) -> None:
        self.queue = []
        self.queue_index = 0
        self.queue_paused = False
        self.queue_source = "chain"
        self.current_agent_task_id = None

    def queue_active(self) -> bool:
        return len(self.queue) > 0 and self.queue_index < len(self.queue)

    def current_step(self) -> Optional[QueueStep]:
        if self.queue_active():
            return self.queue[self.queue_index]
        return None

    def advance_queue(self) -> None:
        if self.queue_index < len(self.queue):
            self.queue_index += 1

    def skip_current(self) -> None:
        self.advance_queue()

    def remaining_steps(self) -> list[QueueStep]:
        return self.queue[self.queue_index:]

    def set_mode(self, mode: str) -> None:
        if mode not in {"normal", "dev"}:
            return
        if self.mode != mode:
            # prevent state mixing across modes
            self.cancel_all()
        self.mode = mode

    # Pending agent plan (for preview before execution)
    _pending_agent_plan: Optional[dict] = field(default=None, repr=False)
    
    # News briefing state
    _news_briefing: Any = field(default=None, repr=False)
    _pending_news_search: Optional[str] = field(default=None, repr=False)
    
    # Page summarizer state
    _page_summarizer: Any = field(default=None, repr=False)
    _pending_page_summarize: Optional[str] = field(default=None, repr=False)
    _pending_page_question: Optional[str] = field(default=None, repr=False)
    
    # Jarvis panel state
    _panel_controller: Any = field(default=None, repr=False)
    _panel_results: list = field(default_factory=list, repr=False)
    _panel_visible: bool = field(default=False, repr=False)

    def set_pending_agent_plan(self, *, task_id: str, steps: list[QueueStep]) -> None:
        """Store a planned agent task awaiting user confirmation."""
        self._pending_agent_plan = {
            "task_id": task_id,
            "steps": steps,
            "created_at": time.time(),
        }

    def get_pending_agent_plan(self) -> Optional[dict]:
        """Get the pending agent plan if any."""
        return self._pending_agent_plan

    def clear_pending_agent_plan(self) -> None:
        """Clear the pending agent plan."""
        self._pending_agent_plan = None

    # News briefing management
    def set_news_briefing(self, news: Any) -> None:
        """Store news briefing instance for follow-up commands."""
        self._news_briefing = news

    def get_news_briefing(self) -> Any:
        """Get the current news briefing instance."""
        return self._news_briefing

    def clear_news_briefing(self) -> None:
        """Clear the news briefing state."""
        self._news_briefing = None
        self._pending_news_search = None

    def set_pending_news_search(self, query: str) -> None:
        """Mark that a news search is pending."""
        self._pending_news_search = query

    def get_pending_news_search(self) -> Optional[str]:
        """Get pending news search query."""
        return self._pending_news_search

    def clear_pending_news_search(self) -> None:
        """Clear pending news search."""
        self._pending_news_search = None

    # Page summarizer management
    def set_page_summarizer(self, summarizer: Any) -> None:
        """Store page summarizer instance for follow-up commands."""
        self._page_summarizer = summarizer

    def get_page_summarizer(self) -> Any:
        """Get the current page summarizer instance."""
        return self._page_summarizer

    def clear_page_summarizer(self) -> None:
        """Clear the page summarizer state."""
        self._page_summarizer = None
        self._pending_page_summarize = None
        self._pending_page_question = None

    def set_pending_page_summarize(self, detail_level: str = "short") -> None:
        """Mark that a page summarization is pending."""
        self._pending_page_summarize = detail_level

    def get_pending_page_summarize(self) -> Optional[str]:
        """Get pending page summarize detail level."""
        return self._pending_page_summarize

    def clear_pending_page_summarize(self) -> None:
        """Clear pending page summarize."""
        self._pending_page_summarize = None

    def set_pending_page_question(self, question: str) -> None:
        """Mark that a page question is pending."""
        self._pending_page_question = question

    def get_pending_page_question(self) -> Optional[str]:
        """Get pending page question."""
        return self._pending_page_question

    def clear_pending_page_question(self) -> None:
        """Clear pending page question."""
        self._pending_page_question = None

    # Jarvis Panel management
    def set_panel_controller(self, controller: Any) -> None:
        """Store panel controller instance for commands."""
        self._panel_controller = controller

    def get_panel_controller(self) -> Any:
        """Get the current panel controller instance."""
        return self._panel_controller

    def set_panel_results(self, results: list) -> None:
        """Store results currently displayed in panel."""
        self._panel_results = results
        self._panel_visible = True

    def get_panel_results(self) -> list:
        """Get results currently displayed in panel."""
        return self._panel_results

    def get_panel_result_by_index(self, index: int) -> Optional[dict]:
        """Get a specific result by 1-indexed number."""
        if 1 <= index <= len(self._panel_results):
            return self._panel_results[index - 1]
        return None

    def is_panel_visible(self) -> bool:
        """Check if panel is currently visible."""
        return self._panel_visible

    def set_panel_visible(self, visible: bool) -> None:
        """Set panel visibility state."""
        self._panel_visible = visible

    def clear_panel(self) -> None:
        """Clear panel state."""
        self._panel_results = []
        self._panel_visible = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "last_intent": self.last_intent,
            "awaiting": self.awaiting,
            "pending": asdict(self.pending) if self.pending else None,
            "active_app": self.active_app,
            "queue_len": len(self.queue),
            "queue_index": self.queue_index,
            "queue_paused": self.queue_paused,
            "queue_source": self.queue_source,
            "current_agent_task_id": self.current_agent_task_id,
            "pending_agent_plan": bool(self._pending_agent_plan),
            "has_news_briefing": self._news_briefing is not None,
            "pending_news_search": self._pending_news_search,
            "has_page_summarizer": self._page_summarizer is not None,
            "pending_page_summarize": self._pending_page_summarize,
            "pending_page_question": self._pending_page_question,
            "panel_visible": self._panel_visible,
            "panel_results_count": len(self._panel_results),
        }
