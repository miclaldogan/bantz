"""
Tests for V2-7 Document Structure Extraction (Issue #39).
"""

import pytest

from bantz.document.structure import (
    StructureType,
    StructureElement,
    TableData,
    DocumentStructure,
    StructureExtractor,
    create_structure_extractor,
)


class TestStructureType:
    """Tests for StructureType enum."""
    
    def test_types_exist(self):
        """Test structure types exist."""
        assert StructureType.HEADING.value == "heading"
        assert StructureType.PARAGRAPH.value == "paragraph"
        assert StructureType.LIST_ITEM.value == "list_item"
        assert StructureType.NUMBERED_ITEM.value == "numbered_item"
        assert StructureType.TABLE.value == "table"
        assert StructureType.CODE_BLOCK.value == "code_block"


class TestStructureElement:
    """Tests for StructureElement."""
    
    def test_create_element(self):
        """Test creating structure element."""
        element = StructureElement(
            type=StructureType.HEADING,
            content="Test Heading",
            level=1,
        )
        
        assert element.type == StructureType.HEADING
        assert element.content == "Test Heading"
        assert element.level == 1
    
    def test_element_to_dict(self):
        """Test element to_dict."""
        element = StructureElement(
            type=StructureType.LIST_ITEM,
            content="Item 1",
            level=0,
        )
        
        data = element.to_dict()
        
        assert data["type"] == "list_item"
        assert data["content"] == "Item 1"
    
    def test_element_with_children(self):
        """Test element with children."""
        child = StructureElement(
            type=StructureType.LIST_ITEM,
            content="Child",
            level=1,
        )
        parent = StructureElement(
            type=StructureType.LIST_ITEM,
            content="Parent",
            level=0,
            children=[child],
        )
        
        assert len(parent.children) == 1
        assert parent.children[0].content == "Child"


class TestTableData:
    """Tests for TableData."""
    
    def test_create_table(self):
        """Test creating table data."""
        table = TableData(
            rows=[["A", "B"], ["C", "D"]],
            headers=["Col1", "Col2"],
        )
        
        assert table.row_count == 2
        assert table.col_count == 2
        assert table.headers == ["Col1", "Col2"]
    
    def test_table_to_dict(self):
        """Test table to_dict."""
        table = TableData(
            rows=[["A", "B"]],
        )
        
        data = table.to_dict()
        
        assert data["rows"] == [["A", "B"]]
        assert data["row_count"] == 1
        assert data["col_count"] == 2


class TestDocumentStructure:
    """Tests for DocumentStructure."""
    
    def test_create_structure(self):
        """Test creating document structure."""
        structure = DocumentStructure()
        
        assert structure.elements == []
        assert structure.headings == []
        assert structure.lists == []
        assert structure.tables == []
    
    def test_get_outline(self):
        """Test getting document outline."""
        h1 = StructureElement(type=StructureType.HEADING, content="H1", level=1)
        h2 = StructureElement(type=StructureType.HEADING, content="H2", level=2)
        
        structure = DocumentStructure(headings=[h1, h2])
        outline = structure.get_outline()
        
        assert outline == [(1, "H1"), (2, "H2")]
    
    def test_get_all_list_items(self):
        """Test getting all list items."""
        item1 = StructureElement(type=StructureType.LIST_ITEM, content="Item 1")
        item2 = StructureElement(type=StructureType.LIST_ITEM, content="Item 2")
        
        structure = DocumentStructure(lists=[[item1], [item2]])
        items = structure.get_all_list_items()
        
        assert len(items) == 2
    
    def test_to_dict(self):
        """Test structure to_dict."""
        structure = DocumentStructure()
        data = structure.to_dict()
        
        assert "elements" in data
        assert "headings" in data
        assert "lists" in data
        assert "tables" in data


class TestStructureExtractor:
    """Tests for StructureExtractor."""
    
    def test_extract_markdown_headings(self):
        """Test extracting markdown headings."""
        extractor = StructureExtractor()
        text = "# Heading 1\n\nContent\n\n## Heading 2"
        
        headings = extractor.find_headings(text)
        
        assert len(headings) == 2
        assert headings[0].content == "Heading 1"
        assert headings[0].level == 1
        assert headings[1].content == "Heading 2"
        assert headings[1].level == 2
    
    def test_extract_heading_levels(self):
        """Test heading levels are correct."""
        extractor = StructureExtractor()
        text = "# H1\n## H2\n### H3\n#### H4"
        
        headings = extractor.find_headings(text)
        
        assert len(headings) == 4
        assert headings[0].level == 1
        assert headings[1].level == 2
        assert headings[2].level == 3
        assert headings[3].level == 4
    
    def test_extract_bullet_list(self):
        """Test extracting bullet list."""
        extractor = StructureExtractor()
        text = "- Item 1\n- Item 2\n- Item 3"
        
        lists = extractor.find_lists(text)
        
        assert len(lists) == 1
        assert len(lists[0]) == 3
        assert lists[0][0].content == "Item 1"
        assert lists[0][0].type == StructureType.LIST_ITEM
    
    def test_extract_numbered_list(self):
        """Test extracting numbered list."""
        extractor = StructureExtractor()
        text = "1. First\n2. Second\n3. Third"
        
        lists = extractor.find_lists(text)
        
        assert len(lists) == 1
        assert len(lists[0]) == 3
        assert lists[0][0].type == StructureType.NUMBERED_ITEM
    
    def test_extract_nested_list(self):
        """Test extracting nested list."""
        extractor = StructureExtractor()
        text = "- Parent\n  - Child 1\n  - Child 2"
        
        lists = extractor.find_lists(text)
        
        assert len(lists) == 1
        items = lists[0]
        assert items[0].level == 0  # Parent
        assert items[1].level == 1  # Child
    
    def test_extract_preserves_order(self):
        """Test element order is preserved."""
        extractor = StructureExtractor()
        text = "# Heading\n\n- Item 1\n- Item 2\n\n## Sub Heading"
        
        structure = extractor.extract(text)
        elements = structure.elements
        
        # First should be heading, then items, then heading
        assert len(elements) >= 3
    
    def test_extract_markdown_table(self):
        """Test extracting markdown table."""
        extractor = StructureExtractor()
        text = "| Col1 | Col2 |\n|------|------|\n| A    | B    |\n| C    | D    |"
        
        tables = extractor.find_tables(text)
        
        assert len(tables) == 1
        assert tables[0].row_count >= 2
    
    def test_extract_full_structure(self):
        """Test full structure extraction."""
        extractor = StructureExtractor()
        text = """# Title

Introduction text.

## Section 1

- Item 1
- Item 2
- Item 3

## Section 2

1. Step one
2. Step two
"""
        
        structure = extractor.extract(text)
        
        assert len(structure.headings) >= 2
        assert len(structure.lists) >= 2
    
    def test_factory_function(self):
        """Test create_structure_extractor factory."""
        extractor = create_structure_extractor()
        
        assert isinstance(extractor, StructureExtractor)
