"""
Vision Tools for Agent Framework.

Provides vision-capable tools for the Bantz agent system.
These tools can be registered with the agent to enable visual understanding.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class ToolParameter:
    """Parameter definition for a vision tool."""
    
    name: str
    type: str  # string, integer, number, boolean, file
    description: str
    required: bool = True
    default: Any = None


@dataclass
class VisionTool:
    """
    Vision tool definition for agent integration.
    
    Follows the same pattern as Bantz's other tool definitions.
    """
    
    name: str
    description: str
    handler: Callable[..., Any]
    parameters: List[ToolParameter] = field(default_factory=list)
    category: str = "vision"
    requires_screen: bool = False
    requires_file: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for agent registration."""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default,
                }
                for p in self.parameters
            ],
        }
    
    def execute(self, **kwargs) -> Any:
        """Execute the tool handler."""
        return self.handler(**kwargs)


class VisionToolRegistry:
    """
    Registry of vision tools.
    
    Manages vision tools and provides them to the agent framework.
    """
    
    def __init__(self):
        self._tools: Dict[str, VisionTool] = {}
        self._vision_llm = None
        self._document_analyzer = None
        self._screen_understanding = None
    
    def configure(
        self,
        vision_llm: Optional[Any] = None,
        document_analyzer: Optional[Any] = None,
        screen_understanding: Optional[Any] = None,
    ) -> None:
        """Configure the registry with vision components."""
        self._vision_llm = vision_llm
        self._document_analyzer = document_analyzer
        self._screen_understanding = screen_understanding
    
    def register(self, tool: VisionTool) -> None:
        """Register a vision tool."""
        self._tools[tool.name] = tool
        logger.debug(f"Registered vision tool: {tool.name}")
    
    def get(self, name: str) -> Optional[VisionTool]:
        """Get a tool by name."""
        return self._tools.get(name)
    
    def list_tools(self) -> List[VisionTool]:
        """List all registered tools."""
        return list(self._tools.values())
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get all tool definitions for agent."""
        return [tool.to_dict() for tool in self._tools.values()]
    
    def execute(self, name: str, **kwargs) -> Any:
        """Execute a tool by name."""
        tool = self.get(name)
        if not tool:
            raise ValueError(f"Unknown vision tool: {name}")
        return tool.execute(**kwargs)


# =============================================================================
# Built-in Vision Tools
# =============================================================================


def create_analyze_screen_tool(
    vision_llm: Any = None,
    screen_understanding: Any = None,
) -> VisionTool:
    """Create the analyze_screen tool."""
    
    def handler(
        question: Optional[str] = None,
        detail_level: str = "normal",
    ) -> Dict[str, Any]:
        """Analyze what's currently on screen."""
        if screen_understanding:
            analysis = screen_understanding.what_is_on_screen(
                detail_level=detail_level
            )
            return {
                "description": analysis.description,
                "active_window": analysis.active_window,
                "elements": [e.to_dict() for e in analysis.elements],
                "errors": analysis.errors,
            }
        elif vision_llm:
            result = vision_llm.analyze_screenshot(question)
            return {"description": result}
        else:
            raise RuntimeError("No vision component configured")
    
    return VisionTool(
        name="analyze_screen",
        description="Ekranı analiz et ve ne olduğunu açıkla. "
                    "Hangi uygulama açık, ne görünüyor, hatalar var mı?",
        handler=handler,
        parameters=[
            ToolParameter(
                name="question",
                type="string",
                description="Ekran hakkında soru (opsiyonel)",
                required=False,
            ),
            ToolParameter(
                name="detail_level",
                type="string",
                description="Detay seviyesi: minimal, normal, detailed",
                required=False,
                default="normal",
            ),
        ],
        requires_screen=True,
    )


