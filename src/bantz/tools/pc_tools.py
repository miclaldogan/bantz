"""PC control & clipboard runtime tool handlers.

Issue #845: Planner-Runtime Tool Gap Kapatma
─────────────────────────────────────────────
Provides runtime handlers for PC control tools using xdotool/xclip.
All PC tools require confirmation by default (policy.json: pc_*=confirm).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Allowed hotkey modifiers/keys — deny dangerous combos
_ALLOWED_MODIFIERS = {"alt", "ctrl", "super", "shift", "meta"}
_BLOCKED_COMBOS = {
    "ctrl+alt+delete",
    "ctrl+alt+del",
    "alt+f4",  # Only blocked for system-wide; can be overridden
}


def _run_cmd(cmd: list[str], timeout: int = 5) -> subprocess.CompletedProcess:
    """Run a subprocess with timeout."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _check_tool(tool_name: str) -> str | None:
    """Check if a tool is available. Returns path or None."""
    return shutil.which(tool_name)


# ── pc_hotkey ───────────────────────────────────────────────────────

def pc_hotkey_tool(*, combo: str = "", **_: Any) -> Dict[str, Any]:
    """Press a keyboard hotkey combination using xdotool."""
    if not combo:
        return {"ok": False, "error": "combo_required"}

    # Normalize
    combo_lower = combo.lower().strip()

    # Block dangerous combos
    if combo_lower.replace(" ", "") in _BLOCKED_COMBOS:
        return {"ok": False, "error": f"blocked_hotkey: {combo}"}

    if not _check_tool("xdotool"):
        return {"ok": False, "error": "xdotool_not_installed"}

    # Convert combo format: "alt+tab" → "alt+Tab" for xdotool
    parts = combo.split("+")
    xdo_keys = []
    for p in parts:
        p = p.strip()
        if p.lower() in _ALLOWED_MODIFIERS:
            xdo_keys.append(p.lower())
        else:
            # Capitalize first letter for xdotool key names
            xdo_keys.append(p.capitalize() if len(p) > 1 else p)

    key_str = "+".join(xdo_keys)

    try:
        result = _run_cmd(["xdotool", "key", key_str])
        if result.returncode == 0:
            return {"ok": True, "combo": combo, "sent": True}
        return {"ok": False, "error": f"xdotool_error: {result.stderr.strip()}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "xdotool_timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── pc_mouse_move ───────────────────────────────────────────────────

def pc_mouse_move_tool(*, x: int = 0, y: int = 0, duration_ms: int = 0, **_: Any) -> Dict[str, Any]:
    """Move mouse to screen coordinate using xdotool."""
    if not _check_tool("xdotool"):
        return {"ok": False, "error": "xdotool_not_installed"}

    # Clamp to reasonable range
    x = max(0, min(x, 7680))
    y = max(0, min(y, 4320))

    try:
        cmd = ["xdotool", "mousemove"]
        if duration_ms > 0:
            # xdotool doesn't have native duration, simulate with --delay
            cmd.extend(["--sync"])
        cmd.extend([str(x), str(y)])

        result = _run_cmd(cmd)
        if result.returncode == 0:
            return {"ok": True, "x": x, "y": y, "moved": True}
        return {"ok": False, "error": f"xdotool_error: {result.stderr.strip()}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── pc_mouse_click ──────────────────────────────────────────────────

def pc_mouse_click_tool(
    *,
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
    double: bool = False,
    **_: Any,
) -> Dict[str, Any]:
    """Mouse click, optionally at specific coordinates."""
    if not _check_tool("xdotool"):
        return {"ok": False, "error": "xdotool_not_installed"}

    button_map = {"left": "1", "middle": "2", "right": "3"}
    btn = button_map.get(button.lower(), "1")

    try:
        # Move first if coordinates given
        if x is not None and y is not None:
            x = max(0, min(x, 7680))
            y = max(0, min(y, 4320))
            move_result = _run_cmd(["xdotool", "mousemove", str(x), str(y)])
            if move_result.returncode != 0:
                return {"ok": False, "error": f"move_failed: {move_result.stderr.strip()}"}

        cmd = ["xdotool", "click"]
        if double:
            cmd.extend(["--repeat", "2", "--delay", "50"])
        cmd.append(btn)

        result = _run_cmd(cmd)
        if result.returncode == 0:
            return {"ok": True, "button": button, "double": double, "x": x, "y": y, "clicked": True}
        return {"ok": False, "error": f"xdotool_error: {result.stderr.strip()}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── pc_mouse_scroll ─────────────────────────────────────────────────

def pc_mouse_scroll_tool(*, direction: str = "down", amount: int = 3, **_: Any) -> Dict[str, Any]:
    """Scroll mouse wheel using xdotool."""
    if not _check_tool("xdotool"):
        return {"ok": False, "error": "xdotool_not_installed"}

    # xdotool: button 4 = scroll up, button 5 = scroll down
    btn = "5" if direction.lower() == "down" else "4"
    amount = max(1, min(amount, 20))

    try:
        result = _run_cmd(["xdotool", "click", "--repeat", str(amount), "--delay", "30", btn])
        if result.returncode == 0:
            return {"ok": True, "direction": direction, "amount": amount, "scrolled": True}
        return {"ok": False, "error": f"xdotool_error: {result.stderr.strip()}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── clipboard_set ───────────────────────────────────────────────────

def clipboard_set_tool(*, text: str = "", **_: Any) -> Dict[str, Any]:
    """Copy text to system clipboard."""
    if not text:
        return {"ok": False, "error": "text_required"}

    # Try xclip first, then xsel
    clip_tool = _check_tool("xclip") or _check_tool("xsel")
    if not clip_tool:
        return {"ok": False, "error": "xclip_or_xsel_not_installed"}

    try:
        if "xclip" in clip_tool:
            proc = subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text,
                capture_output=True,
                text=True,
                timeout=5,
            )
        else:
            proc = subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=text,
                capture_output=True,
                text=True,
                timeout=5,
            )

        if proc.returncode == 0:
            return {"ok": True, "copied": True, "length": len(text)}
        return {"ok": False, "error": f"clipboard_error: {proc.stderr.strip()}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── clipboard_get ───────────────────────────────────────────────────

def clipboard_get_tool(**_: Any) -> Dict[str, Any]:
    """Read current clipboard text."""
    clip_tool = _check_tool("xclip") or _check_tool("xsel")
    if not clip_tool:
        return {"ok": False, "error": "xclip_or_xsel_not_installed"}

    try:
        if "xclip" in clip_tool:
            proc = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        else:
            proc = subprocess.run(
                ["xsel", "--clipboard", "--output"],
                capture_output=True,
                text=True,
                timeout=5,
            )

        if proc.returncode == 0:
            content = proc.stdout
            return {"ok": True, "text": content[:4096], "length": len(content)}
        return {"ok": False, "error": f"clipboard_error: {proc.stderr.strip()}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
