"""
Tests for V2-7 Checklist Generation (Issue #39).
"""

import pytest

from bantz.document.checklist import (
    ChecklistItem,
    Checklist,
    ChecklistGenerator,
    create_checklist_generator,
)
from bantz.document.structure import (
    StructureElement,
    StructureType,
    DocumentStructure,
)


class TestChecklistItem:
    """Tests for ChecklistItem."""
    
    def test_create_item(self):
        """Test creating checklist item."""
        item = ChecklistItem(
            id="item-1",
            text="Complete task",
        )
        
        assert item.id == "item-1"
        assert item.text == "Complete task"
        assert item.completed is False
    
    def test_item_with_parent(self):
        """Test item with parent."""
        item = ChecklistItem(
            id="item-2",
            text="Sub task",
            parent_id="item-1",
        )
        
        assert item.parent_id == "item-1"
    
    def test_item_to_dict(self):
        """Test item to_dict."""
        item = ChecklistItem(
            id="item-1",
            text="Task",
            completed=True,
        )
        
        data = item.to_dict()
        
        assert data["id"] == "item-1"
        assert data["text"] == "Task"
        assert data["completed"] is True
    
    def test_item_from_dict(self):
        """Test item from_dict."""
        data = {
            "id": "item-1",
            "text": "Task",
            "completed": True,
        }
        
        item = ChecklistItem.from_dict(data)
        
        assert item.id == "item-1"
        assert item.text == "Task"
        assert item.completed is True


class TestChecklist:
    """Tests for Checklist."""
    
    def test_create_checklist(self):
        """Test creating checklist."""
        checklist = Checklist(
            id="list-1",
            title="My Tasks",
        )
        
        assert checklist.id == "list-1"
        assert checklist.title == "My Tasks"
        assert checklist.items == []
    
    def test_add_item(self):
        """Test adding item."""
        checklist = Checklist(id="list-1", title="Tasks")
        
        item = checklist.add_item("Task 1")
        
        assert checklist.total_items == 1
        assert item.text == "Task 1"
    
    def test_complete_item(self):
        """Test completing item."""
        checklist = Checklist(id="list-1", title="Tasks")
        item = checklist.add_item("Task 1")
        
        result = checklist.complete_item(item.id)
        
        assert result is True
        assert item.completed is True
        assert checklist.completed_items == 1
    
    def test_complete_nonexistent_item(self):
        """Test completing non-existent item."""
        checklist = Checklist(id="list-1", title="Tasks")
        
        result = checklist.complete_item("fake-id")
        
        assert result is False
    
    def test_progress_percent(self):
        """Test progress calculation."""
        checklist = Checklist(id="list-1", title="Tasks")
        checklist.add_item("Task 1")
        item2 = checklist.add_item("Task 2")
        
        checklist.complete_item(item2.id)
        
        assert checklist.progress_percent == 50.0
    
    def test_progress_empty(self):
        """Test progress for empty checklist."""
        checklist = Checklist(id="list-1", title="Tasks")
        
        assert checklist.progress_percent == 0.0
    
    def test_get_item(self):
        """Test getting item by ID."""
        checklist = Checklist(id="list-1", title="Tasks")
        item = checklist.add_item("Task 1")
        
        found = checklist.get_item(item.id)
        
        assert found == item
    
    def test_get_children(self):
        """Test getting child items."""
        checklist = Checklist(id="list-1", title="Tasks")
        parent = checklist.add_item("Parent")
        child1 = checklist.add_item("Child 1", parent_id=parent.id)
        child2 = checklist.add_item("Child 2", parent_id=parent.id)
        
        children = checklist.get_children(parent.id)
        
        assert len(children) == 2
    
    def test_get_root_items(self):
        """Test getting root items."""
        checklist = Checklist(id="list-1", title="Tasks")
        root1 = checklist.add_item("Root 1")
        root2 = checklist.add_item("Root 2")
        checklist.add_item("Child", parent_id=root1.id)
        
        roots = checklist.get_root_items()
        
        assert len(roots) == 2
    
    def test_to_dict(self):
        """Test checklist to_dict."""
        checklist = Checklist(id="list-1", title="Tasks")
        checklist.add_item("Task 1")
        
        data = checklist.to_dict()
        
        assert data["id"] == "list-1"
        assert data["title"] == "Tasks"
        assert data["total_items"] == 1


