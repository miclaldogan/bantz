"""Browser Context Tracker for Bantz.

Tracks the current browser state (active site, URL, title) to enable
context-aware commands like "X ara" → search on current site.

This is the foundation for the "reasoning" layer - knowing WHERE we are
before deciding WHAT to do.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Site Detection - URL/Title → Site Name
# ─────────────────────────────────────────────────────────────────

SITE_PATTERNS = {
    "youtube": ["youtube.com", "youtu.be"],
    "instagram": ["instagram.com"],
    "twitter": ["twitter.com", "x.com"],
    "facebook": ["facebook.com", "fb.com"],
    "github": ["github.com"],
    "linkedin": ["linkedin.com"],
    "reddit": ["reddit.com"],
    "twitch": ["twitch.tv"],
    "spotify": ["open.spotify.com", "spotify.com"],
    "netflix": ["netflix.com"],
    "whatsapp": ["web.whatsapp.com"],
    "telegram": ["web.telegram.org", "telegram.org"],
    "discord": ["discord.com"],
    "wikipedia": ["wikipedia.org"],
    "amazon": ["amazon.com", "amazon.com.tr"],
    "google": ["google.com", "google.com.tr"],
    "duck": ["duck.ai", "duckduckgo.com"],
    "chatgpt": ["chat.openai.com", "chatgpt.com"],
    "claude": ["claude.ai"],
    "gemini": ["gemini.google.com"],
    "perplexity": ["perplexity.ai"],
}


def detect_site_from_url(url: str) -> Optional[str]:
    """Detect site name from URL.
    
    Returns:
        Site name (youtube, instagram, etc.) or None if unknown
    """
    if not url:
        return None
    
    url_lower = url.lower()
    
    for site, patterns in SITE_PATTERNS.items():
        for pattern in patterns:
            if pattern in url_lower:
                return site
    
    return None


def detect_site_from_title(title: str) -> Optional[str]:
    """Detect site name from window/page title.
    
    Fallback when URL is not available.
    """
    if not title:
        return None
    
    title_lower = title.lower()
    
    # Common title patterns
    title_hints = {
        "youtube": ["youtube", "- youtube"],
        "instagram": ["instagram", "• instagram"],
        "twitter": ["twitter", "/ x", "x.com"],
        "facebook": ["facebook"],
        "github": ["github"],
        "linkedin": ["linkedin"],
        "reddit": ["reddit"],
        "twitch": ["twitch"],
        "spotify": ["spotify"],
        "netflix": ["netflix"],
        "whatsapp": ["whatsapp"],
        "telegram": ["telegram"],
        "discord": ["discord"],
        "wikipedia": ["wikipedia", "vikipedi"],
        "google": ["google search", "google"],
        "duck": ["duck.ai", "duckduckgo"],
        "chatgpt": ["chatgpt"],
        "claude": ["claude"],
        "gemini": ["gemini"],
        "perplexity": ["perplexity"],
    }
    
    for site, hints in title_hints.items():
        for hint in hints:
            if hint in title_lower:
                return site
    
    return None


# ─────────────────────────────────────────────────────────────────
# Action History
# ─────────────────────────────────────────────────────────────────

@dataclass
class BrowserAction:
    """A single browser action for history tracking."""
    action: str  # "open_site", "search", "click", "type", etc.
    site: Optional[str] = None
    query: Optional[str] = None
    url: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    success: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "site": self.site,
            "query": self.query,
            "url": self.url,
            "timestamp": self.timestamp,
            "success": self.success,
        }


# ─────────────────────────────────────────────────────────────────
# Browser Context - The Main State Tracker
# ─────────────────────────────────────────────────────────────────

@dataclass
class BrowserContext:
    """Tracks current browser state for context-aware commands.
    
    Attributes:
        active_site: Current site name (youtube, instagram, etc.)
        active_url: Current page URL
        active_title: Current page title
        recent_actions: Last N actions for context
    """
    active_site: Optional[str] = None
    active_url: Optional[str] = None
    active_title: Optional[str] = None
    last_updated: float = field(default_factory=time.time)
    
    # Action history (last 10)
    recent_actions: List[BrowserAction] = field(default_factory=list)
    max_history: int = 10
    
    # Extension connection state
    extension_connected: bool = False
    
    def update_from_url(self, url: str, title: str = "") -> None:
        """Update context from URL and optional title."""
        self.active_url = url
        self.active_title = title
        self.active_site = detect_site_from_url(url) or detect_site_from_title(title)
        self.last_updated = time.time()
        
        logger.debug(f"[BrowserContext] Updated: site={self.active_site}, url={url[:50]}...")
    
    def update_from_title(self, title: str) -> None:
        """Update context from window title (wmctrl fallback)."""
        if not title:
            return
        
        self.active_title = title
        detected = detect_site_from_title(title)
        if detected:
            self.active_site = detected
        self.last_updated = time.time()
        
        logger.debug(f"[BrowserContext] Updated from title: site={self.active_site}")
    
    def record_action(self, action: str, site: str = None, query: str = None, 
                      url: str = None, success: bool = True) -> None:
        """Record an action in history."""
        self.recent_actions.append(BrowserAction(
            action=action,
            site=site or self.active_site,
            query=query,
            url=url,
            success=success,
        ))
        
        # Trim history
        if len(self.recent_actions) > self.max_history:
            self.recent_actions = self.recent_actions[-self.max_history:]
        
        # Update active site if action specifies one
        if site:
            self.active_site = site
    
    def get_last_action(self) -> Optional[BrowserAction]:
        """Get the most recent action."""
        return self.recent_actions[-1] if self.recent_actions else None
    
    def get_last_site(self) -> Optional[str]:
        """Get the last site we interacted with."""
        # First check current active site
        if self.active_site:
            return self.active_site
        
        # Then check recent actions
        for action in reversed(self.recent_actions):
            if action.site:
                return action.site
        
        return None
    
    def is_on_site(self, site: str) -> bool:
        """Check if we're currently on a specific site."""
        return self.active_site == site.lower()
    
    def is_stale(self, max_age_seconds: int = 300) -> bool:
        """Check if context is too old to be reliable."""
        return (time.time() - self.last_updated) > max_age_seconds
    
    def clear(self) -> None:
        """Clear the context."""
        self.active_site = None
        self.active_url = None
        self.active_title = None
        self.recent_actions = []
    
    def snapshot(self) -> Dict[str, Any]:
        """Get a snapshot of current context (for LLM/logging)."""
        return {
            "active_site": self.active_site,
            "active_url": self.active_url,
            "active_title": self.active_title,
            "last_updated": self.last_updated,
            "recent_actions": [a.to_dict() for a in self.recent_actions[-5:]],
            "extension_connected": self.extension_connected,
        }
    
    def __str__(self) -> str:
        return f"BrowserContext(site={self.active_site}, url={self.active_url[:30] if self.active_url else 'None'}...)"


