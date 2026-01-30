"""
Task templates module.

Provides template registry and builtin templates for common tasks.
"""

from dataclasses import dataclass, field
from typing import Optional
import re


@dataclass
class TaskTemplate:
    """Template for a multi-step task."""
    
    id: str
    """Unique template ID."""
    
    name: str
    """Human-readable name."""
    
    description: str
    """Description of what the template does."""
    
    trigger_patterns: list[str]
    """Regex patterns that trigger this template."""
    
    steps: list[dict]
    """Steps with action, description, parameters."""
    
    required_params: list[str] = field(default_factory=list)
    """Required parameters for instantiation."""
    
    optional_params: dict[str, str] = field(default_factory=dict)
    """Optional parameters with default values."""
    
    category: str = "general"
    """Template category."""
    
    priority: int = 0
    """Priority for matching (higher = more specific)."""
    
    def matches(self, goal: str) -> Optional[dict]:
        """
        Check if goal matches this template.
        
        Args:
            goal: User's goal text.
            
        Returns:
            Extracted parameters if matches, None otherwise.
        """
        goal_lower = goal.lower()
        
        for pattern in self.trigger_patterns:
            match = re.search(pattern, goal_lower, re.IGNORECASE)
            if match:
                return match.groupdict() if match.groupdict() else {}
        
        return None
    
    def instantiate(self, params: dict) -> list[dict]:
        """
        Create concrete steps from template.
        
        Args:
            params: Parameters to fill in.
            
        Returns:
            List of step dictionaries.
        """
        # Merge with defaults
        all_params = {**self.optional_params, **params}
        
        # Check required params
        for param in self.required_params:
            if param not in all_params:
                raise ValueError(f"Missing required parameter: {param}")
        
        # Instantiate steps
        instantiated = []
        for i, step in enumerate(self.steps):
            new_step = {
                "id": f"step_{i + 1}",
                "action": step["action"],
                "description": self._fill_template(step["description"], all_params),
                "parameters": self._fill_dict(step.get("parameters", {}), all_params),
            }
            
            if "depends_on" in step:
                new_step["depends_on"] = step["depends_on"]
            
            instantiated.append(new_step)
        
        return instantiated
    
    def _fill_template(self, text: str, params: dict) -> str:
        """Fill template placeholders in text."""
        result = text
        for key, value in params.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result
    
    def _fill_dict(self, d: dict, params: dict) -> dict:
        """Fill template placeholders in dictionary values."""
        result = {}
        for key, value in d.items():
            if isinstance(value, str):
                result[key] = self._fill_template(value, params)
            elif isinstance(value, dict):
                result[key] = self._fill_dict(value, params)
            else:
                result[key] = value
        return result
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "trigger_patterns": self.trigger_patterns,
            "steps": self.steps,
            "required_params": self.required_params,
            "optional_params": self.optional_params,
            "category": self.category,
            "priority": self.priority,
        }


