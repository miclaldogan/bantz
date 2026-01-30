"""
Context Builder - Build rich context for LLM from memories.

Combines memories, user profile, and personality to create
contextual prompts for the language model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

from bantz.memory.types import (
    Memory,
    MemoryType,
    ConversationMemory,
    TaskMemory,
    PreferenceMemory,
    FactMemory,
    MemoryQuery,
)
from bantz.memory.store import MemoryStore
from bantz.memory.profile import UserProfile
from bantz.memory.personality import Personality, SpeakingStyle, ResponseType


class PromptSection(Enum):
    """Sections of the context prompt."""
    
    SYSTEM = "system"           # System instructions
    PERSONALITY = "personality"  # Personality definition
    USER_FACTS = "user_facts"   # Known facts about user
    MEMORIES = "memories"       # Relevant memories
    PREFERENCES = "preferences" # User preferences
    TASK_HISTORY = "task_history"  # Recent tasks
    CURRENT = "current"         # Current context
    RULES = "rules"             # Behavioral rules
    
    @property
    def priority(self) -> int:
        """Section priority (higher = more important)."""
        priorities = {
            PromptSection.SYSTEM: 100,
            PromptSection.PERSONALITY: 90,
            PromptSection.RULES: 85,
            PromptSection.USER_FACTS: 80,
            PromptSection.PREFERENCES: 70,
            PromptSection.MEMORIES: 60,
            PromptSection.TASK_HISTORY: 50,
            PromptSection.CURRENT: 40,
        }
        return priorities.get(self, 0)


@dataclass
class ContextConfig:
    """Configuration for context building."""
    
    # Token limits
    max_total_tokens: int = 4000
    max_memory_tokens: int = 1000
    max_facts_tokens: int = 500
    max_history_tokens: int = 500
    
    # Memory settings
    max_memories: int = 5
    max_recent_tasks: int = 3
    max_conversation_history: int = 5
    
    # Time filters
    memory_recency_days: int = 30
    task_recency_days: int = 7
    
    # Content settings
    include_timestamps: bool = False
    include_importance_scores: bool = False
    include_task_steps: bool = False
    
    # Sections to include
    sections: List[PromptSection] = field(default_factory=lambda: [
        PromptSection.SYSTEM,
        PromptSection.PERSONALITY,
        PromptSection.USER_FACTS,
        PromptSection.MEMORIES,
        PromptSection.RULES,
    ])
    
    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars per token)."""
        return len(text) // 4


