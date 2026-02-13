"""Pydantic models for the Bantz REST API (Issue #834).

Request and response schemas for all API endpoints.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────
# Chat
# ─────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    """POST /api/v1/chat request body."""

    message: str = Field(..., min_length=1, max_length=4096, description="User message")
    session: str = Field(default="default", description="Session name")
    stream: bool = Field(default=False, description="Stream response via SSE (future)")

    model_config = {"json_schema_extra": {"examples": [{"message": "bugün plan var mı?"}]}}


class ToolCall(BaseModel):
    """A tool invocation within a chat response."""

    tool: str = Field(..., description="Tool name")
    args: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class ChatResponse(BaseModel):
    """POST /api/v1/chat response body."""

    ok: bool = Field(..., description="Whether the request succeeded")
    response: str = Field(..., description="Assistant reply text")
    route: str = Field(default="unknown", description="Detected intent route")
    brain: bool = Field(default=False, description="Whether brain pipeline was used")
    tools_used: Optional[List[ToolCall]] = Field(default=None, description="Tools invoked")
    requires_confirmation: bool = Field(default=False, description="Whether user confirmation is needed")
    confirmation_prompt: Optional[str] = Field(default=None, description="Confirmation prompt if required")
    session: str = Field(default="default", description="Session name")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "ok": True,
                    "response": "Bugün 14:00'te toplantınız var efendim.",
                    "route": "calendar",
                    "brain": True,
                    "session": "default",
                }
            ]
        }
    }


class ErrorResponse(BaseModel):
    """Standard error response."""

    ok: bool = Field(default=False)
    error: str = Field(..., description="Error message")
    code: str = Field(default="internal_error", description="Error code")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ─────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────

class ComponentStatus(str, Enum):
    """Status of an individual component."""

    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class ComponentHealth(BaseModel):
    """Health status of a single component."""

    name: str
    status: ComponentStatus
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    """GET /api/v1/health response."""

    status: str = Field(..., description="Overall status: ok / degraded / down")
    version: str = Field(default="0.3.0", description="Bantz version")
    uptime_seconds: float = Field(..., description="Server uptime in seconds")
    components: List[ComponentHealth] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


# ─────────────────────────────────────────────────────────────
# Skills
# ─────────────────────────────────────────────────────────────

class SkillInfo(BaseModel):
    """Information about a registered skill / tool."""

    name: str
    description: str = ""
    category: str = "general"
    source: str = "builtin"


class SkillsResponse(BaseModel):
    """GET /api/v1/skills response."""

    ok: bool = Field(default=True)
    count: int
    skills: List[SkillInfo]


# ─────────────────────────────────────────────────────────────
# Notifications (SSE)
# ─────────────────────────────────────────────────────────────

class NotificationEvent(BaseModel):
    """A single SSE notification event."""

    id: int
    kind: str
    text: str
    source: str = "core"
    read: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class InboxSnapshot(BaseModel):
    """Current inbox state."""

    items: List[NotificationEvent]
    unread: int


# ─────────────────────────────────────────────────────────────
# WebSocket
# ─────────────────────────────────────────────────────────────

class WSMessage(BaseModel):
    """WebSocket incoming message."""

    type: str = Field(default="chat", description="Message type: chat | ping")
    message: str = Field(default="", description="Chat message text")
    session: str = Field(default="default")


class WSResponse(BaseModel):
    """WebSocket outgoing message."""

    type: str = Field(..., description="Response type: chat | event | pong | error")
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
