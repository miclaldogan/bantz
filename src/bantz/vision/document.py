"""
Document Analyzer.

PDF reading, image analysis, and OCR capabilities.
Uses PyMuPDF (fitz) for PDFs and pytesseract for OCR.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union, Tuple
from pathlib import Path
from enum import Enum
import logging
import io
import base64
import re

logger = logging.getLogger(__name__)


class DocumentType(Enum):
    """Supported document types."""
    
    PDF = "pdf"
    IMAGE = "image"
    TEXT = "text"
    UNKNOWN = "unknown"
    
    @classmethod
    def from_path(cls, path: Union[str, Path]) -> "DocumentType":
        """Detect document type from path."""
        path = Path(path)
        suffix = path.suffix.lower()
        
        if suffix == ".pdf":
            return cls.PDF
        elif suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"}:
            return cls.IMAGE
        elif suffix in {".txt", ".md", ".rst", ".csv", ".json", ".xml", ".html"}:
            return cls.TEXT
        else:
            return cls.UNKNOWN


@dataclass
class DocumentPage:
    """Single page from a document."""
    
    number: int  # 1-indexed
    text: str
    images: List[bytes] = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def has_images(self) -> bool:
        return len(self.images) > 0
    
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass
class DocumentInfo:
    """Document metadata and content."""
    
    path: Path
    doc_type: DocumentType
    title: Optional[str] = None
    author: Optional[str] = None
    page_count: int = 1
    total_words: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Content (loaded on demand)
    pages: List[DocumentPage] = field(default_factory=list)
    full_text: str = ""


@dataclass
class OCRResult:
    """OCR result from an image."""
    
    text: str
    confidence: float = 0.0
    language: str = "unknown"
    boxes: List[Dict[str, Any]] = field(default_factory=list)


class DocumentAnalyzer:
    """
    Document analysis with PDF reading and OCR.
    
    Example:
        analyzer = DocumentAnalyzer()
        
        # Analyze PDF
        doc = analyzer.read_pdf("document.pdf")
        print(doc.full_text)
        
        # Summarize with vision
        summary = analyzer.summarize("document.pdf")
        
        # OCR an image
        text = analyzer.ocr("screenshot.png")
    """
    
    def __init__(
        self,
        vision_llm: Optional[Any] = None,
        default_language: str = "tr",
        ocr_language: str = "tur+eng",
    ):
        """
        Initialize document analyzer.
        
        Args:
            vision_llm: Optional VisionLLM for enhanced analysis
            default_language: Default language for responses
            ocr_language: Tesseract language codes (e.g., "tur+eng")
        """
        self.vision_llm = vision_llm
        self.default_language = default_language
        self.ocr_language = ocr_language
        
        self._pdf_available = self._check_pdf_support()
        self._ocr_available = self._check_ocr_support()
    
    def _check_pdf_support(self) -> bool:
        """Check if PyMuPDF is available."""
        try:
            import fitz  # PyMuPDF
            return True
        except ImportError:
            logger.warning("PyMuPDF not available. Install with: pip install PyMuPDF")
            return False
    
    def _check_ocr_support(self) -> bool:
        """Check if pytesseract is available."""
        try:
            import pytesseract
            # Also check if tesseract binary is installed
            pytesseract.get_tesseract_version()
            return True
        except ImportError:
            logger.warning("pytesseract not available. Install with: pip install pytesseract")
            return False
        except Exception as e:
            logger.warning(f"Tesseract binary not found: {e}")
            return False
    
    def read_pdf(
        self,
        path: Union[str, Path, bytes],
        pages: Optional[List[int]] = None,
        extract_images: bool = False,
    ) -> DocumentInfo:
        """
        Read a PDF document.
        
        Args:
            path: Path to PDF or PDF bytes
            pages: Specific pages to read (1-indexed), None for all
            extract_images: Whether to extract embedded images
            
        Returns:
            DocumentInfo with text and metadata
        """
        if not self._pdf_available:
            raise RuntimeError("PyMuPDF not available. Install with: pip install PyMuPDF")
        
        import fitz
        
        # Open PDF
        if isinstance(path, bytes):
            doc = fitz.open(stream=path, filetype="pdf")
            file_path = Path("<bytes>")
        else:
            path = Path(path)
            doc = fitz.open(str(path))
            file_path = path
        
        try:
            # Extract metadata
            info = DocumentInfo(
                path=file_path,
                doc_type=DocumentType.PDF,
                title=doc.metadata.get("title"),
                author=doc.metadata.get("author"),
                page_count=len(doc),
                metadata=dict(doc.metadata),
            )
            
            # Determine which pages to read
            if pages:
                page_indices = [p - 1 for p in pages if 0 < p <= len(doc)]
            else:
                page_indices = range(len(doc))
            
            # Extract text and images from each page
            all_text = []
            total_words = 0
            
            for idx in page_indices:
                page = doc[idx]
                
                # Extract text
                text = page.get_text()
                all_text.append(text)
                
                # Create page info
                page_info = DocumentPage(
                    number=idx + 1,
                    text=text,
                    width=page.rect.width,
                    height=page.rect.height,
                )
                total_words += page_info.word_count()
                
                # Extract images if requested
                if extract_images:
                    for img in page.get_images():
                        try:
                            xref = img[0]
                            base_image = doc.extract_image(xref)
                            page_info.images.append(base_image["image"])
                        except Exception as e:
                            logger.debug(f"Failed to extract image: {e}")
                
                info.pages.append(page_info)
            
            info.full_text = "\n\n".join(all_text)
            info.total_words = total_words
            
            return info
            
        finally:
            doc.close()
    
    def read_document(self, path: Union[str, Path]) -> DocumentInfo:
        """
        Read any supported document.
        
        Args:
            path: Path to document
            
        Returns:
            DocumentInfo with content
        """
        path = Path(path)
        doc_type = DocumentType.from_path(path)
        
        if doc_type == DocumentType.PDF:
            return self.read_pdf(path)
        elif doc_type == DocumentType.IMAGE:
            return self._read_image_document(path)
        elif doc_type == DocumentType.TEXT:
            return self._read_text_document(path)
        else:
            raise ValueError(f"Unsupported document type: {path.suffix}")
    
    def _read_image_document(self, path: Path) -> DocumentInfo:
        """Read an image as a document (with OCR if available)."""
        info = DocumentInfo(
            path=path,
            doc_type=DocumentType.IMAGE,
        )
        
        # Try OCR
        if self._ocr_available:
            result = self.ocr(path)
            info.full_text = result.text
            info.total_words = len(result.text.split())
            
            # Create single page
            info.pages.append(DocumentPage(
                number=1,
                text=result.text,
                images=[path.read_bytes()],
            ))
        else:
            # Just store the image reference
            info.pages.append(DocumentPage(
                number=1,
                text="[OCR not available]",
                images=[path.read_bytes()],
            ))
            info.full_text = "[Image document - OCR not available]"
        
        return info
    
    def _read_text_document(self, path: Path) -> DocumentInfo:
        """Read a text-based document."""
        text = path.read_text(encoding="utf-8", errors="ignore")
        
        info = DocumentInfo(
            path=path,
            doc_type=DocumentType.TEXT,
            full_text=text,
            total_words=len(text.split()),
        )
        
        info.pages.append(DocumentPage(
            number=1,
            text=text,
        ))
        
        return info
    
    def ocr(
        self,
        image: Union[str, Path, bytes],
        language: Optional[str] = None,
    ) -> OCRResult:
        """
        Perform OCR on an image.
        
        Args:
            image: Image path or bytes
            language: Tesseract language code (default: self.ocr_language)
            
        Returns:
            OCRResult with extracted text
        """
        if not self._ocr_available:
            # Try fallback with vision LLM
            if self.vision_llm:
                return self._ocr_with_vision(image)
            raise RuntimeError(
                "OCR not available. Install tesseract and pytesseract, "
                "or provide a VisionLLM for fallback."
            )
        
        import pytesseract
        from PIL import Image
        
        # Load image
        if isinstance(image, bytes):
            img = Image.open(io.BytesIO(image))
        else:
            img = Image.open(str(image))
        
        lang = language or self.ocr_language
        
        # Get text with confidence data
        try:
            data = pytesseract.image_to_data(
                img,
                lang=lang,
                output_type=pytesseract.Output.DICT,
            )
            
            # Extract text and calculate average confidence
            texts = []
            confidences = []
            boxes = []
            
            for i, text in enumerate(data["text"]):
                conf = data["conf"][i]
                if text.strip() and conf > 0:
                    texts.append(text)
                    confidences.append(conf)
                    boxes.append({
                        "text": text,
                        "x": data["left"][i],
                        "y": data["top"][i],
                        "width": data["width"][i],
                        "height": data["height"][i],
                        "confidence": conf,
                    })
            
            full_text = " ".join(texts)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            return OCRResult(
                text=full_text,
                confidence=avg_confidence / 100.0,  # Normalize to 0-1
                language=lang,
                boxes=boxes,
            )
            
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            # Try simple text extraction
            simple_text = pytesseract.image_to_string(img, lang=lang)
            return OCRResult(text=simple_text, language=lang)
    
    def _ocr_with_vision(self, image: Union[str, Path, bytes]) -> OCRResult:
        """OCR fallback using vision LLM."""
        if self.default_language == "tr":
            prompt = "Bu resimdeki tüm metni aynen oku ve yaz. Sadece metni yaz, başka açıklama ekleme."
        else:
            prompt = "Read and transcribe all text in this image exactly as it appears. Only output the text, no explanations."
        
        text = self.vision_llm.analyze_image(image, prompt)
        
        return OCRResult(
            text=text,
            confidence=0.7,  # Vision LLM confidence estimate
            language=self.default_language,
        )
    
    def summarize(
        self,
        path: Union[str, Path],
        max_length: int = 500,
    ) -> str:
        """
        Summarize a document.
        
        Args:
            path: Path to document
            max_length: Maximum summary length in words
            
        Returns:
            Summary text
        """
        doc = self.read_document(path)
        
        # If we have vision LLM and document has images, use it
        if self.vision_llm and doc.pages and any(p.images for p in doc.pages):
            return self._summarize_with_vision(doc)
        
        # Text-based summary
        return self._summarize_text(doc.full_text, max_length)
    
    def _summarize_text(self, text: str, max_length: int = 500) -> str:
        """Summarize text (simple extractive summary)."""
        if not text.strip():
            return "[Belge boş]" if self.default_language == "tr" else "[Empty document]"
        
        # Simple extractive summary - take first paragraphs
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        
        summary = []
        word_count = 0
        
        for para in paragraphs:
            words = para.split()
            if word_count + len(words) <= max_length:
                summary.append(para)
                word_count += len(words)
            else:
                # Add partial paragraph if we have room
                remaining = max_length - word_count
                if remaining > 20:
                    summary.append(" ".join(words[:remaining]) + "...")
                break
        
        return "\n\n".join(summary)
    
    def _summarize_with_vision(self, doc: DocumentInfo) -> str:
        """Summarize using vision LLM for documents with images."""
        # Get first page image if available
        first_image = None
        for page in doc.pages:
            if page.images:
                first_image = page.images[0]
                break
        
        if not first_image:
            return self._summarize_text(doc.full_text)
        
        if self.default_language == "tr":
            prompt = f"""Bu belgenin ilk sayfasının görüntüsü. Belge hakkında bilgi:
