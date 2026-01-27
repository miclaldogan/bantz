"""
Screen Understanding.

Semantic understanding of screen content using vision LLM.
Provides UI element detection, error understanding, and visual search.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union, Tuple
from pathlib import Path
from enum import Enum
import logging
import json
import re

logger = logging.getLogger(__name__)


class ElementType(Enum):
    """UI element types."""
    
    BUTTON = "button"
    TEXT_FIELD = "text_field"
    LINK = "link"
    MENU = "menu"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    DROPDOWN = "dropdown"
    ICON = "icon"
    IMAGE = "image"
    TAB = "tab"
    DIALOG = "dialog"
    WINDOW = "window"
    TEXT = "text"
    UNKNOWN = "unknown"
    
    @classmethod
    def from_string(cls, s: str) -> "ElementType":
        """Convert string to ElementType."""
        s = s.lower().replace(" ", "_").replace("-", "_")
        try:
            return cls(s)
        except ValueError:
            return cls.UNKNOWN


@dataclass
class UIElement:
    """
    Detected UI element.
    """
    
    element_type: ElementType
    text: str
    x: int
    y: int
    width: int = 0
    height: int = 0
    confidence: float = 0.0
    clickable: bool = True
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def center(self) -> Tuple[int, int]:
        """Get center point."""
        return (
            self.x + self.width // 2,
            self.y + self.height // 2,
        )
    
    @property
    def bounds(self) -> Tuple[int, int, int, int]:
        """Get bounding box (x, y, width, height)."""
        return (self.x, self.y, self.width, self.height)
    
    def contains_point(self, x: int, y: int) -> bool:
        """Check if point is within element."""
        return (
            self.x <= x <= self.x + self.width and
            self.y <= y <= self.y + self.height
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "type": self.element_type.value,
            "text": self.text,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "confidence": self.confidence,
            "clickable": self.clickable,
            "enabled": self.enabled,
            "center": self.center,
        }


@dataclass
class ScreenAnalysis:
    """
    Complete screen analysis result.
    """
    
    description: str
    elements: List[UIElement] = field(default_factory=list)
    active_window: Optional[str] = None
    focused_element: Optional[UIElement] = None
    errors: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    raw_response: str = ""
    
    def find_by_text(self, text: str, partial: bool = True) -> List[UIElement]:
        """Find elements containing text."""
        results = []
        for elem in self.elements:
            if partial:
                if text.lower() in elem.text.lower():
                    results.append(elem)
            else:
                if text.lower() == elem.text.lower():
                    results.append(elem)
        return results
    
    def find_by_type(self, elem_type: Union[str, ElementType]) -> List[UIElement]:
        """Find elements by type."""
        if isinstance(elem_type, str):
            elem_type = ElementType.from_string(elem_type)
        return [e for e in self.elements if e.element_type == elem_type]
    
    def get_buttons(self) -> List[UIElement]:
        """Get all button elements."""
        return self.find_by_type(ElementType.BUTTON)
    
    def get_text_fields(self) -> List[UIElement]:
        """Get all text field elements."""
        return self.find_by_type(ElementType.TEXT_FIELD)


class ScreenUnderstanding:
    """
    Screen understanding using vision LLM.
    
    Provides semantic analysis of screen content:
    - What is on screen
    - UI element detection
    - Error understanding
    - Visual search
    
    Example:
        from bantz.vision import VisionLLM, ScreenUnderstanding
        
        vision = VisionLLM(model="llava")
        screen = ScreenUnderstanding(vision)
        
        # Analyze current screen
        analysis = screen.what_is_on_screen()
        print(analysis.description)
        
        # Find a button
        button = screen.find_element("Save", element_type="button")
        if button:
            print(f"Found at {button.center}")
        
        # Understand error
        error_info = screen.understand_error()
    """
    
    def __init__(
        self,
        vision_llm: Any,
        default_language: str = "tr",
        cache_enabled: bool = True,
    ):
        """
        Initialize screen understanding.
        
        Args:
            vision_llm: VisionLLM instance
            default_language: Default response language
            cache_enabled: Enable analysis caching
        """
        self.vision_llm = vision_llm
        self.default_language = default_language
        self.cache_enabled = cache_enabled
        
        self._last_analysis: Optional[ScreenAnalysis] = None
        self._cache: Dict[str, ScreenAnalysis] = {}
    
    def what_is_on_screen(
        self,
        screenshot: Optional[bytes] = None,
        detail_level: str = "normal",  # minimal, normal, detailed
    ) -> ScreenAnalysis:
        """
        Analyze what's currently on screen.
        
        Args:
            screenshot: Optional screenshot bytes (captures if None)
            detail_level: Level of detail in analysis
            
        Returns:
            ScreenAnalysis with description and elements
        """
        # Capture screen if not provided
        if screenshot is None:
            from bantz.vision.capture import capture_screen
            capture = capture_screen()
            screenshot = capture.image_bytes
        
        # Build prompt based on detail level
        if self.default_language == "tr":
            prompts = {
                "minimal": "Ekranda ne var? Tek cümleyle açıkla.",
                "normal": """Ekranı analiz et ve şunları belirt:
1. Hangi uygulama açık?
2. Ana içerik nedir?
3. Kullanıcı ne yapıyor olabilir?""",
                "detailed": """Bu ekran görüntüsünü detaylı analiz et:

1. GENEL: Hangi uygulama veya sayfa açık?
2. İÇERİK: Ekrandaki ana içerik nedir?
3. ELEMENTLER: Önemli UI elementleri (butonlar, menüler, formlar)
4. DURUM: Herhangi bir hata veya uyarı var mı?
5. ODAK: Kullanıcının odaklandığı yer neresi?

JSON formatında yanıt ver:
{
    "active_window": "...",
    "description": "...",
    "elements": [
        {"type": "button/input/link/...", "text": "...", "x": 0, "y": 0, "width": 0, "height": 0}
    ],
    "errors": [],
    "suggestions": []
}""",
            }
        else:
            prompts = {
                "minimal": "What's on screen? One sentence.",
                "normal": "Analyze the screen: application, content, user activity.",
                "detailed": "Detailed screen analysis with JSON output...",
            }
        
        prompt = prompts.get(detail_level, prompts["normal"])
        
        # Query vision LLM
        response = self.vision_llm.analyze_image(screenshot, prompt)
        
        # Parse response
        analysis = self._parse_screen_response(response, detail_level)
        
        self._last_analysis = analysis
        return analysis
    
    def find_element(
        self,
        description: str,
        element_type: Optional[str] = None,
        screenshot: Optional[bytes] = None,
    ) -> Optional[UIElement]:
        """
        Find a UI element by description.
        
        Args:
            description: Element description (e.g., "login button", "search box")
            element_type: Optional type filter (button, input, link, etc.)
            screenshot: Optional screenshot (captures if None)
            
        Returns:
            UIElement if found, None otherwise
        """
        if screenshot is None:
            from bantz.vision.capture import capture_screen
            capture = capture_screen()
            screenshot = capture.image_bytes
        
        # Build search prompt
        type_hint = f" ({element_type})" if element_type else ""
        
        if self.default_language == "tr":
            prompt = f"""'{description}'{type_hint} elementini bu ekran görüntüsünde bul.

Element bulunursa JSON döndür:
{{
    "found": true,
    "element": {{
        "type": "button/input/link/...",
        "text": "element metni",
        "x": piksel (sol üst köşe),
        "y": piksel (sol üst köşe),
        "width": piksel,
        "height": piksel,
        "confidence": 0.0-1.0
    }}
}}