def create_find_element_tool(
    screen_understanding: Any = None,
    vision_llm: Any = None,
) -> VisionTool:
    """Create the find_element tool."""
    
    def handler(
        description: str,
        element_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Find a UI element by description."""
        if screen_understanding:
            element = screen_understanding.find_element(
                description=description,
                element_type=element_type,
            )
            if element:
                return {
                    "found": True,
                    "element": element.to_dict(),
                }
            return {"found": False, "message": f"'{description}' bulunamadı"}
        elif vision_llm:
            from bantz.vision.capture import capture_screen
            capture = capture_screen()
            result = vision_llm.find_element(capture.image_bytes, description)
            return result or {"found": False}
        else:
            raise RuntimeError("No vision component configured")
    
    return VisionTool(
        name="find_element",
        description="Ekranda bir UI elementi bul (buton, input, link vb.). "
                    "Elementin koordinatlarını döndürür.",
        handler=handler,
        parameters=[
            ToolParameter(
                name="description",
                type="string",
                description="Aranacak element açıklaması (örn: 'kaydet butonu', 'arama kutusu')",
                required=True,
            ),
            ToolParameter(
                name="element_type",
                type="string",
                description="Element tipi filtresi: button, input, link, checkbox vb.",
                required=False,
            ),
        ],
        requires_screen=True,
    )


def create_read_document_tool(
    document_analyzer: Any = None,
) -> VisionTool:
    """Create the read_document tool."""
    
    def handler(
        path: str,
        pages: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """Read and analyze a document."""
        if not document_analyzer:
            raise RuntimeError("DocumentAnalyzer not configured")
        
        doc = document_analyzer.read_document(path)
        return {
            "path": str(doc.path),
            "type": doc.doc_type.value,
            "title": doc.title,
            "page_count": doc.page_count,
            "word_count": doc.total_words,
            "text": doc.full_text[:5000] if len(doc.full_text) > 5000 else doc.full_text,
            "truncated": len(doc.full_text) > 5000,
        }
    
    return VisionTool(
        name="read_document",
        description="PDF veya metin belgesi oku. İçeriği ve meta bilgileri döndürür.",
        handler=handler,
        parameters=[
            ToolParameter(
                name="path",
                type="file",
                description="Belge dosya yolu",
                required=True,
            ),
            ToolParameter(
                name="pages",
                type="array",
                description="Okunacak sayfa numaraları (1-indexed, opsiyonel)",
                required=False,
            ),
        ],
        requires_file=True,
    )


def create_summarize_document_tool(
    document_analyzer: Any = None,
) -> VisionTool:
    """Create the summarize_document tool."""
    
    def handler(
        path: str,
        max_length: int = 500,
    ) -> str:
        """Summarize a document."""
        if not document_analyzer:
            raise RuntimeError("DocumentAnalyzer not configured")
        
        return document_analyzer.summarize(path, max_length=max_length)
    
    return VisionTool(
        name="summarize_document",
        description="Belgeyi özetle. PDF, resim veya metin belgesi olabilir.",
        handler=handler,
        parameters=[
            ToolParameter(
                name="path",
                type="file",
                description="Belge dosya yolu",
                required=True,
            ),
            ToolParameter(
                name="max_length",
                type="integer",
                description="Maksimum özet uzunluğu (kelime)",
                required=False,
                default=500,
            ),
        ],
        requires_file=True,
    )


def create_ocr_tool(
    document_analyzer: Any = None,
) -> VisionTool:
    """Create the OCR tool."""
    
    def handler(
        path: Optional[str] = None,
        capture_screen: bool = False,
    ) -> Dict[str, Any]:
        """Extract text from image using OCR."""
        if not document_analyzer:
            raise RuntimeError("DocumentAnalyzer not configured")
        
        if capture_screen:
            from bantz.vision.capture import capture_screen as do_capture
            capture = do_capture()
            image = capture.image_bytes
        elif path:
            image = path
        else:
            raise ValueError("Either path or capture_screen must be provided")
        
        result = document_analyzer.ocr(image)
        return {
            "text": result.text,
            "confidence": result.confidence,
            "language": result.language,
        }
    
    return VisionTool(
        name="ocr",
        description="Resimden metin çıkar (OCR). Ekran görüntüsü veya dosyadan.",
        handler=handler,
        parameters=[
            ToolParameter(
                name="path",
                type="file",
                description="Resim dosya yolu",
                required=False,
            ),
            ToolParameter(
                name="capture_screen",
                type="boolean",
                description="Ekranı yakala ve OCR yap",
                required=False,
                default=False,
            ),
        ],
    )


def create_vision_ocr_tool() -> VisionTool:
    """Create the Google Vision OCR tool."""

    def handler(
        image_path: str,
    ) -> Dict[str, Any]:
        """Extract text using Google Cloud Vision API."""
        from bantz.vision.google_vision import vision_ocr

        text = vision_ocr(image_path)
        return {"text": text}

    return VisionTool(
        name="vision_ocr",
        description="Google Vision ile OCR yap. PNG/JPG/PDF destekler.",
        handler=handler,
        parameters=[
            ToolParameter(
                name="image_path",
                type="file",
                description="Resim/PDF dosya yolu",
                required=True,
            ),
        ],
        requires_file=True,
    )


def create_vision_describe_tool() -> VisionTool:
    """Create the Google Vision describe tool (labels + logos + faces)."""

    def handler(
        image_path: str,
        max_labels: int = 10,
        include_faces: bool = True,
        include_logos: bool = True,
    ) -> Dict[str, Any]:
        from bantz.vision.google_vision import get_default_google_vision_client

        client = get_default_google_vision_client()
        return client.describe_path(
            image_path,
            max_labels=max_labels,
            include_faces=include_faces,
            include_logos=include_logos,
        )

    return VisionTool(
        name="vision_describe",
        description="Google Vision ile görseli etiketle (labels) ve opsiyonel logo/yüz tespiti yap.",
        handler=handler,
        parameters=[
            ToolParameter(
                name="image_path",
                type="file",
                description="Resim/PDF dosya yolu",
                required=True,
            ),
            ToolParameter(
                name="max_labels",
                type="integer",
                description="Maksimum label sayısı",
                required=False,
                default=10,
            ),
            ToolParameter(
                name="include_faces",
                type="boolean",
                description="Yüz tespiti dahil et",
                required=False,
                default=True,
            ),
            ToolParameter(
                name="include_logos",
                type="boolean",
                description="Logo tespiti dahil et",
                required=False,
                default=True,
            ),
        ],
        requires_file=True,
    )


def create_understand_error_tool(
    screen_understanding: Any = None,
    vision_llm: Any = None,
) -> VisionTool:
    """Create the understand_error tool."""
    
    def handler() -> Dict[str, Any]:
        """Understand error message on screen."""
        if screen_understanding:
            return screen_understanding.understand_error()
        elif vision_llm:
            result = vision_llm.understand_error()
            return {"description": result}
        else:
            raise RuntimeError("No vision component configured")
    
    return VisionTool(
        name="understand_error",
        description="Ekrandaki hata mesajını anla ve çözüm önerisi ver.",
        handler=handler,
        parameters=[],
        requires_screen=True,
    )


def create_capture_screenshot_tool() -> VisionTool:
    """Create the capture_screenshot tool."""
    
    def handler(
        region: Optional[List[int]] = None,
        save_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Capture a screenshot."""
        from bantz.vision.capture import capture_screen, capture_region
        
        if region and len(region) == 4:
            capture = capture_region(*region)
        else:
            capture = capture_screen()
        
        result = {
            "width": capture.width,
            "height": capture.height,
            "format": capture.format,
        }
        
        if save_path:
            capture.save(save_path)
            result["saved_to"] = save_path
        else:
            result["base64"] = capture.to_base64()[:100] + "..."
            result["base64_full_available"] = True
        
        return result
    
    return VisionTool(
        name="capture_screenshot",
        description="Ekran görüntüsü al. Tüm ekran veya belirli bölge.",
        handler=handler,
        parameters=[
            ToolParameter(
                name="region",
                type="array",
                description="Yakalanacak bölge [x, y, genişlik, yükseklik] (opsiyonel)",
                required=False,
            ),
            ToolParameter(
                name="save_path",
                type="file",
                description="Kayıt yolu (opsiyonel)",
                required=False,
            ),
        ],
        requires_screen=True,
    )


def create_compare_images_tool(
    vision_llm: Any = None,
) -> VisionTool:
    """Create the compare_images tool."""
    
    def handler(
        image1: str,
        image2: str,
        focus: Optional[str] = None,
    ) -> str:
        """Compare two images."""
        if not vision_llm:
            raise RuntimeError("VisionLLM not configured")
        
        return vision_llm.compare_images(image1, image2, focus=focus)
    
    return VisionTool(
        name="compare_images",
        description="İki resmi karşılaştır ve farklılıkları açıkla.",
        handler=handler,
        parameters=[
            ToolParameter(
                name="image1",
                type="file",
                description="İlk resim yolu",
                required=True,
            ),
            ToolParameter(
                name="image2",
                type="file",
                description="İkinci resim yolu",
                required=True,
            ),
            ToolParameter(
                name="focus",
                type="string",
                description="Odaklanılacak özellik (opsiyonel)",
                required=False,
            ),
        ],
    )


def create_describe_image_tool(
    vision_llm: Any = None,
) -> VisionTool:
    """Create the describe_image tool."""
    
    def handler(
        path: str,
        question: Optional[str] = None,
    ) -> str:
        """Describe an image."""
        if not vision_llm:
            raise RuntimeError("VisionLLM not configured")
        
        return vision_llm.analyze_image(path, question)
    
    return VisionTool(
        name="describe_image",
        description="Resmi açıkla veya resim hakkında soru sor.",
        handler=handler,
        parameters=[
            ToolParameter(
                name="path",
                type="file",
                description="Resim dosya yolu",
                required=True,
            ),
            ToolParameter(
                name="question",
                type="string",
                description="Resim hakkında soru (opsiyonel)",
                required=False,
            ),
        ],
        requires_file=True,
    )


def create_extract_tables_tool(
    document_analyzer: Any = None,
) -> VisionTool:
    """Create the extract_tables tool."""
    
    def handler(
        path: str,
        page: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Extract tables from document."""
        if not document_analyzer:
            raise RuntimeError("DocumentAnalyzer not configured")
        
        return document_analyzer.extract_tables(path, page=page)
    
    return VisionTool(
        name="extract_tables",
        description="Belgeden tabloları çıkar. PDF veya resim olabilir.",
        handler=handler,
        parameters=[
            ToolParameter(
                name="path",
                type="file",
                description="Belge dosya yolu",
                required=True,
            ),
            ToolParameter(
                name="page",
                type="integer",
                description="Sayfa numarası (1-indexed, opsiyonel)",
                required=False,
            ),
        ],
        requires_file=True,
    )


def create_read_screen_text_tool(
    screen_understanding: Any = None,
) -> VisionTool:
    """Create the read_screen_text tool."""
    
    def handler(
        region: Optional[List[int]] = None,
    ) -> str:
        """Read text from screen."""
        if not screen_understanding:
            raise RuntimeError("ScreenUnderstanding not configured")
        
        region_tuple = tuple(region) if region and len(region) == 4 else None
        return screen_understanding.read_text(region=region_tuple)
    
    return VisionTool(
        name="read_screen_text",
        description="Ekrandaki metni oku. Tüm ekran veya belirli bölge.",
        handler=handler,
        parameters=[
            ToolParameter(
                name="region",
                type="array",
                description="Bölge [x, y, genişlik, yükseklik] (opsiyonel)",
                required=False,
            ),
        ],
        requires_screen=True,
    )


# =============================================================================
# Tool Factory Functions
# =============================================================================


def get_vision_tools(
    vision_llm: Optional[Any] = None,
    document_analyzer: Optional[Any] = None,
    screen_understanding: Optional[Any] = None,
) -> List[VisionTool]:
    """
    Get all vision tools with configured components.
    
    Args:
        vision_llm: VisionLLM instance
        document_analyzer: DocumentAnalyzer instance
        screen_understanding: ScreenUnderstanding instance
        
    Returns:
        List of configured VisionTools
    """
    tools = []
    
    # Screen analysis tools
    if vision_llm or screen_understanding:
        tools.append(create_analyze_screen_tool(vision_llm, screen_understanding))
        tools.append(create_find_element_tool(screen_understanding, vision_llm))
        tools.append(create_understand_error_tool(screen_understanding, vision_llm))
    
    # Document tools
    if document_analyzer:
        tools.append(create_read_document_tool(document_analyzer))
        tools.append(create_summarize_document_tool(document_analyzer))
        tools.append(create_ocr_tool(document_analyzer))
        tools.append(create_extract_tables_tool(document_analyzer))

    # Google Vision tools (call-time configured via env vars)
    tools.append(create_vision_ocr_tool())
    tools.append(create_vision_describe_tool())
    
    # Image tools
    if vision_llm:
        tools.append(create_describe_image_tool(vision_llm))
        tools.append(create_compare_images_tool(vision_llm))
    
    # Screen capture (always available)
    tools.append(create_capture_screenshot_tool())
    
    # Screen text reading
    if screen_understanding:
        tools.append(create_read_screen_text_tool(screen_understanding))
    
    return tools


def create_vision_registry(
    vision_llm: Optional[Any] = None,
    document_analyzer: Optional[Any] = None,
    screen_understanding: Optional[Any] = None,
) -> VisionToolRegistry:
    """
    Create a configured VisionToolRegistry.
    
    Args:
        vision_llm: VisionLLM instance
        document_analyzer: DocumentAnalyzer instance
        screen_understanding: ScreenUnderstanding instance
        
    Returns:
        Configured VisionToolRegistry
    """
    registry = VisionToolRegistry()
    registry.configure(
        vision_llm=vision_llm,
        document_analyzer=document_analyzer,
        screen_understanding=screen_understanding,
    )
    
    # Register all tools
    for tool in get_vision_tools(
        vision_llm=vision_llm,
        document_analyzer=document_analyzer,
        screen_understanding=screen_understanding,
    ):
        registry.register(tool)
    
    return registry


# Convenience exports
VISION_TOOLS = [
    "analyze_screen",
    "find_element",
    "read_document",
    "summarize_document",
    "ocr",
    "vision_ocr",
    "vision_describe",
    "understand_error",
    "capture_screenshot",
    "compare_images",
    "describe_image",
    "extract_tables",
    "read_screen_text",
]