# ─────────────────────────────────────────────────────────────────
# Singleton Instance
# ─────────────────────────────────────────────────────────────────

_browser_context: Optional[BrowserContext] = None


def get_browser_context() -> BrowserContext:
    """Get the global browser context instance."""
    global _browser_context
    if _browser_context is None:
        _browser_context = BrowserContext()
    return _browser_context


def refresh_context_from_extension() -> bool:
    """Refresh context by querying the extension for current page info.
    
    Returns:
        True if successfully updated
    """
    ctx = get_browser_context()
    
    try:
        from bantz.browser.extension_bridge import get_bridge
        bridge = get_bridge()
        
        if not bridge or not bridge.has_client():
            ctx.extension_connected = False
            return False
        
        ctx.extension_connected = True
        
        # Request current page info via scan
        result = bridge.request_scan()
        if result:
            url = result.get("url", "")
            title = result.get("title", "")
            ctx.update_from_url(url, title)
            return True
        
    except Exception as e:
        logger.debug(f"[BrowserContext] Extension query failed: {e}")
        ctx.extension_connected = False
    
    return False


def refresh_context_from_wmctrl() -> bool:
    """Refresh context by checking Firefox window titles via wmctrl.
    
    Fallback when extension is not connected.
    
    Returns:
        True if successfully updated
    """
    ctx = get_browser_context()
    
    try:
        from bantz.browser.firefox import _get_all_firefox_windows
        
        windows = _get_all_firefox_windows()
        if windows:
            # Use the first (or focused) Firefox window
            _, title = windows[0]
            ctx.update_from_title(title)
            return True
        
    except Exception as e:
        logger.debug(f"[BrowserContext] wmctrl query failed: {e}")
    
    return False


def refresh_context() -> bool:
    """Refresh browser context using best available method.
    
    Tries extension first, falls back to wmctrl.
    """
    # Try extension first (more accurate)
    if refresh_context_from_extension():
        return True
    
    # Fallback to wmctrl
    return refresh_context_from_wmctrl()