class TemplateRegistry:
    """Registry for task templates."""
    
    def __init__(self):
        """Initialize the registry."""
        self._templates: dict[str, TaskTemplate] = {}
        self._by_category: dict[str, list[str]] = {}
    
    def register(self, template: TaskTemplate) -> None:
        """
        Register a template.
        
        Args:
            template: Template to register.
        """
        self._templates[template.id] = template
        
        # Index by category
        if template.category not in self._by_category:
            self._by_category[template.category] = []
        self._by_category[template.category].append(template.id)
    
    def unregister(self, template_id: str) -> bool:
        """
        Unregister a template.
        
        Args:
            template_id: ID of template to remove.
            
        Returns:
            True if removed, False if not found.
        """
        if template_id not in self._templates:
            return False
        
        template = self._templates[template_id]
        del self._templates[template_id]
        
        # Remove from category index
        if template.category in self._by_category:
            self._by_category[template.category] = [
                tid for tid in self._by_category[template.category]
                if tid != template_id
            ]
        
        return True
    
    def get(self, template_id: str) -> Optional[TaskTemplate]:
        """
        Get a template by ID.
        
        Args:
            template_id: Template ID.
            
        Returns:
            Template if found, None otherwise.
        """
        return self._templates.get(template_id)
    
    def find_matching(self, goal: str) -> list[tuple[TaskTemplate, dict]]:
        """
        Find templates matching a goal.
        
        Args:
            goal: User's goal text.
            
        Returns:
            List of (template, extracted_params) tuples, sorted by priority.
        """
        matches = []
        
        for template in self._templates.values():
            params = template.matches(goal)
            if params is not None:
                matches.append((template, params))
        
        # Sort by priority (descending)
        matches.sort(key=lambda x: x[0].priority, reverse=True)
        
        return matches
    
    def find_best_match(self, goal: str) -> Optional[tuple[TaskTemplate, dict]]:
        """
        Find the best matching template.
        
        Args:
            goal: User's goal text.
            
        Returns:
            (template, params) tuple if found, None otherwise.
        """
        matches = self.find_matching(goal)
        return matches[0] if matches else None
    
    def instantiate(self, template_id: str, params: dict) -> list[dict]:
        """
        Instantiate a template with parameters.
        
        Args:
            template_id: Template ID.
            params: Parameters to fill in.
            
        Returns:
            List of step dictionaries.
            
        Raises:
            KeyError: If template not found.
        """
        template = self._templates.get(template_id)
        if not template:
            raise KeyError(f"Template not found: {template_id}")
        
        return template.instantiate(params)
    
    def list_templates(self, category: Optional[str] = None) -> list[TaskTemplate]:
        """
        List all templates.
        
        Args:
            category: Optional category filter.
            
        Returns:
            List of templates.
        """
        if category:
            template_ids = self._by_category.get(category, [])
            return [self._templates[tid] for tid in template_ids]
        
        return list(self._templates.values())
    
    def list_categories(self) -> list[str]:
        """List all categories."""
        return list(self._by_category.keys())
    
    def __len__(self) -> int:
        """Get number of templates."""
        return len(self._templates)
    
    def __contains__(self, template_id: str) -> bool:
        """Check if template exists."""
        return template_id in self._templates


# ============================================================
# BUILTIN TEMPLATES
# ============================================================

EMAIL_COMPOSE_SEND = TaskTemplate(
    id="email_compose_send",
    name="Email Compose and Send",
    description="Compose and send an email",
    trigger_patterns=[
        r"e-?posta (?:yaz|gönder).*?(?P<recipient>\S+@\S+)?",
        r"mail (?:yaz|gönder|at).*?(?P<recipient>\S+@\S+)?",
        r"send (?:an? )?e?mail to (?P<recipient>\S+)",
        r"compose (?:an? )?e?mail",
    ],
    steps=[
        {
            "action": "open_email_client",
            "description": "E-posta istemcisini aç",
            "parameters": {},
        },
        {
            "action": "compose_email",
            "description": "Yeni e-posta oluştur",
            "parameters": {
                "to": "{recipient}",
                "subject": "{subject}",
            },
        },
        {
            "action": "fill_email_body",
            "description": "E-posta içeriğini yaz",
            "parameters": {
                "body": "{body}",
            },
            "depends_on": ["step_2"],
        },
        {
            "action": "review_email",
            "description": "E-postayı gözden geçir",
            "parameters": {},
            "depends_on": ["step_3"],
        },
        {
            "action": "send_email",
            "description": "E-postayı gönder",
            "parameters": {},
            "depends_on": ["step_4"],
        },
    ],
    required_params=["recipient"],
    optional_params={
        "subject": "",
        "body": "",
    },
    category="communication",
    priority=10,
)

RESEARCH_SUMMARIZE = TaskTemplate(
    id="research_summarize",
    name="Research and Summarize",
    description="Research a topic and create a summary",
    trigger_patterns=[
        r"(?P<topic>.+?) hakkında araştır",
        r"(?P<topic>.+?) araştır.*?özet",
        r"research (?P<topic>.+)",
        r"summarize (?:information about )?(?P<topic>.+)",
    ],
    steps=[
        {
            "action": "web_search",
            "description": "'{topic}' hakkında web araması yap",
            "parameters": {
                "query": "{topic}",
            },
        },
        {
            "action": "collect_sources",
            "description": "İlgili kaynakları topla",
            "parameters": {
                "max_sources": "{max_sources}",
            },
            "depends_on": ["step_1"],
        },
        {
            "action": "extract_key_points",
            "description": "Anahtar noktaları çıkar",
            "parameters": {},
            "depends_on": ["step_2"],
        },
        {
            "action": "synthesize_summary",
            "description": "Özet oluştur",
            "parameters": {
                "format": "{format}",
            },
            "depends_on": ["step_3"],
        },
        {
            "action": "present_summary",
            "description": "Özeti sun",
            "parameters": {},
            "depends_on": ["step_4"],
        },
    ],
    required_params=["topic"],
    optional_params={
        "max_sources": "5",
        "format": "bullet_points",
    },
    category="research",
    priority=10,
)

