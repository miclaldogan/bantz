"""Browser controller using Playwright (sync API).

Headful mode for visibility and debugging.
Persistent profile for cookies/sessions (stored in ~/.local/share/bantz/browser).
"""
from __future__ import annotations

import atexit
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright


def get_persistent_profile_dir() -> str:
    """Get persistent browser profile directory in user's home."""
    # Use XDG_DATA_HOME or fallback to ~/.local/share
    xdg_data = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    profile_dir = Path(xdg_data) / "bantz" / "browser_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    return str(profile_dir)


@dataclass
class BrowserController:
    """Singleton-ish controller for a visible Chromium instance."""

    _playwright: Optional[Playwright] = field(default=None, repr=False)
    _browser: Optional[Browser] = field(default=None, repr=False)
    _context: Optional[BrowserContext] = field(default=None, repr=False)
    _page: Optional[Page] = field(default=None, repr=False)

    # Persist profile for session cookies (in user's home, not /tmp)
    user_data_dir: str = field(default_factory=get_persistent_profile_dir)

    def _ensure_browser(self) -> Page:
        """Lazily start browser and return active page."""
        if self._page and not self._page.is_closed():
            return self._page

        if not self._playwright:
            self._playwright = sync_playwright().start()
            atexit.register(self.close)

        if not self._browser or not self._browser.is_connected():
            # Headful, persistent context for cookies/sessions
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
                viewport={"width": 1280, "height": 800},
                locale="tr-TR",
            )
            self._browser = None  # persistent context doesn't expose browser object
            pages = self._context.pages
            self._page = pages[0] if pages else self._context.new_page()

        return self._page

    @property
    def page(self) -> Page:
        return self._ensure_browser()

    def navigate(self, url: str) -> tuple[bool, str]:
        """Navigate to URL."""
        try:
            page = self.page
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            title = page.title() or url
            return True, f"Açtım: {title}"
        except Exception as e:
            return False, f"Sayfa açılamadı: {e}"

    def current_url(self) -> str:
        try:
            return self.page.url
        except Exception:
            return ""

    def current_title(self) -> str:
        try:
            return self.page.title()
        except Exception:
            return ""

    def go_back(self) -> tuple[bool, str]:
        try:
            self.page.go_back(timeout=10000)
            return True, f"Geri döndüm: {self.current_title()}"
        except Exception as e:
            return False, f"Geri dönemedim: {e}"

    def scroll_down(self, amount: int = 500) -> tuple[bool, str]:
        try:
            self.page.mouse.wheel(0, amount)
            return True, "Aşağı kaydırdım."
        except Exception as e:
            return False, f"Kaydıramadım: {e}"

    def scroll_up(self, amount: int = 500) -> tuple[bool, str]:
        try:
            self.page.mouse.wheel(0, -amount)
            return True, "Yukarı kaydırdım."
        except Exception as e:
            return False, f"Kaydıramadım: {e}"

    def close(self) -> None:
        """Clean shutdown."""
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None


# Global instance
_controller: Optional[BrowserController] = None


def get_controller() -> BrowserController:
    global _controller
    if _controller is None:
        _controller = BrowserController()
    return _controller
