from __future__ import annotations

import os
import time
from typing import Any


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

    if include_env:
        # Never include secrets. Only expose a small allowlist of non-sensitive flags.
        allow = [
            "BANTZ_VLLM_URL",
            "BANTZ_VLLM_MODEL",
            "BANTZ_GEMINI_MODEL",
        ]
        out["env"] = {k: (os.getenv(k) or "") for k in allow}

    return out
