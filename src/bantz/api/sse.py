"""SSE notification stream for the Bantz REST API (Issue #834).

GET /api/v1/notifications — Server-Sent Events stream.

Pushes real-time events from the EventBus to HTTP clients:
  - bantz_message (proactive notifications)
  - Orchestrator trace events (turn.start, tool.call, etc.)
  - Reminder / check-in triggers
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from bantz.api.auth import require_auth
from bantz.api.models import NotificationEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["notifications"])


@router.get(
    "/notifications",
    summary="SSE notification stream",
    description="Real-time Server-Sent Events stream of Bantz notifications and events.",
    response_description="text/event-stream",
    response_class=Response,
)
async def sse_notifications(
    request: Request,
    event_types: Optional[str] = Query(
        default=None,
        description="Comma-separated event types to filter (e.g. 'bantz_message,turn.end'). "
        "If omitted, all events are streamed.",
    ),
    _token: Optional[str] = Depends(require_auth),
):
    """Stream notifications as Server-Sent Events."""
    from sse_starlette.sse import EventSourceResponse

    type_filter = set()
    if event_types:
        type_filter = {t.strip() for t in event_types.split(",") if t.strip()}

    async def _event_generator() -> AsyncGenerator[dict, None]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=256)

        # Get the event bus from the app state
        event_bus = request.app.state.event_bus

        def _on_event(event) -> None:
            """EventBus callback — push to asyncio queue."""
            if type_filter and event.event_type not in type_filter:
                return
            try:
                queue.put_nowait(event.to_dict())
            except asyncio.QueueFull:
                logger.warning("SSE queue full, dropping event: %s", event.event_type)

        # Subscribe to all events
        event_bus.subscribe_all(_on_event)

        try:
            # Send initial keepalive
            yield {"event": "connected", "data": json.dumps({"status": "connected"})}

            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                try:
                    event_data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield {
                        "event": event_data.get("type", "message"),
                        "data": json.dumps(event_data, ensure_ascii=False),
                    }
                except asyncio.TimeoutError:
                    # Send keepalive comment every 30s
                    yield {"comment": "keepalive"}
        finally:
            event_bus.unsubscribe_all(_on_event)

    return EventSourceResponse(_event_generator())


@router.get(
    "/inbox",
    summary="Get inbox snapshot",
    description="Returns the current proactive inbox (FIFO) with unread count.",
)
async def get_inbox(
    request: Request,
    _token: Optional[str] = Depends(require_auth),
) -> dict:
    """Return the current inbox snapshot."""
    server = request.app.state.bantz_server
    snap = server._inbox.snapshot()
    return {"ok": True, "items": snap["items"], "unread": snap["unread"]}


@router.post(
    "/inbox/{item_id}/read",
    summary="Mark inbox item as read",
)
async def mark_inbox_read(
    item_id: int,
    request: Request,
    _token: Optional[str] = Depends(require_auth),
) -> dict:
    """Mark an inbox item as read."""
    server = request.app.state.bantz_server
    updated = server._inbox.mark_read(item_id)
    return {"ok": updated, "text": "OK" if updated else "Not found"}
