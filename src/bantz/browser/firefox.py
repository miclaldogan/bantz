"""Firefox Browser Backend for Bantz - Original Profile Only.

Uses the user's ORIGINAL Firefox profile (default-release).
Never creates a separate "Bantz profile" - we ARE the user's browser.

This gives us:
- All existing logins (YouTube, Instagram, Google, etc.)
- Saved passwords (via Firefox Password Manager)
- Cookies and sessions
- The "Jarvis controls my real browser" feeling
"""
from __future__ import annotations

import os
import subprocess
import configparser
import time
import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import threading

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Profile Detection - Find the ORIGINAL profile
# ─────────────────────────────────────────────────────────────────

def _find_firefox_dir() -> Optional[Path]:
    """Find Firefox profile directory (handles snap and native installs)."""
    candidates = [
        Path.home() / ".mozilla" / "firefox",
        Path.home() / "snap" / "firefox" / "common" / ".mozilla" / "firefox",
    ]
    for path in candidates:
        if (path / "profiles.ini").exists():
            return path
    return None


def _get_default_profile() -> Optional[Tuple[str, Path]]:
    """Get the default Firefox profile name and path.
    
    Priority:
    1. [Install*] section Default= value (most reliable)
    2. Profile with Default=1 (fallback)
    
    Returns:
        (profile_name, profile_path) or None if not found
    """
    firefox_dir = _find_firefox_dir()
    if not firefox_dir:
        logger.error("[Firefox] Could not find Firefox profiles directory")
        return None
    
    profiles_ini = firefox_dir / "profiles.ini"
    if not profiles_ini.exists():
        logger.error("[Firefox] profiles.ini not found")
        return None
    
    config = configparser.ConfigParser()
    config.read(profiles_ini)
    
    # First, check [Install*] section for Default - THIS IS THE TRUTH
    install_default = None
    for section in config.sections():
        if section.startswith("Install"):
            if config.has_option(section, "Default"):
                install_default = config.get(section, "Default")
                logger.info(f"[Firefox] Install section says default is: {install_default}")
                break
    
    # Build a map of all profiles
    profiles = {}
    fallback_profile = None
    
    for section in config.sections():
        if section.startswith("Profile"):
            name = config.get(section, "Name", fallback="")
            path = config.get(section, "Path", fallback="")
            is_relative = config.get(section, "IsRelative", fallback="1") == "1"
            is_default = config.get(section, "Default", fallback="0") == "1"
            
            # Build full path
            if is_relative:
                full_path = firefox_dir / path
            else:
                full_path = Path(path)
            
            if full_path.exists():
                profiles[path] = (name, full_path)
                if is_default:
                    fallback_profile = (name, full_path)
    
    # Priority 1: Use Install section's Default
    if install_default and install_default in profiles:
        name, path = profiles[install_default]
        logger.info(f"[Firefox] Using Install default profile: {name} at {path}")
        return (name, path)
    
    # Priority 2: Fallback to Default=1 profile
    if fallback_profile:
        logger.info(f"[Firefox] Using Default=1 profile: {fallback_profile[0]}")
        return fallback_profile
    
    # Priority 3: Any profile with "default-release" in name
    for path, (name, full_path) in profiles.items():
        if "default-release" in path:
            logger.info(f"[Firefox] Using default-release profile: {name}")
            return (name, full_path)
    
    logger.error("[Firefox] Could not determine default profile")
    return None


# Cache the profile info
_default_profile: Optional[Tuple[str, Path]] = None


def get_original_profile() -> Optional[Tuple[str, Path]]:
    """Get the user's original Firefox profile (cached)."""
    global _default_profile
    if _default_profile is None:
        _default_profile = _get_default_profile()
    return _default_profile


# ─────────────────────────────────────────────────────────────────
# Firefox Process Management
# ─────────────────────────────────────────────────────────────────

def _find_firefox_executable() -> Optional[str]:
    """Find Firefox executable."""
    import shutil
    candidates = [
        "firefox",
        "firefox-esr", 
        "/usr/bin/firefox",
        "/snap/bin/firefox",
        "/usr/lib/firefox/firefox",
    ]
    for cmd in candidates:
        if shutil.which(cmd):
            return cmd
    return None