class TestChecklistGenerator:
    """Tests for ChecklistGenerator."""
    
    def test_is_actionable_turkish_verb(self):
        """Test actionable detection for Turkish verbs."""
        generator = ChecklistGenerator(language="tr")
        
        assert generator.is_actionable("Yap bu görevi")
        assert generator.is_actionable("Kontrol et sistemi")
        assert generator.is_actionable("Gönder raporu")
    
    def test_is_actionable_english_verb(self):
        """Test actionable detection for English verbs."""
        generator = ChecklistGenerator(language="en")
        
        assert generator.is_actionable("Create new file")
        assert generator.is_actionable("Check the results")
        assert generator.is_actionable("Send email")
    
    def test_is_actionable_todo_pattern(self):
        """Test actionable detection for TODO pattern."""
        generator = ChecklistGenerator()
        
        assert generator.is_actionable("[ ] Unchecked item")
        assert generator.is_actionable("TODO: Fix bug")
    
    def test_is_not_actionable(self):
        """Test non-actionable text."""
        generator = ChecklistGenerator()
        
        assert not generator.is_actionable("This is just a note")
        assert not generator.is_actionable("Description text")
    
    def test_generate_from_list(self):
        """Test generating checklist from list elements."""
        generator = ChecklistGenerator()
        
        elements = [
            StructureElement(
                type=StructureType.LIST_ITEM,
                content="Task 1",
            ),
            StructureElement(
                type=StructureType.LIST_ITEM,
                content="Task 2",
            ),
        ]
        
        checklist = generator.generate_from_list(elements)
        
        assert checklist.total_items == 2
        assert checklist.items[0].text == "Task 1"
    
    def test_generate_preserves_source(self):
        """Test source info is preserved."""
        generator = ChecklistGenerator()
        
        elements = [
            StructureElement(
                type=StructureType.LIST_ITEM,
                content="Task",
                page=5,
                start_pos=100,
            ),
        ]
        
        checklist = generator.generate_from_list(elements, document_id="doc-123")
        
        assert checklist.source_document == "doc-123"
        assert checklist.items[0].source_page == 5
        assert checklist.items[0].source_position == 100
    
    def test_generate_nested_checklist(self):
        """Test nested checklist generation."""
        generator = ChecklistGenerator()
        
        elements = [
            StructureElement(type=StructureType.LIST_ITEM, content="Parent", level=0),
            StructureElement(type=StructureType.LIST_ITEM, content="Child 1", level=1),
            StructureElement(type=StructureType.LIST_ITEM, content="Child 2", level=1),
        ]
        
        checklist = generator.generate_from_list(elements)
        
        # Check parent-child relationships
        parent = checklist.items[0]
        children = checklist.get_children(parent.id)
        
        assert len(children) == 2
    
    def test_generate_from_structure(self):
        """Test generating from document structure."""
        generator = ChecklistGenerator()
        
        elements = [
            StructureElement(type=StructureType.LIST_ITEM, content="Yap task 1"),
            StructureElement(type=StructureType.LIST_ITEM, content="Kontrol et task 2"),
        ]
        
        structure = DocumentStructure(lists=[elements])
        checklists = generator.generate_from_structure(structure)
        
        assert len(checklists) >= 1
    
    def test_extract_priority_high(self):
        """Test high priority extraction."""
        generator = ChecklistGenerator()
        
        assert generator.extract_priority("Acil! Fix bug") == 1
        assert generator.extract_priority("Urgent task") == 1
    
    def test_extract_priority_low(self):
        """Test low priority extraction."""
        generator = ChecklistGenerator()
        
        assert generator.extract_priority("Later: review code") == -1
        assert generator.extract_priority("Optional improvement") == -1
    
    def test_extract_priority_normal(self):
        """Test normal priority."""
        generator = ChecklistGenerator()
        
        assert generator.extract_priority("Regular task") == 0
    
    def test_factory_function(self):
        """Test create_checklist_generator factory."""
        generator = create_checklist_generator(language="en")
        
        assert isinstance(generator, ChecklistGenerator)
        assert generator._language == "en"
