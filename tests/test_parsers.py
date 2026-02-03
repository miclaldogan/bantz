"""
Tests for V2-7 Document Parsers (Issue #39).
"""

import pytest

from bantz.document.parsers.base import DocumentParser, ParseResult
from bantz.document.parsers.txt import TXTParser, MDParser, create_txt_parser
from bantz.document.parsers.pdf import PDFParser
from bantz.document.parsers.docx import DOCXParser


class TestParseResult:
    """Tests for ParseResult."""
    
    def test_create_parse_result(self):
        """Test creating a parse result."""
        result = ParseResult(text="Hello World", page_count=1)
        
        assert result.text == "Hello World"
        assert result.page_count == 1
    
    def test_word_count_calculated(self):
        """Test word count is auto-calculated."""
        result = ParseResult(text="Hello World Test")
        
        assert result.word_count == 3
    
    def test_word_count_explicit(self):
        """Test explicit word count."""
        result = ParseResult(text="Hello", word_count=5)
        
        assert result.word_count == 5
    
    def test_metadata_default(self):
        """Test default metadata is empty dict."""
        result = ParseResult(text="Test")
        
        assert result.metadata == {}


class TestTXTParser:
    """Tests for TXTParser."""
    
    @pytest.mark.asyncio
    async def test_parse_utf8_text(self):
        """Test parsing UTF-8 text."""
        parser = TXTParser()
        data = "Merhaba Dünya! Türkçe karakter testi.".encode("utf-8")
        
        result = await parser.parse(data)
        
        assert "Merhaba Dünya" in result.text
        assert "Türkçe" in result.text
    
    @pytest.mark.asyncio
    async def test_parse_utf8_bom(self):
        """Test parsing UTF-8 with BOM."""
        parser = TXTParser()
        data = b"\xef\xbb\xbfHello BOM"
        
        result = await parser.parse(data)
        
        assert result.text == "Hello BOM"
        assert result.metadata["encoding"] == "utf-8-sig"
    
    @pytest.mark.asyncio
    async def test_parse_latin1(self):
        """Test parsing Latin-1 text."""
        parser = TXTParser()
        data = "Café résumé".encode("latin-1")
        
        result = await parser.parse(data)
        
        assert "Café" in result.text or "Caf" in result.text
    
    def test_can_parse_text(self):
        """Test can_parse for valid text."""
        parser = TXTParser()
        
        assert parser.can_parse(b"Hello World")
        assert parser.can_parse("Türkçe".encode("utf-8"))
    
    def test_supported_extensions(self):
        """Test supported extensions."""
        parser = TXTParser()
        
        assert ".txt" in parser.supported_extensions
        assert ".text" in parser.supported_extensions
    
    def test_mime_types(self):
        """Test MIME types."""
        parser = TXTParser()
        
        assert "text/plain" in parser.mime_types
    
    def test_factory_function(self):
        """Test create_txt_parser factory."""
        parser = create_txt_parser(encoding="latin-1")
        
        assert isinstance(parser, TXTParser)
        assert parser._default_encoding == "latin-1"


class TestMDParser:
    """Tests for MDParser."""
    
    @pytest.mark.asyncio
    async def test_parse_markdown(self):
        """Test parsing markdown text."""
        parser = MDParser()
        data = "# Heading\n\nParagraph text.".encode("utf-8")
        
        result = await parser.parse(data)
        
        assert "# Heading" in result.text
        assert result.metadata["format"] == "markdown"
    
    def test_supported_extensions(self):
        """Test supported extensions."""
        parser = MDParser()
        
        assert ".md" in parser.supported_extensions
        assert ".markdown" in parser.supported_extensions


class TestPDFParser:
    """Tests for PDFParser."""
    
    def test_can_parse_pdf_magic(self):
        """Test PDF detection by magic bytes."""
        parser = PDFParser()
        
        # Valid PDF magic
        assert parser.can_parse(b"%PDF-1.4")
        assert parser.can_parse(b"%PDF-2.0")
        
        # Invalid
        assert not parser.can_parse(b"Hello")
        assert not parser.can_parse(b"PK\x03\x04")
    
    def test_supported_extensions(self):
        """Test supported extensions."""
        parser = PDFParser()
        
        assert ".pdf" in parser.supported_extensions
    
    def test_mime_types(self):
        """Test MIME types."""
        parser = PDFParser()
        
        assert "application/pdf" in parser.mime_types
    
    @pytest.mark.asyncio
    async def test_parse_invalid_pdf_raises(self):
        """Test parsing invalid PDF raises error."""
        parser = PDFParser()

        with pytest.raises(ValueError):
            await parser.parse(b"Not a PDF")


class TestDOCXParser:
    """Tests for DOCXParser."""
    
    def test_can_parse_docx_magic(self):
        """Test DOCX detection by magic bytes."""
        parser = DOCXParser()
        
        # DOCX is a ZIP file
        assert parser.can_parse(b"PK\x03\x04")
        
        # Invalid
        assert not parser.can_parse(b"Hello")
        assert not parser.can_parse(b"%PDF")
    
    def test_supported_extensions(self):
        """Test supported extensions."""
        parser = DOCXParser()
        
        assert ".docx" in parser.supported_extensions
    
    def test_mime_types(self):
        """Test MIME types."""
        parser = DOCXParser()
        
        assert any("wordprocessingml" in m for m in parser.mime_types)
    
    @pytest.mark.asyncio
    async def test_parse_invalid_docx_raises(self):
        """Test parsing invalid DOCX raises error."""
        parser = DOCXParser()
        
        if not parser.is_available:
            pytest.skip("python-docx not available")
        
        with pytest.raises(ValueError):
            await parser.parse(b"PK\x03\x04invalid")