Bulunamazsa: {{"found": false, "reason": "..."}}"""
        else:
            prompt = f"Find '{description}'{type_hint} element. Return JSON with found, element coords."
        
        response = self.vision_llm.analyze_image(screenshot, prompt)
        
        try:
            data = self._parse_json_response(response)
            
            if data.get("found") and "element" in data:
                elem = data["element"]
                return UIElement(
                    element_type=ElementType.from_string(elem.get("type", "unknown")),
                    text=elem.get("text", description),
                    x=elem.get("x", 0),
                    y=elem.get("y", 0),
                    width=elem.get("width", 50),
                    height=elem.get("height", 30),
                    confidence=elem.get("confidence", 0.5),
                )
            
            return None
            
        except Exception as e:
            logger.warning(f"Could not parse element response: {e}")
            return None
    
    def find_all_elements(
        self,
        screenshot: Optional[bytes] = None,
        element_types: Optional[List[str]] = None,
    ) -> List[UIElement]:
        """
        Find all UI elements on screen.
        
        Args:
            screenshot: Optional screenshot
            element_types: Filter by element types
            
        Returns:
            List of detected UIElements
        """
        if screenshot is None:
            from bantz.vision.capture import capture_screen
            capture = capture_screen()
            screenshot = capture.image_bytes
        
        type_filter = ""
        if element_types:
            type_filter = f" Sadece şu tipleri ara: {', '.join(element_types)}."
        
        if self.default_language == "tr":
            prompt = f"""Ekrandaki tüm etkileşimli UI elementlerini bul.{type_filter}

JSON formatında listele:
{{
    "elements": [
        {{
            "type": "button/input/link/checkbox/dropdown/...",
            "text": "element metni veya açıklama",
            "x": piksel,
            "y": piksel,
            "width": piksel,
            "height": piksel,
            "clickable": true/false,
            "enabled": true/false
        }}
    ]
}}"""
        else:
            prompt = f"Find all interactive UI elements on screen.{type_filter} Return JSON."
        
        response = self.vision_llm.analyze_image(screenshot, prompt)
        
        try:
            data = self._parse_json_response(response)
            elements = []
            
            for elem in data.get("elements", []):
                elements.append(UIElement(
                    element_type=ElementType.from_string(elem.get("type", "unknown")),
                    text=elem.get("text", ""),
                    x=elem.get("x", 0),
                    y=elem.get("y", 0),
                    width=elem.get("width", 50),
                    height=elem.get("height", 30),
                    clickable=elem.get("clickable", True),
                    enabled=elem.get("enabled", True),
                ))
            
            return elements
            
        except Exception as e:
            logger.warning(f"Could not parse elements response: {e}")
            return []
    
    def understand_error(
        self,
        screenshot: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """
        Understand error dialogs or messages on screen.
        
        Args:
            screenshot: Optional screenshot
            
        Returns:
            Error information with suggestions
        """
        if screenshot is None:
            from bantz.vision.capture import capture_screen
            capture = capture_screen()
            screenshot = capture.image_bytes
        
        if self.default_language == "tr":
            prompt = """Bu ekran görüntüsünde hata mesajı veya uyarı var mı?

JSON formatında yanıt ver:
{
    "has_error": true/false,
    "error_type": "dialog/notification/inline/none",
    "error_text": "tam hata mesajı",
    "error_code": "varsa hata kodu",
    "severity": "critical/warning/info",
    "cause": "olası sebep",
    "suggestions": ["çözüm önerisi 1", "çözüm önerisi 2"],
    "buttons": ["hata dialogundaki butonlar"]
}

Hata yoksa: {"has_error": false}"""
        else:
            prompt = "Check for error messages. Return JSON with error details and suggestions."
        
        response = self.vision_llm.analyze_image(screenshot, prompt)
        
        try:
            data = self._parse_json_response(response)
            return data
        except Exception:
            return {
                "has_error": "hata" in response.lower() or "error" in response.lower(),
                "raw_response": response,
            }
    
    def read_text(
        self,
        screenshot: Optional[bytes] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> str:
        """
        Read text from screen.
        
        Args:
            screenshot: Optional screenshot
            region: Optional (x, y, width, height) to read from
            
        Returns:
            Extracted text
        """
        if screenshot is None:
            if region:
                from bantz.vision.capture import capture_region
                x, y, w, h = region
                capture = capture_region(x, y, w, h)
            else:
                from bantz.vision.capture import capture_screen
                capture = capture_screen()
            screenshot = capture.image_bytes
        
        if self.default_language == "tr":
            prompt = "Bu resimdeki tüm okunabilir metni aynen yaz. Sadece metni yaz, açıklama ekleme."
        else:
            prompt = "Read all visible text in this image. Output only the text."
        
        return self.vision_llm.analyze_image(screenshot, prompt)
    
    def get_window_info(
        self,
        screenshot: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """
        Get information about visible windows.
        
        Args:
            screenshot: Optional screenshot
            
        Returns:
            Window information
        """
        if screenshot is None:
            from bantz.vision.capture import capture_screen
            capture = capture_screen()
            screenshot = capture.image_bytes
        
        if self.default_language == "tr":
            prompt = """Ekrandaki pencereleri analiz et:

JSON formatında:
{
    "windows": [
        {
            "title": "pencere başlığı",
            "application": "uygulama adı",
            "is_active": true/false,
            "is_maximized": true/false,
            "approximate_position": "sol/sağ/orta/tam ekran"
        }
    ],
    "active_window": "aktif pencere başlığı",
    "desktop_visible": true/false
}"""
        else:
            prompt = "Analyze visible windows. Return JSON with window titles, apps, positions."
        
        response = self.vision_llm.analyze_image(screenshot, prompt)
        
        try:
            return self._parse_json_response(response)
        except Exception:
            return {"raw_response": response}
    
    def wait_for_element(
        self,
        description: str,
        timeout: float = 10.0,
        interval: float = 0.5,
    ) -> Optional[UIElement]:
        """
        Wait for an element to appear on screen.
        
        Args:
            description: Element description
            timeout: Maximum wait time in seconds
            interval: Check interval in seconds
            
        Returns:
            UIElement if found within timeout
        """
        import time
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            element = self.find_element(description)
            if element:
                return element
            time.sleep(interval)
        
        return None
    
    def wait_for_change(
        self,
        reference_screenshot: Optional[bytes] = None,
        timeout: float = 10.0,
        interval: float = 0.5,
        threshold: float = 0.1,
    ) -> bool:
        """
        Wait for screen to change.
        
        Args:
            reference_screenshot: Reference screenshot (current if None)
            timeout: Maximum wait time
            interval: Check interval
            threshold: Change threshold (0-1)
            
        Returns:
            True if screen changed
        """
        import time
        from bantz.vision.capture import capture_screen
        
        if reference_screenshot is None:
            reference_screenshot = capture_screen().image_bytes
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            time.sleep(interval)
            
            current = capture_screen().image_bytes
            
            # Simple size-based change detection
            # A more sophisticated approach would use image comparison
            if len(current) != len(reference_screenshot):
                return True
            
            # Ask vision LLM if there's a change
            if self._detect_change(reference_screenshot, current, threshold):
                return True
        
        return False
    
    def _detect_change(
        self,
        image1: bytes,
        image2: bytes,
        threshold: float,
    ) -> bool:
        """Detect if two images are significantly different."""
        try:
            # Use PIL for basic comparison
            from PIL import Image
            import io
            
            img1 = Image.open(io.BytesIO(image1))
            img2 = Image.open(io.BytesIO(image2))
            
            # Resize for faster comparison
            size = (100, 100)
            img1 = img1.resize(size)
            img2 = img2.resize(size)
            
            # Convert to grayscale
            img1 = img1.convert("L")
            img2 = img2.convert("L")
            
            # Calculate difference
            diff = sum(
                abs(p1 - p2)
                for p1, p2 in zip(img1.getdata(), img2.getdata())
            )
            
            max_diff = 255 * size[0] * size[1]
            change_ratio = diff / max_diff
            
            return change_ratio > threshold
            
        except Exception:
            # Fallback to size comparison
            return len(image1) != len(image2)
    
    def _parse_screen_response(
        self,
        response: str,
        detail_level: str,
    ) -> ScreenAnalysis:
        """Parse screen analysis response."""
        analysis = ScreenAnalysis(
            description="",
            raw_response=response,
        )
        
        if detail_level == "detailed":
            try:
                data = self._parse_json_response(response)
                
                analysis.description = data.get("description", response)
                analysis.active_window = data.get("active_window")
                analysis.errors = data.get("errors", [])
                analysis.suggestions = data.get("suggestions", [])
                
                for elem in data.get("elements", []):
                    analysis.elements.append(UIElement(
                        element_type=ElementType.from_string(elem.get("type", "unknown")),
                        text=elem.get("text", ""),
                        x=elem.get("x", 0),
                        y=elem.get("y", 0),
                        width=elem.get("width", 50),
                        height=elem.get("height", 30),
                    ))
                    
            except Exception as e:
                logger.debug(f"Could not parse detailed response: {e}")
                analysis.description = response
        else:
            analysis.description = response
        
        return analysis
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Extract and parse JSON from response."""
        # Handle markdown code blocks
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            parts = response.split("```")
            if len(parts) >= 2:
                response = parts[1]
        
        # Try to find JSON object
        response = response.strip()
        
        # Find JSON boundaries
        start = response.find("{")
        if start == -1:
            start = response.find("[")
        
        if start != -1:
            # Find matching end
            depth = 0
            end = start
            for i, char in enumerate(response[start:], start):
                if char in "{[":
                    depth += 1
                elif char in "}]":
                    depth -= 1
                if depth == 0:
                    end = i + 1
                    break
            
            response = response[start:end]
        
        return json.loads(response)


