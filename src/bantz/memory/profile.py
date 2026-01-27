"""
User Profile - Learned user preferences and facts.

Stores user information, communication preferences, work patterns,
and learned facts for personalization.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import threading


class CommunicationStyle(Enum):
    """User's preferred communication style."""
    
    FORMAL = "formal"           # Resmi, saygılı
    CASUAL = "casual"           # Samimi, rahat
    BRIEF = "brief"             # Kısa ve öz
    DETAILED = "detailed"       # Detaylı açıklamalar
    TECHNICAL = "technical"     # Teknik terimler
    SIMPLE = "simple"           # Basit anlatım
    
    @property
    def description_tr(self) -> str:
        """Turkish description."""
        descriptions = {
            CommunicationStyle.FORMAL: "Resmi ve saygılı",
            CommunicationStyle.CASUAL: "Samimi ve rahat",
            CommunicationStyle.BRIEF: "Kısa ve öz",
            CommunicationStyle.DETAILED: "Detaylı açıklamalar",
            CommunicationStyle.TECHNICAL: "Teknik terimlerle",
            CommunicationStyle.SIMPLE: "Basit anlatım",
        }
        return descriptions.get(self, self.value)


class PreferenceConfidence(Enum):
    """Confidence level for learned preferences."""
    
    GUESSED = 0.2       # Tahmin
    INFERRED = 0.4      # Çıkarım yapıldı
    OBSERVED = 0.6      # Gözlemlendi
    STATED = 0.8        # Kullanıcı söyledi
    CONFIRMED = 1.0     # Onaylandı
    
    @classmethod
    def from_float(cls, value: float) -> PreferenceConfidence:
        """Get closest confidence level from float."""
        if value >= 0.9:
            return cls.CONFIRMED
        elif value >= 0.7:
            return cls.STATED
        elif value >= 0.5:
            return cls.OBSERVED
        elif value >= 0.3:
            return cls.INFERRED
        else:
            return cls.GUESSED


@dataclass
class WorkPattern:
    """Learned work patterns."""
    
    # Typical hours (24h format)
    start_hour: int = 9
    end_hour: int = 18
    
    # Active days (0=Monday, 6=Sunday)
    active_days: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    
    # Break patterns
    lunch_start: int = 12
    lunch_duration_minutes: int = 60
    
    # Focus time preferences
    focus_hours: List[int] = field(default_factory=lambda: [10, 11, 14, 15, 16])
    meeting_preferred_hours: List[int] = field(default_factory=lambda: [9, 13, 14])
    
    # Productivity patterns
    most_productive_day: int = 2  # Wednesday
    least_productive_day: int = 4  # Friday
    
    def is_work_hour(self, hour: int) -> bool:
        """Check if given hour is during work hours."""
        return self.start_hour <= hour < self.end_hour
    
    def is_work_day(self, weekday: int) -> bool:
        """Check if given weekday is a work day."""
        return weekday in self.active_days
    
    def is_focus_time(self, hour: int) -> bool:
        """Check if given hour is focus time."""
        return hour in self.focus_hours
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "start_hour": self.start_hour,
            "end_hour": self.end_hour,
            "active_days": self.active_days,
            "lunch_start": self.lunch_start,
            "lunch_duration_minutes": self.lunch_duration_minutes,
            "focus_hours": self.focus_hours,
            "meeting_preferred_hours": self.meeting_preferred_hours,
            "most_productive_day": self.most_productive_day,
            "least_productive_day": self.least_productive_day,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkPattern:
        """Create from dictionary."""
        return cls(
            start_hour=data.get("start_hour", 9),
            end_hour=data.get("end_hour", 18),
            active_days=data.get("active_days", [0, 1, 2, 3, 4]),
            lunch_start=data.get("lunch_start", 12),
            lunch_duration_minutes=data.get("lunch_duration_minutes", 60),
            focus_hours=data.get("focus_hours", [10, 11, 14, 15, 16]),
            meeting_preferred_hours=data.get("meeting_preferred_hours", [9, 13, 14]),
            most_productive_day=data.get("most_productive_day", 2),
            least_productive_day=data.get("least_productive_day", 4),
        )


