"""Settings API router — Gemini API Key management & system info (Issue #867).

Endpoints:
    GET  /api/v1/settings/status     — Key status + system info (never returns actual keys)
    POST /api/v1/settings/gemini-key — Store Gemini API key in Fernet vault
    DELETE /api/v1/settings/gemini-key — Remove Gemini API key from vault + env
    GET  /api/v1/qrcode              — QR code PNG for LAN access URL
"""
from __future__ import annotations

import io
import logging
import os
import socket
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from bantz.api.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])

# ── Constants ────────────────────────────────────────────────────
GEMINI_KEY_VAULT_NAME = "GEMINI_API_KEY"


# ─────────────────────────────────────────────────────────────────
# GET /api/v1/settings/status
# ─────────────────────────────────────────────────────────────────

@router.get(
    "/api/v1/settings/status",
    summary="System & key status",
    description="Returns which API keys are configured, system info, and LAN access URL. Never exposes actual key values.",
)
async def settings_status(
    request: Request,
    _token: Optional[str] = Depends(require_auth),
) -> JSONResponse:
    """Return settings status — safe for UI consumption."""
    gemini_set = _is_gemini_key_set()
    api_token_set = bool(os.getenv("BANTZ_API_TOKEN", "").strip())
    uptime = time.time() - request.app.state.start_time

    # Detect brain/finalizer info
    server = request.app.state.bantz_server
    brain_active = server is not None and getattr(server, "_brain", None) is not None
    finalizer = "Gemini 2.0 Flash" if gemini_set else "3B (local)"
    router_model = _get_router_model(server)
    tool_count = _count_tools(server)

    # LAN access URL
    access_url = _get_lan_url(request)

    return JSONResponse(content={
        "gemini_key_set": gemini_set,
        "api_token_set": api_token_set,
        "version": "0.3.0",
        "uptime_seconds": round(uptime, 2),
        "brain_active": brain_active,
        "finalizer": finalizer,
        "router_model": router_model,
        "tool_count": tool_count,
        "access_url": access_url,
    })


# ─────────────────────────────────────────────────────────────────
# POST /api/v1/settings/gemini-key
# ─────────────────────────────────────────────────────────────────

@router.post(
    "/api/v1/settings/gemini-key",
    summary="Store Gemini API key",
    description="Encrypts the key with Fernet and stores it in the vault. Also injects it into the runtime environment.",
)
async def save_gemini_key(
    request: Request,
    _token: Optional[str] = Depends(require_auth),
) -> JSONResponse:
    """Store Gemini API key in vault and inject to env."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Geçersiz JSON body"},
        )

    key = body.get("key", "").strip()
    if not key:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "API key boş olamaz"},
        )

    if not key.startswith("AIza"):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Geçersiz key formatı — AIza... ile başlamalı"},
        )

    try:
        vault = _get_vault()
        from bantz.security.vault import SecretType

        vault.store(
            GEMINI_KEY_VAULT_NAME,
            key,
            secret_type=SecretType.API_KEY,
            metadata={"source": "web_dashboard", "set_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
        )

        # Inject into runtime env so LLM clients pick it up immediately
        os.environ["GEMINI_API_KEY"] = key
        os.environ["GOOGLE_API_KEY"] = key

        logger.info("Gemini API key stored in vault and injected to runtime (source=web_dashboard)")
        return JSONResponse(content={"ok": True, "message": "Key kaydedildi ve aktifleştirildi"})

    except Exception as exc:
        logger.exception("Failed to store Gemini API key: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "Key kaydedilemedi — sunucu hatası. Loglara bakın."},
        )


# ─────────────────────────────────────────────────────────────────
# DELETE /api/v1/settings/gemini-key
# ─────────────────────────────────────────────────────────────────

@router.delete(
    "/api/v1/settings/gemini-key",
    summary="Delete Gemini API key",
    description="Removes the key from vault and runtime environment.",
)
async def delete_gemini_key(
    _token: Optional[str] = Depends(require_auth),
) -> JSONResponse:
    """Delete Gemini API key from vault and env."""
    try:
        vault = _get_vault()
        deleted = vault.delete(GEMINI_KEY_VAULT_NAME)

        # Remove from runtime env
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("GOOGLE_API_KEY", None)

        if deleted:
            logger.info("Gemini API key deleted from vault and runtime")
            return JSONResponse(content={"ok": True, "message": "Key silindi"})
        else:
            return JSONResponse(content={"ok": True, "message": "Key zaten kayıtlı değildi"})

    except Exception as exc:
        logger.exception("Failed to delete Gemini API key: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "Key silinemedi — sunucu hatası. Loglara bakın."},
        )


# ─────────────────────────────────────────────────────────────────
# GET /api/v1/qrcode
# ─────────────────────────────────────────────────────────────────

@router.get(
    "/api/v1/qrcode",
    summary="QR code for phone access",
    description="Returns a PNG QR code encoding the LAN access URL for phone scanning.",
    responses={200: {"content": {"image/png": {}}}, 501: {}},
)
async def qrcode(request: Request) -> Response:
    """Generate QR code for the LAN URL."""
    url = _get_lan_url(request)

    try:
        import qrcode as qr_lib
        from qrcode.image.pil import PilImage

        qr = qr_lib.QRCode(version=1, box_size=8, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img: PilImage = qr.make_image(fill_color="#7c3aed", back_color="#0f0f23")

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return Response(content=buf.read(), media_type="image/png")

    except ImportError:
        # qrcode or Pillow not installed — return URL as plain text
        logger.debug("qrcode package not installed — QR generation skipped")
        return JSONResponse(
            status_code=501,
            content={"error": "qrcode paketi yüklü değil", "url": url},
        )


# ─────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────

def _get_vault():
    """Get or create a SecretsVault instance."""
    from bantz.security.vault import SecretsVault

    return SecretsVault()


def _is_gemini_key_set() -> bool:
    """Check if Gemini API key is set in env or vault."""
    # Check env first (could be set externally)
    if os.getenv("GEMINI_API_KEY", "").strip():
        return True
    if os.getenv("GOOGLE_API_KEY", "").strip():
        return True

    # Check vault
    try:
        vault = _get_vault()
        return vault.exists(GEMINI_KEY_VAULT_NAME)
    except Exception:
        return False


def _get_lan_url(request: Request) -> str:
    """Build the LAN-accessible URL for this server."""
    # Try to detect local IP
    ip = _get_local_ip()
    port = request.url.port or 8088
    return f"http://{ip}:{port}"


def _get_local_ip() -> str:
    """Get the machine's LAN IP address."""
    try:
        # Connect to a public DNS to find our outbound interface
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.0)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _get_router_model(server: Any) -> str:
    """Get the router model name from the brain."""
    if server is None:
        return "-"
    brain = getattr(server, "_brain", None)
    if brain is None:
        return "-"
    # Try to get model from brain config
    config = getattr(brain, "config", None) or getattr(brain, "_config", None)
    if config:
        model = getattr(config, "router_model", None) or getattr(config, "model", None)
        if model:
            return str(model)
    return getattr(brain, "model_name", "-")


def _count_tools(server: Any) -> int:
    """Count registered tools."""
    if server is None:
        return 0
    brain = getattr(server, "_brain", None)
    if brain is None:
        return 0
    tools = getattr(brain, "tools", None)
    if tools is None:
        return 0
    try:
        return len(tools.list_tools())
    except Exception:
        return 0
