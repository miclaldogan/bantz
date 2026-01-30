"""
Document structure extraction module.

Extracts structural elements like headings, lists, tables from documents.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class StructureType(Enum):
    """Types of structural elements."""
    
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    NUMBERED_ITEM = "numbered_item"
    TABLE = "table"
    CODE_BLOCK = "code_block"
    BLOCKQUOTE = "blockquote"


@dataclass
class StructureElement:
    """A structural element in a document."""
    
    type: StructureType
    """Type of the element."""
    
    content: str
    """Text content of the element."""
    
    level: int = 0
    """Level for headings (1-6) or nesting depth for lists."""
    
    page: Optional[int] = None
    """Page number (if available)."""
    
    start_pos: int = 0
    """Start position in raw text."""
    
    end_pos: int = 0
    """End position in raw text."""
    
    children: list["StructureElement"] = field(default_factory=list)
    """Child elements (for nested structures)."""
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "type": self.type.value,
            "content": self.content,
            "level": self.level,
            "page": self.page,
            "start_pos": self.start_pos,
            "end_pos": self.end_pos,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class TableCell:
    """A cell in a table."""
    
    content: str
    row: int
    col: int
    colspan: int = 1
    rowspan: int = 1


@dataclass
class TableData:
    """Table data extracted from a document."""
    
    rows: list[list[str]]
    """Table rows as list of cells."""
    
    headers: Optional[list[str]] = None
    """Table headers (first row if detected)."""
    
    start_pos: int = 0
    """Start position in raw text."""
    
    end_pos: int = 0
    """End position in raw text."""
    
    @property
    def row_count(self) -> int:
        """Get number of rows."""
        return len(self.rows)
    
    @property
    def col_count(self) -> int:
        """Get number of columns."""
        return len(self.rows[0]) if self.rows else 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "rows": self.rows,
            "headers": self.headers,
            "row_count": self.row_count,
            "col_count": self.col_count,
        }


@dataclass
class DocumentStructure:
    """Complete structure of a document."""
    
    elements: list[StructureElement] = field(default_factory=list)
    """All structural elements in order."""
    
    headings: list[StructureElement] = field(default_factory=list)
    """All heading elements."""
    
    lists: list[list[StructureElement]] = field(default_factory=list)
    """Groups of list items."""
    
    tables: list[TableData] = field(default_factory=list)
    """Extracted tables."""
    
    def get_outline(self) -> list[tuple[int, str]]:
        """
        Get document outline from headings.
        
        Returns:
            List of (level, heading_text) tuples.
        """
        return [(h.level, h.content) for h in self.headings]
    
    def get_all_list_items(self) -> list[StructureElement]:
        """Get all list items flattened."""
        items = []
        for lst in self.lists:
            items.extend(lst)
        return items
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "elements": [e.to_dict() for e in self.elements],
            "headings": [h.to_dict() for h in self.headings],
            "lists": [[i.to_dict() for i in lst] for lst in self.lists],
            "tables": [t.to_dict() for t in self.tables],
        }


class StructureExtractor:
    """
    Extracts structural elements from document text.
    
    Recognizes headings, lists, tables, code blocks, etc.
    """
    
    # Markdown heading patterns
    HEADING_PATTERNS = [
        (r"^(#{1,6})\s+(.+)$", "markdown"),  # # Heading
        (r"^(.+)\n={3,}$", "setext_h1"),     # Heading\n===
        (r"^(.+)\n-{3,}$", "setext_h2"),     # Heading\n---
        (r"^(\d+\.)\s+([A-ZÖÜÇŞĞI].+)$", "numbered"),  # 1. Heading (starts with capital)
    ]
    
    # List patterns
    LIST_PATTERNS = [
        (r"^\s*([-*•])\s+(.+)$", StructureType.LIST_ITEM),      # Bullet
        (r"^\s*(\d+)[.)\s]+(.+)$", StructureType.NUMBERED_ITEM), # 1. or 1) or 1
        (r"^\s*([a-z])[.)\s]+(.+)$", StructureType.NUMBERED_ITEM),  # a. or a)
    ]
    
    # Code block pattern
    CODE_BLOCK_PATTERN = r"```[\s\S]*?```"
    
    # Blockquote pattern
    BLOCKQUOTE_PATTERN = r"^>\s+(.+)$"
    
    def __init__(self):
        """Initialize the structure extractor."""
        self._heading_regex = [
            (re.compile(p, re.MULTILINE), style)
            for p, style in self.HEADING_PATTERNS
        ]
        self._list_regex = [
            (re.compile(p, re.MULTILINE), stype)
            for p, stype in self.LIST_PATTERNS
        ]
    
    def extract(self, text: str) -> DocumentStructure:
        """
        Extract structure from text.
        
        Args:
            text: Document text.
            
        Returns:
            DocumentStructure with extracted elements.
        """
        structure = DocumentStructure()
        
        # Extract headings
        structure.headings = self.find_headings(text)
        
        # Extract lists
        structure.lists = self.find_lists(text)
        
        # Extract tables
        structure.tables = self.find_tables(text)
        
        # Build complete element list
        structure.elements = self._build_elements(text, structure)
        
        return structure
    
    def find_headings(self, text: str) -> list[StructureElement]:
        """
        Find all headings in text.
        
        Args:
            text: Document text.
            
        Returns:
            List of heading elements.
        """
        headings = []
        
        for line_num, line in enumerate(text.split("\n")):
            for regex, style in self._heading_regex:
                match = regex.match(line)
                if match:
                    if style == "markdown":
                        hashes, content = match.groups()
                        level = len(hashes)
                    elif style == "setext_h1":
                        content = match.group(1)
                        level = 1
                    elif style == "setext_h2":
                        content = match.group(1)
                        level = 2
                    elif style == "numbered":
                        _, content = match.groups()
                        level = 1
                    else:
                        continue
                    
                    headings.append(StructureElement(
                        type=StructureType.HEADING,
                        content=content.strip(),
                        level=level,
                        start_pos=text.find(line),
                        end_pos=text.find(line) + len(line),
                    ))
                    break  # Only match first pattern
        
        return headings
    
    def find_lists(self, text: str) -> list[list[StructureElement]]:
        """
        Find all lists in text.
        
        Args:
            text: Document text.
            
        Returns:
            List of list groups.
        """
        all_lists = []
        current_list = []
        last_was_list = False
        
        for line in text.split("\n"):
            is_list_item = False
            
            for regex, item_type in self._list_regex:
                match = regex.match(line)
                if match:
                    is_list_item = True
                    
                    # Calculate nesting level from leading whitespace
                    leading_spaces = len(line) - len(line.lstrip())
                    level = leading_spaces // 2  # 2 spaces per level
                    
                    content = match.group(2) if match.lastindex >= 2 else match.group(1)
                    
                    element = StructureElement(
                        type=item_type,
                        content=content.strip(),
                        level=level,
                        start_pos=text.find(line),
                        end_pos=text.find(line) + len(line),
                    )
                    
                    current_list.append(element)
                    break
            
            if not is_list_item and last_was_list and current_list:
                # End of current list
                all_lists.append(current_list)
                current_list = []
            
            last_was_list = is_list_item
        
        # Don't forget the last list
        if current_list:
            all_lists.append(current_list)
        
        return all_lists
    
    def find_tables(self, text: str) -> list[TableData]:
        """
        Find all tables in text.
        
        Recognizes:
        - Markdown tables (| col1 | col2 |)
        - Simple aligned tables
        
        Args:
            text: Document text.
            
        Returns:
            List of extracted tables.
        """
        tables = []
        
        # Markdown table pattern
        # | Header | Header |
        # |--------|--------|
        # | Cell   | Cell   |
        
        lines = text.split("\n")
        i = 0
        
        while i < len(lines):
            line = lines[i]
            
            # Check if this looks like a markdown table row
            if "|" in line and line.strip().startswith("|"):
                table_lines = [line]
                j = i + 1
                
                # Collect consecutive table lines
                while j < len(lines) and "|" in lines[j]:
                    table_lines.append(lines[j])
                    j += 1
                
                if len(table_lines) >= 2:
                    table = self._parse_markdown_table(table_lines)
                    if table:
                        table.start_pos = text.find(table_lines[0])
                        table.end_pos = text.find(table_lines[-1]) + len(table_lines[-1])
                        tables.append(table)
                
                i = j
            else:
                i += 1
        
        return tables
    
    def _parse_markdown_table(self, lines: list[str]) -> Optional[TableData]:
        """Parse markdown table lines into TableData."""
        rows = []
        headers = None
        
        for idx, line in enumerate(lines):
            # Skip separator line (|---|---|)
            if re.match(r"^\|[\s\-:]+\|$", line.strip()):
                continue
            
            # Parse cells
            cells = [
                cell.strip()
                for cell in line.split("|")
                if cell.strip()
            ]
            
            if not cells:
                continue
            
            if idx == 0:
                headers = cells
            
            rows.append(cells)
        
        if not rows:
            return None
        
        return TableData(rows=rows, headers=headers)
    
    def _build_elements(
        self,
        text: str,
        structure: DocumentStructure,
    ) -> list[StructureElement]:
        """Build ordered list of all elements."""
        elements = []
        
        # Combine all elements with positions
        all_items = []
        
        for heading in structure.headings:
            all_items.append((heading.start_pos, heading))
        
        for lst in structure.lists:
            for item in lst:
                all_items.append((item.start_pos, item))
        
        # Sort by position
        all_items.sort(key=lambda x: x[0])
        
        elements = [item for _, item in all_items]
        
        return elements


def create_structure_extractor() -> StructureExtractor:
    """Factory function to create a structure extractor."""
    return StructureExtractor()
