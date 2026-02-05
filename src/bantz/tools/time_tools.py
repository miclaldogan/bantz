from __future__ import annotations

from datetime import datetime
from typing import Any


def time_now_tool(**_: Any) -> dict[str, Any]:
    """Return current local time (timezone-aware).

    Tool-friendly payload. This is intentionally simple and has no external deps.
    """

    now = datetime.now().astimezone()
    return {
        "ok": True,
        "now_iso": now.isoformat(),
        "tz": str(now.tzinfo) if now.tzinfo is not None else None,
        "epoch": int(now.timestamp()),
        "date": now.date().isoformat(),
        "time": now.strftime("%H:%M"),
    }