# =============================================================================
# Mock Implementation for Testing
# =============================================================================


class MockScreenUnderstanding(ScreenUnderstanding):
    """Mock Screen Understanding for testing."""
    
    def __init__(self, *args, **kwargs):
        # Don't require real vision LLM
        kwargs.setdefault("vision_llm", None)
        super().__init__(*args, **kwargs)
        
        self._mock_elements: List[UIElement] = []
        self._mock_analysis: Optional[ScreenAnalysis] = None
        self._mock_error: Optional[Dict[str, Any]] = None
    
    def set_mock_elements(self, elements: List[Dict[str, Any]]) -> None:
        """Set mock UI elements."""
        self._mock_elements = [
            UIElement(
                element_type=ElementType.from_string(e.get("type", "button")),
                text=e.get("text", ""),
                x=e.get("x", 0),
                y=e.get("y", 0),
                width=e.get("width", 100),
                height=e.get("height", 30),
                confidence=e.get("confidence", 0.9),
            )
            for e in elements
        ]
    
    def set_mock_analysis(
        self,
        description: str,
        active_window: Optional[str] = None,
    ) -> None:
        """Set mock screen analysis."""
        self._mock_analysis = ScreenAnalysis(
            description=description,
            elements=self._mock_elements,
            active_window=active_window,
        )
    
    def set_mock_error(self, error_info: Dict[str, Any]) -> None:
        """Set mock error information."""
        self._mock_error = error_info
    
    def what_is_on_screen(
        self,
        screenshot: Optional[bytes] = None,
        detail_level: str = "normal",
    ) -> ScreenAnalysis:
        """Return mock analysis."""
        if self._mock_analysis:
            return self._mock_analysis
        
        return ScreenAnalysis(
            description="Mock ekran analizi. Bir masaüstü ortamı görünüyor.",
            elements=self._mock_elements,
            active_window="Terminal",
        )
    
    def find_element(
        self,
        description: str,
        element_type: Optional[str] = None,
        screenshot: Optional[bytes] = None,
    ) -> Optional[UIElement]:
        """Find mock element by description."""
        for elem in self._mock_elements:
            if description.lower() in elem.text.lower():
                if element_type is None or elem.element_type.value == element_type:
                    return elem
        
        # Default mock element
        return UIElement(
            element_type=ElementType.BUTTON,
            text=description,
            x=500,
            y=300,
            width=100,
            height=30,
            confidence=0.8,
        )
    
    def find_all_elements(
        self,
        screenshot: Optional[bytes] = None,
        element_types: Optional[List[str]] = None,
    ) -> List[UIElement]:
        """Return mock elements."""
        if element_types:
            return [
                e for e in self._mock_elements
                if e.element_type.value in element_types
            ]
        return self._mock_elements
    
    def understand_error(
        self,
        screenshot: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """Return mock error info."""
        if self._mock_error:
            return self._mock_error
        
        return {
            "has_error": False,
            "message": "Hata mesajı görünmüyor.",
        }
    
    def read_text(
        self,
        screenshot: Optional[bytes] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> str:
        """Return mock text."""
        return "Mock metin. Bu ekrandan okunan metin içeriği."
