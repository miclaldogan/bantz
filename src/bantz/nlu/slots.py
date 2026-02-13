# SPDX-License-Identifier: MIT
"""
Slot Extraction Module.

Extracts structured entities (slots) from natural language:
- Time expressions: "5 dakika sonra", "yarın saat 3"
- URLs and site names: "youtube.com", "github"
- App names: "spotify", "discord", "vscode"
- Queries: search terms, file paths

Uses Turkish-aware patterns for accurate extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from bantz.nlu.types import Slot, SlotType


# ============================================================================
# Time Slot
# ============================================================================


@dataclass
class TimeSlot:
    """Extracted time information.
    
    Supports:
    - Relative time: "5 dakika sonra", "yarın", "gelecek hafta"
    - Absolute time: "saat 15:00", "3'te"
    - Combined: "yarın saat 3"
    """
    
    value: datetime
    raw_text: str
    is_relative: bool = True
    confidence: float = 1.0
    
    def to_slot(self) -> Slot:
        """Convert to generic Slot."""
        return Slot(
            name="time",
            value=self.value.isoformat(),
            raw_text=self.raw_text,
            slot_type=SlotType.TIME if not self.is_relative else SlotType.RELATIVE_TIME,
            confidence=self.confidence,
        )


# Turkish number words
TURKISH_NUMBERS = {
    "bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5,
    "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10,
    "yirmi": 20, "otuz": 30, "kırk": 40, "elli": 50,
    "altmış": 60, "yetmiş": 70, "seksen": 80, "doksan": 90,
    "yüz": 100,
    # Common combinations
    "onbir": 11, "oniki": 12, "onüç": 13, "ondört": 14, "onbeş": 15,
    "yarım": 0.5, "buçuk": 0.5,
}

# Time unit patterns
TIME_UNITS = {
    r"saniye|sn": "seconds",
    r"dakika|dk": "minutes",
    r"saat|sa": "hours",
    r"gün": "days",
    r"hafta": "weeks",
    r"ay": "months",
}


def _parse_turkish_number(text: str) -> Optional[float]:
    """Parse Turkish number words to numeric value.

    Issue #1173: Returns float instead of int to support fractional
    values like 'yarım' (0.5) and 'buçuk' (0.5). Callers that need
    int should convert explicitly.
    """
    text = text.lower().strip()
    
    # Direct digit
    if text.isdigit():
        return int(text)
    
    # Direct word match
    if text in TURKISH_NUMBERS:
        return TURKISH_NUMBERS[text]
    
    # Compound numbers like "on beş" or "yirmi üç"
    # Also handles "bir buçuk" (1.5), "iki buçuk" (2.5)
    parts = text.split()
    if len(parts) == 2:
        first = TURKISH_NUMBERS.get(parts[0], 0)
        second = TURKISH_NUMBERS.get(parts[1], 0)
        if parts[1] == "buçuk" and first >= 1:
            return first + 0.5
        if first >= 10 and second < 10:
            return first + second
    
    return None


def extract_time(text: str, base_time: Optional[datetime] = None) -> Optional[TimeSlot]:
    """Extract time from Turkish text.
    
    Supports:
    - Relative: "5 dakika sonra", "yarın", "2 saat sonra"
    - Absolute: "saat 15:00", "3'te", "15.30'da"
    - Combined: "yarın saat 3"
    
    Args:
        text: Input text
        base_time: Base time for relative calculations (default: now)
    
    Returns:
        TimeSlot if found, None otherwise
    """
    if base_time is None:
        # Issue #1179: Use BANTZ_TIMEZONE if available so NLU resolves
        # times in the user's timezone, not the server's.
        import os as _os
        _tz_name = _os.environ.get("BANTZ_TIMEZONE", "").strip()
        if _tz_name:
            try:
                from zoneinfo import ZoneInfo
                base_time = datetime.now(tz=ZoneInfo(_tz_name))
            except Exception:
                base_time = datetime.now()
        else:
            base_time = datetime.now()
    
    text_lower = text.lower()
    
    # Pattern 1: X dakika/saat/gün sonra
    # Issue #1173: Added yarım|buçuk so "yarım saat sonra" is matched.
    pattern_relative = re.compile(
        r"(\d+|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on|yirmi|otuz|yarım|buçuk)\s*"
        r"(saniye|sn|dakika|dk|saat|sa|gün|hafta)\s*"
        r"(sonra|içinde)",
        re.IGNORECASE,
    )
    
    match = pattern_relative.search(text_lower)
    if match:
        num_str = match.group(1)
        unit = match.group(2).lower()
        
        # Parse number
        num = _parse_turkish_number(num_str)
        if num is None:
            num = 1  # Default to 1
        
        # Calculate delta
        unit_key = None
        for pattern, key in TIME_UNITS.items():
            if re.match(pattern, unit):
                unit_key = key
                break
        
        if unit_key:
            delta_kwargs = {unit_key: num}
            target_time = base_time + timedelta(**delta_kwargs)
            
            return TimeSlot(
                value=target_time,
                raw_text=match.group(0),
                is_relative=True,
                confidence=0.95,
            )
    
    # Pattern 2: Yarın, bugün, etc.
    day_offsets = {
        r"\byarın\b": 1,
        r"\bbugün\b": 0,
        r"\bdün\b": -1,
        r"\böbür\s*gün\b": 2,
        r"\bgelecek\s*hafta\b": 7,
        r"\bhaftaya\b": 7,
    }
    
    # Turkish number word pattern for hour extraction
    _TR_NUM_WORDS = '|'.join(sorted(
        [k for k, v in TURKISH_NUMBERS.items() if isinstance(v, int) and 0 < v <= 23],
        key=len, reverse=True,
    ))

    for pattern, offset in day_offsets.items():
        if re.search(pattern, text_lower):
            target_time = base_time + timedelta(days=offset)
            
            # Check for time specification (digits or Turkish number words)
            # Suffix pattern handles dative (-e/-a/-ye/-ya) and locative (-de/-da/-te/-ta)
            time_match = re.search(
                rf"saat\s*(?:(\d{{1,2}})(?:[:.:](\d{{2}}))?|({_TR_NUM_WORDS}))(?:[ydt]?[eaEA])?\b",
                text_lower,
            )
            if time_match:
                if time_match.group(1):
                    hour = int(time_match.group(1))
                    minute = int(time_match.group(2) or 0)
                elif time_match.group(3):
                    hour = int(_parse_turkish_number(time_match.group(3)))
                    minute = 0
                else:
                    hour = 0
                    minute = 0
                # PM heuristic: if hour 1-6 and current time is past noon,
                # assume afternoon.
                if 1 <= hour <= 6 and base_time.hour >= 12:
                    hour += 12
                target_time = target_time.replace(hour=hour, minute=minute, second=0)
            
            raw = re.search(pattern, text_lower)
            return TimeSlot(
                value=target_time,
                raw_text=raw.group(0) if raw else text,
                is_relative=True,
                confidence=0.90,
            )
    
    # Pattern 3: Absolute time "saat 15:00", "3'te"
    time_patterns = [
        r"saat\s*(\d{1,2})(?:[:.:](\d{2}))?",  # saat 15:00
        r"(\d{1,2})[:.:](\d{2})",  # 15:00
        r"(\d{1,2})[''`](?:de|da|te|ta)\b",  # 3'te
    ]
    
    for pattern in time_patterns:
        match = re.search(pattern, text_lower)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.lastindex >= 2 and match.group(2) else 0
            
            # Validate hour
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                # PM heuristic: if hour 1-6 and current time is past noon,
                # assume afternoon.
                if 1 <= hour <= 6 and base_time.hour >= 12:
                    hour += 12
                target_time = base_time.replace(hour=hour, minute=minute, second=0)
                
                # If time has passed today, assume tomorrow
                if target_time < base_time:
                    target_time += timedelta(days=1)
                
                return TimeSlot(
                    value=target_time,
                    raw_text=match.group(0),
                    is_relative=False,
                    confidence=0.85,
                )

    # Pattern 4: "saat dört", "saat ikiye" — Turkish number words as time
    _tr_num_re = '|'.join(sorted(
        [k for k, v in TURKISH_NUMBERS.items() if isinstance(v, int) and 0 < v <= 23],
        key=len, reverse=True,
    ))
    # Suffix pattern: dative -e/-a/-ye/-ya, locative -de/-da/-te/-ta
    tr_time_match = re.search(
        rf"saat\s*({_tr_num_re})(?:[ydt]?[eaEA])?\b",
        text_lower,
    )
    if tr_time_match:
        hour = int(_parse_turkish_number(tr_time_match.group(1)))
        if 1 <= hour <= 6 and base_time.hour >= 12:
            hour += 12
        if 0 <= hour <= 23:
            target_time = base_time.replace(hour=hour, minute=0, second=0)
            if target_time < base_time:
                target_time += timedelta(days=1)
            return TimeSlot(
                value=target_time,
                raw_text=tr_time_match.group(0),
                is_relative=False,
                confidence=0.85,
            )

    return None


# ============================================================================
# URL Slot
# ============================================================================


@dataclass
class URLSlot:
    """Extracted URL information.
    
    Handles both full URLs and site names:
    - "https://youtube.com/watch?v=abc" -> full URL
    - "youtube" -> maps to youtube.com
    """
    
    url: str
    site_name: Optional[str] = None
    raw_text: str = ""
    is_full_url: bool = False
    confidence: float = 1.0
    
    def to_slot(self) -> Slot:
        """Convert to generic Slot."""
        return Slot(
            name="url",
            value=self.url,
            raw_text=self.raw_text,
            slot_type=SlotType.URL,
            confidence=self.confidence,
        )


# Common site mappings
SITE_MAPPINGS = {
    # Social
    "youtube": "https://www.youtube.com",
    "twitter": "https://twitter.com",
    "x": "https://twitter.com",
    "instagram": "https://www.instagram.com",
    "insta": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "fb": "https://www.facebook.com",
    "linkedin": "https://www.linkedin.com",
    "reddit": "https://www.reddit.com",
    "tiktok": "https://www.tiktok.com",
    "twitch": "https://www.twitch.tv",
    "discord": "https://discord.com/app",
    
    # Dev
    "github": "https://github.com",
    "gitlab": "https://gitlab.com",
    "stackoverflow": "https://stackoverflow.com",
    "npm": "https://www.npmjs.com",
    "pypi": "https://pypi.org",
    
    # Search
    "google": "https://www.google.com",
    "bing": "https://www.bing.com",
    "duckduckgo": "https://duckduckgo.com",
    "ddg": "https://duckduckgo.com",
    
    # Reference
    "wikipedia": "https://tr.wikipedia.org",
    "vikipedi": "https://tr.wikipedia.org",
    "wiki": "https://tr.wikipedia.org",
    
    # Shopping
    "amazon": "https://www.amazon.com.tr",
    "trendyol": "https://www.trendyol.com",
    "hepsiburada": "https://www.hepsiburada.com",
    "n11": "https://www.n11.com",
    
    # News
    "haberler": "https://www.google.com/news",
    "news": "https://www.google.com/news",
    
    # Entertainment
    "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com",
    "prime": "https://www.primevideo.com",
    
    # Mail
    "gmail": "https://mail.google.com",
    "mail": "https://mail.google.com",
    "outlook": "https://outlook.live.com",
    
    # Other
    "maps": "https://www.google.com/maps",
    "harita": "https://www.google.com/maps",
    "translate": "https://translate.google.com",
    "çeviri": "https://translate.google.com",
}

# Turkish site suffixes to strip
TURKISH_SUFFIXES = [
    "'a", "'e", "'ı", "'i", "'u", "'ü",
    "'ta", "'te", "'da", "'de",
    "'tan", "'ten", "'dan", "'den",
    "'ya", "'ye", 
    "a", "e", "i", "ı", "u", "ü",  # Without apostrophe
]


def _normalize_site_name(text: str) -> str:
    """Normalize site name by removing Turkish suffixes."""
    text = text.lower().strip()
    
    # Remove common suffixes
    for suffix in sorted(TURKISH_SUFFIXES, key=len, reverse=True):
        if text.endswith(suffix) and len(text) > len(suffix):
            candidate = text[:-len(suffix)]
            if candidate in SITE_MAPPINGS:
                return candidate
    
    return text


def extract_url(text: str) -> Optional[URLSlot]:
    """Extract URL or site name from text.
    
    Args:
        text: Input text
    
    Returns:
        URLSlot if found, None otherwise
    """
    text_lower = text.lower()
    
    # Pattern 1: Full URL
    url_pattern = re.compile(
        r"(https?://[^\s<>\"']+)",
        re.IGNORECASE,
    )
    
    match = url_pattern.search(text)
    if match:
        url = match.group(1)
        # Clean trailing punctuation
        url = re.sub(r"[.,;!?]+$", "", url)
        
        try:
            parsed = urlparse(url)
            site_name = parsed.netloc.replace("www.", "").split(".")[0]
            
            return URLSlot(
                url=url,
                site_name=site_name,
                raw_text=match.group(0),
                is_full_url=True,
                confidence=0.99,
            )
        except Exception:
            pass
    
    # Pattern 2: Domain-like (xxx.com, xxx.org)
    domain_pattern = re.compile(
        r"([a-zA-Z0-9-]+)\.(com|org|net|io|dev|app|tv|co|me|ai)",
        re.IGNORECASE,
    )
    
    match = domain_pattern.search(text)
    if match:
        domain = match.group(0)
        site_name = match.group(1).lower()
        
        return URLSlot(
            url=f"https://{domain}",
            site_name=site_name,
            raw_text=match.group(0),
            is_full_url=False,
            confidence=0.95,
        )
    
    # Pattern 3: Known site names
    words = re.findall(r"[a-zA-ZğüşıöçĞÜŞİÖÇ0-9']+", text_lower)
    
    for word in words:
        normalized = _normalize_site_name(word)
        if normalized in SITE_MAPPINGS:
            return URLSlot(
                url=SITE_MAPPINGS[normalized],
                site_name=normalized,
                raw_text=word,
                is_full_url=False,
                confidence=0.90,
            )
    
    return None


# ============================================================================
# App Slot
# ============================================================================


@dataclass
class AppSlot:
    """Extracted application name.
    
    Maps natural names to executable names:
    - "spotify" -> "spotify"
    - "kod editörü" -> "code" (VS Code)
    - "tarayıcı" -> "firefox"
    """
    
    app_name: str
    executable: Optional[str] = None
    raw_text: str = ""
    confidence: float = 1.0
    
    def to_slot(self) -> Slot:
        """Convert to generic Slot."""
        return Slot(
            name="app",
            value=self.executable or self.app_name,
            raw_text=self.raw_text,
            slot_type=SlotType.APP,
            confidence=self.confidence,
        )


# App name mappings
APP_MAPPINGS = {
    # Browsers
    "firefox": ("firefox", ["firefox", "tarayıcı", "web"]),
    "chrome": ("google-chrome", ["chrome", "krom"]),
    "chromium": ("chromium", ["chromium"]),
    "brave": ("brave-browser", ["brave"]),
    "edge": ("microsoft-edge", ["edge"]),
    
    # Development
    "vscode": ("code", ["vscode", "code", "vs code", "visual studio code", "kod editörü", "editör"]),
    "terminal": ("gnome-terminal", ["terminal", "konsol", "komut satırı"]),
    "sublime": ("sublime_text", ["sublime", "sublime text"]),
    "vim": ("vim", ["vim", "vi"]),
    "neovim": ("nvim", ["neovim", "nvim"]),
    "pycharm": ("pycharm", ["pycharm"]),
    "intellij": ("idea", ["intellij", "idea"]),
    
    # Media
    "spotify": ("spotify", ["spotify", "müzik", "spoti"]),
    "vlc": ("vlc", ["vlc", "video player", "medya oynatıcı"]),
    "totem": ("totem", ["videos", "totem"]),
    
    # Communication
    "discord": ("discord", ["discord", "disc"]),
    "slack": ("slack", ["slack"]),
    "teams": ("teams", ["teams", "microsoft teams"]),
    "zoom": ("zoom", ["zoom"]),
    "telegram": ("telegram-desktop", ["telegram", "tg"]),
    "whatsapp": ("whatsapp-desktop", ["whatsapp", "wp"]),
    
    # Office
    "libreoffice": ("libreoffice", ["libreoffice", "libre", "office"]),
    "writer": ("libreoffice --writer", ["writer", "word"]),
    "calc": ("libreoffice --calc", ["calc", "excel", "tablo"]),
    "impress": ("libreoffice --impress", ["impress", "powerpoint", "sunum"]),
    
    # Files
    "nautilus": ("nautilus", ["nautilus", "dosyalar", "files", "dosya yöneticisi"]),
    "thunar": ("thunar", ["thunar"]),
    
    # System
    "settings": ("gnome-control-center", ["ayarlar", "settings", "sistem ayarları"]),
    "btop": ("btop", ["btop", "htop", "top", "sistem monitörü"]),
    
    # Graphics
    "gimp": ("gimp", ["gimp", "fotoğraf", "resim düzenleyici"]),
    "blender": ("blender", ["blender", "3d"]),
    "inkscape": ("inkscape", ["inkscape", "vektör"]),
    
    # Games
    "steam": ("steam", ["steam", "oyun"]),
}

# Build reverse lookup
_APP_NAME_TO_KEY: Dict[str, str] = {}
for key, (executable, names) in APP_MAPPINGS.items():
    for name in names:
        _APP_NAME_TO_KEY[name.lower()] = key


def extract_app(text: str) -> Optional[AppSlot]:
    """Extract application name from text.
    
    Args:
        text: Input text
    
    Returns:
        AppSlot if found, None otherwise
    """
    text_lower = text.lower()
    
    # Remove common verbs and particles
    cleaned = re.sub(
        r"\b(aç|kapat|başlat|çalıştır|getir|göster|git|uygulamasını|uygulaması|uygulamayı)\b",
        " ",
        text_lower,
    )
    
    # Try to find app names
    words = re.findall(r"[a-zA-ZğüşıöçĞÜŞİÖÇ0-9]+(?:\s+[a-zA-ZğüşıöçĞÜŞİÖÇ0-9]+)?", cleaned)
    
    for word in words:
        word = word.strip().lower()
        
        # Strip Turkish suffixes
        for suffix in TURKISH_SUFFIXES:
            if word.endswith(suffix) and len(word) > len(suffix):
                candidate = word[:-len(suffix)]
                if candidate in _APP_NAME_TO_KEY:
                    word = candidate
                    break
        
        if word in _APP_NAME_TO_KEY:
            key = _APP_NAME_TO_KEY[word]
            executable, _ = APP_MAPPINGS[key]
            
            return AppSlot(
                app_name=key,
                executable=executable,
                raw_text=word,
                confidence=0.90,
            )
    
    return None


# ============================================================================
# Query Slot
# ============================================================================


@dataclass
class QuerySlot:
    """Extracted search query.
    
    Extracts the search terms from commands like:
    - "youtube'da coldplay ara" -> "coldplay"
    - "google'da python tutorial bul" -> "python tutorial"
    """
    
    query: str
    site: Optional[str] = None
    raw_text: str = ""
    confidence: float = 1.0
    
    def to_slot(self) -> Slot:
        """Convert to generic Slot."""
        return Slot(
            name="query",
            value=self.query,
            raw_text=self.raw_text,
            slot_type=SlotType.QUERY,
            confidence=self.confidence,
        )


def extract_query(text: str) -> Optional[QuerySlot]:
    """Extract search query from text.
    
    Args:
        text: Input text
    
    Returns:
        QuerySlot if found, None otherwise
    """
    text_lower = text.lower()
    
    # Pattern 1: "X'da Y ara/bul" or "X'de Y araması yap"
    search_pattern = re.compile(
        r"([a-zA-ZğüşıöçĞÜŞİÖÇ0-9]+)[''`]?(?:da|de|ta|te)\s+(.+?)\s+"
        r"(?:ara|bul|araması|aratır|arat)",
        re.IGNORECASE,
    )
    
    match = search_pattern.search(text_lower)
    if match:
        site = _normalize_site_name(match.group(1))
        query = match.group(2).strip()
        
        return QuerySlot(
            query=query,
            site=site if site in SITE_MAPPINGS else None,
            raw_text=match.group(0),
            confidence=0.90,
        )
    
    # Pattern 2: "Y ara X'da" (reversed)
    reverse_pattern = re.compile(
        r"(.+?)\s+(?:ara|bul)\s+([a-zA-ZğüşıöçĞÜŞİÖÇ0-9]+)[''`]?(?:da|de|ta|te)",
        re.IGNORECASE,
    )
    
    match = reverse_pattern.search(text_lower)
    if match:
        query = match.group(1).strip()
        site = _normalize_site_name(match.group(2))
        
        return QuerySlot(
            query=query,
            site=site if site in SITE_MAPPINGS else None,
            raw_text=match.group(0),
            confidence=0.85,
        )
    
    # Pattern 3: Simple "Y ara" / "Y'yi ara"
    simple_pattern = re.compile(
        r"(.+?)[''`]?(?:yi|ı|i|u|ü)?\s*ara\b",
        re.IGNORECASE,
    )
    
    match = simple_pattern.search(text_lower)
    if match:
        query = match.group(1).strip()
        # Remove leading verbs
        query = re.sub(r"^(?:google|youtube|wiki|vikipedi|bana)\s+", "", query)
        
        if query and len(query) > 1:
            return QuerySlot(
                query=query,
                site=None,
                raw_text=match.group(0),
                confidence=0.75,
            )
    
    return None


# ============================================================================
# Position Slot
# ============================================================================


POSITION_MAPPINGS = {
    # Corners
    "sağ üst": "top-right",
    "üst sağ": "top-right",
    "sol üst": "top-left",
    "üst sol": "top-left",
    "sağ alt": "bottom-right",
    "alt sağ": "bottom-right",
    "sol alt": "bottom-left",
    "alt sol": "bottom-left",
    
    # Edges
    "üst orta": "top-center",
    "orta üst": "top-center",
    "alt orta": "bottom-center",
    "orta alt": "bottom-center",
    "sol orta": "center-left",
    "orta sol": "center-left",
    "sağ orta": "center-right",
    "orta sağ": "center-right",
    
    # Center
    "orta": "center",
    "merkez": "center",
    "ortaya": "center",
}


def extract_position(text: str) -> Optional[Slot]:
    """Extract screen position from text.
    
    Args:
        text: Input text
    
    Returns:
        Slot if found, None otherwise
    """
    text_lower = text.lower()
    
    # Try each position pattern
    for turkish, english in POSITION_MAPPINGS.items():
        if turkish in text_lower:
            return Slot(
                name="position",
                value=english,
                raw_text=turkish,
                slot_type=SlotType.TEXT,
                confidence=0.95,
            )
    
    return None


# ============================================================================
# Slot Extractor (Main Class)
# ============================================================================


class SlotExtractor:
    """Main slot extraction interface.
    
    Extracts all types of slots from text:
    - Time (relative and absolute)
    - URL/site names
    - App names
    - Search queries
    - Positions
    
    Example:
        extractor = SlotExtractor()
        slots = extractor.extract_all("5 dakika sonra spotify aç")
        # {'time': TimeSlot(...), 'app': AppSlot(...)}
    """
    
    def __init__(self):
        """Initialize the extractor."""
        pass
    
    def extract_all(
        self, text: str, *, base_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Extract all possible slots from text.
        
        Args:
            text: Input text
            base_time: Base time for relative calculations. If *None*,
                ``extract_time`` will fall back to ``BANTZ_TIMEZONE`` env
                then ``datetime.now()``.
        
        Returns:
            Dictionary of slot name to extracted value
        """
        slots = {}
        
        # Extract time
        time_slot = extract_time(text, base_time=base_time)
        if time_slot:
            slots["time"] = time_slot
        
        # Extract URL
        url_slot = extract_url(text)
        if url_slot:
            slots["url"] = url_slot
            if url_slot.site_name:
                slots["site"] = url_slot.site_name
        
        # Extract app
        app_slot = extract_app(text)
        if app_slot:
            slots["app"] = app_slot
        
        # Extract query
        query_slot = extract_query(text)
        if query_slot:
            slots["query"] = query_slot
        
        # Extract position
        position_slot = extract_position(text)
        if position_slot:
            slots["position"] = position_slot.value
        
        return slots
    
    def extract_for_intent(
        self,
        text: str,
        intent: str,
    ) -> Dict[str, Any]:
        """Extract slots relevant to a specific intent.
        
        Args:
            text: Input text
            intent: Target intent
        
        Returns:
            Dictionary of relevant slots
        """
        all_slots = self.extract_all(text)
        
        # Filter based on intent
        relevant = {}
        
        if intent.startswith("browser_"):
            if "url" in all_slots:
                relevant["url"] = all_slots["url"].url if hasattr(all_slots["url"], "url") else all_slots["url"]
            if "site" in all_slots:
                relevant["site"] = all_slots["site"]
            if "query" in all_slots:
                relevant["query"] = all_slots["query"].query if hasattr(all_slots["query"], "query") else all_slots["query"]
        
        elif intent.startswith("app_"):
            if "app" in all_slots:
                app = all_slots["app"]
                relevant["app"] = app.executable if hasattr(app, "executable") else app
        
        elif intent in ("reminder_add", "checkin_add"):
            if "time" in all_slots:
                time = all_slots["time"]
                relevant["time"] = time.value.isoformat() if hasattr(time, "value") else time
        
        elif intent == "overlay_move":
            if "position" in all_slots:
                relevant["position"] = all_slots["position"]
        
        return relevant
    
    def to_flat_dict(self, slots: Dict[str, Any]) -> Dict[str, Any]:
        """Convert slot objects to flat dictionary of values.
        
        Args:
            slots: Dictionary of slot objects
        
        Returns:
            Flat dictionary with simple values
        """
        flat = {}
        
        for name, slot in slots.items():
            if hasattr(slot, "value"):
                flat[name] = slot.value
            elif hasattr(slot, "url"):
                flat[name] = slot.url
            elif hasattr(slot, "query"):
                flat[name] = slot.query
            elif hasattr(slot, "executable"):
                flat[name] = slot.executable
            else:
                flat[name] = slot
        
        return flat


