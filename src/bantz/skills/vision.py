"""Vision skills (Issue #1).

This module is intentionally dependency-light at import time.
If optional vision deps are missing, functions return helpful errors.

Install deps: `pip install -e '.[vision]'`
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ScreenshotResult:
    path: str
    region: Optional[dict] = None


def _default_screenshot_dir() -> Path:
    base = Path.home() / ".local" / "share" / "bantz" / "screenshots"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _timestamp_name() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def take_screenshot(
    *,
    x: Optional[int] = None,
    y: Optional[int] = None,
    w: Optional[int] = None,
    h: Optional[int] = None,
    out_path: Optional[str] = None,
) -> tuple[bool, str, Optional[ScreenshotResult]]:
    """Take a screenshot (full screen or region) and save to PNG."""

    region = None
    if any(v is not None for v in (x, y, w, h)):
        if None in (x, y, w, h):
            return False, "❌ Bölge için x y w h gerekli.", None
        if int(w) <= 0 or int(h) <= 0:
            return False, "❌ Genişlik/yükseklik pozitif olmalı.", None
        region = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}

    dest = Path(out_path) if out_path else (_default_screenshot_dir() / f"screenshot-{_timestamp_name()}.png")

    try:
        from bantz.vision.capture import VisionDepsMissing, capture_region, capture_screen
        from PIL import Image

        if region:
            rgb = capture_region(region["x"], region["y"], region["w"], region["h"])
        else:
            rgb = capture_screen(monitor=1)

        img = Image.fromarray(rgb, mode="RGB")
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, format="PNG")

        msg = f"✅ Ekran görüntüsü kaydedildi: {dest}"
        return True, msg, ScreenshotResult(path=str(dest), region=region)

    except VisionDepsMissing:
        return (
            False,
            "❌ Vision bağımlılıkları eksik. Kurulum: `pip install -e '.[vision]'`",
            None,
        )
    except Exception as e:
        return False, f"❌ Ekran görüntüsü alınamadı: {e}", None