@dataclass
class LearnedPreference:
    """A single learned preference with confidence tracking."""
    
    key: str
    value: Any
    confidence: float = 0.5
    source: str = "inferred"
    first_observed: datetime = field(default_factory=datetime.now)
    last_confirmed: Optional[datetime] = None
    confirmation_count: int = 1
    contradiction_count: int = 0
    
    def confirm(self) -> None:
        """Confirm this preference."""
        self.confirmation_count += 1
        self.confidence = min(1.0, self.confidence + 0.1)
        self.last_confirmed = datetime.now()
    
    def contradict(self) -> None:
        """Register a contradiction."""
        self.contradiction_count += 1
        self.confidence = max(0.0, self.confidence - 0.2)
    
    @property
    def is_reliable(self) -> bool:
        """Check if preference is reliable enough to use."""
        return self.confidence >= 0.5 and self.contradiction_count < self.confirmation_count
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "source": self.source,
            "first_observed": self.first_observed.isoformat(),
            "last_confirmed": self.last_confirmed.isoformat() if self.last_confirmed else None,
            "confirmation_count": self.confirmation_count,
            "contradiction_count": self.contradiction_count,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LearnedPreference:
        """Create from dictionary."""
        return cls(
            key=data["key"],
            value=data["value"],
            confidence=data.get("confidence", 0.5),
            source=data.get("source", "inferred"),
            first_observed=datetime.fromisoformat(data["first_observed"]) if "first_observed" in data else datetime.now(),
            last_confirmed=datetime.fromisoformat(data["last_confirmed"]) if data.get("last_confirmed") else None,
            confirmation_count=data.get("confirmation_count", 1),
            contradiction_count=data.get("contradiction_count", 0),
        )


