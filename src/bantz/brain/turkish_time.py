"""Turkish Time Window Parsing (Issue #229).

This module provides Turkish natural language time parsing for:
- "önümüzdeki X saat" (next X hours)
- "bu akşam" (this evening)
- "yarın" (tomorrow)
- "yarın sabah" (tomorrow morning)
- "bu hafta" (this week)
- "öğle" (noon)
- Relative time expressions

All outputs are timezone-aware RFC3339 datetime strings.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any, Optional, Tuple, Union

try:
    import zoneinfo
    ZoneInfo = zoneinfo.ZoneInfo
except ImportError:
    # Python 3.8 fallback
    try:
        from backports import zoneinfo  # type: ignore
        ZoneInfo = zoneinfo.ZoneInfo
    except ImportError:
        ZoneInfo = None  # type: ignore


# Turkish word to number mapping
TURKISH_NUMBERS: dict[str, int] = {
    "bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5,
    "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10,
    "onbir": 11, "oniki": 12, "yarım": 0,  # yarım saat = 30 min
}

# Turkish time period definitions (start_hour, end_hour)
TIME_PERIODS: dict[str, tuple[int, int]] = {
    "sabah": (6, 12),      # Morning: 06:00-12:00
    "öğle": (12, 14),      # Noon: 12:00-14:00
    "öğleden_sonra": (14, 18),  # Afternoon: 14:00-18:00
    "akşam": (18, 22),     # Evening: 18:00-22:00
    "gece": (22, 6),       # Night: 22:00-06:00
}


def get_timezone(tz: Optional[Union[str, tzinfo]] = None) -> tzinfo:
    """Get timezone object from string or tzinfo."""
    if tz is None:
        # Default to UTC if no timezone provided
        if ZoneInfo is not None:
            return ZoneInfo("UTC")
        from datetime import timezone
        return timezone.utc
    
    if isinstance(tz, tzinfo):
        return tz
    
    if isinstance(tz, str):
        if ZoneInfo is not None:
            try:
                return ZoneInfo(tz)
            except Exception:
                pass
        # Fallback to UTC for unknown strings
        from datetime import timezone
        return timezone.utc
    
    from datetime import timezone
    return timezone.utc


def parse_time_window_tr(
    text: str,
    now: Optional[datetime] = None,
    tz: Optional[Union[str, tzinfo]] = None,
) -> Optional[dict[str, Any]]:
    """Parse Turkish natural language time expression to time window.
    
    Args:
        text: Turkish time expression (e.g., "yarın akşam", "önümüzdeki 2 saat")
        now: Reference datetime (defaults to current time)
        tz: Timezone (string like "Europe/Istanbul" or tzinfo object)
        
    Returns:
        Dict with:
            - start: RFC3339 datetime string
            - end: RFC3339 datetime string  
            - hint: Original time hint (e.g., "tomorrow_evening")
            - confidence: Parsing confidence 0.0-1.0
        Or None if no time expression found.
    
    Examples:
        >>> parse_time_window_tr("yarın sabah", tz="Europe/Istanbul")
        {"start": "2024-01-16T06:00:00+03:00", "end": "2024-01-16T12:00:00+03:00", ...}
        
        >>> parse_time_window_tr("önümüzdeki 3 saat", tz="Europe/Istanbul")
        {"start": "2024-01-15T14:00:00+03:00", "end": "2024-01-15T17:00:00+03:00", ...}
    """
    if not text:
        return None
    
    text = text.lower().strip()
    timezone_obj = get_timezone(tz)
    
    if now is None:
        now = datetime.now(timezone_obj)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone_obj)
    
    # Try each pattern in order of specificity
    parsers = [
        _parse_next_n_hours,
        _parse_tomorrow_period,
        _parse_today_period,
        _parse_this_week,
        _parse_specific_day,
        _parse_relative_period,
    ]
    
    for parser in parsers:
        result = parser(text, now, timezone_obj)
        if result is not None:
            return result
    
    return None


def _parse_next_n_hours(
    text: str, 
    now: datetime, 
    tz: tzinfo,
) -> Optional[dict[str, Any]]:
    """Parse 'önümüzdeki X saat' pattern."""
    
    # Pattern: önümüzdeki/sonraki + number + saat/dakika
    patterns = [
        r"önümüzdeki\s+(\d+)\s*saat",
        r"sonraki\s+(\d+)\s*saat",
        r"önümüzdeki\s+(\w+)\s*saat",
        r"sonraki\s+(\w+)\s*saat",
        r"(\d+)\s*saat\s*içinde",
        r"(\w+)\s*saat\s*içinde",
        r"önümüzdeki\s+(\d+)\s*dakika",
        r"(\d+)\s*dakika\s*içinde",
        r"yarım\s*saat\s*içinde",
        r"önümüzdeki\s+yarım\s*saat",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            # Handle "yarım saat" (half hour)
            if "yarım" in pattern or "yarım" in text:
                minutes = 30
                hours = 0
            elif match.groups():
                num_str = match.group(1)
                # Try parsing as integer
                try:
                    num = int(num_str)
                except ValueError:
                    # Try Turkish word
                    num = TURKISH_NUMBERS.get(num_str.lower())
                    if num is None:
                        continue
                
                if "dakika" in pattern:
                    minutes = num
                    hours = 0
                else:
                    hours = num
                    minutes = 0
            else:
                continue
            
            start = now.replace(second=0, microsecond=0)
            delta = timedelta(hours=hours, minutes=minutes)
            end = start + delta
            
            return {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "hint": f"next_{hours}h_{minutes}m" if minutes else f"next_{hours}h",
                "confidence": 0.9,
            }
    
    return None


def _parse_tomorrow_period(
    text: str, 
    now: datetime, 
    tz: tzinfo,
) -> Optional[dict[str, Any]]:
    """Parse 'yarın' with optional period."""
    
    if "yarın" not in text:
        return None
    
    tomorrow = now.date() + timedelta(days=1)
    
    # Check for period qualifiers
    if "sabah" in text:
        start_hour, end_hour = TIME_PERIODS["sabah"]
        hint = "tomorrow_morning"
    elif "öğle" in text:
        start_hour, end_hour = TIME_PERIODS["öğle"]
        hint = "tomorrow_noon"
    elif "öğleden sonra" in text or "öğleden_sonra" in text:
        start_hour, end_hour = TIME_PERIODS["öğleden_sonra"]
        hint = "tomorrow_afternoon"
    elif "akşam" in text:
        start_hour, end_hour = TIME_PERIODS["akşam"]
        hint = "tomorrow_evening"
    elif "gece" in text:
        start_hour, end_hour = TIME_PERIODS["gece"]
        hint = "tomorrow_night"
    else:
        # Default: whole day
        start_hour, end_hour = 0, 24
        hint = "tomorrow"
    
    # Handle night period (crosses midnight)
    if start_hour > end_hour:
        start_dt = datetime.combine(tomorrow, time(start_hour, 0), tzinfo=tz)
        end_dt = datetime.combine(tomorrow + timedelta(days=1), time(end_hour, 0), tzinfo=tz)
    else:
        start_dt = datetime.combine(tomorrow, time(start_hour, 0), tzinfo=tz)
        if end_hour == 24:
            end_dt = datetime.combine(tomorrow + timedelta(days=1), time(0, 0), tzinfo=tz)
        else:
            end_dt = datetime.combine(tomorrow, time(end_hour, 0), tzinfo=tz)
    
    return {
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "hint": hint,
        "confidence": 0.85,
    }


def _parse_today_period(
    text: str, 
    now: datetime, 
    tz: tzinfo,
) -> Optional[dict[str, Any]]:
    """Parse 'bugün' or 'bu akşam/sabah' patterns."""
    
    today = now.date()
    
    # Check for "bu akşam"
    if "bu akşam" in text or (text.strip() == "akşam"):
        start_hour, end_hour = TIME_PERIODS["akşam"]
        start_dt = datetime.combine(today, time(start_hour, 0), tzinfo=tz)
        end_dt = datetime.combine(today, time(end_hour, 0), tzinfo=tz)
        return {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "hint": "evening",
            "confidence": 0.9,
        }
    
    # Check for "bu sabah"
    if "bu sabah" in text or (text.strip() == "sabah"):
        start_hour, end_hour = TIME_PERIODS["sabah"]
        start_dt = datetime.combine(today, time(start_hour, 0), tzinfo=tz)
        end_dt = datetime.combine(today, time(end_hour, 0), tzinfo=tz)
        return {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "hint": "morning",
            "confidence": 0.9,
        }
    
    # Check for "öğle"/"öğlen"
    if "öğle" in text or "öğlen" in text:
        start_hour, end_hour = TIME_PERIODS["öğle"]
        start_dt = datetime.combine(today, time(start_hour, 0), tzinfo=tz)
        end_dt = datetime.combine(today, time(end_hour, 0), tzinfo=tz)
        return {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "hint": "noon",
            "confidence": 0.85,
        }
    
    # Check for "bugün"
    if "bugün" in text:
        start_dt = datetime.combine(today, time(0, 0), tzinfo=tz)
        end_dt = datetime.combine(today + timedelta(days=1), time(0, 0), tzinfo=tz)
        return {
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "hint": "today",
            "confidence": 0.8,
        }
    
    return None


def _parse_this_week(
    text: str, 
    now: datetime, 
    tz: tzinfo,
) -> Optional[dict[str, Any]]:
    """Parse 'bu hafta' pattern."""
    
    if "bu hafta" not in text and "hafta içi" not in text:
        return None
    
    today = now.date()
    
    if "hafta içi" in text:
        # Weekdays only (Mon-Fri)
        # Find next Monday if already past
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0 and today.weekday() == 0:
            monday = today
        elif today.weekday() < 5:  # Currently weekday
            monday = today - timedelta(days=today.weekday())
        else:  # Weekend
            days_until_monday = (7 - today.weekday()) % 7
            monday = today + timedelta(days=days_until_monday)
        
        friday = monday + timedelta(days=4)
        start_dt = datetime.combine(monday, time(0, 0), tzinfo=tz)
        end_dt = datetime.combine(friday + timedelta(days=1), time(0, 0), tzinfo=tz)
        hint = "weekdays"
    else:
        # This week (Sun/Mon to Sat/Sun depending on locale)
        # Use Monday as week start
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        start_dt = datetime.combine(monday, time(0, 0), tzinfo=tz)
        end_dt = datetime.combine(sunday + timedelta(days=1), time(0, 0), tzinfo=tz)
        hint = "week"
    
    return {
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "hint": hint,
        "confidence": 0.8,
    }


def _parse_specific_day(
    text: str, 
    now: datetime, 
    tz: tzinfo,
) -> Optional[dict[str, Any]]:
    """Parse specific day names like 'pazartesi', 'salı', etc.

    Issue #602: Context-aware direction —
      - 'geçen/önceki/son' → look backward (past occurrence)
      - 'bu/gelecek/önümüzdeki' → look forward (future occurrence)
      - Ambiguous → default forward (most natural expectation)
    """
    
    # Turkish day names to weekday number (0=Monday)
    # Sorted by length descending to match longer names first (cumartesi before cuma)
    day_names = [
        ("cumartesi", 5),
        ("pazartesi", 0),
        ("perşembe", 3),
        ("çarşamba", 2),
        ("pazar", 6),
        ("salı", 1),
        ("cuma", 4),
    ]
    
    today = now.date()

    # Determine direction from context keywords
    look_backward = any(kw in text for kw in ["geçen ", "önceki ", "son "])
    look_forward = any(kw in text for kw in ["bu ", "gelecek ", "önümüzdeki "])
    
    for day_name, weekday in day_names:
        if day_name in text:
            if look_backward:
                # Past occurrence: how many days ago was that weekday?
                days_back = (today.weekday() - weekday) % 7
                if days_back == 0:
                    days_back = 7  # "geçen pazartesi" on Monday = last Monday
                target_date = today - timedelta(days=days_back)
            else:
                # Future occurrence (default): how many days until that weekday?
                days_ahead = (weekday - today.weekday()) % 7
                if days_ahead == 0:
                    # Same day — "bu salı" on Tuesday = today; but bare "salı" = next week
                    if look_forward:
                        days_ahead = 0  # "bu salı" = today
                    else:
                        days_ahead = 7  # bare "salı" = next week
                target_date = today + timedelta(days=days_ahead)
            
            # Check for period qualifier
            if "sabah" in text:
                start_hour, end_hour = TIME_PERIODS["sabah"]
                hint = f"{day_name}_morning"
            elif "akşam" in text:
                start_hour, end_hour = TIME_PERIODS["akşam"]
                hint = f"{day_name}_evening"
            else:
                start_hour, end_hour = 0, 24
                hint = day_name
            
            start_dt = datetime.combine(target_date, time(start_hour, 0), tzinfo=tz)
            if end_hour == 24:
                end_dt = datetime.combine(target_date + timedelta(days=1), time(0, 0), tzinfo=tz)
            else:
                end_dt = datetime.combine(target_date, time(end_hour, 0), tzinfo=tz)
            
            return {
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat(),
                "hint": hint,
                "confidence": 0.85,
            }
    
    return None


def _parse_relative_period(
    text: str, 
    now: datetime, 
    tz: tzinfo,
) -> Optional[dict[str, Any]]:
    """Parse relative periods like 'birazdan', 'az sonra', etc."""
    
    # birazdan, az sonra -> next 30 minutes
    if any(p in text for p in ["birazdan", "az sonra", "biraz sonra"]):
        start = now.replace(second=0, microsecond=0)
        end = start + timedelta(minutes=30)
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "hint": "soon",
            "confidence": 0.7,
        }
    
    # şimdi -> next 15 minutes
    if text.strip() == "şimdi" or "şu an" in text:
        start = now.replace(second=0, microsecond=0)
        end = start + timedelta(minutes=15)
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "hint": "now",
            "confidence": 0.75,
        }
    
    # daha sonra, sonra -> next 2 hours
    if text.strip() == "sonra" or text.strip() == "daha sonra":
        start = now.replace(second=0, microsecond=0)
        end = start + timedelta(hours=2)
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "hint": "later",
            "confidence": 0.6,
        }
    
    return None


def parse_duration_tr(text: str) -> Optional[int]:
    """Parse Turkish duration expression to minutes.
    
    Args:
        text: Duration text (e.g., "1 saat", "30 dakika", "bir buçuk saat")
        
    Returns:
        Duration in minutes, or None if not parseable.
    """
    if not text:
        return None
    
    text = text.lower().strip()
    total_minutes = 0
    has_hours = False
    
    # Hour patterns
    hour_patterns = [
        r"(\d+)\s*saat",
        r"(bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on|onbir|oniki)\s*(?:buçuk\s*)?saat",
    ]
    
    for pattern in hour_patterns:
        match = re.search(pattern, text)
        if match:
            num_str = match.group(1)
            try:
                hours = int(num_str)
            except ValueError:
                hours = TURKISH_NUMBERS.get(num_str, 0)
            total_minutes += hours * 60
            has_hours = True
            break
    
    # Check for "buçuk" with implied hour (e.g., "bir buçuk saat" = 1.5 hours)
    # If "buçuk" appears with "saat" but no explicit hour, assume 0.5
    if "buçuk" in text and "saat" in text and not has_hours:
        # Just "buçuk saat" without number = 0.5 hours (30 min)
        total_minutes += 30
    elif "buçuk" in text and has_hours:
        # "X buçuk saat" = X + 0.5 hours
        total_minutes += 30
    
    # Minute patterns
    minute_patterns = [
        r"(\d+)\s*dakika",
        r"(bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on)\s*dakika",
    ]
    
    for pattern in minute_patterns:
        match = re.search(pattern, text)
        if match:
            num_str = match.group(1)
            try:
                minutes = int(num_str)
            except ValueError:
                minutes = TURKISH_NUMBERS.get(num_str, 0)
            total_minutes += minutes
            break
    
    # "yarım saat" = 30 minutes (but not if we already counted buçuk)
    if "yarım" in text and "buçuk" not in text:
        total_minutes += 30
    
    return total_minutes if total_minutes > 0 else None
