"""
Base document parser interface.

Provides the abstract base class for all document parsers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bantz.document.structure import DocumentStructure


@dataclass
class ParseResult:
    """Result of parsing a document."""
    
    text: str
    """Extracted raw text content."""
    
    page_count: int = 1
    """Number of pages in the document."""
    
    word_count: int = 0
    """Number of words in the document."""
    
    metadata: dict = field(default_factory=dict)
    """Additional metadata extracted from the document."""
    
    def __post_init__(self):
        """Calculate word count if not provided."""
        if self.word_count == 0 and self.text:
            self.word_count = len(self.text.split())


class DocumentParser(ABC):
    """
    Abstract base class for document parsers.
    
    Each parser handles a specific document format and extracts
    text content along with structural information.
    """
    
    @abstractmethod
    async def parse(self, data: bytes) -> ParseResult:
        """
        Parse document data and extract text.
        
        Args:
            data: Raw bytes of the document.
            
        Returns:
            ParseResult containing extracted text and metadata.
            
        Raises:
            ValueError: If the document cannot be parsed.
        """
        pass
    
    @abstractmethod
    def can_parse(self, data: bytes) -> bool:
        """
        Check if this parser can handle the given data.
        
        Args:
            data: Raw bytes to check.
            
        Returns:
            True if this parser can handle the data.
        """
        pass
    
    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """
        Get list of file extensions this parser supports.
        
        Returns:
            List of extensions (e.g., [".pdf"]).
        """
        pass
    
    @property
    @abstractmethod
    def mime_types(self) -> list[str]:
        """
        Get list of MIME types this parser supports.
        
        Returns:
            List of MIME types.
        """
        pass