@dataclass
class UserProfile:
    """
    Learned user preferences and facts.
    
    Stores everything known about the user for personalization:
    - Basic info (name, language)
    - Communication preferences
    - Work patterns
    - App preferences
    - Learned facts
    """
    
    # Basic info
    name: Optional[str] = None
    preferred_language: str = "tr"
    timezone: str = "Europe/Istanbul"
    
    # Communication style preferences
    formality_level: float = 0.5      # 0=casual, 1=formal
    verbosity_preference: float = 0.5  # 0=brief, 1=detailed
    humor_appreciation: float = 0.5    # 0=serious, 1=humorous
    technical_level: float = 0.5       # 0=simple, 1=technical
    
    # Interaction preferences
    preferred_styles: List[CommunicationStyle] = field(default_factory=lambda: [
        CommunicationStyle.FORMAL,
        CommunicationStyle.BRIEF,
    ])
    
    # Work patterns
    work_pattern: WorkPattern = field(default_factory=WorkPattern)
    
    # App and task preferences
    common_tasks: List[str] = field(default_factory=list)
    favorite_apps: List[str] = field(default_factory=list)
    app_positions: Dict[str, Tuple[int, int, int, int]] = field(default_factory=dict)  # app -> (x, y, w, h)
    
    # Learned facts about user
    facts: Dict[str, str] = field(default_factory=dict)
    
    # Dynamic preferences with confidence tracking
    preferences: Dict[str, LearnedPreference] = field(default_factory=dict)
    
    # Interaction statistics
    total_interactions: int = 0
    first_interaction: Optional[datetime] = None
    last_interaction: Optional[datetime] = None
    session_count: int = 0
    
    # Version for migrations
    version: int = 1
    
    def get_fact(self, category: str) -> Optional[str]:
        """Get a fact about the user."""
        return self.facts.get(category)
    
    def set_fact(self, category: str, value: str) -> None:
        """Set a fact about the user."""
        self.facts[category] = value
    
    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a learned preference."""
        if key in self.preferences:
            pref = self.preferences[key]
            if pref.is_reliable:
                return pref.value
        return default
    
    def set_preference(
        self,
        key: str,
        value: Any,
        confidence: float = 0.5,
        source: str = "inferred",
    ) -> None:
        """Set or update a preference."""
        if key in self.preferences:
            existing = self.preferences[key]
            if existing.value == value:
                existing.confirm()
            else:
                # New value - only update if more confident
                if confidence > existing.confidence:
                    self.preferences[key] = LearnedPreference(
                        key=key,
                        value=value,
                        confidence=confidence,
                        source=source,
                    )
                else:
                    existing.contradict()
        else:
            self.preferences[key] = LearnedPreference(
                key=key,
                value=value,
                confidence=confidence,
                source=source,
            )
    
    def record_interaction(self) -> None:
        """Record an interaction."""
        now = datetime.now()
        self.total_interactions += 1
        self.last_interaction = now
        if not self.first_interaction:
            self.first_interaction = now
    
    def add_common_task(self, task: str) -> None:
        """Add a task to common tasks."""
        if task not in self.common_tasks:
            self.common_tasks.append(task)
            # Keep only top 20
            if len(self.common_tasks) > 20:
                self.common_tasks = self.common_tasks[-20:]
    
    def add_favorite_app(self, app: str) -> None:
        """Add an app to favorites."""
        if app not in self.favorite_apps:
            self.favorite_apps.append(app)
            # Keep only top 10
            if len(self.favorite_apps) > 10:
                self.favorite_apps = self.favorite_apps[-10:]
    
    def get_app_position(self, app: str) -> Optional[Tuple[int, int, int, int]]:
        """Get preferred position for an app."""
        return self.app_positions.get(app.lower())
    
    def set_app_position(
        self,
        app: str,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> None:
        """Set preferred position for an app."""
        self.app_positions[app.lower()] = (x, y, width, height)
    
    def get_communication_prompt(self) -> str:
        """Get prompt describing communication preferences."""
        parts = []
        
        # Formality
        if self.formality_level > 0.7:
            parts.append("Resmi ve saygılı konuş")
        elif self.formality_level < 0.3:
            parts.append("Samimi ve rahat konuş")
        
        # Verbosity
        if self.verbosity_preference < 0.3:
            parts.append("Kısa ve öz cevaplar ver")
        elif self.verbosity_preference > 0.7:
            parts.append("Detaylı açıklamalar yap")
        
        # Technical level
        if self.technical_level > 0.7:
            parts.append("Teknik terimler kullanabilirsin")
        elif self.technical_level < 0.3:
            parts.append("Basit ve anlaşılır anlat")
        
        # Humor
        if self.humor_appreciation > 0.7:
            parts.append("Espri yapabilirsin")
        elif self.humor_appreciation < 0.3:
            parts.append("Ciddi ve profesyonel kal")
        
        return ". ".join(parts) if parts else "Normal iletişim tarzı kullan"
    
    def get_facts_summary(self) -> str:
        """Get summary of known facts."""
        if not self.facts:
            return "Kullanıcı hakkında henüz bilgi yok."
        
        lines = ["Kullanıcı hakkında bildiklerim:"]
        for category, value in self.facts.items():
            lines.append(f"  • {category}: {value}")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert profile to dictionary for serialization."""
        return {
            "version": self.version,
            "name": self.name,
            "preferred_language": self.preferred_language,
            "timezone": self.timezone,
            "formality_level": self.formality_level,
            "verbosity_preference": self.verbosity_preference,
            "humor_appreciation": self.humor_appreciation,
            "technical_level": self.technical_level,
            "preferred_styles": [s.value for s in self.preferred_styles],
            "work_pattern": self.work_pattern.to_dict(),
            "common_tasks": self.common_tasks,
            "favorite_apps": self.favorite_apps,
            "app_positions": self.app_positions,
            "facts": self.facts,
            "preferences": {
                k: v.to_dict() for k, v in self.preferences.items()
            },
            "total_interactions": self.total_interactions,
            "first_interaction": self.first_interaction.isoformat() if self.first_interaction else None,
            "last_interaction": self.last_interaction.isoformat() if self.last_interaction else None,
            "session_count": self.session_count,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UserProfile:
        """Create profile from dictionary."""
        profile = cls(
            name=data.get("name"),
            preferred_language=data.get("preferred_language", "tr"),
            timezone=data.get("timezone", "Europe/Istanbul"),
            formality_level=data.get("formality_level", 0.5),
            verbosity_preference=data.get("verbosity_preference", 0.5),
            humor_appreciation=data.get("humor_appreciation", 0.5),
            technical_level=data.get("technical_level", 0.5),
            common_tasks=data.get("common_tasks", []),
            favorite_apps=data.get("favorite_apps", []),
            app_positions=data.get("app_positions", {}),
            facts=data.get("facts", {}),
            total_interactions=data.get("total_interactions", 0),
            session_count=data.get("session_count", 0),
            version=data.get("version", 1),
        )
        
        # Parse preferred styles
        if "preferred_styles" in data:
            profile.preferred_styles = [
                CommunicationStyle(s) for s in data["preferred_styles"]
            ]
        
        # Parse work pattern
        if "work_pattern" in data:
            profile.work_pattern = WorkPattern.from_dict(data["work_pattern"])
        
        # Parse preferences
        if "preferences" in data:
            profile.preferences = {
                k: LearnedPreference.from_dict(v)
                for k, v in data["preferences"].items()
            }
        
        # Parse dates
        if data.get("first_interaction"):
            profile.first_interaction = datetime.fromisoformat(data["first_interaction"])
        if data.get("last_interaction"):
            profile.last_interaction = datetime.fromisoformat(data["last_interaction"])
        
        return profile


class ProfileManager:
    """
    Manage user profile persistence.
    
    Handles loading, saving, and updating user profiles with
    automatic learning from interactions.
    """
    
    def __init__(
        self,
        profile_path: str = "~/.bantz/profile.json",
        auto_save: bool = True,
    ):
        """
        Initialize profile manager.
        
        Args:
            profile_path: Path to profile JSON file
            auto_save: Whether to auto-save after changes
        """
        self.profile_path = Path(profile_path).expanduser()
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.auto_save = auto_save
        self._profile: Optional[UserProfile] = None
        self._lock = threading.RLock()
        self._dirty = False
    
    @property
    def profile(self) -> UserProfile:
        """Get current profile, loading if necessary."""
        if self._profile is None:
            self._profile = self.load()
        return self._profile
    
    def load(self) -> UserProfile:
        """Load profile from disk."""
        with self._lock:
            if self.profile_path.exists():
                try:
                    with open(self.profile_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    return UserProfile.from_dict(data)
                except (json.JSONDecodeError, KeyError) as e:
                    # Corrupted file, backup and create new
                    backup_path = self.profile_path.with_suffix('.json.bak')
                    self.profile_path.rename(backup_path)
            
            return UserProfile()
    
    def save(self, profile: Optional[UserProfile] = None) -> None:
        """Save profile to disk."""
        with self._lock:
            profile = profile or self._profile
            if profile is None:
                return
            
            with open(self.profile_path, 'w', encoding='utf-8') as f:
                json.dump(profile.to_dict(), f, indent=2, ensure_ascii=False)
            
            self._dirty = False
    
    def _mark_dirty(self) -> None:
        """Mark profile as modified."""
        self._dirty = True
        if self.auto_save:
            self.save()
    
    def get_name(self) -> Optional[str]:
        """Get user's name."""
        return self.profile.name
    
    def set_name(self, name: str) -> None:
        """Set user's name."""
        with self._lock:
            self.profile.name = name
            self.profile.set_fact("name", name)
            self._mark_dirty()
    
    def learn_preference(
        self,
        key: str,
        value: Any,
        confidence: float = 0.5,
        source: str = "inferred",
    ) -> None:
        """
        Learn a new preference with confidence.
        
        Args:
            key: Preference key (e.g., "app.discord.monitor")
            value: Preference value
            confidence: Confidence level (0.0 - 1.0)
            source: Source of preference (inferred, stated, observed)
        """
        with self._lock:
            self.profile.set_preference(key, value, confidence, source)
            self._mark_dirty()
    
    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a preference value."""
        return self.profile.get_preference(key, default)
    
    def learn_fact(
        self,
        category: str,
        value: str,
        source: str = "user_stated",
    ) -> None:
        """
        Learn a fact about the user.
        
        Args:
            category: Fact category (name, job, location, etc.)
            value: Fact value
            source: Source of fact
        """
        with self._lock:
            self.profile.set_fact(category, value)
            
            # Also store as preference for confidence tracking
            self.learn_preference(
                f"fact.{category}",
                value,
                confidence=0.9 if source == "user_stated" else 0.5,
                source=source,
            )
            
            self._mark_dirty()
    
    def get_fact(self, category: str) -> Optional[str]:
        """Get a fact about the user."""
        return self.profile.get_fact(category)
    
    def update_communication_style(
        self,
        formality: Optional[float] = None,
        verbosity: Optional[float] = None,
        humor: Optional[float] = None,
        technical: Optional[float] = None,
    ) -> None:
        """Update communication style preferences."""
        with self._lock:
            if formality is not None:
                self.profile.formality_level = max(0.0, min(1.0, formality))
            if verbosity is not None:
                self.profile.verbosity_preference = max(0.0, min(1.0, verbosity))
            if humor is not None:
                self.profile.humor_appreciation = max(0.0, min(1.0, humor))
            if technical is not None:
                self.profile.technical_level = max(0.0, min(1.0, technical))
            
            self._mark_dirty()
    
    def record_app_usage(self, app_name: str) -> None:
        """Record that an app was used."""
        with self._lock:
            self.profile.add_favorite_app(app_name)
            self._mark_dirty()
    
    def record_task(self, task_description: str) -> None:
        """Record a task that was performed."""
        with self._lock:
            self.profile.add_common_task(task_description)
            self._mark_dirty()
    
    def record_app_position(
        self,
        app_name: str,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> None:
        """Record preferred position for an app."""
        with self._lock:
            self.profile.set_app_position(app_name, x, y, width, height)
            self._mark_dirty()
    
    def start_session(self) -> None:
        """Record start of a new session."""
        with self._lock:
            self.profile.session_count += 1
            self.profile.record_interaction()
            self._mark_dirty()
    
    def record_interaction(self) -> None:
        """Record an interaction."""
        with self._lock:
            self.profile.record_interaction()
            self._mark_dirty()
    
    def get_work_status(self) -> Dict[str, Any]:
        """Get current work status based on patterns."""
        now = datetime.now()
        pattern = self.profile.work_pattern
        
        return {
            "is_work_hour": pattern.is_work_hour(now.hour),
            "is_work_day": pattern.is_work_day(now.weekday()),
            "is_focus_time": pattern.is_focus_time(now.hour),
            "current_hour": now.hour,
            "current_day": now.weekday(),
        }
    
    def export_profile(self, filepath: str) -> None:
        """Export profile to a file."""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.profile.to_dict(), f, indent=2, ensure_ascii=False)
    
    def import_profile(self, filepath: str) -> None:
        """Import profile from a file."""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        with self._lock:
            self._profile = UserProfile.from_dict(data)
            self._mark_dirty()
    
    def reset(self) -> None:
        """Reset profile to defaults."""
        with self._lock:
            self._profile = UserProfile()
            self._mark_dirty()