class ContextBuilder:
    """
    Build rich context for LLM from memories.
    
    Combines:
    - Memory store for relevant memories
    - User profile for personalization
    - Personality for response style
    """
    
    def __init__(
        self,
        memory_store: Optional[MemoryStore] = None,
        profile: Optional[UserProfile] = None,
        personality: Optional[Personality] = None,
        config: Optional[ContextConfig] = None,
    ):
        """
        Initialize context builder.
        
        Args:
            memory_store: Memory store instance
            profile: User profile
            personality: Personality configuration
            config: Context configuration
        """
        self.memory = memory_store
        self.profile = profile or UserProfile()
        self.personality = personality or Personality()
        self.config = config or ContextConfig()
        
        # Cache for built sections
        self._section_cache: Dict[PromptSection, str] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=5)
    
    def build_system_prompt(self) -> str:
        """
        Build complete system prompt.
        
        Returns:
            Full system prompt for LLM
        """
        sections = []
        
        for section in sorted(self.config.sections, key=lambda s: -s.priority):
            content = self._build_section(section)
            if content:
                sections.append(content)
        
        return "\n\n".join(sections)
    
    def _build_section(self, section: PromptSection) -> str:
        """Build a single prompt section."""
        # Check cache
        if self._is_cache_valid() and section in self._section_cache:
            return self._section_cache[section]
        
        builders = {
            PromptSection.SYSTEM: self._build_system_section,
            PromptSection.PERSONALITY: self._build_personality_section,
            PromptSection.USER_FACTS: self._build_facts_section,
            PromptSection.MEMORIES: self._build_memories_section,
            PromptSection.PREFERENCES: self._build_preferences_section,
            PromptSection.TASK_HISTORY: self._build_task_history_section,
            PromptSection.RULES: self._build_rules_section,
            PromptSection.CURRENT: self._build_current_section,
        }
        
        builder = builders.get(section)
        content = builder() if builder else ""
        
        # Cache result
        self._section_cache[section] = content
        self._cache_timestamp = datetime.now()
        
        return content
    
    def _is_cache_valid(self) -> bool:
        """Check if section cache is still valid."""
        if not self._cache_timestamp:
            return False
        return datetime.now() - self._cache_timestamp < self._cache_ttl
    
    def invalidate_cache(self) -> None:
        """Invalidate section cache."""
        self._section_cache.clear()
        self._cache_timestamp = None
    
    def _build_system_section(self) -> str:
        """Build system instructions section."""
        name = self.profile.name or "kullanıcı"
        
        return f"""Sen {self.personality.name}'sin, {name}'nın kişisel asistanısın.
{self.personality.full_name}

Görevin: Kullanıcıya bilgisayar görevlerinde yardımcı olmak, soruları cevaplamak ve istekleri yerine getirmek."""
    
    def _build_personality_section(self) -> str:
        """Build personality section."""
        lines = ["## Kişilik"]
        
        # Speaking style
        lines.append(f"- İletişim tarzı: {self.personality.speaking_style.description_tr}")
        
        # Honorifics
        if self.personality.use_honorifics:
            lines.append("- 'Efendim' gibi saygılı hitap şekillerini kullan")
        else:
            lines.append("- Samimi bir dil kullan")
        
        # Humor
        if self.personality.witty_remarks:
            lines.append(f"- Zaman zaman nükteli yorumlar yapabilirsin")
        
        return "\n".join(lines)
    
    def _build_facts_section(self) -> str:
        """Build user facts section."""
        facts = self.profile.facts
        if not facts:
            return ""
        
        lines = ["## Kullanıcı Hakkında Bildiklerim"]
        
        for category, value in facts.items():
            lines.append(f"- {category.title()}: {value}")
        
        # Add learned preferences if reliable
        reliable_prefs = [
            (k, v) for k, v in self.profile.preferences.items()
            if v.is_reliable
        ]
        
        if reliable_prefs:
            lines.append("")
            lines.append("### Öğrenilmiş Tercihler")
            for key, pref in reliable_prefs[:5]:  # Limit to 5
                lines.append(f"- {key}: {pref.value}")
        
        return "\n".join(lines)
    
    def _build_memories_section(self) -> str:
        """Build relevant memories section."""
        if not self.memory:
            return ""
        
        # Get recent important memories
        cutoff = datetime.now() - timedelta(days=self.config.memory_recency_days)
        
        query = MemoryQuery(
            since=cutoff,
            min_importance=0.3,
            limit=self.config.max_memories,
            sort_by="importance",
        )
        
        memories = self.memory.query(query)
        
        if not memories:
            return ""
        
        lines = ["## Önemli Anılar"]
        
        for memory in memories:
            summary = self._summarize_memory(memory)
            if summary:
                lines.append(f"- {summary}")
        
        return "\n".join(lines)
    
    def _summarize_memory(self, memory: Memory) -> str:
        """Summarize a memory for context."""
        if memory.type == MemoryType.CONVERSATION:
            # Shorten conversation
            if len(memory.content) > 100:
                return memory.content[:100] + "..."
            return memory.content
        
        elif memory.type == MemoryType.TASK:
            meta = memory.metadata
            status = "✓" if meta.get("success", True) else "✗"
            return f"[{status}] {meta.get('task_description', memory.content)}"
        
        elif memory.type == MemoryType.FACT:
            return f"{memory.metadata.get('fact_category', 'Fact')}: {memory.metadata.get('fact_value', memory.content)}"
        
        elif memory.type == MemoryType.PREFERENCE:
            return f"Tercih: {memory.metadata.get('preference_key', '')}"
        
        return memory.content[:100] if len(memory.content) > 100 else memory.content
    
    def _build_preferences_section(self) -> str:
        """Build preferences section."""
        lines = ["## İletişim Tercihleri"]
        lines.append(self.profile.get_communication_prompt())
        
        # Add common tasks
        if self.profile.common_tasks:
            lines.append("")
            lines.append("### Sık Yapılan Görevler")
            for task in self.profile.common_tasks[-5:]:
                lines.append(f"- {task}")
        
        # Add favorite apps
        if self.profile.favorite_apps:
            lines.append("")
            lines.append("### Sık Kullanılan Uygulamalar")
            lines.append(", ".join(self.profile.favorite_apps[-5:]))
        
        return "\n".join(lines)
    
    def _build_task_history_section(self) -> str:
        """Build recent task history section."""
        if not self.memory:
            return ""
        
        cutoff = datetime.now() - timedelta(days=self.config.task_recency_days)
        
        query = MemoryQuery(
            types=[MemoryType.TASK],
            since=cutoff,
            limit=self.config.max_recent_tasks,
            sort_by="timestamp",
        )
        
        tasks = self.memory.query(query)
        
        if not tasks:
            return ""
        
        lines = ["## Son Görevler"]
        
        for task in tasks:
            meta = task.metadata
            status = "✓" if meta.get("success", True) else "✗"
            desc = meta.get("task_description", task.content)
            lines.append(f"- [{status}] {desc}")
        
        return "\n".join(lines)
    
    def _build_rules_section(self) -> str:
        """Build behavioral rules section."""
        lines = ["## Kurallar"]
        
        # Core rules
        lines.extend([
            "- Kısa ve net cevaplar ver (1-2 cümle)",
            "- Gereksiz açıklama yapma",
            "- Bilmediğin konularda dürüst ol",
            "- Türkçe konuş (kullanıcı İngilizce sorarsa İngilizce cevap ver)",
        ])
        
        # Personality-specific rules
        if self.personality.always_confirm_dangerous:
            lines.append("- Dosya silme, sistem değişikliği gibi riskli işlemlerde onay iste")
        
        if self.personality.proactive_suggestions:
            lines.append("- Yararlı öneriler sunabilirsin")
        
        if self.personality.remember_preferences:
            lines.append("- Kullanıcının tercihlerini hatırla ve uygula")
        
        return "\n".join(lines)
    
    def _build_current_section(self) -> str:
        """Build current context section (time, work status)."""
        now = datetime.now()
        
        lines = ["## Şu An"]
        lines.append(f"- Tarih: {now.strftime('%d %B %Y, %A')}")
        lines.append(f"- Saat: {now.strftime('%H:%M')}")
        
        # Work status
        work_pattern = self.profile.work_pattern
        if work_pattern.is_work_hour(now.hour):
            if work_pattern.is_focus_time(now.hour):
                lines.append("- Durum: Odaklanma saati")
            else:
                lines.append("- Durum: Çalışma saati")
        else:
            lines.append("- Durum: Çalışma saatleri dışı")
        
        return "\n".join(lines)
    
    def build_context(
        self,
        current_query: str,
        conversation_history: Optional[List[Tuple[str, str]]] = None,
    ) -> str:
        """
        Build context with relevant memories for a query.
        
        Args:
            current_query: Current user query
            conversation_history: List of (user, assistant) message pairs
            
        Returns:
            Context string to append to system prompt
        """
        parts = []
        
        # Add relevant memories
        if self.memory and current_query:
            relevant = self.memory.recall(
                current_query,
                limit=self.config.max_memories,
            )
            
            if relevant:
                parts.append("## İlgili Anılar")
                for memory in relevant:
                    summary = self._summarize_memory(memory)
                    if summary:
                        parts.append(f"- {summary}")
        
        # Add recent conversation if provided
        if conversation_history:
            parts.append("")
            parts.append("## Son Konuşma")
            for user_msg, assistant_msg in conversation_history[-self.config.max_conversation_history:]:
                parts.append(f"Kullanıcı: {user_msg}")
                parts.append(f"Asistan: {assistant_msg}")
                parts.append("")
        
        return "\n".join(parts)
    
    def get_response_template(self, response_type: ResponseType) -> str:
        """Get a response template for given type."""
        return self.personality.format_response(response_type)
    
    def format_response(
        self,
        response_type: ResponseType,
        **kwargs,
    ) -> str:
        """Format a response with personality."""
        return self.personality.format_response(response_type, **kwargs)
    
    def get_full_prompt(
        self,
        current_query: str,
        conversation_history: Optional[List[Tuple[str, str]]] = None,
    ) -> str:
        """
        Get complete prompt including system and context.
        
        Args:
            current_query: Current user query
            conversation_history: Recent conversation history
            
        Returns:
            Complete prompt string
        """
        system = self.build_system_prompt()
        context = self.build_context(current_query, conversation_history)
        
        parts = [system]
        if context:
            parts.append(context)
        
        return "\n\n".join(parts)
    
    def estimate_token_usage(self) -> Dict[str, int]:
        """Estimate token usage for each section."""
        usage = {}
        
        for section in self.config.sections:
            content = self._build_section(section)
            usage[section.value] = self.config.estimate_tokens(content)
        
        usage["total"] = sum(usage.values())
        
        return usage
    
    def update_profile(self, profile: UserProfile) -> None:
        """Update the user profile."""
        self.profile = profile
        self.invalidate_cache()
    
    def update_personality(self, personality: Personality) -> None:
        """Update the personality."""
        self.personality = personality
        self.invalidate_cache()
    
    def set_memory_store(self, memory_store: MemoryStore) -> None:
        """Set the memory store."""
        self.memory = memory_store
        self.invalidate_cache()


def create_context_builder(
    db_path: str = "~/.bantz/memory.db",
    profile_path: str = "~/.bantz/profile.json",
    personality_name: str = "jarvis",
) -> ContextBuilder:
    """
    Create a context builder with default configuration.
    
    Args:
        db_path: Path to memory database
        profile_path: Path to profile JSON
        personality_name: Name of personality preset
        
    Returns:
        Configured ContextBuilder instance
    """
    from bantz.memory.store import MemoryStore
    from bantz.memory.profile import ProfileManager
    from bantz.memory.personality import get_personality
    
    memory_store = MemoryStore(db_path)
    profile_manager = ProfileManager(profile_path)
    personality = get_personality(personality_name)
    
    return ContextBuilder(
        memory_store=memory_store,
        profile=profile_manager.profile,
        personality=personality,
    )
