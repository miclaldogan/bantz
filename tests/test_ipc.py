"""
Tests for bantz.ipc module — IPC protocol, messages, encoding/decoding.
"""

import json
import pytest

from bantz.ipc.protocol import (
    IPC_VERSION,
    MessageType,
    OverlayState,
    OverlayPosition,
    ActionType,
    EventType,
    EventReason,
    BaseMessage,
    StateMessage,
    ActionMessage,
    EventMessage,
    AckMessage,
    PingMessage,
    PongMessage,
    encode_message,
    decode_message,
    parse_message,
    get_socket_path,
    state_idle,
    state_wake,
    state_listening,
    state_thinking,
    state_speaking,
    event_timeout,
    event_dismissed,
    action_preview,
    action_cursor_dot,
    action_highlight_rect,
)


# ── Enum tests ──────────────────────────────────────────────────


class TestMessageType:
    def test_values(self):
        assert MessageType.STATE.value == "state"
        assert MessageType.ACTION.value == "action"
        assert MessageType.EVENT.value == "event"
        assert MessageType.PING.value == "ping"
        assert MessageType.PONG.value == "pong"
        assert MessageType.ACK.value == "ack"


class TestOverlayState:
    def test_values(self):
        assert OverlayState.IDLE.value == "idle"
        assert OverlayState.WAKE.value == "wake"
        assert OverlayState.LISTENING.value == "listening"
        assert OverlayState.THINKING.value == "thinking"
        assert OverlayState.SPEAKING.value == "speaking"


class TestOverlayPosition:
    def test_values(self):
        assert OverlayPosition.CENTER.value == "center"
        assert OverlayPosition.TOP_RIGHT.value == "top_right"
        assert OverlayPosition.TOP_LEFT.value == "top_left"
        assert OverlayPosition.BOTTOM_RIGHT.value == "bottom_right"
        assert OverlayPosition.BOTTOM_LEFT.value == "bottom_left"


class TestActionType:
    def test_values(self):
        assert ActionType.PREVIEW.value == "preview"
        assert ActionType.CURSOR_DOT.value == "cursor_dot"
        assert ActionType.HIGHLIGHT.value == "highlight"


class TestEventType:
    def test_values(self):
        assert EventType.TIMEOUT.value == "timeout"
        assert EventType.DISMISSED.value == "dismissed"


class TestEventReason:
    def test_values(self):
        assert EventReason.NO_SPEECH.value == "no_speech"
        assert EventReason.USER_CLOSE.value == "user_close"
        assert EventReason.INTERNAL.value == "internal"


# ── Message dataclass tests ─────────────────────────────────────


class TestBaseMessage:
    def test_defaults(self):
        msg = BaseMessage()
        assert msg.v == IPC_VERSION
        assert msg.type == ""
        assert isinstance(msg.id, str) and len(msg.id) == 12
        assert isinstance(msg.ts, int)

    def test_to_dict(self):
        msg = BaseMessage(type="test")
        d = msg.to_dict()
        assert d["type"] == "test"
        assert d["v"] == IPC_VERSION
        assert "id" in d
        assert "ts" in d


class TestStateMessage:
    def test_defaults(self):
        msg = StateMessage()
        assert msg.type == MessageType.STATE.value
        assert msg.state == OverlayState.IDLE.value
        assert msg.position == OverlayPosition.CENTER.value
        assert msg.sticky is False
        assert msg.priority == 10

    def test_auto_icon(self):
        msg = StateMessage(state=OverlayState.LISTENING.value)
        assert msg.icon == OverlayState.LISTENING.value

    def test_custom_icon(self):
        msg = StateMessage(state=OverlayState.IDLE.value, icon="custom")
        assert msg.icon == "custom"

    def test_with_text_and_timeout(self):
        msg = StateMessage(text="Hello", timeout_ms=5000)
        d = msg.to_dict()
        assert d["text"] == "Hello"
        assert d["timeout_ms"] == 5000


class TestActionMessage:
    def test_defaults(self):
        msg = ActionMessage()
        assert msg.type == MessageType.ACTION.value
        assert msg.action == ActionType.PREVIEW.value
        assert msg.duration_ms == 1200

    def test_with_coordinates(self):
        msg = ActionMessage(action=ActionType.CURSOR_DOT.value, x=100, y=200)
        d = msg.to_dict()
        assert d["x"] == 100
        assert d["y"] == 200

    def test_with_rect(self):
        msg = ActionMessage(
            action=ActionType.HIGHLIGHT.value,
            rect_x=10, rect_y=20, rect_w=100, rect_h=50,
        )
        d = msg.to_dict()
        assert d["rect_x"] == 10
        assert d["rect_w"] == 100


class TestEventMessage:
    def test_defaults(self):
        msg = EventMessage()
        assert msg.type == MessageType.EVENT.value
        assert msg.event == EventType.TIMEOUT.value
        assert msg.reason == EventReason.INTERNAL.value


