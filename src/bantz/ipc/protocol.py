"""
Bantz IPC Protocol - Message Types and JSONL Encoding
v0.6.2.1

Spec:
- Unix domain socket (stream) + JSONL (each message ends with \n)
- Socket path: ~/.local/share/bantz/ipc/overlay.sock
- Common fields: v, type, ts, id
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, Any, Union

logger = logging.getLogger(__name__)

# Protocol version - increment on breaking changes
IPC_VERSION = 1


class MessageType(str, Enum):
    """IPC message types."""
    STATE = "state"
    ACTION = "action"
    EVENT = "event"
    PING = "ping"
    PONG = "pong"
    ACK = "ack"
    BRIEFING_START = "briefing_start"
    BRIEFING_CARD = "briefing_card"
    BRIEFING_END = "briefing_end"
    VOICE_STATE = "voice_state"


class ActionType(str, Enum):
    """Daemon → Overlay: ephemeral action visuals."""
    PREVIEW = "preview"      # short text shown under main state
    CURSOR_DOT = "cursor_dot"  # show a dot/ring at a screen coordinate
    HIGHLIGHT = "highlight"  # highlight a rectangle region


class OverlayState(str, Enum):
    """Overlay visual states."""
    IDLE = "idle"
    WAKE = "wake"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


class OverlayPosition(str, Enum):
    """Overlay screen positions."""
    CENTER = "center"
    TOP_RIGHT = "top_right"
    TOP_LEFT = "top_left"
    BOTTOM_RIGHT = "bottom_right"
    BOTTOM_LEFT = "bottom_left"


class EventType(str, Enum):
    """Overlay event types (Overlay → Daemon)."""
    TIMEOUT = "timeout"
    DISMISSED = "dismissed"


class EventReason(str, Enum):
    """Reasons for overlay events."""
    NO_SPEECH = "no_speech"
    USER_CLOSE = "user_close"
    INTERNAL = "internal"


def _generate_id() -> str:
    """Generate unique message ID."""
    return uuid.uuid4().hex[:12]


def _now_ms() -> int:
    """Current timestamp in milliseconds."""
    return int(time.time() * 1000)


@dataclass
class BaseMessage:
    """Base class for all IPC messages."""
    v: int = IPC_VERSION
    type: str = ""
    id: str = field(default_factory=_generate_id)
    ts: int = field(default_factory=_now_ms)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        # Remove None values
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class StateMessage(BaseMessage):
    """
    Daemon → Overlay: State update message.
    Single source of truth for overlay appearance.
    """
    type: str = MessageType.STATE.value
    state: str = OverlayState.IDLE.value
    text: Optional[str] = None
    position: str = OverlayPosition.CENTER.value
    icon: Optional[str] = None  # listening, speaking, thinking, idle
    timeout_ms: Optional[int] = None
    sticky: bool = False
    priority: int = 10
    
    def __post_init__(self):
        # Auto-set icon from state if not provided
        if self.icon is None:
            self.icon = self.state


@dataclass
class ActionMessage(BaseMessage):
    """Daemon → Overlay: Show transient action feedback."""
    type: str = MessageType.ACTION.value
    action: str = ActionType.PREVIEW.value
    text: Optional[str] = None

    # Screen coordinate (global)
    x: Optional[int] = None
    y: Optional[int] = None

    # Rectangle (global screen coords)
    rect_x: Optional[int] = None
    rect_y: Optional[int] = None
    rect_w: Optional[int] = None
    rect_h: Optional[int] = None

    # Lifetime
    duration_ms: Optional[int] = 1200


@dataclass
class EventMessage(BaseMessage):
    """
    Overlay → Daemon: Event notification.
    """
    type: str = MessageType.EVENT.value
    event: str = EventType.TIMEOUT.value
    reason: str = EventReason.INTERNAL.value


@dataclass
class AckMessage(BaseMessage):
    """
    Overlay → Daemon: Acknowledgment of state message.
    """
    type: str = MessageType.ACK.value
    # id should match the acknowledged message's id


@dataclass
class PingMessage(BaseMessage):
    """
    Daemon → Overlay: Health check ping.
    """
    type: str = MessageType.PING.value


@dataclass
class PongMessage(BaseMessage):
    """
    Overlay → Daemon: Health check response.
    """
    type: str = MessageType.PONG.value


@dataclass
class BriefingStartMessage(BaseMessage):
    """Daemon → Overlay: Start of a briefing sequence."""
    type: str = MessageType.BRIEFING_START.value


@dataclass
class BriefingCardMessage(BaseMessage):
    """Daemon → Overlay: A single briefing card (news, calendar, weather, etc.)."""
    type: str = MessageType.BRIEFING_CARD.value
    category: str = ""          # news, calendar, task, weather, system
    title: Optional[str] = None
    headline: Optional[str] = None
    source: Optional[str] = None
    summary: Optional[str] = None
    body: Optional[str] = None
    image_url: Optional[str] = None
    url: Optional[str] = None
    active: bool = False
    # Calendar fields
    start: Optional[str] = None
    end: Optional[str] = None
    all_day: bool = False
    completed: bool = False
    # Weather fields
    temperature: Optional[float] = None
    condition: Optional[str] = None
    humidity: Optional[float] = None
    wind_speed: Optional[float] = None
    # System fields
    cpu: Optional[float] = None
    ram: Optional[float] = None
    disk: Optional[float] = None
    uptime_seconds: Optional[int] = None


@dataclass
class BriefingEndMessage(BaseMessage):
    """Daemon → Overlay: End of a briefing sequence."""
    type: str = MessageType.BRIEFING_END.value


@dataclass
class VoiceStateMessage(BaseMessage):
    """Daemon → Overlay: Voice pipeline state change."""
    type: str = MessageType.VOICE_STATE.value
    state: str = OverlayState.IDLE.value
    trigger: Optional[str] = None
    data: Optional[dict] = None


# Type alias for all message types
IPCMessage = Union[
    StateMessage, ActionMessage, EventMessage,
    AckMessage, PingMessage, PongMessage,
    BriefingStartMessage, BriefingCardMessage, BriefingEndMessage,
    VoiceStateMessage,
]


def encode_message(msg: BaseMessage) -> bytes:
    """
    Encode message to JSONL format (JSON + newline).
    
    Returns bytes ready to send over socket.
    """
    data = msg.to_dict()
    json_str = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    return (json_str + '\n').encode('utf-8')


def decode_message(data: bytes) -> Optional[dict]:
    """
    Decode JSONL message from bytes.
    
    Returns parsed dict or None on error.
    """
    try:
        line = data.decode('utf-8').strip()
        if not line:
            return None
        return json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("[IPC] Decode error: %s", e)
        return None


def parse_message(data: dict) -> Optional[IPCMessage]:
    """
    Parse dict into typed message object.
    
    Returns appropriate message type or None if invalid.
    """
    if not data or 'type' not in data:
        return None
    
    msg_type = data.get('type')
    
    try:
        if msg_type == MessageType.STATE.value:
            return StateMessage(
                v=data.get('v', IPC_VERSION),
                id=data.get('id', _generate_id()),
                ts=data.get('ts', _now_ms()),
                state=data.get('state', OverlayState.IDLE.value),
                text=data.get('text'),
                position=data.get('position', OverlayPosition.CENTER.value),
                icon=data.get('icon'),
                timeout_ms=data.get('timeout_ms'),
                sticky=data.get('sticky', False),
                priority=data.get('priority', 10),
            )
        elif msg_type == MessageType.ACTION.value:
            return ActionMessage(
                v=data.get('v', IPC_VERSION),
                id=data.get('id', _generate_id()),
                ts=data.get('ts', _now_ms()),
                action=data.get('action', ActionType.PREVIEW.value),
                text=data.get('text'),
                x=data.get('x'),
                y=data.get('y'),
                rect_x=data.get('rect_x'),
                rect_y=data.get('rect_y'),
                rect_w=data.get('rect_w'),
                rect_h=data.get('rect_h'),
                duration_ms=data.get('duration_ms', 1200),
            )
        elif msg_type == MessageType.EVENT.value:
            return EventMessage(
                v=data.get('v', IPC_VERSION),
                id=data.get('id', _generate_id()),
                ts=data.get('ts', _now_ms()),
                event=data.get('event', EventType.TIMEOUT.value),
                reason=data.get('reason', EventReason.INTERNAL.value),
            )
        elif msg_type == MessageType.ACK.value:
            return AckMessage(
                v=data.get('v', IPC_VERSION),
                id=data.get('id', _generate_id()),
                ts=data.get('ts', _now_ms()),
            )
        elif msg_type == MessageType.PING.value:
            return PingMessage(
                v=data.get('v', IPC_VERSION),
                id=data.get('id', _generate_id()),
                ts=data.get('ts', _now_ms()),
            )
        elif msg_type == MessageType.PONG.value:
            return PongMessage(
                v=data.get('v', IPC_VERSION),
                id=data.get('id', _generate_id()),
                ts=data.get('ts', _now_ms()),
            )
        elif msg_type == MessageType.BRIEFING_START.value:
            return BriefingStartMessage(
                v=data.get('v', IPC_VERSION),
                id=data.get('id', _generate_id()),
                ts=data.get('ts', _now_ms()),
            )
        elif msg_type == MessageType.BRIEFING_CARD.value:
            return BriefingCardMessage(
                v=data.get('v', IPC_VERSION),
                id=data.get('id', _generate_id()),
                ts=data.get('ts', _now_ms()),
                category=data.get('category', ''),
                title=data.get('title'),
                headline=data.get('headline'),
                source=data.get('source'),
                summary=data.get('summary'),
                body=data.get('body'),
                image_url=data.get('image_url'),
                url=data.get('url'),
                active=data.get('active', False),
                start=data.get('start'),
                end=data.get('end'),
                all_day=data.get('all_day', False),
                completed=data.get('completed', False),
                temperature=data.get('temperature'),
                condition=data.get('condition'),
                humidity=data.get('humidity'),
                wind_speed=data.get('wind_speed'),
                cpu=data.get('cpu'),
                ram=data.get('ram'),
                disk=data.get('disk'),
                uptime_seconds=data.get('uptime_seconds'),
            )
        elif msg_type == MessageType.BRIEFING_END.value:
            return BriefingEndMessage(
                v=data.get('v', IPC_VERSION),
                id=data.get('id', _generate_id()),
                ts=data.get('ts', _now_ms()),
            )
        elif msg_type == MessageType.VOICE_STATE.value:
            return VoiceStateMessage(
                v=data.get('v', IPC_VERSION),
                id=data.get('id', _generate_id()),
                ts=data.get('ts', _now_ms()),
                state=data.get('state', OverlayState.IDLE.value),
                trigger=data.get('trigger'),
                data=data.get('data'),
            )
    except Exception as e:
        logger.warning("[IPC] Parse error: %s", e)
    
    return None


def get_socket_path() -> Path:
    """
    Get the IPC socket path.
    
    Default: ~/.local/share/bantz/ipc/overlay.sock
    """
    base_dir = Path.home() / ".local" / "share" / "bantz" / "ipc"
    return base_dir / "overlay.sock"


def ensure_socket_dir() -> Path:
    """
    Ensure the IPC directory exists and return socket path.
    """
    socket_path = get_socket_path()
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    return socket_path


def cleanup_socket() -> None:
    """
    Remove stale socket file if exists.
    """
    socket_path = get_socket_path()
    if socket_path.exists():
        try:
            socket_path.unlink()
        except OSError:
            pass


# Convenience functions for creating messages
def state_idle(position: str = OverlayPosition.CENTER.value) -> StateMessage:
    """Create idle state message (overlay hidden)."""
    return StateMessage(state=OverlayState.IDLE.value, position=position)


def state_wake(text: str = "Sizi dinliyorum efendim.", position: str = OverlayPosition.CENTER.value) -> StateMessage:
    """Create wake state message."""
    return StateMessage(
        state=OverlayState.WAKE.value,
        text=text,
        position=position,
        timeout_ms=8000,  # 8 second timeout for wake
    )


def state_listening(text: str = "Dinliyorum...", position: str = OverlayPosition.CENTER.value) -> StateMessage:
    """Create listening state message."""
    return StateMessage(
        state=OverlayState.LISTENING.value,
        text=text,
        position=position,
    )


def state_thinking(text: str = "Düşünüyorum...", position: str = OverlayPosition.CENTER.value) -> StateMessage:
    """Create thinking state message."""
    return StateMessage(
        state=OverlayState.THINKING.value,
        text=text,
        position=position,
    )


def state_speaking(text: str, position: str = OverlayPosition.CENTER.value, timeout_ms: int = 5000) -> StateMessage:
    """Create speaking state message."""
    return StateMessage(
        state=OverlayState.SPEAKING.value,
        text=text,
        position=position,
        timeout_ms=timeout_ms,
    )


def event_timeout(reason: str = EventReason.NO_SPEECH.value) -> EventMessage:
    """Create timeout event."""
    return EventMessage(event=EventType.TIMEOUT.value, reason=reason)


def event_dismissed(reason: str = EventReason.USER_CLOSE.value) -> EventMessage:
    """Create dismissed event."""
    return EventMessage(event=EventType.DISMISSED.value, reason=reason)


def action_preview(text: str, duration_ms: int = 1200) -> ActionMessage:
    """Create a transient action preview message."""
    return ActionMessage(action=ActionType.PREVIEW.value, text=text, duration_ms=duration_ms)


def action_cursor_dot(x: int, y: int, duration_ms: int = 800) -> ActionMessage:
    """Create a cursor dot/ring message."""
    return ActionMessage(action=ActionType.CURSOR_DOT.value, x=x, y=y, duration_ms=duration_ms)


def action_highlight_rect(x: int, y: int, w: int, h: int, duration_ms: int = 1200) -> ActionMessage:
    """Create a highlight rectangle message."""
    return ActionMessage(
        action=ActionType.HIGHLIGHT.value,
        rect_x=x,
        rect_y=y,
        rect_w=w,
        rect_h=h,
        duration_ms=duration_ms,
    )


# ─── Briefing convenience factories ─────────────────────────────

def briefing_start() -> BriefingStartMessage:
    """Create a briefing_start message."""
    return BriefingStartMessage()


def briefing_card(category: str, **kwargs) -> BriefingCardMessage:
    """Create a briefing_card message with the given category and fields."""
    return BriefingCardMessage(category=category, **kwargs)


def briefing_end() -> BriefingEndMessage:
    """Create a briefing_end message."""
    return BriefingEndMessage()


def voice_state(state: str, trigger: Optional[str] = None, data: Optional[dict] = None) -> VoiceStateMessage:
    """Create a voice_state message."""
    return VoiceStateMessage(state=state, trigger=trigger, data=data)
