"""
Bantz Vision Module.

Multi-modal input capabilities:
- Screen capture and analysis
- Document understanding (PDF, images)
- Vision LLM integration (OpenAI-compatible API via vLLM)
- OCR text extraction
"""

from bantz.vision.capture import (
    capture_screen,
    capture_region,
    capture_window,
    capture_active_window,
    get_screen_info,
    ScreenInfo,
    CaptureResult,
    MockScreenCapture,
)
from bantz.vision.llm import (
    VisionLLM,
    VisionMessage,
    VisionResponse,
    VisionModel,
    ImageContent,
    MockVisionLLM,
)
from bantz.vision.document import (
    DocumentAnalyzer,
    DocumentType,
    DocumentInfo,
    DocumentPage,
    OCRResult,
    MockDocumentAnalyzer,
)
from bantz.vision.google_vision import (
    GoogleVisionClient,
    GoogleVisionError,
    vision_ocr,
    vision_describe,
)
from bantz.vision.screen import (
    ScreenUnderstanding,
    ScreenAnalysis,
    UIElement,
    ElementType,
    MockScreenUnderstanding,
)
from bantz.vision.tools import (
    get_vision_tools,
    create_vision_registry,
    VisionToolRegistry,
    VisionTool,
    ToolParameter,
    VISION_TOOLS,
)

__all__ = [
    # Capture
    "capture_screen",
    "capture_region",
    "capture_window",
    "capture_active_window",
    "get_screen_info",
    "ScreenInfo",
    "CaptureResult",
    "MockScreenCapture",
    # LLM
    "VisionLLM",
    "VisionMessage",
    "VisionResponse",
    "VisionModel",
    "ImageContent",
    "MockVisionLLM",
    # Document
    "DocumentAnalyzer",
    "DocumentType",
    "DocumentInfo",
    "DocumentPage",
    "OCRResult",
    "MockDocumentAnalyzer",
    # Google Vision
    "GoogleVisionClient",
    "GoogleVisionError",
    "vision_ocr",
    "vision_describe",
    # Screen
    "ScreenUnderstanding",
    "ScreenAnalysis",
    "UIElement",
    "ElementType",
    "MockScreenUnderstanding",
    # Tools
    "get_vision_tools",
    "create_vision_registry",
    "VisionToolRegistry",
    "VisionTool",
    "ToolParameter",
    "VISION_TOOLS",
]
