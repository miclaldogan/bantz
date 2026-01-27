"""
PDF document parser.

Uses pdfplumber for PDF text extraction.
"""

import io
from typing import Optional

from bantz.document.parsers.base import DocumentParser, ParseResult


# PDF magic bytes
PDF_MAGIC = b"%PDF"


class PDFParser(DocumentParser):
    """
    Parser for PDF documents.
    
    Uses pdfplumber library for text extraction.
    Falls back to PyMuPDF if pdfplumber is not available.
    """
    
    def __init__(self):
        """Initialize PDF parser."""
        self._pdfplumber = None
        self._pymupdf = None
        self._load_library()
    
    def _load_library(self) -> None:
        """Load PDF library (pdfplumber or PyMuPDF)."""
        try:
            import pdfplumber
            self._pdfplumber = pdfplumber
        except ImportError:
            try:
                import fitz  # PyMuPDF
                self._pymupdf = fitz
            except ImportError:
                pass
    
    @property
    def is_available(self) -> bool:
        """Check if a PDF library is available."""
        return self._pdfplumber is not None or self._pymupdf is not None
    
    async def parse(self, data: bytes) -> ParseResult:
        """
        Parse PDF document and extract text.
        
        Args:
            data: Raw PDF bytes.
            
        Returns:
            ParseResult with extracted text.
            
        Raises:
            ValueError: If PDF cannot be parsed.
            ImportError: If no PDF library is available.
        """
        if not self.is_available:
            raise ImportError(
                "No PDF library available. Install pdfplumber or PyMuPDF: "
                "pip install pdfplumber or pip install PyMuPDF"
            )
        
        if not self.can_parse(data):
            raise ValueError("Data does not appear to be a valid PDF")
        
        if self._pdfplumber:
            return await self._parse_with_pdfplumber(data)
        else:
            return await self._parse_with_pymupdf(data)
    
    async def _parse_with_pdfplumber(self, data: bytes) -> ParseResult:
        """Parse PDF using pdfplumber."""
        text_parts = []
        page_count = 0
        metadata = {}
        
        try:
            with self._pdfplumber.open(io.BytesIO(data)) as pdf:
                page_count = len(pdf.pages)
                metadata = pdf.metadata or {}
                
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
        except Exception as e:
            raise ValueError(f"Failed to parse PDF: {e}") from e
        
        full_text = "\n\n".join(text_parts)
        
        return ParseResult(
            text=full_text,
            page_count=page_count,
            metadata=self._clean_metadata(metadata),
        )
    
    async def _parse_with_pymupdf(self, data: bytes) -> ParseResult:
        """Parse PDF using PyMuPDF."""
        text_parts = []
        page_count = 0
        metadata = {}
        
        try:
            doc = self._pymupdf.open(stream=data, filetype="pdf")
            page_count = len(doc)
            metadata = doc.metadata or {}
            
            for page in doc:
                page_text = page.get_text()
                if page_text:
                    text_parts.append(page_text)
            
            doc.close()
        except Exception as e:
            raise ValueError(f"Failed to parse PDF: {e}") from e
        
        full_text = "\n\n".join(text_parts)
        
        return ParseResult(
            text=full_text,
            page_count=page_count,
            metadata=self._clean_metadata(metadata),
        )
    
    def _clean_metadata(self, metadata: dict) -> dict:
        """Clean metadata dictionary."""
        cleaned = {}
        for key, value in metadata.items():
            if value is not None:
                # Remove leading slash from keys (pdfplumber style)
                clean_key = key.lstrip("/").lower()
                cleaned[clean_key] = str(value) if value else ""
        return cleaned
    
    def can_parse(self, data: bytes) -> bool:
        """
        Check if data is a PDF.
        
        Args:
            data: Raw bytes to check.
            
        Returns:
            True if data starts with PDF magic bytes.
        """
        return data[:4] == PDF_MAGIC
    
    @property
    def supported_extensions(self) -> list[str]:
        """Get supported file extensions."""
        return [".pdf"]
    
    @property
    def mime_types(self) -> list[str]:
        """Get supported MIME types."""
        return ["application/pdf"]


def create_pdf_parser() -> PDFParser:
    """Factory function to create a PDF parser."""
    return PDFParser()
