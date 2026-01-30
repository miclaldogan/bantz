"""
Tests for Bantz Vision Module.

Comprehensive tests for:
- Screen capture
- Vision LLM
- Document analysis
- Screen understanding
- Vision tools
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import io
import json
import base64


# =============================================================================
# Capture Tests
# =============================================================================


class TestCaptureResult:
    """Tests for CaptureResult dataclass."""
    
    def test_capture_result_creation(self):
        """Test CaptureResult creation."""
        from bantz.vision.capture import CaptureResult
        
        data = b"fake image data"
        result = CaptureResult(
            image_bytes=data,
            width=1920,
            height=1080,
            format="png",
        )
        
        assert result.image_bytes == data
        assert result.width == 1920
        assert result.height == 1080
        assert result.format == "png"
    
    def test_capture_result_to_base64(self):
        """Test base64 encoding."""
        from bantz.vision.capture import CaptureResult
        
        data = b"test data"
        result = CaptureResult(
            image_bytes=data,
            width=100,
            height=100,
            format="png",
        )
        
        encoded = result.to_base64()
        assert encoded == base64.b64encode(data).decode("utf-8")
    
    def test_capture_result_to_data_uri(self):
        """Test data URI generation."""
        from bantz.vision.capture import CaptureResult
        
        data = b"test data"
        result = CaptureResult(
            image_bytes=data,
            width=100,
            height=100,
            format="png",
        )
        
        uri = result.to_data_uri()
        assert uri.startswith("data:image/png;base64,")
        assert base64.b64encode(data).decode("utf-8") in uri
    
    def test_capture_result_save(self, tmp_path):
        """Test saving to file."""
        from bantz.vision.capture import CaptureResult
        
        data = b"test image data"
        result = CaptureResult(
            image_bytes=data,
            width=100,
            height=100,
            format="png",
        )
        
        save_path = tmp_path / "test.png"
        result.save(str(save_path))
        
        assert save_path.exists()
        assert save_path.read_bytes() == data


class TestScreenInfo:
    """Tests for ScreenInfo dataclass."""
    
    def test_screen_info_creation(self):
        """Test ScreenInfo creation."""
        from bantz.vision.capture import ScreenInfo
        
        info = ScreenInfo(
            index=0,
            width=1920,
            height=1080,
            x=0,
            y=0,
            is_primary=True,
            name="HDMI-1",
        )
        
        assert info.index == 0
        assert info.width == 1920
        assert info.height == 1080
        assert info.is_primary is True
        assert info.name == "HDMI-1"


class TestMockScreenCapture:
    """Tests for MockScreenCapture."""
    
    def test_mock_capture_screen(self):
        """Test mock screen capture."""
        from bantz.vision.capture import MockScreenCapture
        
        mock = MockScreenCapture()
        result = mock.capture_screen()
        
        assert result.width == 1920
        assert result.height == 1080
        assert len(result.image_bytes) > 0
    
    def test_mock_capture_region(self):
        """Test mock region capture."""
        from bantz.vision.capture import MockScreenCapture
        
        mock = MockScreenCapture()
        result = mock.capture_region(100, 100, 200, 150)
        
        assert result.width == 200
        assert result.height == 150
    
    def test_mock_get_screen_info(self):
        """Test mock screen info."""
        from bantz.vision.capture import MockScreenCapture
        
        mock = MockScreenCapture()
        info = mock.get_screen_info()
        
        assert len(info) >= 1
        assert info[0].is_primary is True


# =============================================================================
# Vision LLM Tests
# =============================================================================


class TestImageContent:
    """Tests for ImageContent dataclass."""
    
    def test_from_bytes(self):
        """Test creating from bytes."""
        from bantz.vision.llm import ImageContent
        
        data = b"fake image"
        content = ImageContent.from_bytes(data)
        
        assert content.data == data
        assert content.to_base64() == base64.b64encode(data).decode("utf-8")
    
    def test_from_file(self, tmp_path):
        """Test creating from file."""
        from bantz.vision.llm import ImageContent
        
        file_path = tmp_path / "test.png"
        file_path.write_bytes(b"image data")
        
        content = ImageContent.from_file(file_path)
        assert content.to_base64() == base64.b64encode(b"image data").decode("utf-8")
    
    def test_from_base64(self):
        """Test creating from base64."""
        from bantz.vision.llm import ImageContent
        
        # Create a longer base64 string that meets the detection threshold
        original_data = b"test data that is long enough to be detected as base64" * 5
        b64 = base64.b64encode(original_data).decode("utf-8")
        content = ImageContent.from_base64(b64)
        
        # The from_base64 stores the base64 string, to_base64 should return it as-is
        assert content.to_base64() == b64


class TestVisionMessage:
    """Tests for VisionMessage."""
    
    def test_create_message(self):
        """Test creating a vision message."""
        from bantz.vision.llm import VisionMessage
        
        msg = VisionMessage(text="What's in this image?")
        assert msg.text == "What's in this image?"
        assert msg.role == "user"
        assert len(msg.images) == 0
    
    def test_add_image(self):
        """Test adding image to message."""
        from bantz.vision.llm import VisionMessage
        
        msg = VisionMessage(text="Describe this")
        msg.add_image(b"image bytes")
        
        assert len(msg.images) == 1
    
    def test_to_ollama_format(self):
        """Test Ollama format conversion."""
        from bantz.vision.llm import VisionMessage
        
        msg = VisionMessage(text="Test", role="user")
        msg.add_image(b"data")
        
        formatted = msg.to_ollama_format()
        assert formatted["role"] == "user"
        assert formatted["content"] == "Test"
        assert "images" in formatted
        assert len(formatted["images"]) == 1


class TestVisionModel:
    """Tests for VisionModel enum."""
    
    def test_vision_models(self):
        """Test vision model values."""
        from bantz.vision.llm import VisionModel
        
        assert VisionModel.LLAVA.value == "llava"
        assert VisionModel.LLAVA_13B.value == "llava:13b"
        assert VisionModel.default() == VisionModel.LLAVA


class TestMockVisionLLM:
    """Tests for MockVisionLLM."""
    
    def test_analyze_image(self):
        """Test mock image analysis."""
        from bantz.vision.llm import MockVisionLLM
        
        mock = MockVisionLLM()
        result = mock.analyze_image(b"fake image", "Ne görüyorsun?")
        
        assert len(result) > 0
        assert isinstance(result, str)
    
    def test_set_response(self):
        """Test setting mock response."""
        from bantz.vision.llm import MockVisionLLM
        
        mock = MockVisionLLM()
        mock.set_response("test", "Custom response")
        
        result = mock.analyze_image(b"image", "This is a test")
        assert "Custom response" in result
    
    def test_describe_ui(self):
        """Test UI description."""
        from bantz.vision.llm import MockVisionLLM
        
        mock = MockVisionLLM()
        result = mock.describe_ui(b"screenshot")
        
        # Should return JSON-like structure
        assert "elements" in result.lower() or "{" in result
    
    def test_find_element(self):
        """Test element finding."""
        from bantz.vision.llm import MockVisionLLM
        
        mock = MockVisionLLM()
        result = mock.find_element(b"screenshot", "OK button")
        
        assert result is not None
        assert "found" in result
    
    def test_is_available(self):
        """Test availability check."""
        from bantz.vision.llm import MockVisionLLM
        
        mock = MockVisionLLM()
        assert mock.is_available() is True
    
    def test_chat_conversation(self):
        """Test chat conversation."""
        from bantz.vision.llm import MockVisionLLM
        
        mock = MockVisionLLM()
        
        response1 = mock.chat("What's on screen?")
        response2 = mock.chat("Tell me more")
        
        assert mock._query_count == 2
        assert len(mock._conversation) == 4  # 2 user + 2 assistant
    
    def test_clear_conversation(self):
        """Test clearing conversation."""
        from bantz.vision.llm import MockVisionLLM
        
        mock = MockVisionLLM()
        mock.chat("test")
        mock.clear_conversation()
        
        assert len(mock._conversation) == 0


class TestVisionLLM:
    """Tests for VisionLLM class."""
    
    def test_init_default(self):
        """Test default initialization."""
        from bantz.vision.llm import VisionLLM
        
        llm = VisionLLM()
        assert llm.model == "llava"
        assert "11434" in llm.base_url
    
    def test_init_custom_model(self):
        """Test custom model initialization."""
        from bantz.vision.llm import VisionLLM, VisionModel
        
        llm = VisionLLM(model=VisionModel.LLAVA_13B)
        assert llm.model == "llava:13b"
    
    def test_init_string_model(self):
        """Test string model initialization."""
        from bantz.vision.llm import VisionLLM
        
        llm = VisionLLM(model="custom-model")
        assert llm.model == "custom-model"


# =============================================================================
# Document Analyzer Tests
# =============================================================================


class TestDocumentType:
    """Tests for DocumentType enum."""
    
    def test_from_path_pdf(self):
        """Test PDF detection."""
        from bantz.vision.document import DocumentType
        
        assert DocumentType.from_path("file.pdf") == DocumentType.PDF
        assert DocumentType.from_path("/path/to/doc.PDF") == DocumentType.PDF
    
    def test_from_path_image(self):
        """Test image detection."""
        from bantz.vision.document import DocumentType
        
        assert DocumentType.from_path("image.png") == DocumentType.IMAGE
        assert DocumentType.from_path("photo.jpg") == DocumentType.IMAGE
        assert DocumentType.from_path("pic.jpeg") == DocumentType.IMAGE
    
    def test_from_path_text(self):
        """Test text detection."""
        from bantz.vision.document import DocumentType
        
        assert DocumentType.from_path("readme.txt") == DocumentType.TEXT
        assert DocumentType.from_path("doc.md") == DocumentType.TEXT
    
    def test_from_path_unknown(self):
        """Test unknown type."""
        from bantz.vision.document import DocumentType
        
        assert DocumentType.from_path("file.xyz") == DocumentType.UNKNOWN


class TestDocumentPage:
    """Tests for DocumentPage dataclass."""
    
    def test_page_creation(self):
        """Test page creation."""
        from bantz.vision.document import DocumentPage
        
        page = DocumentPage(
            number=1,
            text="Hello world",
        )
        
        assert page.number == 1
        assert page.text == "Hello world"
        assert page.word_count() == 2
        assert page.has_images() is False
    
    def test_page_with_images(self):
        """Test page with images."""
        from bantz.vision.document import DocumentPage
        
        page = DocumentPage(
            number=1,
            text="Text",
            images=[b"img1", b"img2"],
        )
        
        assert page.has_images() is True
        assert len(page.images) == 2


class TestDocumentInfo:
    """Tests for DocumentInfo dataclass."""
    
    def test_document_info_creation(self):
        """Test document info creation."""
        from bantz.vision.document import DocumentInfo, DocumentType
        
        doc = DocumentInfo(
            path=Path("/test/doc.pdf"),
            doc_type=DocumentType.PDF,
            title="Test Document",
            page_count=10,
            total_words=1000,
        )
        
        assert doc.title == "Test Document"
        assert doc.page_count == 10
        assert doc.total_words == 1000


class TestOCRResult:
    """Tests for OCRResult dataclass."""
    
    def test_ocr_result_creation(self):
        """Test OCR result creation."""
        from bantz.vision.document import OCRResult
        
        result = OCRResult(
            text="Extracted text",
            confidence=0.95,
            language="tur",
        )
        
        assert result.text == "Extracted text"
        assert result.confidence == 0.95
        assert result.language == "tur"


class TestMockDocumentAnalyzer:
    """Tests for MockDocumentAnalyzer."""
    
    def test_read_document(self):
        """Test mock document reading."""
        from bantz.vision.document import MockDocumentAnalyzer
        
        analyzer = MockDocumentAnalyzer()
        doc = analyzer.read_document("/test/doc.pdf")
        
        assert doc is not None
        assert doc.doc_type.value == "pdf"
    
    def test_add_mock_document(self):
        """Test adding mock document."""
        from bantz.vision.document import MockDocumentAnalyzer
        
        analyzer = MockDocumentAnalyzer()
        analyzer.add_mock_document(
            "/test/custom.pdf",
            "Custom content",
            pages=5,
            title="Custom Doc",
        )
        
        doc = analyzer.read_document("/test/custom.pdf")
        assert doc.title == "Custom Doc"
        assert doc.page_count == 5
        assert doc.full_text == "Custom content"
    
    def test_ocr(self):
        """Test mock OCR."""
        from bantz.vision.document import MockDocumentAnalyzer
        
        analyzer = MockDocumentAnalyzer()
        result = analyzer.ocr("/test/image.png")
        
        assert len(result.text) > 0
        assert result.confidence > 0
    
    def test_add_mock_ocr(self):
        """Test adding mock OCR result."""
        from bantz.vision.document import MockDocumentAnalyzer
        
        analyzer = MockDocumentAnalyzer()
        analyzer.add_mock_ocr("/test/image.png", "Custom OCR text", 0.99)
        
        result = analyzer.ocr("/test/image.png")
        assert result.text == "Custom OCR text"
        assert result.confidence == 0.99


class TestDocumentAnalyzer:
    """Tests for DocumentAnalyzer class."""
    
    def test_init(self):
        """Test initialization."""
        from bantz.vision.document import DocumentAnalyzer
        
        analyzer = DocumentAnalyzer(default_language="tr")
        assert analyzer.default_language == "tr"
    
    def test_summarize_text(self):
        """Test text summarization."""
        from bantz.vision.document import DocumentAnalyzer
        
        analyzer = DocumentAnalyzer()
        
        long_text = "Bu bir test paragrafıdır. " * 100
        summary = analyzer._summarize_text(long_text, max_length=50)
        
        assert len(summary.split()) <= 60  # Allow some margin
    
    def test_search_text(self, tmp_path):
        """Test text search in document."""
        from bantz.vision.document import DocumentAnalyzer, MockDocumentAnalyzer
        
        analyzer = MockDocumentAnalyzer()
        analyzer.add_mock_document(
            "/test/doc.txt",
            "The quick brown fox jumps over the lazy dog."
        )
        
        matches = analyzer.search_text("/test/doc.txt", "fox")
        
        assert len(matches) == 1
        assert matches[0]["match"] == "fox"


# =============================================================================
# Screen Understanding Tests
# =============================================================================


class TestElementType:
    """Tests for ElementType enum."""
    
    def test_from_string(self):
        """Test string conversion."""
        from bantz.vision.screen import ElementType
        
        assert ElementType.from_string("button") == ElementType.BUTTON
        assert ElementType.from_string("text_field") == ElementType.TEXT_FIELD
        assert ElementType.from_string("text-field") == ElementType.TEXT_FIELD
        assert ElementType.from_string("unknown_type") == ElementType.UNKNOWN


class TestUIElement:
    """Tests for UIElement dataclass."""
    
    def test_element_creation(self):
        """Test element creation."""
        from bantz.vision.screen import UIElement, ElementType
        
        elem = UIElement(
            element_type=ElementType.BUTTON,
            text="Submit",
            x=100,
            y=200,
            width=80,
            height=30,
        )
        
        assert elem.text == "Submit"
        assert elem.center == (140, 215)
    
    def test_contains_point(self):
        """Test point containment."""
        from bantz.vision.screen import UIElement, ElementType
        
        elem = UIElement(
            element_type=ElementType.BUTTON,
            text="Test",
            x=100,
            y=100,
            width=50,
            height=30,
        )
        
        assert elem.contains_point(110, 110) is True
        assert elem.contains_point(200, 200) is False
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        from bantz.vision.screen import UIElement, ElementType
        
        elem = UIElement(
            element_type=ElementType.LINK,
            text="Click here",
            x=0,
            y=0,
            width=100,
            height=20,
        )
        
        d = elem.to_dict()
        assert d["type"] == "link"
        assert d["text"] == "Click here"
        assert "center" in d


class TestScreenAnalysis:
    """Tests for ScreenAnalysis dataclass."""
    
    def test_find_by_text(self):
        """Test finding elements by text."""
        from bantz.vision.screen import ScreenAnalysis, UIElement, ElementType
        
        analysis = ScreenAnalysis(
            description="Test screen",
            elements=[
                UIElement(ElementType.BUTTON, "Save", 0, 0),
                UIElement(ElementType.BUTTON, "Save As", 100, 0),
                UIElement(ElementType.BUTTON, "Cancel", 200, 0),
            ],
        )
        
        results = analysis.find_by_text("Save")
        assert len(results) == 2
        
        results = analysis.find_by_text("Save", partial=False)
        assert len(results) == 1
    
    def test_find_by_type(self):
        """Test finding elements by type."""
        from bantz.vision.screen import ScreenAnalysis, UIElement, ElementType
        
        analysis = ScreenAnalysis(
            description="Test",
            elements=[
                UIElement(ElementType.BUTTON, "Submit", 0, 0),
                UIElement(ElementType.TEXT_FIELD, "", 0, 50),
                UIElement(ElementType.LINK, "Help", 0, 100),
            ],
        )
        
        buttons = analysis.get_buttons()
        assert len(buttons) == 1
        
        fields = analysis.get_text_fields()
        assert len(fields) == 1


class TestMockScreenUnderstanding:
    """Tests for MockScreenUnderstanding."""
    
    def test_what_is_on_screen(self):
        """Test mock screen analysis."""
        from bantz.vision.screen import MockScreenUnderstanding
        
        mock = MockScreenUnderstanding()
        analysis = mock.what_is_on_screen()
        
        assert analysis is not None
        assert len(analysis.description) > 0
    
    def test_set_mock_elements(self):
        """Test setting mock elements."""
        from bantz.vision.screen import MockScreenUnderstanding, ElementType
        
        mock = MockScreenUnderstanding()
        mock.set_mock_elements([
            {"type": "button", "text": "OK", "x": 100, "y": 200},
            {"type": "button", "text": "Cancel", "x": 200, "y": 200},
        ])
        
        analysis = mock.what_is_on_screen()
        assert len(analysis.elements) == 2
    
    def test_find_element(self):
        """Test finding element."""
        from bantz.vision.screen import MockScreenUnderstanding
        
        mock = MockScreenUnderstanding()
        mock.set_mock_elements([
            {"type": "button", "text": "Submit", "x": 500, "y": 300},
        ])
        
        elem = mock.find_element("Submit")
        assert elem is not None
        assert elem.text == "Submit"
    
    def test_understand_error(self):
        """Test error understanding."""
        from bantz.vision.screen import MockScreenUnderstanding
        
        mock = MockScreenUnderstanding()
        result = mock.understand_error()
        
        assert "has_error" in result
    
    def test_set_mock_error(self):
        """Test setting mock error."""
        from bantz.vision.screen import MockScreenUnderstanding
        
        mock = MockScreenUnderstanding()
        mock.set_mock_error({
            "has_error": True,
            "error_text": "Connection failed",
            "suggestions": ["Check network"],
        })
        
        result = mock.understand_error()
        assert result["has_error"] is True
        assert "Connection failed" in result["error_text"]
    
    def test_read_text(self):
        """Test text reading."""
        from bantz.vision.screen import MockScreenUnderstanding
        
        mock = MockScreenUnderstanding()
        text = mock.read_text()
        
        assert len(text) > 0


class TestScreenUnderstanding:
    """Tests for ScreenUnderstanding class."""
    
    def test_init(self):
        """Test initialization."""
        from bantz.vision.screen import ScreenUnderstanding
        from bantz.vision.llm import MockVisionLLM
        
        vision = MockVisionLLM()
        screen = ScreenUnderstanding(vision, default_language="tr")
        
        assert screen.default_language == "tr"
    
    def test_parse_json_response(self):
        """Test JSON response parsing."""
        from bantz.vision.screen import ScreenUnderstanding
        from bantz.vision.llm import MockVisionLLM
        
        vision = MockVisionLLM()
        screen = ScreenUnderstanding(vision)
        
        # Test with markdown code block
        response = '```json\n{"found": true}\n```'
        result = screen._parse_json_response(response)
        assert result["found"] is True
        
        # Test with plain JSON
        response = '{"status": "ok"}'
        result = screen._parse_json_response(response)
        assert result["status"] == "ok"


# =============================================================================
# Vision Tools Tests
# =============================================================================


class TestToolParameter:
    """Tests for ToolParameter dataclass."""
    
    def test_parameter_creation(self):
        """Test parameter creation."""
        from bantz.vision.tools import ToolParameter
        
        param = ToolParameter(
            name="path",
            type="file",
            description="File path",
            required=True,
        )
        
        assert param.name == "path"
        assert param.required is True


class TestVisionTool:
    """Tests for VisionTool dataclass."""
    
    def test_tool_creation(self):
        """Test tool creation."""
        from bantz.vision.tools import VisionTool, ToolParameter
        
        tool = VisionTool(
            name="test_tool",
            description="A test tool",
            handler=lambda: "result",
            parameters=[
                ToolParameter("arg1", "string", "First argument"),
            ],
        )
        
        assert tool.name == "test_tool"
        assert len(tool.parameters) == 1
    
    def test_to_dict(self):
        """Test dictionary conversion."""
        from bantz.vision.tools import VisionTool
        
        tool = VisionTool(
            name="my_tool",
            description="Does something",
            handler=lambda: None,
        )
        
        d = tool.to_dict()
        assert d["name"] == "my_tool"
        assert d["description"] == "Does something"
        assert d["category"] == "vision"
    
    def test_execute(self):
        """Test tool execution."""
        from bantz.vision.tools import VisionTool
        
        def my_handler(x, y):
            return x + y
        
        tool = VisionTool(
            name="add",
            description="Add numbers",
            handler=my_handler,
        )
        
        result = tool.execute(x=1, y=2)
        assert result == 3


class TestVisionToolRegistry:
    """Tests for VisionToolRegistry."""
    
    def test_register_tool(self):
        """Test registering a tool."""
        from bantz.vision.tools import VisionToolRegistry, VisionTool
        
        registry = VisionToolRegistry()
        tool = VisionTool(
            name="test",
            description="Test tool",
            handler=lambda: "ok",
        )
        
        registry.register(tool)
        
        assert registry.get("test") is not None
    
    def test_list_tools(self):
        """Test listing tools."""
        from bantz.vision.tools import VisionToolRegistry, VisionTool
        
        registry = VisionToolRegistry()
        
        for i in range(3):
            registry.register(VisionTool(
                name=f"tool_{i}",
                description=f"Tool {i}",
                handler=lambda: None,
            ))
        
        tools = registry.list_tools()
        assert len(tools) == 3
    
    def test_execute_tool(self):
        """Test executing tool by name."""
        from bantz.vision.tools import VisionToolRegistry, VisionTool
        
        registry = VisionToolRegistry()
        registry.register(VisionTool(
            name="greet",
            description="Greet",
            handler=lambda person: f"Hello, {person}!",
        ))
        
        result = registry.execute("greet", person="World")
        assert result == "Hello, World!"
    
    def test_execute_unknown_tool(self):
        """Test executing unknown tool."""
        from bantz.vision.tools import VisionToolRegistry
        
        registry = VisionToolRegistry()
        
        with pytest.raises(ValueError, match="Unknown vision tool"):
            registry.execute("nonexistent")


class TestGetVisionTools:
    """Tests for get_vision_tools function."""
    
    def test_get_tools_empty(self):
        """Test getting tools without components."""
        from bantz.vision.tools import get_vision_tools
        
        tools = get_vision_tools()
        
        # Should at least have capture_screenshot
        assert len(tools) >= 1
        
        tool_names = [t.name for t in tools]
        assert "capture_screenshot" in tool_names
    
    def test_get_tools_with_vision_llm(self):
        """Test getting tools with vision LLM."""
        from bantz.vision.tools import get_vision_tools
        from bantz.vision.llm import MockVisionLLM
        
        vision = MockVisionLLM()
        tools = get_vision_tools(vision_llm=vision)
        
        tool_names = [t.name for t in tools]
        assert "analyze_screen" in tool_names
        assert "describe_image" in tool_names
    
    def test_get_tools_with_document_analyzer(self):
        """Test getting tools with document analyzer."""
        from bantz.vision.tools import get_vision_tools
        from bantz.vision.document import MockDocumentAnalyzer
        
        analyzer = MockDocumentAnalyzer()
        tools = get_vision_tools(document_analyzer=analyzer)
        
        tool_names = [t.name for t in tools]
        assert "read_document" in tool_names
        assert "summarize_document" in tool_names
        assert "ocr" in tool_names
    
    def test_get_tools_with_screen_understanding(self):
        """Test getting tools with screen understanding."""
        from bantz.vision.tools import get_vision_tools
        from bantz.vision.screen import MockScreenUnderstanding
        
        screen = MockScreenUnderstanding()
        tools = get_vision_tools(screen_understanding=screen)
        
        tool_names = [t.name for t in tools]
        assert "find_element" in tool_names
        assert "understand_error" in tool_names


class TestCreateVisionRegistry:
    """Tests for create_vision_registry function."""
    
    def test_create_registry(self):
        """Test creating a vision registry."""
        from bantz.vision.tools import create_vision_registry
        from bantz.vision.llm import MockVisionLLM
        from bantz.vision.document import MockDocumentAnalyzer
        from bantz.vision.screen import MockScreenUnderstanding
        
        registry = create_vision_registry(
            vision_llm=MockVisionLLM(),
            document_analyzer=MockDocumentAnalyzer(),
            screen_understanding=MockScreenUnderstanding(),
        )
        
        # Should have all tools registered
        tools = registry.list_tools()
        assert len(tools) > 5
        
        # Test specific tools exist
        assert registry.get("analyze_screen") is not None
        assert registry.get("read_document") is not None
        assert registry.get("capture_screenshot") is not None


class TestBuiltInTools:
    """Tests for built-in vision tools."""
    
    def test_capture_screenshot_tool(self):
        """Test capture screenshot tool."""
        from bantz.vision.tools import create_capture_screenshot_tool
        
        tool = create_capture_screenshot_tool()
        assert tool.name == "capture_screenshot"
        assert tool.requires_screen is True
    
    def test_analyze_screen_tool(self):
        """Test analyze screen tool."""
        from bantz.vision.tools import create_analyze_screen_tool
        from bantz.vision.screen import MockScreenUnderstanding
        
        mock = MockScreenUnderstanding()
        tool = create_analyze_screen_tool(screen_understanding=mock)
        
        result = tool.execute()
        assert "description" in result
    
    def test_read_document_tool(self):
        """Test read document tool."""
        from bantz.vision.tools import create_read_document_tool
        from bantz.vision.document import MockDocumentAnalyzer
        
        analyzer = MockDocumentAnalyzer()
        tool = create_read_document_tool(analyzer)
        
        result = tool.execute(path="/test/doc.pdf")
        assert "path" in result
        assert "type" in result
    
    def test_ocr_tool(self):
        """Test OCR tool."""
        from bantz.vision.tools import create_ocr_tool
        from bantz.vision.document import MockDocumentAnalyzer
        
        analyzer = MockDocumentAnalyzer()
        tool = create_ocr_tool(analyzer)
        
        result = tool.execute(path="/test/image.png")
        assert "text" in result
        assert "confidence" in result


# =============================================================================
# Integration Tests
# =============================================================================


class TestVisionModuleIntegration:
    """Integration tests for the vision module."""
    
    def test_import_all(self):
        """Test importing all exports."""
        from bantz.vision import (
            capture_screen,
            capture_region,
            VisionLLM,
            VisionMessage,
            DocumentAnalyzer,
            ScreenUnderstanding,
            get_vision_tools,
            VISION_TOOLS,
        )
        
        assert capture_screen is not None
        assert VisionLLM is not None
        assert len(VISION_TOOLS) > 0
    
    def test_mock_components_work_together(self):
        """Test mock components working together."""
        from bantz.vision import (
            MockVisionLLM,
            MockDocumentAnalyzer,
            MockScreenUnderstanding,
            create_vision_registry,
        )
        
        # Create all mock components
        vision = MockVisionLLM()
        doc = MockDocumentAnalyzer()
        screen = MockScreenUnderstanding(vision_llm=vision)
        
        # Create registry
        registry = create_vision_registry(
            vision_llm=vision,
            document_analyzer=doc,
            screen_understanding=screen,
        )
        
        # Test various operations
        screen_result = registry.execute("analyze_screen")
        assert "description" in screen_result
        
        doc_result = registry.execute("read_document", path="/test/doc.pdf")
        assert doc_result is not None
    
    def test_vision_tools_list(self):
        """Test VISION_TOOLS constant."""
        from bantz.vision import VISION_TOOLS
        
        expected_tools = [
            "analyze_screen",
            "find_element",
            "read_document",
            "summarize_document",
            "ocr",
            "capture_screenshot",
        ]
        
        for tool in expected_tools:
            assert tool in VISION_TOOLS


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_invalid_image_content_type(self):
        """Test invalid image content type."""
        from bantz.vision.llm import ImageContent
        
        content = ImageContent(data=12345)  # Invalid type
        
        with pytest.raises(ValueError, match="Unsupported image data type"):
            content.to_base64()
    
    def test_document_analyzer_no_pdf_support(self):
        """Test document analyzer without PDF support."""
        from bantz.vision.document import DocumentAnalyzer
        
        analyzer = DocumentAnalyzer()
        analyzer._pdf_available = False
        
        with pytest.raises(RuntimeError, match="PyMuPDF not available"):
            analyzer.read_pdf("/test.pdf")
    
    def test_document_analyzer_unsupported_type(self):
        """Test unsupported document type."""
        from bantz.vision.document import DocumentAnalyzer
        
        analyzer = DocumentAnalyzer()
        
        with pytest.raises(ValueError, match="Unsupported document type"):
            analyzer.read_document("/test.xyz")
    
    def test_tool_without_component(self):
        """Test tool execution without required component."""
        from bantz.vision.tools import create_analyze_screen_tool
        
        tool = create_analyze_screen_tool()  # No components
        
        with pytest.raises(RuntimeError, match="No vision component configured"):
            tool.execute()
