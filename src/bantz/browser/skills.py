"""Browser skills for Bantz - Firefox Original Profile + Extension.

All browser commands go through Firefox with user's ORIGINAL profile.
Extension bridge handles in-page interactions (scan, click, type).
Playwright has been removed - Firefox is the only backend.
"""
from __future__ import annotations

from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# Firefox Backend - Original Profile
# ─────────────────────────────────────────────────────────────────

from bantz.browser.firefox import (
    open_url,
    open_site,
    is_running as is_firefox_running,
    start_firefox,
    get_state as get_firefox_state,
    require_extension,
    SITE_URLS,
)


def browser_navigate(url: str) -> Tuple[bool, str]:
    """Open URL in Firefox browser."""
    from bantz.browser.context import get_browser_context
    
    ok, msg = open_url(url)
    
    # Update context on success
    if ok:
        ctx = get_browser_context()
        ctx.update_from_url(url)
        ctx.record_action("navigate", url=url)
    
    return ok, msg


def browser_open(site_or_url: str) -> Tuple[bool, str]:
    """Open a site or URL in Firefox.
    
    Args:
        site_or_url: Site name (youtube, duck, etc.) or full URL
    """
    from bantz.browser.context import get_browser_context
    
    site_lower = site_or_url.lower().strip()
    
    # Check if it's a known site
    if site_lower in SITE_URLS:
        ok, msg = open_site(site_lower)
        
        # Update context on success
        if ok:
            ctx = get_browser_context()
            ctx.record_action("open_site", site=site_lower, url=SITE_URLS.get(site_lower))
            ctx.active_site = site_lower
        
        return ok, msg
    
    # Check if it's a URL
    if "." in site_lower or site_lower.startswith(("http://", "https://")):
        ok, msg = open_url(site_or_url)
        
        if ok:
            ctx = get_browser_context()
            ctx.update_from_url(site_or_url)
            ctx.record_action("open_url", url=site_or_url)
        
        return ok, msg
    
    # Unknown - try as site name anyway
    return open_site(site_or_url)


# ─────────────────────────────────────────────────────────────────
# Extension Bridge Commands (for advanced interactions)
# These require the Firefox extension to be installed
# ─────────────────────────────────────────────────────────────────

def _get_bridge():
    """Get the extension bridge instance."""
    try:
        from bantz.browser.extension_bridge import get_bridge
        return get_bridge()
    except Exception as e:
        logger.warning(f"Extension bridge not available: {e}")
        return None


def browser_scan() -> Tuple[bool, str, Optional[dict]]:
    """Scan current page for interactable elements via extension.
    
    Returns:
        (success, message, scan_data)
    """
    bridge = _get_bridge()
    if not bridge or not bridge.has_client():
        return False, "Extension bağlı değil. Firefox'ta Bantz extension yüklü mü?", None
    
    try:
        result = bridge.request_scan()
        if result:
            return True, f"Sayfa tarandı: {len(result.get('elements', []))} öğe bulundu", result
        return False, "Tarama sonucu alınamadı", None
    except Exception as e:
        return False, f"Tarama hatası: {e}", None


def browser_click_index(index: int) -> Tuple[bool, str]:
    """Click element by index from last scan (via extension)."""
    bridge = _get_bridge()
    if not bridge or not bridge.has_client():
        return False, "Extension bağlı değil"
    
    try:
        ok = bridge.request_click(index=index)
        if ok:
            return True, f"[{index}] öğesine tıkladım"
        return False, f"[{index}] tıklanamadı"
    except Exception as e:
        return False, f"Tıklama hatası: {e}"


def browser_click_text(text: str) -> Tuple[bool, str]:
    """Click element by text match (via extension)."""
    bridge = _get_bridge()
    if not bridge or not bridge.has_client():
        return False, "Extension bağlı değil"
    
    try:
        ok = bridge.request_click(text=text)
        if ok:
            return True, f"'{text}' öğesine tıkladım"
        return False, f"'{text}' tıklanamadı"
    except Exception as e:
        return False, f"Tıklama hatası: {e}"


