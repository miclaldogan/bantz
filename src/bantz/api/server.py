"""Bantz REST API Server — FastAPI application (Issues #834 + #867).

This module provides the HTTP REST API and web dashboard for Bantz,
wrapping the existing BantzServer and brain pipeline behind standard
HTTP endpoints with a responsive web UI.

Architecture:
    - Shares the same BantzServer instance as the Unix socket
    - handle_command() is the universal entry point for both protocols
    - EventBus provides real-time SSE and WebSocket streaming
    - Bearer token auth via BANTZ_API_TOKEN env var
    - Web dashboard served from GET / (static HTML, mobile-friendly)

Endpoints:
    GET  /                         — Web dashboard (Issue #867)
    POST /api/v1/chat              — Send a message, get a response
    GET  /api/v1/health            — Health check
    GET  /api/v1/skills            — List registered skills/tools
    GET  /api/v1/settings/status   — Key & system status (Issue #867)
    POST /api/v1/settings/gemini-key — Store Gemini API key (Issue #867)
    DELETE /api/v1/settings/gemini-key — Remove Gemini API key (Issue #867)
    GET  /api/v1/qrcode            — QR code for phone access (Issue #867)
    GET  /api/v1/notifications     — SSE event stream
    GET  /api/v1/inbox             — Inbox snapshot
    POST /api/v1/inbox/{id}/read   — Mark inbox item as read
    WS   /ws/chat                  — WebSocket bidirectional chat

Usage:
    from bantz.api.server import create_app, run_http_server

    app = create_app(bantz_server)
    run_http_server(bantz_server, port=8088)
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from bantz.api.auth import require_auth, is_auth_enabled
from bantz.api.models import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthResponse,
    ComponentHealth,
    ComponentStatus,
    SkillInfo,
    SkillsResponse,
)

logger = logging.getLogger(__name__)


def create_app(
    bantz_server: Any = None,
    event_bus: Any = None,
) -> FastAPI:
    """Create the FastAPI application.

    Parameters
    ----------
    bantz_server:
        A BantzServer instance (shared with Unix socket server).
        If None, creates a new one at startup.
    event_bus:
        Shared EventBus. If None, uses the global singleton.

    Returns
    -------
    FastAPI
        Configured application ready to serve.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Manage application lifecycle."""
        # Startup
        if app.state.bantz_server is None:
            from bantz.server import BantzServer

            app.state.bantz_server = BantzServer()
            logger.info("BantzServer created for HTTP API")

        if app.state.event_bus is None:
            from bantz.core.events import get_event_bus

            app.state.event_bus = get_event_bus()

        app.state._executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="bantz-chat"
        )

        auth_status = "enabled" if is_auth_enabled() else "DISABLED (dev mode)"
        logger.info(
            "Bantz HTTP API started — auth=%s, docs=/docs", auth_status
        )

        yield

        # Shutdown
        app.state._executor.shutdown(wait=False)
        logger.info("Bantz HTTP API stopped")

    app = FastAPI(
        title="Bantz API",
        description=(
            "Bantz Personal AI Assistant — REST API.\n\n"
            "Dışarıdan HTTP erişimi ile Bantz brain pipeline'ına komut gönderin."
        ),
        version="0.3.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── CORS ────────────────────────────────────────────────────────
    origins, origin_regex = _get_cors_config()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── App state ───────────────────────────────────────────────────
    app.state.bantz_server = bantz_server
    app.state.event_bus = event_bus
    app.state.start_time = time.time()
    # Issue #884: session-scoped locks instead of single global lock.
    # Each session gets its own lock so different sessions can run
    # concurrently.  Same-session requests still serialize (required
    # because brain_state is per-session, not thread-safe).
    app.state._session_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)  # type: ignore[assignment]
    app.state._session_locks_guard = threading.Lock()  # protects dict access

    # Issue #901: IP-based rate limiter for /api/v1/chat
    # Sliding-window counter — lightweight, no external deps.
    _rate_limit_max = int(os.getenv("BANTZ_RATE_LIMIT_RPM", "30"))  # requests per minute
    _rate_buckets: dict[str, list[float]] = defaultdict(list)
    _rate_lock = threading.Lock()

    def _check_rate_limit(client_ip: str) -> bool:
        """Return True if request is within rate limit, False if exceeded."""
        now = time.time()
        window = 60.0  # 1 minute
        with _rate_lock:
            bucket = _rate_buckets[client_ip]
            # Prune entries older than window
            cutoff = now - window
            while bucket and bucket[0] < cutoff:
                bucket.pop(0)
            if len(bucket) >= _rate_limit_max:
                return False
            bucket.append(now)
            return True

    # ── Exception handler ───────────────────────────────────────────
    @app.exception_handler(Exception)
    async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error: %s", exc)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="Dahili sunucu hatası",
                code="internal_error",
            ).model_dump(),
        )

    # ── Register routers ────────────────────────────────────────────
    from bantz.api.sse import router as sse_router
    from bantz.api.ws import router as ws_router
    from bantz.api.settings import router as settings_router

    app.include_router(sse_router)
    app.include_router(ws_router)
    app.include_router(settings_router)

    # ── Static files & dashboard ────────────────────────────────────
    _static_dir = Path(__file__).parent / "static"
    if _static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard() -> HTMLResponse:
        """Serve the web dashboard."""
        index_path = _static_dir / "index.html"
        if index_path.exists():
            return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
        return HTMLResponse(
            content=(
                "<html><body style='background:#0f0f23;color:#e2e2f0;font-family:sans-serif;"
                "display:flex;justify-content:center;align-items:center;height:100vh'>"
                "<div style='text-align:center'><h1>🧠 Bantz API</h1>"
                "<p>Dashboard dosyası bulunamadı.</p>"
                "<p><a href='/docs' style='color:#a78bfa'>API Docs →</a></p></div>"
                "</body></html>"
            )
        )

    @app.get("/mobile", response_class=HTMLResponse, include_in_schema=False)
    async def mobile_pwa() -> HTMLResponse:
        """Serve the mobile PWA client (Issue #847)."""
        mobile_path = _static_dir / "mobile.html"
        if mobile_path.exists():
            return HTMLResponse(content=mobile_path.read_text(encoding="utf-8"))
        return HTMLResponse(content="<html><body>Mobile client not found.</body></html>", status_code=404)

    # ── Core endpoints ──────────────────────────────────────────────

    @app.post(
        "/api/v1/chat",
        response_model=ChatResponse,
        responses={401: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
        summary="Send a chat message",
        description="Process a user message through the Bantz brain pipeline and return the response.",
        tags=["chat"],
    )
    async def chat(
        body: ChatRequest,
        request: Request,
        _token: Optional[str] = Depends(require_auth),
    ) -> ChatResponse:
        """Chat endpoint — wraps BantzServer.handle_command()."""
        # Issue #901: Rate limiting
        client_ip = request.client.host if request.client else "unknown"
        if not _check_rate_limit(client_ip):
            logger.warning("[RATE_LIMIT] %s exceeded %d req/min", client_ip, _rate_limit_max)
            return JSONResponse(
                status_code=429,
                content=ErrorResponse(
                    error="Çok fazla istek — lütfen biraz bekleyin efendim.",
                    code="rate_limited",
                ).model_dump(),
                headers={"Retry-After": "60"},
            )

        server = request.app.state.bantz_server
        executor = request.app.state._executor

        # Issue #884: acquire a per-session lock so different sessions
        # can proceed in parallel.  The guard lock only protects the
        # defaultdict lookup (nanoseconds), not the command execution.
        session_id = body.session or "default"
        guard = request.app.state._session_locks_guard
        with guard:
            session_lock = request.app.state._session_locks[session_id]

        loop = asyncio.get_running_loop()

        def _run_command() -> dict:
            with session_lock:
                return server.handle_command(body.message)

        result = await loop.run_in_executor(executor, _run_command)

        return ChatResponse(
            ok=result.get("ok", False),
            response=result.get("text", ""),
            route=result.get("route", result.get("intent", "unknown")),
            brain=result.get("brain", False),
            requires_confirmation=result.get("needs_confirmation", False),
            confirmation_prompt=result.get("confirmation_prompt"),
            session=body.session,
        )

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        summary="Health check",
        description="Returns service health status and component diagnostics.",
        tags=["system"],
    )
    async def health(request: Request) -> HealthResponse:
        """Health endpoint — no auth required."""
        uptime = time.time() - request.app.state.start_time
        components = _check_components(request.app.state.bantz_server)

        # Overall status
        statuses = [c.status for c in components]
        if ComponentStatus.DOWN in statuses:
            overall = "degraded"
        elif ComponentStatus.DEGRADED in statuses:
            overall = "degraded"
        else:
            overall = "ok"

        return HealthResponse(
            status=overall,
            uptime_seconds=round(uptime, 2),
            components=components,
        )

    @app.get(
        "/api/v1/skills",
        response_model=SkillsResponse,
        responses={401: {"model": ErrorResponse}},
        summary="List skills and tools",
        description="Returns all registered skills/tools available in the brain pipeline.",
        tags=["skills"],
    )
    async def list_skills(
        request: Request,
        _token: Optional[str] = Depends(require_auth),
    ) -> SkillsResponse:
        """List all registered tools and declarative skills."""
        skills = _get_skills(request.app.state.bantz_server)
        return SkillsResponse(ok=True, count=len(skills), skills=skills)

    return app


# ─────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────

def _get_cors_config() -> tuple[list[str], str | None]:
    """Get CORS config: (explicit origins, optional origin regex).

    Issue #885: Starlette CORSMiddleware does NOT support glob
    patterns like ``http://localhost:*``.  We use:
    - ``allow_origins`` for exact matches (explicit ports)
    - ``allow_origin_regex`` for localhost/127.0.0.1 on any port

    Env:
        BANTZ_CORS_ORIGINS  – comma-separated explicit origins (overrides defaults)
    """
    import os

    origins_str = os.getenv("BANTZ_CORS_ORIGINS", "").strip()
    if origins_str:
        origins = [o.strip() for o in origins_str.split(",") if o.strip()]
        return origins, None

    # Default (dev): explicit common ports + regex for any localhost port
    explicit = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:8000",
    ]
    # Regex covers ANY port on localhost / 127.0.0.1
    regex = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    return explicit, regex


