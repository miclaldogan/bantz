"""Web page opener tool for BrainLoop (Issue #89).

Opens a URL and extracts readable text content.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# URL allowlist patterns (for safety)
ALLOWED_DOMAINS = {
    # Common safe domains
    "wikipedia.org",
    "github.com",
    "stackoverflow.com",
    "python.org",
    "mozilla.org",
    "w3.org",
    # News
    "bbc.com",
    "cnn.com",
    "reuters.com",
    # Turkish
    "tr.wikipedia.org",
    # Can be extended via config
}

# Deny patterns (never allow)
DENY_PATTERNS = [
    r"localhost",
    r"127\.0\.0\.1",
    r"192\.168\.",
    r"10\.",
    r"172\.(1[6-9]|2[0-9]|3[01])\.",  # Private IP ranges
]


def web_open(url: str, max_chars: int = 20000) -> dict[str, Any]:
    """Open a URL and extract readable text.
    
    Args:
        url: URL to open
        max_chars: Maximum characters to return (default: 20000)
    
    Returns:
        {
            "ok": bool,
            "title": str,
            "text": str,
            "url": str,
            "error": str (if ok=False)
        }
    """
    url = str(url or "").strip()
    if not url:
        return {"ok": False, "error": "Empty URL", "url": "", "title": "", "text": ""}
    
    # Validate URL
    if not _is_url_allowed(url):
        return {
            "ok": False,
            "error": "URL not allowed by policy",
            "url": url,
            "title": "",
            "text": "",
        }
    
    try:
        import requests
    except ImportError:
        return {
            "ok": False,
            "error": "requests library not installed",
            "url": url,
            "title": "",
            "text": "",
        }
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        html = response.text
        
        # Extract title
        title = _extract_title(html)
        
        # Extract readable text (simple approach)
        text = _extract_text(html)
        
        # Truncate if too long
        max_chars = max(100, min(int(max_chars or 20000), 50000))
        if len(text) > max_chars:
            text = text[:max_chars - 3] + "..."
        
        return {
            "ok": True,
            "title": title,
            "text": text,
            "url": url,
        }
    
    except Exception as e:
        logger.error(f"web_open error for {url}: {e}")
        return {
            "ok": False,
            "error": str(e),
            "url": url,
            "title": "",
            "text": "",
        }


def _is_url_allowed(url: str) -> bool:
    """Check if URL is allowed by policy."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Check deny patterns
        for pattern in DENY_PATTERNS:
            if re.search(pattern, domain, re.IGNORECASE):
                return False
        
        # For now, allow all HTTPS URLs from known domains
        # In production, implement more strict allowlist
        if parsed.scheme not in ("http", "https"):
            return False
        
        # Check if domain matches allowed patterns
        # Simple approach: allow if contains any allowed domain
        for allowed in ALLOWED_DOMAINS:
            if allowed in domain:
                return True
        
        # For MVP, allow all HTTPS URLs (can be restricted later)
        # Remove this in production for stricter control
        if parsed.scheme == "https":
            return True
        
        return False
    
    except Exception:
        return False


def _extract_title(html: str) -> str:
    """Extract page title from HTML."""
    match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if match:
        title = re.sub(r'<[^>]+>', '', match.group(1)).strip()
        return title[:200]  # Limit length
    return "Untitled"


def _extract_text(html: str) -> str:
    """Extract readable text from HTML (simple approach).
    
    For production, use libraries like:
    - readability-lxml
    - newspaper3k
    - trafilatura
    """
    # Remove script and style tags (Security Alert #44: match tag name with optional whitespace)
    # Pattern matches: </script>, </script >, </  script>, etc.
    html = re.sub(r'<script[^>]*>.*?<\s*/\s*script\s*>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?<\s*/\s*style\s*>', '', html, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html)
    
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    return text
