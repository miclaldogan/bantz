"""WebSocket chat endpoint for the Bantz REST API (Issue #834).

WS /ws/chat — Bidirectional WebSocket for streaming chat.

Protocol:
  Client → Server:
    {"type": "chat", "message": "bugün plan var mı?"}
    {"type": "ping"}

  Server → Client:
    {"type": "chat", "data": {"ok": true, "response": "...", "route": "calendar", ...}}
    {"type": "event", "data": {"type": "tool.call", ...}}
    {"type": "pong", "data": {}}
    {"type": "error", "data": {"error": "...", "code": "..."}}
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from bantz.api.auth import is_auth_enabled, _resolve_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# Thread pool for running sync handle_command in async context
_ws_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bantz-ws")


@router.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None, alias="token"),
) -> None:
    """WebSocket chat endpoint with optional token auth via query param.

    Auth is done via query param since WebSocket doesn't support
    Authorization headers in all browsers:
        ws://localhost:8088/ws/chat?token=<BANTZ_API_TOKEN>
    """
    # Auth check
    if is_auth_enabled():
        expected = _resolve_token()
        if not token or not secrets.compare_digest(token, expected or ""):
            await websocket.close(code=4001, reason="Unauthorized")
            return

    await websocket.accept()
    logger.info("WebSocket client connected: %s", websocket.client)

    # Get server from app state
    server = websocket.app.state.bantz_server
    event_bus = websocket.app.state.event_bus
    event_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=256)

    def _on_event(event) -> None:
        """Forward EventBus events to WebSocket client."""
        try:
            event_queue.put_nowait(event.to_dict())
        except asyncio.QueueFull:
            pass

    # Subscribe to all events for real-time streaming
    event_bus.subscribe_all(_on_event)

    # Background task: forward events to client
    async def _event_forwarder() -> None:
        try:
            while True:
                event_data = await event_queue.get()
                msg = {
                    "type": "event",
                    "data": event_data,
                    "timestamp": datetime.now().isoformat(),
                }
                await websocket.send_json(msg)
        except (WebSocketDisconnect, Exception):
            pass

    forwarder_task = asyncio.create_task(_event_forwarder())

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "data": {"error": "Invalid JSON", "code": "invalid_json"},
                    "timestamp": datetime.now().isoformat(),
                })
                continue

            msg_type = msg.get("type", "chat")

            if msg_type == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "data": {},
                    "timestamp": datetime.now().isoformat(),
                })
                continue

            if msg_type == "chat":
                message = str(msg.get("message", "")).strip()
                if not message:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"error": "Empty message", "code": "empty_message"},
                        "timestamp": datetime.now().isoformat(),
                    })
                    continue

                # Run sync handle_command in thread pool
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    _ws_executor,
                    server.handle_command,
                    message,
                )

                await websocket.send_json({
                    "type": "chat",
                    "data": {
                        "ok": result.get("ok", False),
                        "response": result.get("text", ""),
                        "route": result.get("route", result.get("intent", "unknown")),
                        "brain": result.get("brain", False),
                    },
                    "timestamp": datetime.now().isoformat(),
                })
                continue

            # Unknown message type
            await websocket.send_json({
                "type": "error",
                "data": {"error": f"Unknown type: {msg_type}", "code": "unknown_type"},
                "timestamp": datetime.now().isoformat(),
            })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: %s", websocket.client)
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
    finally:
        forwarder_task.cancel()
        event_bus.unsubscribe_all(_on_event)
        try:
            await websocket.close()
        except Exception:
            pass
