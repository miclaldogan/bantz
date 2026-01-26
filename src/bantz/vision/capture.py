"""Screen capture helpers.

Design goals:
- Fast capture via `mss`
- Simple return types: numpy arrays (H, W, 3) RGB
- Safe errors when optional deps are missing

Install deps: `pip install -e '.[vision]'`
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


class VisionDepsMissing(RuntimeError):
    pass


def _require_vision_deps():
    try:
        import mss  # noqa: F401
        import numpy as np  # noqa: F401
    except Exception as e:  # pragma: no cover
        raise VisionDepsMissing(
            "Vision dependencies are missing. Install with `pip install -e '.[vision]'`."
        ) from e


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    w: int
    h: int


def _to_rgb(frame_bgra) -> "object":
    """Convert BGRA bytes to RGB numpy array."""
    import numpy as np

    arr = np.asarray(frame_bgra)  # shape (h, w, 4) BGRA
    # BGRA -> RGB
    rgb = arr[:, :, :3][:, :, ::-1]
    return rgb


def capture_screen(monitor: int = 1) -> "object":
    """Capture full monitor as RGB numpy array.

    Args:
        monitor: 1-based monitor index (mss convention).

    Returns:
        numpy.ndarray: (H, W, 3) RGB
    """
    _require_vision_deps()
    import mss

    with mss.mss() as sct:
        mon = sct.monitors[monitor]
        frame = sct.grab(mon)
        return _to_rgb(frame)


def capture_region(x: int, y: int, w: int, h: int, monitor: int = 0) -> "object":
    """Capture an arbitrary region as RGB numpy array.

    Args:
        x,y,w,h: Region in screen coordinates.
        monitor: 0 means virtual screen in mss; kept for compatibility.

    Returns:
        numpy.ndarray: (h, w, 3) RGB
    """
    _require_vision_deps()
    import mss

    box = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
    with mss.mss() as sct:
        frame = sct.grab(box)
        return _to_rgb(frame)


def capture_window(window_id: str) -> "object":
    """Best-effort window capture.

    For X11, can be implemented via xwininfo/xwd + PIL; for now this is a
    placeholder that raises a clear error.

    Notes:
        We keep this function for the Issue #1 contract, but it requires
        OS-specific tooling. We'll implement it once window geometry is
        available reliably across X11/Wayland.
    """
    raise NotImplementedError(
        "capture_window(window_id) is not implemented yet. Use capture_region() with window geometry."
    )


def get_cursor_position() -> Tuple[int, int]:
    """Get cursor position (x, y).

    Best-effort approach:
    - Use `xdotool getmouselocation --shell` when available

    Returns:
        (x, y)

    Raises:
        RuntimeError if no method is available.
    """
    import shutil
    import subprocess

    if shutil.which("xdotool"):
        proc = subprocess.run(
            ["xdotool", "getmouselocation", "--shell"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if proc.returncode == 0:
            vals = {}
            for line in proc.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    vals[k.strip()] = v.strip()
            try:
                return int(vals.get("X", "0")), int(vals.get("Y", "0"))
            except Exception:
                pass

    raise RuntimeError("Unable to get cursor position (xdotool not available).")