def browser_type_text(text: str, element_index: Optional[int] = None) -> Tuple[bool, str]:
    """Type text into element (via extension)."""
    bridge = _get_bridge()
    if not bridge or not bridge.has_client():
        return False, "Extension bağlı değil"
    
    try:
        ok = bridge.request_type(text, element_index=element_index)
        if ok:
            return True, f"Yazdım: {text[:30]}..."
        return False, "Yazılamadı"
    except Exception as e:
        return False, f"Yazma hatası: {e}"


def browser_scroll_down() -> Tuple[bool, str]:
    """Scroll page down (via extension)."""
    bridge = _get_bridge()
    if not bridge or not bridge.has_client():
        return False, "Extension bağlı değil"
    
    try:
        ok = bridge.request_scroll("down")
        return (True, "Aşağı kaydırdım") if ok else (False, "Kaydırılamadı")
    except Exception as e:
        return False, f"Kaydırma hatası: {e}"


def browser_scroll_up() -> Tuple[bool, str]:
    """Scroll page up (via extension)."""
    bridge = _get_bridge()
    if not bridge or not bridge.has_client():
        return False, "Extension bağlı değil"
    
    try:
        ok = bridge.request_scroll("up")
        return (True, "Yukarı kaydırdım") if ok else (False, "Kaydırılamadı")
    except Exception as e:
        return False, f"Kaydırma hatası: {e}"


def browser_go_back() -> Tuple[bool, str]:
    """Go back in browser history (via extension)."""
    bridge = _get_bridge()
    if not bridge or not bridge.has_client():
        # Fallback: just say we can't
        return False, "Extension bağlı değil"
    
    # Extension doesn't have go_back yet, but we can add it
    return False, "Geri gitme henüz desteklenmiyor"


def browser_current_info() -> Tuple[bool, str]:
    """Get current page info (via extension)."""
    bridge = _get_bridge()
    if not bridge or not bridge.has_client():
        return False, "Extension bağlı değil"
    
    try:
        result = bridge.request_scan()  # scan includes URL and title
        if result:
            return True, f"Sayfa: {result.get('title', '?')}\nURL: {result.get('url', '?')}"
        return False, "Bilgi alınamadı"
    except Exception as e:
        return False, f"Hata: {e}"


def browser_wait(seconds: int) -> Tuple[bool, str]:
    """Wait for specified seconds."""
    import time
    if seconds < 1:
        seconds = 1
    if seconds > 30:
        seconds = 30
    time.sleep(seconds)
    return True, f"{seconds} saniye bekledim"


def browser_search_in_page(query: str, force_site: str = None) -> Tuple[bool, str]:
    """Search within the current page context (context-aware).
    
    Uses BrowserContext to determine which site we're on, then searches there.
    This is the HEURISTIC layer - no LLM needed for common cases.
    
    Priority:
    1. force_site parameter (if explicitly specified)
    2. BrowserContext.active_site (tracked state)
    3. Extension scan (real-time check)
    4. Default to YouTube
    
    Args:
        query: Search term
        force_site: Optional site to force search on (youtube, instagram, etc.)
        
    Returns:
        (success, message)
    """
    from urllib.parse import quote_plus
    from bantz.browser.context import get_browser_context, refresh_context
    
    # Get current context
    ctx = get_browser_context()
    
    # Determine which site to search on
    site = None
    
    # Priority 1: Explicit site parameter
    if force_site:
        site = force_site.lower()
    
    # Priority 2: Use tracked context (if not stale)
    if not site and ctx.active_site and not ctx.is_stale(max_age_seconds=60):
        site = ctx.active_site
        logger.debug(f"[Search] Using tracked context: {site}")
    
    # Priority 3: Refresh from extension/wmctrl
    if not site:
        refresh_context()
        if ctx.active_site:
            site = ctx.active_site
            logger.debug(f"[Search] Refreshed context: {site}")
    
    # Priority 4: Default to YouTube
    if not site:
        site = "youtube"
        logger.debug("[Search] No context, defaulting to YouTube")
    
    # Build search URL based on site
    search_urls = {
        "youtube": f"https://www.youtube.com/results?search_query={quote_plus(query)}",
        "instagram": f"https://www.instagram.com/explore/tags/{quote_plus(query.replace(' ', ''))}/",
        "google": f"https://www.google.com/search?q={quote_plus(query)}",
        "wikipedia": f"https://tr.wikipedia.org/w/index.php?search={quote_plus(query)}",
        "twitter": f"https://twitter.com/search?q={quote_plus(query)}",
        "reddit": f"https://www.reddit.com/search/?q={quote_plus(query)}",
        "github": f"https://github.com/search?q={quote_plus(query)}",
        "amazon": f"https://www.amazon.com.tr/s?k={quote_plus(query)}",
        "spotify": f"https://open.spotify.com/search/{quote_plus(query)}",
        "twitch": f"https://www.twitch.tv/search?term={quote_plus(query)}",
    }
    
    search_url = search_urls.get(site, f"https://www.youtube.com/results?search_query={quote_plus(query)}")
    
    # Site display names
    site_names = {
        "youtube": "YouTube",
        "instagram": "Instagram",
        "google": "Google",
        "wikipedia": "Wikipedia",
        "twitter": "Twitter/X",
        "reddit": "Reddit",
        "github": "GitHub",
        "amazon": "Amazon",
        "spotify": "Spotify",
        "twitch": "Twitch",
    }
    site_name = site_names.get(site, site.capitalize())
    
    # Execute search
    ok, msg = open_url(search_url)
    
    # Record action in context
    if ok:
        ctx.record_action("search", site=site, query=query, url=search_url)
        return True, f"{site_name}'da aradım: {query}"
    
    return False, msg


