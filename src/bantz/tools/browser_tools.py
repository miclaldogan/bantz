"""Browser runtime tool handlers — wraps ExtensionBridge for OrchestratorLoop.

Issue #845: Planner-Runtime Tool Gap Kapatma
─────────────────────────────────────────────
Provides runtime handlers for 11 browser tools that were previously
schema-only in the planner catalog (builtin_tools.py).

All handlers use the global ExtensionBridge instance to communicate
with the Firefox extension via WebSocket.
"""

from __future__ import annotations

import logging
import time as _time
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _get_bridge():
    """Lazy import to avoid circular deps."""
    try:
        from bantz.browser.extension_bridge import get_bridge
        return get_bridge()
    except Exception:
        return None


def _ensure_bridge():
    """Get bridge or return error dict."""
    bridge = _get_bridge()
    if bridge is None:
        return None, {"ok": False, "error": "extension_bridge_unavailable"}
    if not bridge.has_client():
        return None, {"ok": False, "error": "no_browser_extension_connected"}
    return bridge, None


# ── browser_open ────────────────────────────────────────────────────

def browser_open_tool(*, url: str = "", **_: Any) -> Dict[str, Any]:
    """Open a URL in Firefox via extension bridge."""
    if not url:
        return {"ok": False, "error": "url_required"}

    # Normalize: bare domain → https://
    if not url.startswith(("http://", "https://")):
        # Common site shortcuts
        shortcuts = {
            "youtube": "https://www.youtube.com",
            "google": "https://www.google.com",
            "github": "https://github.com",
            "twitter": "https://twitter.com",
            "x": "https://x.com",
            "reddit": "https://www.reddit.com",
            "linkedin": "https://www.linkedin.com",
            "instagram": "https://www.instagram.com",
            "facebook": "https://www.facebook.com",
            "gmail": "https://mail.google.com",
            "calendar": "https://calendar.google.com",
            "drive": "https://drive.google.com",
            "maps": "https://maps.google.com",
        }
        url = shortcuts.get(url.lower(), f"https://{url}")

    bridge, err = _ensure_bridge()
    if err:
        return err

    success = bridge.request_navigate(url)
    if success:
        _time.sleep(1.0)  # Wait for page load
        return {"ok": True, "url": url, "navigated": True}
    return {"ok": False, "error": "navigate_failed", "url": url}


# ── browser_scan ────────────────────────────────────────────────────

def browser_scan_tool(**_: Any) -> Dict[str, Any]:
    """Scan current page and list clickable elements."""
    bridge, err = _ensure_bridge()
    if err:
        return err

    scan = bridge.request_scan()
    if scan is None:
        return {"ok": False, "error": "scan_failed"}

    elements = scan.get("elements", [])
    # Truncate for LLM context
    summary = []
    for i, el in enumerate(elements[:50]):
        summary.append({
            "index": i,
            "tag": el.get("tag", "?"),
            "text": (el.get("text", "") or "")[:80],
            "type": el.get("type", ""),
        })

    return {
        "ok": True,
        "url": scan.get("url", ""),
        "title": scan.get("title", ""),
        "element_count": len(elements),
        "elements": summary,
    }


# ── browser_click ───────────────────────────────────────────────────

def browser_click_tool(*, index: int | None = None, text: str | None = None, **_: Any) -> Dict[str, Any]:
    """Click an element by index (preferred) or text match."""
    if index is None and not text:
        return {"ok": False, "error": "index_or_text_required"}

    bridge, err = _ensure_bridge()
    if err:
        return err

    success = bridge.request_click(index=index, text=text)
    if success:
        _time.sleep(0.3)
        return {"ok": True, "clicked": True, "index": index, "text": text}
    return {"ok": False, "error": "click_failed"}


# ── browser_type ────────────────────────────────────────────────────

def browser_type_tool(*, text: str = "", index: int | None = None, submit: bool = False, **_: Any) -> Dict[str, Any]:
    """Type text into the page, optionally into a specific element."""
    if not text:
        return {"ok": False, "error": "text_required"}

    bridge, err = _ensure_bridge()
    if err:
        return err

    success = bridge.request_type(text, element_index=index, submit=submit)
    if success:
        return {"ok": True, "typed": True, "text": text[:100], "submit": submit}
    return {"ok": False, "error": "type_failed"}


# ── browser_back ────────────────────────────────────────────────────

def browser_back_tool(**_: Any) -> Dict[str, Any]:
    """Navigate back in browser history."""
    bridge, err = _ensure_bridge()
    if err:
        return err

    success = bridge.request_go_back()
    if success:
        _time.sleep(0.5)
        return {"ok": True, "navigated_back": True}
    return {"ok": False, "error": "back_failed"}


# ── browser_info ────────────────────────────────────────────────────

def browser_info_tool(**_: Any) -> Dict[str, Any]:
    """Get current page info (title, url)."""
    bridge, err = _ensure_bridge()
    if err:
        return err

    page = bridge.get_current_page()
    if page:
        return {"ok": True, **page}
    return {"ok": False, "error": "no_page_info"}


# ── browser_detail ──────────────────────────────────────────────────

def browser_detail_tool(*, index: int = 0, **_: Any) -> Dict[str, Any]:
    """Get detailed info about a scanned element by index."""
    bridge, err = _ensure_bridge()
    if err:
        return err

    elements = bridge.get_page_elements()
    if not elements:
        return {"ok": False, "error": "no_scan_data_run_browser_scan_first"}

    if index < 0 or index >= len(elements):
        return {"ok": False, "error": f"index_out_of_range_0_{len(elements) - 1}"}

    el = elements[index]
    return {"ok": True, "index": index, "element": el}


# ── browser_wait ────────────────────────────────────────────────────

def browser_wait_tool(*, seconds: int = 2, **_: Any) -> Dict[str, Any]:
    """Wait for a specified number of seconds (1-30)."""
    seconds = max(1, min(30, seconds))
    _time.sleep(seconds)
    return {"ok": True, "waited_seconds": seconds}


# ── browser_search ──────────────────────────────────────────────────

def browser_search_tool(*, query: str = "", **_: Any) -> Dict[str, Any]:
    """Search within the current site/page context."""
    if not query:
        return {"ok": False, "error": "query_required"}

    bridge, err = _ensure_bridge()
    if err:
        return err

    # Type into search and submit
    success = bridge.request_type(query, submit=True)
    if success:
        _time.sleep(1.0)
        return {"ok": True, "searched": True, "query": query}
    return {"ok": False, "error": "search_failed"}


# ── browser_scroll_down ────────────────────────────────────────────

def browser_scroll_down_tool(*, amount: int = 500, **_: Any) -> Dict[str, Any]:
    """Scroll down on the page."""
    bridge, err = _ensure_bridge()
    if err:
        return err

    success = bridge.request_scroll(direction="down", amount=amount)
    if success:
        return {"ok": True, "scrolled": "down", "amount": amount}
    return {"ok": False, "error": "scroll_failed"}


# ── browser_scroll_up ──────────────────────────────────────────────

def browser_scroll_up_tool(*, amount: int = 500, **_: Any) -> Dict[str, Any]:
    """Scroll up on the page."""
    bridge, err = _ensure_bridge()
    if err:
        return err

    success = bridge.request_scroll(direction="up", amount=amount)
    if success:
        return {"ok": True, "scrolled": "up", "amount": amount}
    return {"ok": False, "error": "scroll_failed"}