def _check_components(server: Any) -> list[ComponentHealth]:
    """Check health of all components."""
    components: list[ComponentHealth] = []

    # Brain
    if server and server._brain is not None:
        components.append(
            ComponentHealth(name="brain", status=ComponentStatus.OK, detail="BantzRuntime active")
        )
    else:
        components.append(
            ComponentHealth(
                name="brain",
                status=ComponentStatus.DEGRADED,
                detail="Legacy router fallback",
            )
        )

    # Event bus
    try:
        from bantz.core.events import get_event_bus

        bus = get_event_bus()
        components.append(
            ComponentHealth(
                name="event_bus",
                status=ComponentStatus.OK,
                detail=f"history_size={len(bus._history)}",
            )
        )
    except Exception:
        components.append(
            ComponentHealth(name="event_bus", status=ComponentStatus.DOWN)
        )

    # vLLM
    try:
        import os

        vllm_url = os.getenv("BANTZ_VLLM_URL", "http://localhost:8001")
        # Quick TCP check (no HTTP request to avoid latency)
        import socket as _sock

        host = vllm_url.replace("http://", "").replace("https://", "").split(":")[0]
        port = int(vllm_url.rstrip("/").split(":")[-1])
        s = _sock.create_connection((host, port), timeout=2.0)
        s.close()
        components.append(
            ComponentHealth(name="vllm", status=ComponentStatus.OK, detail=vllm_url)
        )
    except Exception:
        components.append(
            ComponentHealth(name="vllm", status=ComponentStatus.DOWN, detail="unreachable")
        )

    # Gemini (Issue #867) — check if API key is configured
    gemini_key = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
    if gemini_key.strip():
        components.append(
            ComponentHealth(
                name="gemini",
                status=ComponentStatus.OK,
                detail="API key configured",
            )
        )
    else:
        # Check vault as fallback
        try:
            from bantz.security.vault import SecretsVault

            vault = SecretsVault()
            if vault.exists("GEMINI_API_KEY"):
                key = vault.retrieve("GEMINI_API_KEY")
                if key:
                    os.environ["GEMINI_API_KEY"] = key
                    os.environ["GOOGLE_API_KEY"] = key
                    components.append(
                        ComponentHealth(
                            name="gemini",
                            status=ComponentStatus.OK,
                            detail="API key loaded from vault",
                        )
                    )
                else:
                    components.append(
                        ComponentHealth(
                            name="gemini",
                            status=ComponentStatus.DOWN,
                            detail="key in vault but decrypt failed",
                        )
                    )
            else:
                components.append(
                    ComponentHealth(
                        name="gemini",
                        status=ComponentStatus.DOWN,
                        detail="no API key — set via /settings",
                    )
                )
        except Exception:
            components.append(
                ComponentHealth(
                    name="gemini",
                    status=ComponentStatus.DOWN,
                    detail="no API key configured",
                )
            )

    return components


