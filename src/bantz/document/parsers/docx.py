"""
DOCX document parser.

Uses python-docx for DOCX text extraction.
"""

import io
from typing import Optional

from bantz.document.parsers.base import DocumentParser, ParseResult


# DOCX magic bytes (ZIP file with specific structure)
DOCX_MAGIC = b"PK\x03\x04"


class DOCXParser(DocumentParser):
    """
    Parser for DOCX documents.
    
    Uses python-docx library for text extraction.
    """
    
    def __init__(self):
        """Initialize DOCX parser."""
        self._docx = None
        self._load_library()
    
    def _load_library(self) -> None:
        """Load python-docx library."""
        try:
            import docx
            self._docx = docx
        except ImportError:
            pass
    
    @property
    def is_available(self) -> bool:
        """Check if python-docx is available."""
        return self._docx is not None
    
    async def parse(self, data: bytes) -> ParseResult:
        """
        Parse DOCX document and extract text.
        
        Args:
            data: Raw DOCX bytes.
            
        Returns:
            ParseResult with extracted text.
            
        Raises:
            ValueError: If DOCX cannot be parsed.
            ImportError: If python-docx is not available.
        """
        if not self.is_available:
            raise ImportError(
                "python-docx is not available. Install it: pip install python-docx"
            )
        
        if not self.can_parse(data):
            raise ValueError("Data does not appear to be a valid DOCX")
        
        text_parts = []
        metadata = {}
        
        try:
            doc = self._docx.Document(io.BytesIO(data))
            
            # Extract core properties
            if doc.core_properties:
                props = doc.core_properties
                if props.author:
                    metadata["author"] = props.author
                if props.title:
                    metadata["title"] = props.title
                if props.created:
                    metadata["created"] = props.created.isoformat()
                if props.modified:
                    metadata["modified"] = props.modified.isoformat()
            
            # Extract paragraphs
            for para in doc.paragraphs:
                if para.text.strip():
                    text_parts.append(para.text)
            
            # Extract tables
            for table in doc.tables:
                for row in table.rows:
                    row_text = []
                    for cell in row.cells:
                        if cell.text.strip():
                            row_text.append(cell.text.strip())
                    if row_text:
                        text_parts.append(" | ".join(row_text))
                        
        except Exception as e:
            raise ValueError(f"Failed to parse DOCX: {e}") from e
        
        full_text = "\n\n".join(text_parts)
        
        # Estimate page count (rough: ~500 words per page)
        word_count = len(full_text.split())
        page_count = max(1, word_count // 500)
        
        return ParseResult(
            text=full_text,
            page_count=page_count,
            word_count=word_count,
            metadata=metadata,
        )
    
    def can_parse(self, data: bytes) -> bool:
        """
        Check if data is a DOCX.
        
        Args:
            data: Raw bytes to check.
            
        Returns:
            True if data appears to be a DOCX (ZIP with specific content).
        """
        if data[:4] != DOCX_MAGIC:
            return False
        
        # Further check: look for [Content_Types].xml or word/ in the ZIP
        # For performance, just check magic bytes
        return True
    
    @property
    def supported_extensions(self) -> list[str]:
        """Get supported file extensions."""
        return [".docx"]
    
    @property
    def mime_types(self) -> list[str]:
        """Get supported MIME types."""
        return [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ]


class DOCParser(DocumentParser):
    """
    Parser for legacy DOC documents.
    
    Note: Legacy DOC parsing is limited without external tools.
    This provides basic support only.
    """
    
    # DOC magic bytes (OLE Compound File)
    DOC_MAGIC = b"\xd0\xcf\x11\xe0"
    
    def __init__(self):
        """Initialize DOC parser."""
        self._antiword_available = False
        self._check_antiword()
    
    def _check_antiword(self) -> None:
        """Check if antiword is available for DOC parsing."""
        import shutil
        self._antiword_available = shutil.which("antiword") is not None
    
    @property
    def is_available(self) -> bool:
        """Check if DOC parsing is available."""
        return self._antiword_available
    
    async def parse(self, data: bytes) -> ParseResult:
        """
        Parse DOC document.
        
        Args:
            data: Raw DOC bytes.
            
        Returns:
            ParseResult with extracted text.
            
        Raises:
            ValueError: If DOC cannot be parsed.
        """
        if not self.is_available:
            raise ImportError(
                "antiword is not available. Install it: sudo apt install antiword"
            )
        
        if not self.can_parse(data):
            raise ValueError("Data does not appear to be a valid DOC")
        
        import subprocess
        import tempfile
        
        try:
            # Write to temp file and use antiword
            with tempfile.NamedTemporaryFile(suffix=".doc", delete=True) as f:
                f.write(data)
                f.flush()
                
                result = subprocess.run(
                    ["antiword", f.name],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                
                if result.returncode != 0:
                    raise ValueError(f"antiword failed: {result.stderr}")
                
                text = result.stdout
                
        except subprocess.TimeoutExpired:
            raise ValueError("DOC parsing timed out")
        except Exception as e:
            raise ValueError(f"Failed to parse DOC: {e}") from e
        
        return ParseResult(
            text=text,
            page_count=1,
        )
    
    def can_parse(self, data: bytes) -> bool:
        """Check if data is a DOC file."""
        return data[:4] == self.DOC_MAGIC
    
    @property
    def supported_extensions(self) -> list[str]:
        """Get supported file extensions."""
        return [".doc"]
    
    @property
    def mime_types(self) -> list[str]:
        """Get supported MIME types."""
        return ["application/msword"]


def create_docx_parser() -> DOCXParser:
    """Factory function to create a DOCX parser."""
    return DOCXParser()