def get_search_site_from_context() -> Optional[str]:
    """Get the current site for search context.
    
    Helper function for intent parsing to determine search context.
    """
    from bantz.browser.context import get_browser_context, refresh_context
    
    ctx = get_browser_context()
    
    # Refresh if stale
    if ctx.is_stale(max_age_seconds=30):
        refresh_context()
    
    return ctx.active_site


# ─────────────────────────────────────────────────────────────────
# AI Chat Skills (duck.ai, chatgpt, etc.)
# ─────────────────────────────────────────────────────────────────

# URL mapping for AI services
_AI_SERVICE_URLS = {
    "duck": "https://duck.ai",
    "chatgpt": "https://chat.openai.com",
    "claude": "https://claude.ai",
    "gemini": "https://gemini.google.com",
    "perplexity": "https://perplexity.ai",
}


def browser_ai_chat(service: str, prompt: str) -> Tuple[bool, str]:
    """Navigate to AI chat service and prepare to send prompt.
    
    Opens the service in Firefox. The user can then interact manually
    or wait for extension-based automation.
    
    Args:
        service: AI service name (duck, chatgpt, claude, gemini, perplexity)
        prompt: Text to send to the AI
    
    Returns:
        (success, message)
    """
    service_lower = service.lower()
    url = _AI_SERVICE_URLS.get(service_lower)
    if not url:
        return False, f"Bilinmeyen AI servisi: {service}. Desteklenen: {', '.join(_AI_SERVICE_URLS.keys())}"
    
    # Open the service in Firefox
    ok, msg = open_url_in_firefox(url)
    if not ok:
        return False, f"{service} açılamadı: {msg}"
    
    # Try to use extension to type the prompt
    bridge = _get_bridge()
    if bridge and bridge.has_client():
        import time
        time.sleep(2)  # Wait for page to load
        
        # Try to type the prompt via extension
        try:
            ok = bridge.request_type(prompt, submit=True)
            if ok:
                return True, f"✅ {service.capitalize()}'a sordum: \"{prompt[:50]}{'...' if len(prompt) > 50 else ''}\""
        except Exception as e:
            logger.warning(f"Extension type failed: {e}")
    
    # Extension not available or failed - still successful opening
    return True, f"✅ {service.capitalize()} açıldı. Sorgunuz: \"{prompt[:50]}{'...' if len(prompt) > 50 else ''}\""