# ============================================================================
# Free Slot Request Extraction (Issue #237)
# ============================================================================


@dataclass
class FreeSlotRequest:
    """Extracted free slot search parameters.
    
    Default behavior (Issue #237):
    - duration: 30 minutes (if not specified)
    - window: today 09:00-18:00 (if not specified)
    - One clarifying question max
    """
    
    duration_minutes: int = 30
    day: Optional[str] = None  # "bugün", "yarın", "pazartesi", etc.
    window_start: Optional[str] = None  # "09:00"
    window_end: Optional[str] = None  # "18:00"
    raw_text: str = ""
    needs_clarification: bool = False
    clarification_type: Optional[str] = None  # "duration", "day", "window"


def extract_free_slot_request(text: str, reference_time: Optional[datetime] = None) -> Optional[FreeSlotRequest]:
    """Extract free slot search parameters from natural language.
    
    Patterns supported:
    - "uygun saat var mı" -> default (30m, today 09-18)
    - "yarın 1 saatlik boşluk" -> tomorrow, 60m, 09-18
    - "bugün öğleden sonra boş zaman" -> today, 30m, 13-18
    - "pazartesi sabah toplantı için boşluk" -> monday, 30m (needs duration clarification)
    
    Args:
        text: User input
        reference_time: Current time for relative calculations
    
    Returns:
        FreeSlotRequest or None if not a free slot query
    """
    if reference_time is None:
        reference_time = datetime.now()
    
    text_lower = text.lower().strip()
    
    # Check if this is a free slot query
    free_slot_patterns = [
        r"uygun\s+(saat|zaman|boşluk)",
        r"boş\s+(saat|zaman|slot)",
        r"müsait\s+(saat|zaman)",
        r"ne\s+zaman\s+(boş|müsait|uygun)",
        r"boşluk\s+(var|bul|ara)",
        r"\bboşluk\b",  # standalone "boşluk"
        r"için\s+(boşluk|saat|zaman)",  # "toplantı için boşluk/saat"
        r"toplantı.*için.*saat",  # "toplantı için saat"
        r"(sabah|öğlen|akşam|öğleden sonra)\s+toplantı",  # "akşam toplantı"
    ]
    
    is_free_slot_query = any(re.search(pattern, text_lower) for pattern in free_slot_patterns)
    if not is_free_slot_query:
        return None
    
    request = FreeSlotRequest(raw_text=text)
    
    # Extract duration
    duration_patterns = [
        (r"(\d+)\s*saatlik", lambda m: int(m.group(1)) * 60),
        (r"(\d+)\s*dakika", lambda m: int(m.group(1))),
        (r"(yarım|30)\s*saat", lambda m: 30),
        (r"(bir|1)\s*saat", lambda m: 60),
        (r"(iki|2)\s*saat", lambda m: 120),
    ]
    
    for pattern, extractor in duration_patterns:
        match = re.search(pattern, text_lower)
        if match:
            request.duration_minutes = extractor(match)
            break
    
    # Extract day
    day_patterns = [
        (r"\bbugün\b", "bugün"),
        (r"\byarın\b", "yarın"),
        (r"\bpazartesi\b", "pazartesi"),
        (r"\bsalı\b", "salı"),
        (r"\bçarşamba\b", "çarşamba"),
        (r"\bperşembe\b", "perşembe"),
        (r"\bcuma\b", "cuma"),
        (r"\bcumartesi\b", "cumartesi"),
        (r"\bpazar\b", "pazar"),
    ]
    
    for pattern, day in day_patterns:
        if re.search(pattern, text_lower):
            request.day = day
            break
    
    # Default to today if no day specified
    if request.day is None:
        request.day = "bugün"
    
    # Extract time window hints
    time_of_day_patterns = [
        (r"\bsabah\b", ("09:00", "12:00")),
        (r"\böğleden sonra\b", ("13:00", "18:00")),
        (r"\bakşam\b", ("18:00", "21:00")),
        (r"\böğlen\b", ("12:00", "14:00")),
    ]
    
    for pattern, (start, end) in time_of_day_patterns:
        if re.search(pattern, text_lower):
            request.window_start = start
            request.window_end = end
            break
    
    # Default window: 09:00-18:00 (business hours)
    if request.window_start is None:
        request.window_start = "09:00"
    if request.window_end is None:
        request.window_end = "18:00"
    
    return request


