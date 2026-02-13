"""Scheduler Intent Handlers (Issue #420).

Extracted from Router._dispatch() — handles reminder_* and checkin_* intents.
"""

from __future__ import annotations

from bantz.router.context import ConversationContext
from bantz.router.handler_registry import register_handler
from bantz.router.types import RouterResult


def _follow(in_queue: bool) -> str:
    return "" if in_queue else " Başka ne yapayım?"


def handle_reminder_add(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.scheduler.reminder import get_reminder_manager
    manager = get_reminder_manager()
    time_str = str(slots.get("time", "")).strip()
    message = str(slots.get("message", "")).strip()
    result_data = manager.add_reminder(time_str, message)
    ctx.last_intent = intent
    return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + _follow(in_queue))


def handle_reminder_list(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.scheduler.reminder import get_reminder_manager
    manager = get_reminder_manager()
    result_data = manager.list_reminders()
    ctx.last_intent = intent
    return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + _follow(in_queue))


def handle_reminder_delete(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.scheduler.reminder import get_reminder_manager
    manager = get_reminder_manager()
    reminder_id = int(slots.get("id", 0))
    result_data = manager.delete_reminder(reminder_id)
    ctx.last_intent = intent
    return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + _follow(in_queue))


def handle_reminder_snooze(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.scheduler.reminder import get_reminder_manager
    manager = get_reminder_manager()
    reminder_id = int(slots.get("id", 0))
    minutes = int(slots.get("minutes", 10))
    result_data = manager.snooze_reminder(reminder_id, minutes)
    ctx.last_intent = intent
    return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + _follow(in_queue))


def handle_checkin_add(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.scheduler.checkin import get_checkin_manager
    manager = get_checkin_manager()
    schedule_str = str(slots.get("schedule", "")).strip()
    prompt = str(slots.get("prompt", "")).strip()
    result_data = manager.add_checkin(schedule_str, prompt)
    ctx.last_intent = intent
    return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + _follow(in_queue))


def handle_checkin_list(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.scheduler.checkin import get_checkin_manager
    manager = get_checkin_manager()
    result_data = manager.list_checkins()
    ctx.last_intent = intent
    return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + _follow(in_queue))


def handle_checkin_delete(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.scheduler.checkin import get_checkin_manager
    manager = get_checkin_manager()
    checkin_id = int(slots.get("id", 0))
    result_data = manager.delete_checkin(checkin_id)
    ctx.last_intent = intent
    return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + _follow(in_queue))


def handle_checkin_pause(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.scheduler.checkin import get_checkin_manager
    manager = get_checkin_manager()
    checkin_id = int(slots.get("id", 0))
    result_data = manager.pause_checkin(checkin_id)
    ctx.last_intent = intent
    return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + _follow(in_queue))


def handle_checkin_resume(*, intent: str, slots: dict, ctx: ConversationContext, router: object, in_queue: bool) -> RouterResult:
    from bantz.scheduler.checkin import get_checkin_manager
    manager = get_checkin_manager()
    checkin_id = int(slots.get("id", 0))
    result_data = manager.resume_checkin(checkin_id)
    ctx.last_intent = intent
    return RouterResult(ok=result_data["ok"], intent=intent, user_text=result_data["text"] + _follow(in_queue))


# ── Registration ──────────────────────────────────────────────────────────

def register_all() -> None:
    """Register all scheduler intent handlers."""
    register_handler("reminder_add", handle_reminder_add)
    register_handler("reminder_list", handle_reminder_list)
    register_handler("reminder_delete", handle_reminder_delete)
    register_handler("reminder_snooze", handle_reminder_snooze)
    register_handler("checkin_add", handle_checkin_add)
    register_handler("checkin_list", handle_checkin_list)
    register_handler("checkin_delete", handle_checkin_delete)
    register_handler("checkin_pause", handle_checkin_pause)
    register_handler("checkin_resume", handle_checkin_resume)
