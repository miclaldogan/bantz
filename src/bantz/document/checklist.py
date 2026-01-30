"""
Checklist generation from document structure.

Converts lists and structured content into actionable checklists.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from bantz.document.structure import (
    DocumentStructure,
    StructureElement,
    StructureType,
)


@dataclass
class ChecklistItem:
    """A single item in a checklist."""
    
    id: str
    """Unique item ID."""
    
    text: str
    """Item text."""
    
    completed: bool = False
    """Whether the item is completed."""
    
    parent_id: Optional[str] = None
    """Parent item ID for nested items."""
    
    source_page: Optional[int] = None
    """Page number from source document."""
    
    source_position: int = 0
    """Position in source document."""
    
    priority: int = 0
    """Priority level (0 = normal, 1 = high, -1 = low)."""
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "text": self.text,
            "completed": self.completed,
            "parent_id": self.parent_id,
            "source_page": self.source_page,
            "source_position": self.source_position,
            "priority": self.priority,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ChecklistItem":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            text=data["text"],
            completed=data.get("completed", False),
            parent_id=data.get("parent_id"),
            source_page=data.get("source_page"),
            source_position=data.get("source_position", 0),
            priority=data.get("priority", 0),
        )


@dataclass
class Checklist:
    """A checklist with items."""
    
    id: str
    """Unique checklist ID."""
    
    title: str
    """Checklist title."""
    
    items: list[ChecklistItem] = field(default_factory=list)
    """Checklist items."""
    
    source_document: Optional[str] = None
    """Source document ID."""
    
    created_at: datetime = field(default_factory=datetime.now)
    """Creation timestamp."""
    
    def __post_init__(self):
        """Generate ID if empty."""
        if not self.id:
            self.id = str(uuid.uuid4())
    
    @property
    def total_items(self) -> int:
        """Get total number of items."""
        return len(self.items)
    
    @property
    def completed_items(self) -> int:
        """Get number of completed items."""
        return sum(1 for item in self.items if item.completed)
    
    @property
    def progress_percent(self) -> float:
        """Get completion percentage."""
        if not self.items:
            return 0.0
        return (self.completed_items / self.total_items) * 100
    
    def add_item(
        self,
        text: str,
        parent_id: Optional[str] = None,
        **kwargs,
    ) -> ChecklistItem:
        """
        Add an item to the checklist.
        
        Args:
            text: Item text.
            parent_id: Parent item ID for nesting.
            **kwargs: Additional item properties.
            
        Returns:
            The created item.
        """
        item = ChecklistItem(
            id=str(uuid.uuid4()),
            text=text,
            parent_id=parent_id,
            **kwargs,
        )
        self.items.append(item)
        return item
    
    def complete_item(self, item_id: str) -> bool:
        """
        Mark an item as completed.
        
        Args:
            item_id: Item ID to complete.
            
        Returns:
            True if item was found and updated.
        """
        for item in self.items:
            if item.id == item_id:
                item.completed = True
                return True
        return False
    
    def get_item(self, item_id: str) -> Optional[ChecklistItem]:
        """Get item by ID."""
        for item in self.items:
            if item.id == item_id:
                return item
        return None
    
    def get_children(self, parent_id: str) -> list[ChecklistItem]:
        """Get child items of a parent."""
        return [item for item in self.items if item.parent_id == parent_id]
    
    def get_root_items(self) -> list[ChecklistItem]:
        """Get top-level items (no parent)."""
        return [item for item in self.items if item.parent_id is None]
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "items": [item.to_dict() for item in self.items],
            "source_document": self.source_document,
            "created_at": self.created_at.isoformat(),
            "total_items": self.total_items,
            "completed_items": self.completed_items,
            "progress_percent": self.progress_percent,
        }


class ChecklistGenerator:
    """
    Generates checklists from document structure.
    
    Recognizes actionable items in lists and converts them
    to interactive checklists.
    """
    
    # Turkish action verbs (infinitive forms and imperatives)
    ACTION_VERBS_TR = [
        "yap", "yapılacak", "yapın",
        "kontrol et", "kontrol edin",
        "gönder", "gönderin", "gönderilecek",
        "al", "alın", "alınacak",
        "ver", "verin", "verilecek",
        "ara", "arayın", "aranacak",
        "oku", "okuyun", "okunacak",
        "yaz", "yazın", "yazılacak",
        "hazırla", "hazırlayın", "hazırlanacak",
        "tamamla", "tamamlayın", "tamamlanacak",
        "bitir", "bitirin", "bitirilecek",
        "incele", "inceleyin", "incelenecek",
        "düzenle", "düzenleyin", "düzenlenecek",
        "güncelle", "güncelleyin", "güncellenecek",
        "sil", "silin", "silinecek",
        "ekle", "ekleyin", "eklenecek",
        "ayarla", "ayarlayın", "ayarlanacak",
        "onayla", "onaylayın", "onaylanacak",
        "iptal et", "iptal edin", "iptal edilecek",
        "başla", "başlayın", "başlanacak",
    ]
    
    # English action verbs
    ACTION_VERBS_EN = [
        "do", "make", "create", "build", "write",
        "check", "verify", "validate", "test",
        "send", "submit", "deliver", "share",
        "get", "fetch", "retrieve", "obtain",
        "give", "provide", "supply",
        "call", "contact", "reach",
        "read", "review", "examine",
        "prepare", "setup", "configure",
        "complete", "finish", "finalize",
        "update", "modify", "change", "edit",
        "delete", "remove", "clear",
        "add", "include", "insert",
        "approve", "confirm", "accept",
        "cancel", "reject", "decline",
        "start", "begin", "initiate",
        "stop", "end", "terminate",
        "install", "deploy", "publish",
        "fix", "repair", "resolve",
    ]
    
    def __init__(self, language: str = "tr"):
        """
        Initialize the checklist generator.
        
        Args:
            language: Primary language ("tr" or "en").
        """
        self._language = language
        self._action_verbs = (
            self.ACTION_VERBS_TR if language == "tr"
            else self.ACTION_VERBS_EN
        )
    
    def generate_from_structure(
        self,
        structure: DocumentStructure,
        document_id: Optional[str] = None,
    ) -> list[Checklist]:
        """
        Generate checklists from document structure.
        
        Args:
            structure: Document structure.
            document_id: Source document ID.
            
        Returns:
            List of generated checklists.
        """
        checklists = []
        
        for lst in structure.lists:
            # Check if this list looks like a checklist
            actionable_count = sum(
                1 for item in lst if self.is_actionable(item.content)
            )
            
            # If at least 50% of items are actionable, create a checklist
            if lst and actionable_count >= len(lst) * 0.5:
                checklist = self.generate_from_list(lst, document_id)
                checklists.append(checklist)
        
        return checklists
    
    def generate_from_list(
        self,
        list_elements: list[StructureElement],
        document_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Checklist:
        """
        Generate a checklist from list elements.
        
        Args:
            list_elements: List elements from structure.
            document_id: Source document ID.
            title: Checklist title (auto-generated if not provided).
            
        Returns:
            Generated checklist.
        """
        if not title:
            # Try to generate title from first item
            if list_elements:
                first_text = list_elements[0].content[:50]
                title = f"Checklist: {first_text}..."
            else:
                title = "Untitled Checklist"
        
        checklist = Checklist(
            id=str(uuid.uuid4()),
            title=title,
            source_document=document_id,
        )
        
        # Track parent items for nesting
        parent_stack: list[tuple[int, str]] = []  # (level, item_id)
        
        for element in list_elements:
            # Find parent based on nesting level
            parent_id = None
            
            while parent_stack and parent_stack[-1][0] >= element.level:
                parent_stack.pop()
            
            if parent_stack:
                parent_id = parent_stack[-1][1]
            
            # Create item
            item = checklist.add_item(
                text=element.content,
                parent_id=parent_id,
                source_page=element.page,
                source_position=element.start_pos,
            )
            
            # Add to parent stack if it might have children
            parent_stack.append((element.level, item.id))
        
        return checklist
    
    def is_actionable(self, text: str) -> bool:
        """
        Check if text is an actionable item.
        
        Args:
            text: Text to check.
            
        Returns:
            True if text appears to be an action item.
        """
        text_lower = text.lower().strip()
        
        # Check if starts with action verb
        for verb in self._action_verbs:
            if text_lower.startswith(verb):
                return True
        
        # Check for common TODO patterns
        todo_patterns = [
            r"^\[\s*\]",           # [ ] unchecked checkbox
            r"^TODO:",            # TODO: prefix
            r"^YAPILACAK:",       # Turkish TODO
            r"^ACTION:",          # ACTION: prefix
            r"^TASK:",            # TASK: prefix
        ]
        
        for pattern in todo_patterns:
            if re.match(pattern, text, re.IGNORECASE):
                return True
        
        return False
    
    def extract_priority(self, text: str) -> int:
        """
        Extract priority level from text.
        
        Args:
            text: Item text.
            
        Returns:
            Priority level (-1, 0, or 1).
        """
        text_lower = text.lower()
        
        # High priority markers
        high_markers = ["!", "acil", "urgent", "önemli", "important", "critical"]
        for marker in high_markers:
            if marker in text_lower:
                return 1
        
        # Low priority markers
        low_markers = ["later", "sonra", "optional", "opsiyonel", "nice to have"]
        for marker in low_markers:
            if marker in text_lower:
                return -1
        
        return 0


def create_checklist_generator(language: str = "tr") -> ChecklistGenerator:
    """
    Factory function to create a checklist generator.
    
    Args:
        language: Primary language for action verb detection.
        
    Returns:
        Configured ChecklistGenerator instance.
    """
    return ChecklistGenerator(language=language)