# ============================================================================
# Timezone Extraction (Issue #167)
# ============================================================================


@dataclass
class TimezoneSlot:
    """Extracted timezone information.
    
    Supports city names, timezone abbreviations, and UTC offsets.
    Example: "New York", "PST", "GMT+1", "Istanbul"
    """
    
    iana_name: str  # IANA timezone name: "America/New_York"
    raw_text: str  # Original matched text
    display_name: str  # Human-readable: "New York (EST)"
    confidence: float = 1.0


# Common timezone mappings for natural language
TIMEZONE_MAPPINGS = {
    # Turkish cities
    "istanbul": "Europe/Istanbul",
    "ankara": "Europe/Istanbul",
    "izmir": "Europe/Istanbul",
    
    # Major world cities
    "new york": "America/New_York",
    "newyork": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "london": "Europe/London",
    "paris": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "tokyo": "Asia/Tokyo",
    "hong kong": "Asia/Hong_Kong",
    "singapore": "Asia/Singapore",
    "dubai": "Asia/Dubai",
    "sydney": "Australia/Sydney",
    "moscow": "Europe/Moscow",
    
    # US timezone abbreviations
    "est": "America/New_York",
    "edt": "America/New_York",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "pacific": "America/Los_Angeles",
    "pacific time": "America/Los_Angeles",
    
    # European timezone abbreviations
    "cet": "Europe/Paris",
    "cest": "Europe/Paris",
    "gmt": "Europe/London",
    "bst": "Europe/London",
    
    # Asian timezones
    "jst": "Asia/Tokyo",
    "kst": "Asia/Seoul",
    "ist": "Asia/Kolkata",
    "sgt": "Asia/Singapore",
}