- Sayfa sayısı: {doc.page_count}
- Toplam kelime: {doc.total_words}
- Başlık: {doc.title or 'Bilinmiyor'}

Bu belgeyi özetle. Ana konular ve önemli noktaları belirt."""
        else:
            prompt = f"""This is the first page of a document. Document info:
- Pages: {doc.page_count}
- Word count: {doc.total_words}
- Title: {doc.title or 'Unknown'}

Summarize this document. Mention main topics and key points."""
        
        return self.vision_llm.analyze_image(first_image, prompt)
    
    def extract_tables(
        self,
        path: Union[str, Path],
        page: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Extract tables from a document.
        
        Args:
            path: Path to document (PDF or image)
            page: Specific page number (1-indexed), None for all
            
        Returns:
            List of extracted tables
        """
        path = Path(path)
        doc_type = DocumentType.from_path(path)
        
        if doc_type == DocumentType.PDF and self._pdf_available:
            return self._extract_tables_pdf(path, page)
        elif self.vision_llm:
            return self._extract_tables_vision(path, page)
        else:
            raise RuntimeError("Table extraction requires PyMuPDF or VisionLLM")
    
    def _extract_tables_pdf(
        self,
        path: Path,
        page: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Extract tables from PDF using PyMuPDF."""
        import fitz
        
        tables = []
        doc = fitz.open(str(path))
        
        try:
            pages_to_check = [page - 1] if page else range(len(doc))
            
            for idx in pages_to_check:
                if idx < 0 or idx >= len(doc):
                    continue
                    
                pg = doc[idx]
                
                # Try to find tables using tabs/structure
                # This is a simple heuristic - real table extraction is complex
                text = pg.get_text("dict")
                
                # Group text blocks that look like tables
                # (blocks with consistent column positions)
                blocks = text.get("blocks", [])
                
                # Very basic table detection
                for block in blocks:
                    if block.get("type") == 0:  # Text block
                        lines = block.get("lines", [])
                        if len(lines) > 1:
                            # Check if lines have similar structure
                            # (multiple spans at similar positions)
                            span_counts = [len(line.get("spans", [])) for line in lines]
                            if min(span_counts) >= 2 and max(span_counts) - min(span_counts) <= 1:
                                # Likely a table
                                table_data = []
                                for line in lines:
                                    row = [span.get("text", "") for span in line.get("spans", [])]
                                    table_data.append(row)
                                
                                tables.append({
                                    "page": idx + 1,
                                    "data": table_data,
                                    "rows": len(table_data),
                                    "cols": len(table_data[0]) if table_data else 0,
                                })
            
            return tables
            
        finally:
            doc.close()
    
    def _extract_tables_vision(
        self,
        path: Path,
        page: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Extract tables using vision LLM."""
        if self.default_language == "tr":
            prompt = """Bu belgede tablo var mı? Varsa tabloları JSON formatında çıkar:
[
    {
        "title": "tablo başlığı",
        "headers": ["sütun1", "sütun2", ...],
        "rows": [
            ["değer1", "değer2", ...],
            ...
        ]
    }
]

Tablo yoksa boş liste döndür: []"""
        else:
            prompt = """Are there tables in this document? If yes, extract them in JSON format."""
        
        response = self.vision_llm.analyze_image(path, prompt)
        
        try:
            # Parse JSON from response
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]
            
            import json
            tables = json.loads(response.strip())
            
            # Add page info
            for table in tables:
                table["page"] = page or 1
                if "rows" in table:
                    table["row_count"] = len(table["rows"])
                    if table["rows"]:
                        table["col_count"] = len(table["rows"][0])
            
            return tables
            
        except Exception as e:
            logger.warning(f"Could not parse table response: {e}")
            return []
    
    def search_text(
        self,
        path: Union[str, Path],
        query: str,
        case_sensitive: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Search for text in a document.
        
        Args:
            path: Path to document
            query: Search query
            case_sensitive: Case-sensitive search
            
        Returns:
            List of matches with page and context
        """
        doc = self.read_document(path)
        
        matches = []
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(re.escape(query), flags)
        
        for page in doc.pages:
            for match in pattern.finditer(page.text):
                # Get context around match
                start = max(0, match.start() - 50)
                end = min(len(page.text), match.end() + 50)
                context = page.text[start:end]
                
                # Mark the match
                context = context.replace(
                    match.group(),
                    f"**{match.group()}**"
                )
                
                matches.append({
                    "page": page.number,
                    "position": match.start(),
                    "match": match.group(),
                    "context": f"...{context}...",
                })
        
        return matches


# =============================================================================
# Mock Implementation for Testing
# =============================================================================


class MockDocumentAnalyzer(DocumentAnalyzer):
    """Mock Document Analyzer for testing."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mock_documents: Dict[str, DocumentInfo] = {}
        self._mock_ocr: Dict[str, OCRResult] = {}
    
    def add_mock_document(
        self,
        path: str,
        text: str,
        pages: int = 1,
        title: Optional[str] = None,
    ) -> None:
        """Add a mock document."""
        doc = DocumentInfo(
            path=Path(path),
            doc_type=DocumentType.from_path(path),
            title=title,
            page_count=pages,
            full_text=text,
            total_words=len(text.split()),
        )
        doc.pages = [
            DocumentPage(number=i + 1, text=text)
            for i in range(pages)
        ]
        self._mock_documents[path] = doc
    
    def add_mock_ocr(self, path: str, text: str, confidence: float = 0.9) -> None:
        """Add a mock OCR result."""
        self._mock_ocr[path] = OCRResult(
            text=text,
            confidence=confidence,
            language=self.ocr_language,
        )
    
    def read_document(self, path: Union[str, Path]) -> DocumentInfo:
        """Return mock document."""
        path_str = str(path)
        if path_str in self._mock_documents:
            return self._mock_documents[path_str]
        
        # Generate default mock document
        return DocumentInfo(
            path=Path(path),
            doc_type=DocumentType.from_path(path),
            title="Mock Document",
            page_count=1,
            full_text="Bu bir mock belgedir. Test amaçlı oluşturulmuştur.",
            total_words=7,
            pages=[DocumentPage(number=1, text="Bu bir mock belgedir.")],
        )
    
    def read_pdf(
        self,
        path: Union[str, Path, bytes],
        pages: Optional[List[int]] = None,
        extract_images: bool = False,
    ) -> DocumentInfo:
        """Return mock PDF document."""
        if isinstance(path, bytes):
            path = Path("<bytes>")
        return self.read_document(path)
    
    def ocr(
        self,
        image: Union[str, Path, bytes],
        language: Optional[str] = None,
    ) -> OCRResult:
        """Return mock OCR result."""
        if not isinstance(image, bytes):
            path_str = str(image)
            if path_str in self._mock_ocr:
                return self._mock_ocr[path_str]
        
        return OCRResult(
            text="Mock OCR metni. Bu resimden çıkarıldı.",
            confidence=0.95,
            language=language or self.ocr_language,
        )
