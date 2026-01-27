"""
Document ingestion module.

Provides document type detection, metadata extraction, and unified ingestion pipeline.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from bantz.document.parsers.base import DocumentParser, ParseResult
from bantz.document.parsers.pdf import PDFParser
from bantz.document.parsers.docx import DOCXParser
from bantz.document.parsers.txt import TXTParser, MDParser

if TYPE_CHECKING:
    from bantz.document.structure import DocumentStructure


class DocumentType(Enum):
    """Supported document types."""
    
    PDF = "pdf"
    DOC = "doc"
    DOCX = "docx"
    TXT = "txt"
    MD = "md"
    UNKNOWN = "unknown"


# Extension to document type mapping
EXTENSION_MAP: dict[str, DocumentType] = {
    ".pdf": DocumentType.PDF,
    ".doc": DocumentType.DOC,
    ".docx": DocumentType.DOCX,
    ".txt": DocumentType.TXT,
    ".text": DocumentType.TXT,
    ".md": DocumentType.MD,
    ".markdown": DocumentType.MD,
    ".mdown": DocumentType.MD,
}


# Magic bytes for document type detection
MAGIC_BYTES: dict[bytes, DocumentType] = {
    b"%PDF": DocumentType.PDF,
    b"PK\x03\x04": DocumentType.DOCX,  # Could also be DOC in ZIP
    b"\xd0\xcf\x11\xe0": DocumentType.DOC,  # OLE Compound File
}


@dataclass
class DocumentMetadata:
    """Metadata about a document."""
    
    filename: str
    """Original filename."""
    
    doc_type: DocumentType
    """Detected document type."""
    
    page_count: int
    """Number of pages."""
    
    word_count: int
    """Number of words."""
    
    file_size: int = 0
    """File size in bytes."""
    
    created_at: Optional[datetime] = None
    """Document creation time."""
    
    modified_at: Optional[datetime] = None
    """Document modification time."""
    
    author: Optional[str] = None
    """Document author."""
    
    title: Optional[str] = None
    """Document title."""
    
    extra: dict = field(default_factory=dict)
    """Additional metadata."""
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "filename": self.filename,
            "doc_type": self.doc_type.value,
            "page_count": self.page_count,
            "word_count": self.word_count,
            "file_size": self.file_size,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
            "author": self.author,
            "title": self.title,
            "extra": self.extra,
        }


@dataclass
class IngestedDocument:
    """A fully ingested document with extracted content."""
    
    id: str
    """Unique document ID."""
    
    metadata: DocumentMetadata
    """Document metadata."""
    
    raw_text: str
    """Extracted raw text content."""
    
    structure: Optional["DocumentStructure"] = None
    """Extracted document structure (if analyzed)."""
    
    ingested_at: datetime = field(default_factory=datetime.now)
    """When the document was ingested."""
    
    source_path: Optional[str] = None
    """Original file path (if from file)."""
    
    def __post_init__(self):
        """Generate ID if not provided."""
        if not self.id:
            self.id = str(uuid.uuid4())
    
    @property
    def summary(self) -> str:
        """Get a brief summary of the document."""
        preview = self.raw_text[:200].replace("\n", " ").strip()
        if len(self.raw_text) > 200:
            preview += "..."
        return preview
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "metadata": self.metadata.to_dict(),
            "raw_text": self.raw_text,
            "ingested_at": self.ingested_at.isoformat(),
            "source_path": self.source_path,
        }


class DocumentIngester:
    """
    Main document ingestion pipeline.
    
    Handles document type detection, parsing, and metadata extraction.
    """
    
    def __init__(self, extract_structure: bool = True):
        """
        Initialize the document ingester.
        
        Args:
            extract_structure: Whether to extract document structure.
        """
        self._extract_structure = extract_structure
        self._parsers: dict[DocumentType, DocumentParser] = {}
        self._structure_extractor = None
        
        # Register default parsers
        self._register_default_parsers()
    
    def _register_default_parsers(self) -> None:
        """Register default document parsers."""
        self._parsers[DocumentType.PDF] = PDFParser()
        self._parsers[DocumentType.DOCX] = DOCXParser()
        self._parsers[DocumentType.TXT] = TXTParser()
        self._parsers[DocumentType.MD] = MDParser()
    
    def register_parser(self, doc_type: DocumentType, parser: DocumentParser) -> None:
        """
        Register a custom parser for a document type.
        
        Args:
            doc_type: Document type to handle.
            parser: Parser instance.
        """
        self._parsers[doc_type] = parser
    
    def get_parser(self, doc_type: DocumentType) -> Optional[DocumentParser]:
        """
        Get parser for a document type.
        
        Args:
            doc_type: Document type.
            
        Returns:
            Parser instance or None if not available.
        """
        return self._parsers.get(doc_type)
    
    def detect_type(self, file_path: Path) -> DocumentType:
        """
        Detect document type from file path.
        
        Args:
            file_path: Path to the file.
            
        Returns:
            Detected document type.
        """
        ext = file_path.suffix.lower()
        return EXTENSION_MAP.get(ext, DocumentType.UNKNOWN)
    
    def detect_type_by_magic(self, data: bytes) -> DocumentType:
        """
        Detect document type from magic bytes.
        
        Args:
            data: First bytes of the document.
            
        Returns:
            Detected document type.
        """
        for magic, doc_type in MAGIC_BYTES.items():
            if data.startswith(magic):
                return doc_type
        
        # Try to detect text
        txt_parser = TXTParser()
        if txt_parser.can_parse(data):
            return DocumentType.TXT
        
        return DocumentType.UNKNOWN
    
    async def ingest(self, file_path: Path) -> IngestedDocument:
        """
        Ingest a document from file.
        
        Args:
            file_path: Path to the document file.
            
        Returns:
            Ingested document with extracted content.
            
        Raises:
            FileNotFoundError: If file doesn't exist.
            ValueError: If document type is not supported.
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Read file
        data = file_path.read_bytes()
        
        # Detect type
        doc_type = self.detect_type(file_path)
        if doc_type == DocumentType.UNKNOWN:
            doc_type = self.detect_type_by_magic(data)
        
        # Ingest
        document = await self.ingest_bytes(
            data=data,
            doc_type=doc_type,
            filename=file_path.name,
        )
        
        document.source_path = str(file_path.absolute())
        
        return document
    
    async def ingest_bytes(
        self,
        data: bytes,
        doc_type: DocumentType,
        filename: str = "document",
    ) -> IngestedDocument:
        """
        Ingest a document from bytes.
        
        Args:
            data: Raw document bytes.
            doc_type: Document type.
            filename: Original filename.
            
        Returns:
            Ingested document with extracted content.
            
        Raises:
            ValueError: If document type is not supported.
        """
        parser = self.get_parser(doc_type)
        if parser is None:
            raise ValueError(f"No parser available for document type: {doc_type}")
        
        # Parse document
        parse_result = await parser.parse(data)
        
        # Build metadata
        metadata = DocumentMetadata(
            filename=filename,
            doc_type=doc_type,
            page_count=parse_result.page_count,
            word_count=parse_result.word_count,
            file_size=len(data),
            author=parse_result.metadata.get("author"),
            title=parse_result.metadata.get("title"),
            extra=parse_result.metadata,
        )
        
        # Extract creation/modification dates if available
        if "created" in parse_result.metadata:
            try:
                metadata.created_at = datetime.fromisoformat(
                    parse_result.metadata["created"]
                )
            except (ValueError, TypeError):
                pass
        
        if "modified" in parse_result.metadata:
            try:
                metadata.modified_at = datetime.fromisoformat(
                    parse_result.metadata["modified"]
                )
            except (ValueError, TypeError):
                pass
        
        # Create document
        document = IngestedDocument(
            id=str(uuid.uuid4()),
            metadata=metadata,
            raw_text=parse_result.text,
        )
        
        # Extract structure if enabled
        if self._extract_structure and self._structure_extractor:
            document.structure = self._structure_extractor.extract(parse_result.text)
        
        return document
    
    def set_structure_extractor(self, extractor: "StructureExtractor") -> None:
        """
        Set the structure extractor.
        
        Args:
            extractor: Structure extractor instance.
        """
        self._structure_extractor = extractor
    
    @property
    def supported_types(self) -> list[DocumentType]:
        """Get list of supported document types."""
        return [
            doc_type
            for doc_type, parser in self._parsers.items()
            if hasattr(parser, "is_available") and parser.is_available
            or not hasattr(parser, "is_available")
        ]


def create_document_ingester(extract_structure: bool = True) -> DocumentIngester:
    """
    Factory function to create a document ingester.
    
    Args:
        extract_structure: Whether to extract document structure.
        
    Returns:
        Configured DocumentIngester instance.
    """
    return DocumentIngester(extract_structure=extract_structure)
