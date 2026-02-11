from __future__ import annotations

from typing import Any, Optional


def _get_pii_filter():
    """Lazy import to break memory → brain reverse dependency (Issue #872)."""
    from bantz.brain.memory_lite import PIIFilter
    return PIIFilter


def mask_pii(text: str) -> str:
    """Best-effort PII masking for any memory content.

    This is intentionally lightweight: it complements `WritePolicy` redaction,
    and is used for generating safe summaries (e.g., episodic tool logs).
    """

    t = str(text or "")
    t = " ".join(t.split()).strip()
    if not t:
        return ""
    try:
        PIIFilter = _get_pii_filter()
        return PIIFilter.filter(t, enabled=True)
    except Exception:
        return t


def safe_tool_episode(
    *,
    tool_name: str,
    params: Optional[dict[str, Any]] = None,
    result: Any = None,
    max_len: int = 240,
) -> str:
    """Create a PII-safe episodic summary for a tool call.

    Design goal: never store raw tool output and avoid copying user-provided
    strings like event titles, locations, attendee emails, etc.
    """

    name = str(tool_name or "").strip() or "tool"
    p = params if isinstance(params, dict) else {}

    action = "başarılı"
    if name.endswith(".create_event"):
        action = "takvim etkinliği oluşturuldu"
    elif name.endswith(".update_event"):
        action = "takvim etkinliği güncellendi"
    elif name.endswith(".delete_event"):
        action = "takvim etkinliği silindi"
    elif name.endswith(".list_events"):
        action = "takvim etkinlikleri listelendi"

    pieces: list[str] = [f"Tool {name} başarılı: {action}"]

    # Times are generally safe (but still masked just in case).
    start = str(p.get("start") or "").strip()
    end = str(p.get("end") or "").strip()
    if start and end:
        pieces.append(f"({start}–{end})")

    # Safe aggregate (count only).
    if name.endswith(".list_events") and isinstance(result, dict):
        evs = result.get("events")
        if isinstance(evs, list):
            pieces.append(f"count={len(evs)}")

    text = " ".join([x for x in pieces if str(x).strip()]).strip()
    text = mask_pii(text)

    if max_len is not None:
        try:
            ml = int(max_len)
        except Exception:
            ml = 240
        ml = max(60, min(800, ml))
        if len(text) > ml:
            text = (text[: ml - 1].rstrip() + "…").strip()

    return text
