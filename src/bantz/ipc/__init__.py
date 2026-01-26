"""
Bantz IPC Module - Inter-Process Communication for Overlay
v0.6.2.1

Transport: Unix Domain Socket + JSONL (JSON Lines)
"""

from .protocol import (
    IPC_VERSION,
    MessageType,
    OverlayState,
    OverlayPosition,
    StateMessage,
    EventMessage,
    AckMessage,
    PingMessage,
    PongMessage,
    encode_message,
    decode_message,
    get_socket_path,
)
from .overlay_client import OverlayClient
from .overlay_server import OverlayServer

__all__ = [
    "IPC_VERSION",
    "MessageType",
    "OverlayState",
    "OverlayPosition",
    "StateMessage",
    "EventMessage",
    "AckMessage",
    "PingMessage",
    "PongMessage",
    "encode_message",
    "decode_message",
    "get_socket_path",
    "OverlayClient",
    "OverlayServer",
]