def _is_firefox_running() -> bool:
    """Check if Firefox is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "firefox"],
            capture_output=True,
            text=True,
            timeout=2
        )
        return result.returncode == 0
    except Exception:
        return False


def _get_firefox_pid() -> Optional[int]:
    """Get Firefox main process ID."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "/usr/lib/firefox/firefox$"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split()[0])
        
        # Fallback: any firefox
        result = subprocess.run(
            ["pgrep", "-f", "firefox"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split()[0])
    except Exception:
        pass
    return None


def _find_firefox_window_by_title(title_pattern: str) -> Optional[str]:
    """Find Firefox window ID by title pattern using wmctrl.
    
    Args:
        title_pattern: Substring to search in window title (case insensitive)
        
    Returns:
        Window ID (hex string) or None
    """
    try:
        result = subprocess.run(
            ["wmctrl", "-l"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode != 0:
            return None
        
        title_lower = title_pattern.lower()
        for line in result.stdout.strip().split('\n'):
            # Format: 0x12345678  0 hostname Window Title
            parts = line.split(None, 3)
            if len(parts) >= 4:
                window_id = parts[0]
                window_title = parts[3].lower()
                # Check if it's a Firefox window with matching title
                if ("firefox" in window_title or "mozilla" in window_title) and title_lower in window_title:
                    return window_id
        
        return None
    except Exception as e:
        logger.debug(f"[Firefox] wmctrl error: {e}")
        return None


def _focus_window(window_id: str) -> bool:
    """Focus a window by its ID using wmctrl.
    
    Args:
        window_id: Window ID (hex string from wmctrl)
        
    Returns:
        True if successful
    """
    try:
        result = subprocess.run(
            ["wmctrl", "-i", "-a", window_id],
            capture_output=True,
            timeout=2
        )
        return result.returncode == 0
    except Exception as e:
        logger.debug(f"[Firefox] wmctrl focus error: {e}")
        return False


def _get_all_firefox_windows() -> list:
    """Get all Firefox windows with their titles.
    
    Returns:
        List of (window_id, title) tuples
    """
    windows = []
    try:
        result = subprocess.run(
            ["wmctrl", "-l"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode != 0:
            return windows
        
        for line in result.stdout.strip().split('\n'):
            parts = line.split(None, 3)
            if len(parts) >= 4:
                window_id = parts[0]
                window_title = parts[3]
                # Check if it's a Firefox window
                title_lower = window_title.lower()
                if "firefox" in title_lower or "mozilla" in title_lower:
                    windows.append((window_id, window_title))
        
    except Exception as e:
        logger.debug(f"[Firefox] wmctrl list error: {e}")
    
    return windows


def _get_running_profile() -> Optional[str]:
    """Try to detect which profile the running Firefox is using.
    
    Method: Check /proc/{pid}/cmdline for -profile argument.
    Fallback: Check for fresh lock symlinks.
    """
    # First, double-check Firefox is actually running
    if not _is_firefox_running():
        return None
    
    # Try to get profile from command line
    try:
        result = subprocess.run(
            ["pgrep", "-a", "-f", "firefox.*-profile"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            # Parse: "12345 /usr/lib/firefox/firefox -profile /path/to/profile"
            for line in result.stdout.strip().split('\n'):
                if '-profile' in line:
                    parts = line.split('-profile')
                    if len(parts) > 1:
                        profile_path = parts[1].strip().split()[0]
                        return Path(profile_path).name
    except Exception:
        pass
    
    # Fallback: Check for recent lock symlinks (created in last 10 seconds)
    firefox_dir = _find_firefox_dir()
    if not firefox_dir:
        return None
    
    import os
    now = time.time()
    
    for item in firefox_dir.iterdir():
        if item.is_dir() and not item.name.startswith('.'):
            lock_file = item / "lock"
            
            # Check if lock is a symlink and was modified recently
            if lock_file.is_symlink():
                try:
                    mtime = os.lstat(lock_file).st_mtime
                    # If lock was modified in last 60 seconds, likely active
                    if now - mtime < 60:
                        return item.name
                except Exception:
                    pass
    
    # If Firefox is running but we can't determine profile, assume it's fine
    # (user opened Firefox normally, probably with default profile)
    return None


# ─────────────────────────────────────────────────────────────────
# Main API
# ─────────────────────────────────────────────────────────────────

def start_firefox(url: Optional[str] = None) -> Tuple[bool, str]:
    """Start Firefox with the user's ORIGINAL profile.
    
    If Firefox is already running with the correct profile, opens URL in new tab.
    If Firefox is running with wrong profile, returns error (no auto-switch).
    If Firefox is not running, starts it with original profile.
    """
    firefox_cmd = _find_firefox_executable()
    if not firefox_cmd:
        return False, "Firefox bulunamadı. Kurulu mu?"
    
    profile_info = get_original_profile()
    if not profile_info:
        return False, "Firefox profili bulunamadı. about:profiles sayfasını kontrol et."
    
    profile_name, profile_path = profile_info
    
    # Check if Firefox is already running
    if _is_firefox_running():
        running_profile = _get_running_profile()
        expected_profile_dir = profile_path.name
        
        # Check if it's the correct profile
        if running_profile and running_profile != expected_profile_dir:
            return False, (
                f"Firefox yanlış profille açık ({running_profile}). "
                f"Original profile ({expected_profile_dir}) ile açmak için "
                f"bu pencereyi kapat."
            )
        
        # Firefox is running (hopefully with correct profile)
        if url:
            try:
                subprocess.Popen(
                    [firefox_cmd, "--new-tab", url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return True, f"Açtım: {_format_url(url)}"
            except Exception as e:
                return False, f"Tab açılamadı: {e}"
        
        return True, "Firefox zaten açık"
    
    # Firefox not running - start with original profile
    # Use -P with profile NAME (not path) to bypass profile selector
    args = [
        firefox_cmd,
        "-P", profile_name,  # Use profile NAME, not path
        "-no-remote",  # Allow our instance even if another Firefox is running
    ]
    
    if url:
        args.append(url)
    
    try:
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        
        # Wait a bit for Firefox to start
        time.sleep(1.5)
        
        logger.info(f"[Firefox] Started with original profile: {profile_name}")
        
        if url:
            return True, f"Firefox açıldı: {_format_url(url)}"
        return True, "Firefox açıldı (original profile)"
        
    except Exception as e:
        logger.error(f"[Firefox] Failed to start: {e}")
        return False, f"Firefox başlatılamadı: {e}"


def _format_url(url: str) -> str:
    """Format URL for display (extract site name)."""
    try:
        from urllib.parse import urlparse

        candidate = url.strip()
        if "://" not in candidate:
            candidate = "https://" + candidate

        parsed = urlparse(candidate)
        host = (parsed.hostname or "").lower()

        def host_is(domain: str) -> bool:
            return host == domain

        def host_is_or_subdomain(domain: str) -> bool:
            return host == domain or host.endswith("." + domain)

        if host_is("youtu.be") or host_is_or_subdomain("youtube.com"):
            return "YouTube"
        if host_is_or_subdomain("instagram.com"):
            return "Instagram"
        if host_is("duck.ai") or host_is_or_subdomain("duckduckgo.com"):
            return "DuckDuckGo AI Chat"
        if host_is_or_subdomain("twitter.com") or host_is_or_subdomain("x.com"):
            return "Twitter/X"
        if host_is_or_subdomain("facebook.com"):
            return "Facebook"
        if host_is_or_subdomain("github.com"):
            return "GitHub"
        if host_is_or_subdomain("openai.com") or host_is("chat.openai.com"):
            return "ChatGPT"
        if host_is_or_subdomain("claude.ai"):
            return "Claude"
        if host_is_or_subdomain("google.com") or host_is_or_subdomain("gemini.google.com"):
            return "Gemini"
        if host_is_or_subdomain("perplexity.ai"):
            return "Perplexity"
        if host_is_or_subdomain("whatsapp.com"):
            return "WhatsApp Web"
        if host_is_or_subdomain("telegram.org"):
            return "Telegram Web"
        if host_is_or_subdomain("discord.com"):
            return "Discord"
        if host_is_or_subdomain("reddit.com"):
            return "Reddit"
        if host_is_or_subdomain("linkedin.com"):
            return "LinkedIn"
        if host_is_or_subdomain("spotify.com"):
            return "Spotify"
        if host_is_or_subdomain("netflix.com"):
            return "Netflix"
        if host_is_or_subdomain("twitch.tv"):
            return "Twitch"
        if host_is_or_subdomain("wikipedia.org"):
            return "Wikipedia"

        return parsed.netloc or url
    except Exception:
        return url


def open_url(url: str) -> Tuple[bool, str]:
    """Open URL in Firefox (ensures https://)."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return start_firefox(url)


# Site URL mappings
SITE_URLS = {
    "youtube": "https://www.youtube.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://twitter.com",
    "x": "https://x.com",
    "facebook": "https://www.facebook.com",
    "github": "https://github.com",
    "linkedin": "https://www.linkedin.com",
    "reddit": "https://www.reddit.com",
    "twitch": "https://www.twitch.tv",
    "spotify": "https://open.spotify.com",
    "netflix": "https://www.netflix.com",
    "whatsapp": "https://web.whatsapp.com",
    "telegram": "https://web.telegram.org",
    "discord": "https://discord.com/app",
    "wikipedia": "https://tr.wikipedia.org",
    "vikipedi": "https://tr.wikipedia.org",
    "amazon": "https://www.amazon.com.tr",
    "duck": "https://duck.ai",
    "duckduckgo": "https://duckduckgo.com",
    "chatgpt": "https://chat.openai.com",
    "claude": "https://claude.ai",
    "gemini": "https://gemini.google.com",
    "perplexity": "https://perplexity.ai",
    "google": "https://www.google.com",
}


def open_site(site: str) -> Tuple[bool, str]:
    """Open a known site in Firefox - switches to existing tab if open.
    
    Priority:
    1. If site already open in a Firefox window → focus that window
    2. If Firefox running but site not open → open new tab
    3. If Firefox not running → start Firefox with site
    """
    site_lower = site.lower().strip()
    
    if site_lower not in SITE_URLS:
        # Looks like a domain?
        if "." in site_lower:
            return open_url(site_lower)
        return False, f"Bilmediğim site: {site}. URL olarak söyler misin?"
    
    url = SITE_URLS[site_lower]
    site_name = _format_url(url)
    
    # Check if Firefox is running
    if not _is_firefox_running():
        # Firefox not running - start it with this site
        return start_firefox(url)
    
    # Firefox is running - check if site is already open
    # Use various title patterns that might match
    title_patterns = _get_title_patterns(site_lower)
    
    for pattern in title_patterns:
        window_id = _find_firefox_window_by_title(pattern)
        if window_id:
            # Found existing window/tab with this site - focus it!
            if _focus_window(window_id):
                logger.info(f"[Firefox] Focused existing {site_name} window")
                return True, f"{site_name} penceresine geçtim"
    
    # Site not found in any window - open new tab
    return open_url(url)


def _get_title_patterns(site: str) -> list:
    """Get possible window title patterns for a site.
    
    Args:
        site: Site name (youtube, instagram, etc.)
        
    Returns:
        List of title patterns to search for
    """
    patterns = {
        "youtube": ["youtube", "- youtube"],
        "instagram": ["instagram", "• instagram"],
        "twitter": ["twitter", "x.com", "/ x"],
        "x": ["twitter", "x.com", "/ x"],
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
        "wikipedia": ["vikipedi", "wikipedia"],
        "vikipedi": ["vikipedi", "wikipedia"],
        "amazon": ["amazon"],
        "duck": ["duck.ai", "duckduckgo"],
        "duckduckgo": ["duckduckgo", "duck.ai"],
        "chatgpt": ["chatgpt", "chat.openai"],
        "claude": ["claude"],
        "gemini": ["gemini"],
        "perplexity": ["perplexity"],
        "google": ["google"],
    }
    return patterns.get(site, [site])


def is_running() -> bool:
    """Check if Firefox is running."""
    return _is_firefox_running()


def get_state() -> Dict[str, Any]:
    """Get current Firefox state."""
    running = _is_firefox_running()
    profile_info = get_original_profile()
    
    return {
        "running": running,
        "pid": _get_firefox_pid() if running else None,
        "original_profile": profile_info[0] if profile_info else None,
        "profile_path": str(profile_info[1]) if profile_info else None,
        "running_profile": _get_running_profile() if running else None,
    }


# ─────────────────────────────────────────────────────────────────
# Extension Bridge Check
# ─────────────────────────────────────────────────────────────────

def is_extension_connected() -> bool:
    """Check if Firefox extension is connected to WebSocket bridge."""
    try:
        from bantz.browser.extension_bridge import get_bridge
        bridge = get_bridge()
        return bridge is not None and bridge.has_client()
    except Exception:
        return False


def require_extension() -> Tuple[bool, str]:
    """Check extension connection - returns error message if not connected.
    
    Use this before any extension-dependent operation.
    """
    if not _is_firefox_running():
        return False, "Firefox kapalı. Önce Firefox'u aç."
    
    if not is_extension_connected():
        return False, (
            "Bantz Extension bağlı değil. "
            "Firefox'ta Bantz extension'ı yükle ve bağlan."
        )
    
    return True, "Extension bağlı"