class TestAckMessage:
    def test_defaults(self):
        msg = AckMessage()
        assert msg.type == MessageType.ACK.value


class TestPingPong:
    def test_ping(self):
        msg = PingMessage()
        assert msg.type == MessageType.PING.value

    def test_pong(self):
        msg = PongMessage()
        assert msg.type == MessageType.PONG.value


# ── Encode / Decode ─────────────────────────────────────────────


class TestEncoding:
    def test_encode_returns_bytes(self):
        msg = StateMessage(text="test")
        raw = encode_message(msg)
        assert isinstance(raw, bytes)
        assert raw.endswith(b"\n")

    def test_encode_is_valid_json(self):
        msg = StateMessage(text="merhaba")
        raw = encode_message(msg)
        parsed = json.loads(raw.decode("utf-8"))
        assert parsed["text"] == "merhaba"
        assert parsed["type"] == "state"

    def test_roundtrip_state(self):
        msg = StateMessage(text="hello", state=OverlayState.SPEAKING.value)
        raw = encode_message(msg)
        decoded = decode_message(raw)
        assert decoded is not None
        assert decoded["text"] == "hello"
        assert decoded["state"] == "speaking"

    def test_decode_invalid_bytes(self):
        result = decode_message(b"not-json\n")
        assert result is None

    def test_decode_empty(self):
        result = decode_message(b"")
        assert result is None

    def test_unicode_support(self):
        msg = StateMessage(text="Düşünüyorum efendim...")
        raw = encode_message(msg)
        decoded = decode_message(raw)
        assert decoded["text"] == "Düşünüyorum efendim..."


# ── parse_message ────────────────────────────────────────────────


class TestParseMessage:
    def test_parse_state(self):
        data = {"type": "state", "state": "listening", "text": "ok"}
        msg = parse_message(data)
        assert isinstance(msg, StateMessage)
        assert msg.state == "listening"

    def test_parse_action(self):
        data = {"type": "action", "action": "preview", "text": "hi"}
        msg = parse_message(data)
        assert isinstance(msg, ActionMessage)
        assert msg.text == "hi"

    def test_parse_event(self):
        data = {"type": "event", "event": "timeout", "reason": "no_speech"}
        msg = parse_message(data)
        assert isinstance(msg, EventMessage)
        assert msg.reason == "no_speech"

    def test_parse_ack(self):
        data = {"type": "ack", "id": "abc123"}
        msg = parse_message(data)
        assert isinstance(msg, AckMessage)

    def test_parse_ping(self):
        msg = parse_message({"type": "ping"})
        assert isinstance(msg, PingMessage)

    def test_parse_pong(self):
        msg = parse_message({"type": "pong"})
        assert isinstance(msg, PongMessage)

    def test_parse_invalid_type(self):
        assert parse_message({"type": "unknown"}) is None

    def test_parse_empty(self):
        assert parse_message({}) is None
        assert parse_message(None) is None


# ── Convenience constructors ─────────────────────────────────────


class TestConvenienceFunctions:
    def test_state_idle(self):
        msg = state_idle()
        assert msg.state == "idle"
        assert msg.position == "center"

    def test_state_wake(self):
        msg = state_wake("Merhaba")
        assert msg.state == "wake"
        assert msg.text == "Merhaba"
        assert msg.timeout_ms == 8000

    def test_state_listening(self):
        msg = state_listening()
        assert msg.state == "listening"

    def test_state_thinking(self):
        msg = state_thinking()
        assert msg.state == "thinking"

    def test_state_speaking(self):
        msg = state_speaking("Anlattım efendim")
        assert msg.state == "speaking"
        assert msg.text == "Anlattım efendim"

    def test_event_timeout(self):
        msg = event_timeout()
        assert msg.event == "timeout"
        assert msg.reason == "no_speech"

    def test_event_dismissed(self):
        msg = event_dismissed()
        assert msg.event == "dismissed"
        assert msg.reason == "user_close"

    def test_action_preview(self):
        msg = action_preview("test", duration_ms=2000)
        assert msg.action == "preview"
        assert msg.text == "test"
        assert msg.duration_ms == 2000

    def test_action_cursor_dot(self):
        msg = action_cursor_dot(100, 200)
        assert msg.x == 100
        assert msg.y == 200

    def test_action_highlight_rect(self):
        msg = action_highlight_rect(10, 20, 100, 50)
        assert msg.rect_x == 10
        assert msg.rect_y == 20
        assert msg.rect_w == 100
        assert msg.rect_h == 50


# ── Socket path ──────────────────────────────────────────────────


class TestSocketPath:
    def test_get_socket_path_returns_path(self):
        path = get_socket_path()
        assert str(path).endswith("overlay.sock")
        assert "bantz" in str(path)
