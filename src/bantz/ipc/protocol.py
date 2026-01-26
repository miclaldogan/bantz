"""
Bantz IPC Protocol - Message Types and JSONL Encoding
v0.6.2.1

Spec:
- Unix domain socket (stream) + JSONL (each message ends with \n)
- Socket path: ~/.local/share/bantz/ipc/overlay.sock
- Common fields: v, type, ts, id
"""

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, Any, Union

# Protocol version - increment on breaking changes
IPC_VERSION = 1


class MessageType(str, Enum):
    """IPC message types."""
    STATE = "state"
    EVENT = "event"
    PING = "ping"
    PONG = "pong"
    ACK = "ack"


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


# Type alias for all message types
IPCMessage = Union[StateMessage, EventMessage, AckMessage, PingMessage, PongMessage]


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
        print(f"[IPC] Decode error: {e}")
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
    except Exception as e:
        print(f"[IPC] Parse error: {e}")
    
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