FILE_ORGANIZE = TaskTemplate(
    id="file_organize",
    name="File Organization",
    description="Organize files in a folder",
    trigger_patterns=[
        r"dosyaları (?:düzenle|organize et)",
        r"(?P<folder>.+?) klasörünü düzenle",
        r"organize (?:files in )?(?P<folder>.+)",
    ],
    steps=[
        {
            "action": "scan_folder",
            "description": "Klasörü tara",
            "parameters": {
                "path": "{folder}",
            },
        },
        {
            "action": "categorize_files",
            "description": "Dosyaları kategorile",
            "parameters": {},
            "depends_on": ["step_1"],
        },
        {
            "action": "create_subfolders",
            "description": "Alt klasörleri oluştur",
            "parameters": {},
            "depends_on": ["step_2"],
        },
        {
            "action": "move_files",
            "description": "Dosyaları taşı",
            "parameters": {},
            "depends_on": ["step_3"],
        },
        {
            "action": "report_changes",
            "description": "Değişiklikleri raporla",
            "parameters": {},
            "depends_on": ["step_4"],
        },
    ],
    required_params=["folder"],
    optional_params={},
    category="files",
    priority=10,
)

SCHEDULE_MEETING = TaskTemplate(
    id="schedule_meeting",
    name="Schedule Meeting",
    description="Schedule a meeting with participants",
    trigger_patterns=[
        r"toplantı (?:ayarla|planla|oluştur)",
        r"(?P<participants>.+?) ile toplantı",
        r"schedule (?:a )?meeting",
        r"set up (?:a )?meeting with (?P<participants>.+)",
    ],
    steps=[
        {
            "action": "open_calendar",
            "description": "Takvimi aç",
            "parameters": {},
        },
        {
            "action": "find_available_slot",
            "description": "Uygun zaman dilimi bul",
            "parameters": {
                "participants": "{participants}",
                "duration": "{duration}",
            },
            "depends_on": ["step_1"],
        },
        {
            "action": "create_event",
            "description": "Etkinlik oluştur",
            "parameters": {
                "title": "{title}",
                "description": "{description}",
            },
            "depends_on": ["step_2"],
        },
        {
            "action": "send_invites",
            "description": "Davetiye gönder",
            "parameters": {
                "participants": "{participants}",
            },
            "depends_on": ["step_3"],
        },
    ],
    required_params=["participants"],
    optional_params={
        "duration": "60",
        "title": "Toplantı",
        "description": "",
    },
    category="calendar",
    priority=10,
)

DAILY_STANDUP = TaskTemplate(
    id="daily_standup",
    name="Daily Standup",
    description="Perform daily standup routine",
    trigger_patterns=[
        r"günlük (?:standup|durum)",
        r"sabah rutini",
        r"daily standup",
        r"morning routine",
    ],
    steps=[
        {
            "action": "check_calendar",
            "description": "Bugünkü takvimi kontrol et",
            "parameters": {},
        },
        {
            "action": "check_emails",
            "description": "Yeni e-postaları kontrol et",
            "parameters": {
                "unread_only": "true",
            },
        },
        {
            "action": "check_tasks",
            "description": "Bekleyen görevleri kontrol et",
            "parameters": {},
        },
        {
            "action": "summarize_day",
            "description": "Günün özetini sun",
            "parameters": {},
            "depends_on": ["step_1", "step_2", "step_3"],
        },
    ],
    required_params=[],
    optional_params={},
    category="productivity",
    priority=5,
)


# List of all builtin templates
BUILTIN_TEMPLATES = [
    EMAIL_COMPOSE_SEND,
    RESEARCH_SUMMARIZE,
    FILE_ORGANIZE,
    SCHEDULE_MEETING,
    DAILY_STANDUP,
]


def create_template_registry(load_builtins: bool = True) -> TemplateRegistry:
    """
    Factory function to create a template registry.
    
    Args:
        load_builtins: Whether to load builtin templates.
        
    Returns:
        Configured TemplateRegistry instance.
    """
    registry = TemplateRegistry()
    
    if load_builtins:
        for template in BUILTIN_TEMPLATES:
            registry.register(template)
    
    return registry