def browser_detail(index: int) -> Tuple[bool, str]:
    """Get detailed info about an element (via extension scan data)."""
    # This would need cached scan data - simplified for now
    return False, "Detay görüntüleme henüz desteklenmiyor. 'sayfayı tara' komutunu kullanın."


def browser_profile_action(action_name: str, **variables) -> Tuple[bool, str]:
    """Execute a site profile action (via extension).
    
    This is a placeholder - full profile actions need extension support.
    """
    return False, "Profil aksiyonları henüz desteklenmiyor"


# ─────────────────────────────────────────────────────────────────
# Interactive Search Primitives (Extension-based)
# ─────────────────────────────────────────────────────────────────

def youtube_search_interactive(query: str) -> Tuple[bool, str]:
    """Search on YouTube using extension (click search box → type → enter).
    
    Alternative to URL-based search - works even on video pages.
    
    Args:
        query: Search term
        
    Returns:
        (success, message)
    """
    bridge = _get_bridge()
    if not bridge or not bridge.has_client():
        # Fallback to URL-based search
        logger.debug("[YouTube] Extension not connected, falling back to URL")
        from urllib.parse import quote_plus
        return open_url(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
    
    import time
    
    try:
        # Step 1: Click search input (multiple possible selectors)
        # Try clicking by text first
        clicked = bridge.request_click(text="Search")
        if not clicked:
            clicked = bridge.request_click(text="Ara")
        
        time.sleep(0.3)
        
        # Step 2: Type query with submit
        ok = bridge.request_type(query, submit=True)
        
        if ok:
            # Update context
            from bantz.browser.context import get_browser_context
            ctx = get_browser_context()
            ctx.record_action("search", site="youtube", query=query)
            
            return True, f"YouTube'da aradım: {query}"
        else:
            # Fallback to URL
            from urllib.parse import quote_plus
            return open_url(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
            
    except Exception as e:
        logger.warning(f"[YouTube] Interactive search failed: {e}")
        from urllib.parse import quote_plus
        return open_url(f"https://www.youtube.com/results?search_query={quote_plus(query)}")


def focus_search_box() -> Tuple[bool, str]:
    """Focus the search box on current page.
    
    Works on YouTube, Google, and other sites with standard search boxes.
    """
    bridge = _get_bridge()
    if not bridge or not bridge.has_client():
        return False, "Extension bağlı değil"
    
    # Try common search box selectors
    search_texts = ["Search", "Ara", "Arama"]
    
    for text in search_texts:
        if bridge.request_click(text=text):
            return True, "Arama kutusuna odaklandım"
    
    # Try by index if scan was done
    scan = bridge.get_last_scan()
    if scan:
        elements = scan.get("elements", [])
        for i, el in enumerate(elements):
            if el.get("tag") == "input" and "search" in el.get("text", "").lower():
                bridge.request_click(index=i)
                return True, "Arama kutusuna odaklandım"
    
    return False, "Arama kutusu bulunamadı"


def type_and_submit(text: str) -> Tuple[bool, str]:
    """Type text and press Enter.
    
    Used after focus_search_box() or clicking an input.
    """
    bridge = _get_bridge()
    if not bridge or not bridge.has_client():
        return False, "Extension bağlı değil"
    
    ok = bridge.request_type(text, submit=True)
    if ok:
        return True, f"Yazdım ve gönderdim: {text[:30]}..."
    return False, "Yazılamadı"


# ─────────────────────────────────────────────────────────────────
# Context Info Helper
# ─────────────────────────────────────────────────────────────────

def get_browser_state() -> dict:
    """Get current browser state for debugging/logging.
    
    Returns:
        Dictionary with active_site, active_url, etc.
    """
    from bantz.browser.context import get_browser_context, refresh_context
    from bantz.browser.firefox import get_state as get_firefox_state
    
    ctx = get_browser_context()
    refresh_context()
    
    return {
        "browser_context": ctx.snapshot(),
        "firefox": get_firefox_state(),
        "extension_connected": ctx.extension_connected,
    }


# ─────────────────────────────────────────────────────────────────
# Compatibility exports
# ─────────────────────────────────────────────────────────────────

def get_page_memory():
    """Legacy - page memory is now handled by extension."""
    return None
