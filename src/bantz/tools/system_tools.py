from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from typing import Any

logger = logging.getLogger(__name__)


def system_status(*, include_env: bool = False, **_: Any) -> dict[str, Any]:
    """Return lightweight system health info (CPU/RAM/load).

    Notes:
    - Avoids extra deps like psutil.
    - Linux-first implementation; returns best-effort values.
    """

    out: dict[str, Any] = {"ok": True, "ts": int(time.time())}

    try:
        load1, load5, load15 = os.getloadavg()
        out["loadavg"] = {"1m": load1, "5m": load5, "15m": load15}
    except Exception:
        out["loadavg"] = None

    try:
        out["cpu_count"] = os.cpu_count()
    except Exception:
        out["cpu_count"] = None

    mem: dict[str, Any] = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            raw = f.read().splitlines()
        kv: dict[str, int] = {}
        for line in raw:
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            parts = v.strip().split()
            if not parts:
                continue
            try:
                kv[k.strip()] = int(parts[0])  # kB
            except Exception:
                continue

        total_kb = kv.get("MemTotal")
        avail_kb = kv.get("MemAvailable")
        if total_kb is not None:
            mem["total_mb"] = round(total_kb / 1024.0, 1)
        if avail_kb is not None:
            mem["available_mb"] = round(avail_kb / 1024.0, 1)
        if total_kb is not None and avail_kb is not None and total_kb > 0:
            used_mb = (total_kb - avail_kb) / 1024.0
            mem["used_mb"] = round(used_mb, 1)
            mem["used_pct"] = round(100.0 * used_mb / (total_kb / 1024.0), 1)
    except Exception:
        mem = {}

    out["memory"] = mem or None

    # --- Gemini / quality status (Issue #658) -------------------------------
    try:
        from dataclasses import asdict
        from bantz.llm.privacy import get_cloud_privacy_config
        from bantz.llm.gemini_client import get_default_circuit_breaker, get_default_quota_tracker
        from bantz.llm.quality_status import get_quality_degradation_status
        from bantz.llm.tier_env import (
            get_tier_debug,
            get_tier_force,
            get_tier_force_finalizer,
            get_tier_metrics,
            get_tier_mode_enabled,
        )

        privacy = get_cloud_privacy_config()
        api_key_configured = bool(
            os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("BANTZ_GEMINI_API_KEY")
        )

        circuit = get_default_circuit_breaker()
        quota = get_default_quota_tracker()

        out["gemini"] = {
            "cloud_mode": str(getattr(privacy, "mode", "") or ""),
            "api_key_configured": api_key_configured,
            "circuit_state": str(getattr(circuit, "state", "") or ""),
            "quota": asdict(quota.get_stats()) if quota is not None else None,
        }
        out["quality_degradation"] = get_quality_degradation_status()
        out["tiering"] = {
            "enabled": bool(get_tier_mode_enabled()),
            "forced": get_tier_force() or "auto",
            "finalizer_forced": get_tier_force_finalizer() or "auto",
            "debug": bool(get_tier_debug()),
            "metrics": bool(get_tier_metrics()),
        }
    except Exception:
        out["gemini"] = None
        out["quality_degradation"] = None
        out["tiering"] = None

    if include_env:
        # Never include secrets. Only expose a small allowlist of non-sensitive flags.
        allow = [
            "BANTZ_VLLM_URL",
            "BANTZ_VLLM_MODEL",
            "BANTZ_GEMINI_MODEL",
        ]
        out["env"] = {k: (os.getenv(k) or "") for k in allow}

    return out


# ── system_notify (Issue #1051) ─────────────────────────────────────

def system_notify_tool(*, message: str = "", title: str = "Bantz", **_: Any) -> dict[str, Any]:
    """Show a desktop notification using notify-send (Linux).

    Falls back gracefully when notify-send is not available.
    """
    import shutil
    import subprocess

    if not message:
        return {"ok": False, "error": "message_required"}

    if not shutil.which("notify-send"):
        return {"ok": False, "error": "notify-send not installed"}

    try:
        result = subprocess.run(
            ["notify-send", "--app-name=Bantz", title, message],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return {"ok": True, "sent": True}
        return {"ok": False, "error": f"notify-send error: {result.stderr.strip()}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "notify-send timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def system_screenshot_tool(*, monitor: int = 0, **_: Any) -> dict[str, Any]:
    """Capture a screenshot and return base64-encoded image data.

    Uses the vision module's capture_screen() which tries mss → PIL → pyautogui
    → X11 fallback, in order of availability.

    Returns:
        dict with ok, base64, width, height, format on success;
        dict with ok=False and error on failure.
    """
    try:
        from bantz.vision.capture import capture_screen
    except ImportError:
        return {
            "ok": False,
            "error": (
                "Vision dependencies are not installed. "
                "Install with: pip install -e '.[vision]'"
            ),
        }

    try:
        result = capture_screen(monitor=monitor)
        return {
            "ok": True,
            "base64": result.to_base64(),
            "width": result.width,
            "height": result.height,
            "format": result.format,
        }
    except Exception as e:
        logger.warning("system.screenshot failed: %s", e)
        return {"ok": False, "error": str(e)}


# ── system_volume (Issue #1385) ─────────────────────────────────────

def system_volume_tool(
    *, level: int | str | None = None, action: str = "get", **_: Any
) -> dict[str, Any]:
    """Get or set system audio volume using pactl (PipeWire/PulseAudio).

    Args:
        level: Target volume 0-100 (for action="set"). Ignored for "get".
        action: "get" | "set" | "up" | "down" | "mute" | "unmute"

    Returns:
        dict with ok, volume (0-100), muted (bool), and optional error.
    """
    if not shutil.which("pactl"):
        return {"ok": False, "error": "pactl not installed (PulseAudio/PipeWire required)"}

    def _get_volume() -> dict[str, Any]:
        """Read current volume and mute state from default sink."""
        try:
            proc = subprocess.run(
                ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                capture_output=True, text=True, timeout=5,
            )
            vol_pct: int | None = None
            if proc.returncode == 0:
                # Output like: "Volume: front-left: 42000 /  64% / -11.74 dB, ..."
                for part in proc.stdout.split("/"):
                    part = part.strip()
                    if part.endswith("%"):
                        try:
                            vol_pct = int(part[:-1].strip())
                            break
                        except ValueError:
                            continue
        except Exception:
            vol_pct = None

        muted: bool | None = None
        try:
            proc = subprocess.run(
                ["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0:
                muted = "yes" in proc.stdout.lower()
        except Exception:
            pass

        return {"volume": vol_pct, "muted": muted}

    action = str(action).lower().strip()

    if action == "get":
        info = _get_volume()
        return {"ok": True, **info}

    try:
        if action == "set":
            val = int(level) if level is not None else 50
            val = max(0, min(150, val))  # clamp to 0-150%
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{val}%"],
                capture_output=True, text=True, timeout=5, check=True,
            )
        elif action == "up":
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%"],
                capture_output=True, text=True, timeout=5, check=True,
            )
        elif action == "down":
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%"],
                capture_output=True, text=True, timeout=5, check=True,
            )
        elif action == "mute":
            subprocess.run(
                ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"],
                capture_output=True, text=True, timeout=5, check=True,
            )
        elif action == "unmute":
            subprocess.run(
                ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"],
                capture_output=True, text=True, timeout=5, check=True,
            )
        else:
            return {"ok": False, "error": f"Unknown action: {action}. Use get/set/up/down/mute/unmute."}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": f"pactl failed: {e.stderr or str(e)}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pactl timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    info = _get_volume()
    return {"ok": True, "action": action, **info}
