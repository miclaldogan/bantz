"""Bantz REST API — HTTP server & web dashboard (Issues #834 + #867).

Provides:
- GET  /                          — Web dashboard
- POST /api/v1/chat               — Send a message, get a response
- GET  /api/v1/health             — Health check
- GET  /api/v1/skills             — List registered skills
- GET  /api/v1/settings/status    — Key & system status
- POST /api/v1/settings/gemini-key — Store Gemini API key
- DELETE /api/v1/settings/gemini-key — Remove Gemini API key
- GET  /api/v1/qrcode             — QR code for phone access
- WS   /ws/chat                   — WebSocket streaming chat
- GET  /api/v1/notifications      — SSE notification stream

Start via CLI:
    bantz --serve --http
    bantz --serve --http --port 8088
"""

__all__ = ["create_app"]