# UTC offset patterns (GMT+1, UTC-5, etc.)
UTC_OFFSET_PATTERN = re.compile(
    r"\b(utc|gmt)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?\b",
    re.IGNORECASE
)


def extract_timezone(text: str) -> Optional[TimezoneSlot]:
    """Extract timezone from natural language.
    
    Patterns supported:
    - City names: "New York", "Istanbul", "Tokyo"
    - Abbreviations: "PST", "EST", "CET"
    - UTC offsets: "GMT+1", "UTC-5", "GMT+5:30"
    
    Args:
        text: User input
    
    Returns:
        TimezoneSlot or None if no timezone found
    """
    text_lower = text.lower().strip()
    
    # Check for UTC offset FIRST (GMT+1, UTC-5, etc.) before abbreviations
    # This prevents "GMT" abbreviation from matching "GMT+1"
    match = UTC_OFFSET_PATTERN.search(text)
    if match:
        base = match.group(1).upper()  # UTC or GMT
        sign = match.group(2)
        hours = int(match.group(3))
        minutes = int(match.group(4)) if match.group(4) else 0
        
        # Build display name
        offset_str = f"{sign}{hours}"
        if minutes:
            offset_str += f":{minutes:02d}"
        
        display = f"{base}{offset_str}"

        # For integer-hour offsets, prefer Etc/GMT zones (note: signs are inverted in Etc/GMT).
        # For minute offsets (e.g., +05:30), represent as a fixed-offset identifier like "UTC+05:30".
        if minutes == 0:
            etc_sign = "-" if sign == "+" else "+"
            return TimezoneSlot(
                iana_name=f"Etc/GMT{etc_sign}{hours}",
                raw_text=match.group(0),
                display_name=display,
                confidence=0.85,  # Lower confidence for offset-only
            )

        # Fixed offset token handled by downstream formatting/construction.
        fixed = f"{base}{sign}{hours:02d}:{minutes:02d}"
        return TimezoneSlot(
            iana_name=fixed,
            raw_text=match.group(0),
            display_name=display,
            confidence=0.85,
        )
    
    # Check for direct city/abbreviation matches
    for key, iana_name in TIMEZONE_MAPPINGS.items():
        # Use word boundaries for abbreviations, flexible for multi-word cities
        if len(key.split()) > 1:
            # Multi-word city names
            if key in text_lower:
                return TimezoneSlot(
                    iana_name=iana_name,
                    raw_text=key,
                    display_name=key.title(),
                    confidence=0.95,
                )
        else:
            # Single word or abbreviations - use word boundaries
            pattern = rf"\b{re.escape(key)}\b"
            if re.search(pattern, text_lower):
                return TimezoneSlot(
                    iana_name=iana_name,
                    raw_text=key,
                    display_name=key.upper() if len(key) <= 4 else key.title(),
                    confidence=0.95,
                )
    
    return None


