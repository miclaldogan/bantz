"""
Tests for V2-7 Document Ingestion (Issue #39).
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

from bantz.document.ingestion import (
    DocumentType,
    DocumentMetadata,
    IngestedDocument,
    DocumentIngester,
    create_document_ingester,
    EXTENSION_MAP,
)


class TestDocumentType:
    """Tests for DocumentType enum."""
    
    def test_types_exist(self):
        """Test document types exist."""
        assert DocumentType.PDF.value == "pdf"
        assert DocumentType.DOC.value == "doc"
        assert DocumentType.DOCX.value == "docx"
        assert DocumentType.TXT.value == "txt"
        assert DocumentType.MD.value == "md"
    
    def test_unknown_type(self):
        """Test unknown type."""
        assert DocumentType.UNKNOWN.value == "unknown"


class TestDocumentMetadata:
    """Tests for DocumentMetadata."""
    
    def test_create_metadata(self):
        """Test creating metadata."""
        metadata = DocumentMetadata(
            filename="test.pdf",
            doc_type=DocumentType.PDF,
            page_count=5,
            word_count=1000,
        )
        
        assert metadata.filename == "test.pdf"
        assert metadata.doc_type == DocumentType.PDF
        assert metadata.page_count == 5
        assert metadata.word_count == 1000
    
    def test_metadata_optional_fields(self):
        """Test optional metadata fields."""
        metadata = DocumentMetadata(
            filename="test.pdf",
            doc_type=DocumentType.PDF,
            page_count=1,
            word_count=100,
            author="Test Author",
            title="Test Title",
        )
        
        assert metadata.author == "Test Author"
        assert metadata.title == "Test Title"
    
    def test_metadata_to_dict(self):
        """Test metadata to_dict."""
        metadata = DocumentMetadata(
            filename="test.pdf",
            doc_type=DocumentType.PDF,
            page_count=5,
            word_count=1000,
        )
        
        data = metadata.to_dict()
        
        assert data["filename"] == "test.pdf"
        assert data["doc_type"] == "pdf"
        assert data["page_count"] == 5


class TestIngestedDocument:
    """Tests for IngestedDocument."""
    
    def test_create_document(self):
        """Test creating ingested document."""
        metadata = DocumentMetadata(
            filename="test.txt",
            doc_type=DocumentType.TXT,
            page_count=1,
            word_count=10,
        )
        
        doc = IngestedDocument(
            id="doc-123",
            metadata=metadata,
            raw_text="Hello World",
        )
        
        assert doc.id == "doc-123"
        assert doc.metadata.filename == "test.txt"
        assert doc.raw_text == "Hello World"
    
    def test_auto_generate_id(self):
        """Test ID is auto-generated if empty."""
        metadata = DocumentMetadata(
            filename="test.txt",
            doc_type=DocumentType.TXT,
            page_count=1,
            word_count=10,
        )
        
        doc = IngestedDocument(
            id="",
            metadata=metadata,
            raw_text="Test",
        )
        
        assert doc.id != ""
        assert len(doc.id) > 0
    
    def test_summary(self):
        """Test document summary."""
        metadata = DocumentMetadata(
            filename="test.txt",
            doc_type=DocumentType.TXT,
            page_count=1,
            word_count=10,
        )
        
        doc = IngestedDocument(
            id="doc-123",
            metadata=metadata,
            raw_text="Short text",
        )
        
        assert doc.summary == "Short text"
    
    def test_summary_truncated(self):
        """Test long text summary is truncated."""
        metadata = DocumentMetadata(
            filename="test.txt",
            doc_type=DocumentType.TXT,
            page_count=1,
            word_count=1000,
        )
        
        long_text = "A" * 300
        doc = IngestedDocument(
            id="doc-123",
            metadata=metadata,
            raw_text=long_text,
        )
        
        assert len(doc.summary) < len(long_text)
        assert doc.summary.endswith("...")
    
    def test_to_dict(self):
        """Test document to_dict."""
        metadata = DocumentMetadata(
            filename="test.txt",
            doc_type=DocumentType.TXT,
            page_count=1,
            word_count=10,
        )
        
        doc = IngestedDocument(
            id="doc-123",
            metadata=metadata,
            raw_text="Test",
        )
        
        data = doc.to_dict()
        
        assert data["id"] == "doc-123"
        assert data["raw_text"] == "Test"
        assert "metadata" in data


class TestDocumentIngester:
    """Tests for DocumentIngester."""
    
    def test_create_ingester(self):
        """Test creating ingester."""
        ingester = DocumentIngester()
        
        assert ingester is not None
    
    def test_detect_type_by_extension(self):
        """Test type detection by extension."""
        ingester = DocumentIngester()
        
        assert ingester.detect_type(Path("test.pdf")) == DocumentType.PDF
        assert ingester.detect_type(Path("test.docx")) == DocumentType.DOCX
        assert ingester.detect_type(Path("test.txt")) == DocumentType.TXT
        assert ingester.detect_type(Path("test.md")) == DocumentType.MD
    
    def test_detect_type_unknown_extension(self):
        """Test unknown extension."""
        ingester = DocumentIngester()
        
        assert ingester.detect_type(Path("test.xyz")) == DocumentType.UNKNOWN
    
    def test_detect_type_by_magic_pdf(self):
        """Test PDF magic bytes detection."""
        ingester = DocumentIngester()
        
        assert ingester.detect_type_by_magic(b"%PDF-1.4") == DocumentType.PDF
    
    def test_detect_type_by_magic_docx(self):
        """Test DOCX magic bytes detection."""
        ingester = DocumentIngester()
        
        assert ingester.detect_type_by_magic(b"PK\x03\x04") == DocumentType.DOCX
    
    def test_detect_type_by_magic_text(self):
        """Test text detection."""
        ingester = DocumentIngester()
        
        assert ingester.detect_type_by_magic(b"Hello World") == DocumentType.TXT
    
    def test_register_parser(self):
        """Test registering custom parser."""
        ingester = DocumentIngester()
        mock_parser = Mock()
        
        ingester.register_parser(DocumentType.PDF, mock_parser)
        
        assert ingester.get_parser(DocumentType.PDF) == mock_parser
    
    @pytest.mark.asyncio
    async def test_ingest_bytes_txt(self):
        """Test ingesting TXT bytes."""
        ingester = DocumentIngester()
        data = b"Hello World Test Content"
        
        doc = await ingester.ingest_bytes(
            data=data,
            doc_type=DocumentType.TXT,
            filename="test.txt",
        )
        
        assert doc.raw_text == "Hello World Test Content"
        assert doc.metadata.filename == "test.txt"
        assert doc.metadata.doc_type == DocumentType.TXT
    
    @pytest.mark.asyncio
    async def test_ingest_bytes_unsupported_type(self):
        """Test ingesting unsupported type raises error."""
        ingester = DocumentIngester()
        
        with pytest.raises(ValueError):
            await ingester.ingest_bytes(
                data=b"test",
                doc_type=DocumentType.UNKNOWN,
            )
    
    @pytest.mark.asyncio
    async def test_ingest_file_not_found(self):
        """Test ingesting non-existent file."""
        ingester = DocumentIngester()
        
        with pytest.raises(FileNotFoundError):
            await ingester.ingest(Path("/non/existent/file.txt"))
    
    def test_supported_types(self):
        """Test getting supported types."""
        ingester = DocumentIngester()
        
        supported = ingester.supported_types
        
        assert DocumentType.TXT in supported
        assert DocumentType.MD in supported
    
    def test_factory_function(self):
        """Test create_document_ingester factory."""
        ingester = create_document_ingester(extract_structure=False)
        
        assert isinstance(ingester, DocumentIngester)
        assert ingester._extract_structure is False
