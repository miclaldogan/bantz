"""
Plain text and Markdown document parsers.
"""

from bantz.document.parsers.base import DocumentParser, ParseResult


class TXTParser(DocumentParser):
    """
    Parser for plain text documents.
    
    Handles UTF-8 and other common encodings.
    """
    
    # Common text file encodings to try
    ENCODINGS = ["utf-8", "utf-16", "latin-1", "cp1252", "iso-8859-1"]
    
    def __init__(self, default_encoding: str = "utf-8"):
        """
        Initialize TXT parser.
        
        Args:
            default_encoding: Default encoding to try first.
        """
        self._default_encoding = default_encoding
    
    async def parse(self, data: bytes) -> ParseResult:
        """
        Parse text document.
        
        Args:
            data: Raw text bytes.
            
        Returns:
            ParseResult with decoded text.
            
        Raises:
            ValueError: If text cannot be decoded.
        """
        text = self._decode(data)
        
        # Count lines as rough "page" estimate (50 lines per page)
        lines = text.count("\n") + 1
        page_count = max(1, lines // 50)
        
        return ParseResult(
            text=text,
            page_count=page_count,
            metadata={"encoding": self._detected_encoding},
        )
    
    def _decode(self, data: bytes) -> str:
        """
        Decode bytes to string, trying multiple encodings.
        
        Args:
            data: Raw bytes.
            
        Returns:
            Decoded string.
            
        Raises:
            ValueError: If no encoding works.
        """
        # Check for BOM
        if data.startswith(b"\xef\xbb\xbf"):
            self._detected_encoding = "utf-8-sig"
            return data[3:].decode("utf-8")
        elif data.startswith(b"\xff\xfe"):
            self._detected_encoding = "utf-16-le"
            return data.decode("utf-16")
        elif data.startswith(b"\xfe\xff"):
            self._detected_encoding = "utf-16-be"
            return data.decode("utf-16")
        
        # Try default encoding first
        encodings = [self._default_encoding] + [
            e for e in self.ENCODINGS if e != self._default_encoding
        ]
        
        for encoding in encodings:
            try:
                text = data.decode(encoding)
                self._detected_encoding = encoding
                return text
            except (UnicodeDecodeError, LookupError):
                continue
        
        raise ValueError("Could not decode text with any known encoding")
    
    def can_parse(self, data: bytes) -> bool:
        """
        Check if data is parseable text.
        
        Args:
            data: Raw bytes to check.
            
        Returns:
            True if data can be decoded as text.
        """
        try:
            self._decode(data[:1024])  # Check first 1KB
            return True
        except ValueError:
            return False
    
    @property
    def supported_extensions(self) -> list[str]:
        """Get supported file extensions."""
        return [".txt", ".text"]
    
    @property
    def mime_types(self) -> list[str]:
        """Get supported MIME types."""
        return ["text/plain"]


class MDParser(TXTParser):
    """
    Parser for Markdown documents.
    
    Extends TXT parser with Markdown-specific handling.
    """
    
    async def parse(self, data: bytes) -> ParseResult:
        """
        Parse Markdown document.
        
        Args:
            data: Raw Markdown bytes.
            
        Returns:
            ParseResult with decoded text.
        """
        result = await super().parse(data)
        result.metadata["format"] = "markdown"
        return result
    
    @property
    def supported_extensions(self) -> list[str]:
        """Get supported file extensions."""
        return [".md", ".markdown", ".mdown"]
    
    @property
    def mime_types(self) -> list[str]:
        """Get supported MIME types."""
        return ["text/markdown", "text/x-markdown"]


def create_txt_parser(encoding: str = "utf-8") -> TXTParser:
    """Factory function to create a TXT parser."""
    return TXTParser(default_encoding=encoding)


def create_md_parser() -> MDParser:
    """Factory function to create a Markdown parser."""
    return MDParser()