def _get_skills(server: Any) -> list[SkillInfo]:
    """Collect all registered tools/skills."""
    skills: list[SkillInfo] = []

    # Built-in tools from brain runtime
    if server and server._brain is not None:
        try:
            tool_registry = server._brain.tools
            for name in tool_registry.names():
                tool = tool_registry.get(name)
                desc = ""
                category = "builtin"
                if tool:
                    desc = getattr(tool, "description", "") or ""
                    # Derive category from tool name prefix (e.g. gmail.send → gmail)
                    category = name.split(".")[0] if "." in name else "builtin"
                skills.append(
                    SkillInfo(name=name, description=desc, category=category, source="builtin")
                )
        except Exception as exc:
            logger.debug("Error listing built-in tools: %s", exc)

    # Declarative skills
    try:
        from bantz.skills.declarative.registry import get_skill_registry

        registry = get_skill_registry()
        for skill_name in registry.skill_names:
            skill = registry.get_skill(skill_name)
            if skill:
                skills.append(
                    SkillInfo(
                        name=skill_name,
                        description=getattr(skill, "description", ""),
                        category=getattr(skill, "category", "declarative"),
                        source="declarative",
                    )
                )
    except Exception:
        pass

    return skills


def run_http_server(
    bantz_server: Any = None,
    *,
    host: str = "0.0.0.0",
    port: int = 8088,
    event_bus: Any = None,
    log_level: str = "info",
) -> None:
    """Start the Bantz HTTP server (blocking).

    This is the main entry point for `bantz --serve --http`.

    Parameters
    ----------
    bantz_server:
        Shared BantzServer instance.
    host:
        Bind address (default: 0.0.0.0).
    port:
        Port number (default: 8088).
    event_bus:
        Shared EventBus.
    log_level:
        Uvicorn log level.
    """
    import uvicorn

    app = create_app(bantz_server=bantz_server, event_bus=event_bus)

    print(f"\n🌐 Bantz HTTP API başlatılıyor — http://{host}:{port}")
    print(f"   Dashboard: http://localhost:{port}/")
    print(f"   Docs: http://localhost:{port}/docs")
    print(f"   Health: http://localhost:{port}/api/v1/health")
    auth_status = "✓ aktif" if is_auth_enabled() else "⚠ KAPALI (BANTZ_API_TOKEN ayarlanmamış)"
    print(f"   Auth: {auth_status}")

    # Show LAN URL for phone access
    try:
        from bantz.api.settings import _get_local_ip
        lan_ip = _get_local_ip()
        if lan_ip != "127.0.0.1":
            print(f"   📱 Telefon: http://{lan_ip}:{port}")
    except Exception:
        pass
    print()

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level,
        access_log=True,
    )


def start_http_server_background(
    bantz_server: Any = None,
    *,
    host: str = "0.0.0.0",
    port: int = 8088,
    event_bus: Any = None,
) -> threading.Thread:
    """Start the HTTP server in a daemon thread.

    Used when running HTTP alongside the Unix socket server
    (bantz --serve --http).

    Returns the server thread.
    """

    def _run() -> None:
        run_http_server(
            bantz_server=bantz_server,
            host=host,
            port=port,
            event_bus=event_bus,
            log_level="warning",
        )

    thread = threading.Thread(
        target=_run,
        name="bantz-http",
        daemon=True,
    )
    thread.start()
    logger.info("HTTP server started in background on port %d", port)
    return thread
