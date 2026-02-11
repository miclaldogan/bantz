"""Bantz REST API — HTTP server for external access (Issue #834).

Provides:
- POST /api/v1/chat      — Send a message, get a response
- GET  /api/v1/health     — Health check
- GET  /api/v1/skills     — List registered skills
- WS   /ws/chat           — WebSocket streaming chat
- GET  /api/v1/notifications — SSE notification stream

Start via CLI:
    bantz --serve --http
    bantz --serve --http --port 8088
"""

__all__ = ["create_app"]