def format_timezone_aware_time(dt: datetime, timezone_name: str) -> str:
    """Format datetime with timezone information.
    
    Args:
        dt: Datetime object
        timezone_name: IANA timezone name
    
    Returns:
        Formatted string like "15:00 EST" or "15:00 PST"
    """
    tz_name = str(timezone_name or "").strip()
    if not tz_name:
        return dt.strftime("%H:%M")

    # First try IANA via zoneinfo.
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
        dt_tz = dt.astimezone(tz)
        time_str = dt_tz.strftime("%H:%M")
        tz_abbr = dt_tz.strftime("%Z")
        return f"{time_str} {tz_abbr}".strip()
    except Exception:
        pass

    # Fallback: fixed-offset tokens like "UTC+05:30" / "GMT-04:00".
    try:
        from datetime import timedelta, timezone

        m = re.match(r"^(UTC|GMT)\s*([+-])\s*(\d{1,2})(?::(\d{2}))?$", tz_name, flags=re.IGNORECASE)
        if m:
            sign = 1 if m.group(2) == "+" else -1
            hours = int(m.group(3))
            minutes = int(m.group(4) or 0)
            offset = timedelta(hours=hours, minutes=minutes) * sign
            label = f"{m.group(1).upper()}{m.group(2)}{hours:02d}:{minutes:02d}"
            tz = timezone(offset, name=label)
            dt_tz = dt.astimezone(tz)
            return f"{dt_tz.strftime('%H:%M')} {dt_tz.strftime('%Z')}".strip()
    except Exception:
        pass

    return dt.strftime("%H:%M")
