"""
Vision LLM Client.

Integration with vision-capable LLMs like LLaVA via Ollama.
Provides image analysis, description, and visual question answering.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
import logging
import base64
import io
import json
from enum import Enum

logger = logging.getLogger(__name__)


class VisionModel(Enum):
    """Supported vision models."""
    
    LLAVA = "llava"
    LLAVA_13B = "llava:13b"
    LLAVA_34B = "llava:34b"
    BAKLLAVA = "bakllava"
    LLAVA_LLAMA3 = "llava-llama3"
    MOONDREAM = "moondream"
    
    @classmethod
    def default(cls) -> "VisionModel":
        return cls.LLAVA


@dataclass
class ImageContent:
    """
    Image content for vision analysis.
    
    Supports multiple formats:
    - bytes: Raw image bytes
    - Path: File path to image
    - str (URL): URL to image
    - str (base64): Base64 encoded image
    """
    
    data: Union[bytes, Path, str]
    format: str = "auto"  # auto, png, jpeg, webp
    
    def to_base64(self) -> str:
        """Convert to base64 string."""
        if isinstance(self.data, bytes):
            return base64.b64encode(self.data).decode("utf-8")
        elif isinstance(self.data, Path):
            return base64.b64encode(self.data.read_bytes()).decode("utf-8")
        elif isinstance(self.data, str):
            if self.data.startswith("http"):
                # Download and encode
                return self._download_and_encode(self.data)
            elif len(self.data) > 200 and "/" not in self.data[:50]:
                # Likely already base64
                return self.data
            else:
                # File path as string
                return base64.b64encode(Path(self.data).read_bytes()).decode("utf-8")
        else:
            raise ValueError(f"Unsupported image data type: {type(self.data)}")
    
    def _download_and_encode(self, url: str) -> str:
        """Download image and encode to base64."""
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=10) as response:
                data = response.read()
            return base64.b64encode(data).decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to download image: {e}")
            raise
    
    @classmethod
    def from_bytes(cls, data: bytes, format: str = "png") -> "ImageContent":
        """Create from raw bytes."""
        return cls(data=data, format=format)
    
    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "ImageContent":
        """Create from file path."""
        path = Path(path)
        format = path.suffix.lstrip(".").lower() or "auto"
        return cls(data=path, format=format)
    
    @classmethod
    def from_url(cls, url: str) -> "ImageContent":
        """Create from URL."""
        return cls(data=url, format="auto")
    
    @classmethod
    def from_base64(cls, data: str, format: str = "png") -> "ImageContent":
        """Create from base64 string."""
        return cls(data=data, format=format)


@dataclass
class VisionMessage:
    """
    Message with text and/or images for vision LLM.
    """
    
    text: str
    images: List[ImageContent] = field(default_factory=list)
    role: str = "user"  # user, assistant, system
    
    def add_image(self, image: Union[ImageContent, bytes, Path, str]) -> "VisionMessage":
        """Add an image to the message."""
        if isinstance(image, ImageContent):
            self.images.append(image)
        elif isinstance(image, bytes):
            self.images.append(ImageContent.from_bytes(image))
        elif isinstance(image, Path):
            self.images.append(ImageContent.from_file(image))
        elif isinstance(image, str):
            if image.startswith("http"):
                self.images.append(ImageContent.from_url(image))
            else:
                self.images.append(ImageContent.from_file(image))
        else:
            raise ValueError(f"Unsupported image type: {type(image)}")
        return self
    
    def to_ollama_format(self) -> Dict[str, Any]:
        """Convert to Ollama API format."""
        result = {
            "role": self.role,
            "content": self.text,
        }
        if self.images:
            result["images"] = [img.to_base64() for img in self.images]
        return result


@dataclass
class VisionResponse:
    """Response from vision LLM."""
    
    text: str
    model: str
    tokens_used: int = 0
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class VisionLLM:
    """
    Vision-capable LLM client.
    
    Uses Ollama to run vision models like LLaVA locally.
    
    Example:
        vision = VisionLLM(model="llava:13b")
        
        # Analyze an image
        result = vision.analyze_image(
            image_path,
            question="Bu resimde ne var?"
        )
        
        # Analyze screenshot
        result = vision.analyze_screenshot("Ekranda ne görüyorsun?")
    """
    
    def __init__(
        self,
        model: Union[str, VisionModel] = VisionModel.LLAVA,
        base_url: str = "http://localhost:11434",
        timeout: float = 120.0,
        default_language: str = "tr",
    ):
        """
        Initialize Vision LLM client.
        
        Args:
            model: Vision model to use
            base_url: Ollama API base URL
            timeout: Request timeout in seconds
            default_language: Default response language
        """
        if isinstance(model, VisionModel):
            self.model = model.value
        else:
            self.model = model
        
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.default_language = default_language
        
        self._conversation: List[VisionMessage] = []
    
    def analyze_image(
        self,
        image: Union[ImageContent, bytes, Path, str],
        question: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Analyze an image with optional question.
        
        Args:
            image: Image to analyze
            question: Question about the image
            system_prompt: Custom system prompt
            
        Returns:
            Analysis text
        """
        if question is None:
            if self.default_language == "tr":
                question = "Bu resimde ne görüyorsun? Detaylı açıkla."
            else:
                question = "What do you see in this image? Describe in detail."
        
        # Create message with image
        message = VisionMessage(text=question)
        message.add_image(image)
        
        return self._query([message], system_prompt)
    
    def analyze_screenshot(
        self,
        question: Optional[str] = None,
        region: Optional[tuple] = None,
    ) -> str:
        """
        Analyze current screen.
        
        Args:
            question: Question about the screen
            region: Optional (x, y, width, height) to capture specific region
            
        Returns:
            Analysis text
        """
        from bantz.vision.capture import capture_screen, capture_region
        
        if region:
            x, y, w, h = region
            capture = capture_region(x, y, w, h)
        else:
            capture = capture_screen()
        
        if question is None:
            if self.default_language == "tr":
                question = "Ekranda ne var? Hangi uygulama açık? Kısaca açıkla."
            else:
                question = "What's on the screen? Which application is open? Briefly describe."
        
        return self.analyze_image(capture.image_bytes, question)
    
    def describe_ui(self, image: Union[ImageContent, bytes, Path, str]) -> str:
        """
        Describe UI elements in an image.
        
        Args:
            image: Screenshot or UI image
            
        Returns:
            UI element descriptions
        """
        if self.default_language == "tr":
            prompt = """Bu ekran görüntüsündeki UI elementlerini listele:
- Butonlar (metin ve konum)
- Metin alanları
- Linkler ve menüler
- Görseller
- Formlar

Her birinin amacını kısaca belirt. JSON formatında yanıt ver:
{
    "elements": [
        {"type": "button", "text": "...", "location": "...", "purpose": "..."},
        ...
    ],
    "current_focus": "...",
    "main_action": "..."
}"""
        else:
            prompt = """List the UI elements in this screenshot:
- Buttons (text and location)
- Text fields
- Links and menus
- Images
- Forms

Briefly describe the purpose of each. Respond in JSON format."""
        
        return self.analyze_image(image, prompt)
    
    def find_element(
        self,
        image: Union[ImageContent, bytes, Path, str],
        description: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Find a UI element by description.
        
        Args:
            image: Screenshot
            description: Element description (e.g., "red submit button")
            
        Returns:
            Element info with coordinates or None
        """
        if self.default_language == "tr":
            prompt = f"""'{description}' elementini bu ekran görüntüsünde bul.

Yanıt JSON formatında:
{{
    "found": true/false,
    "element": {{
        "type": "button/input/link/...",
        "text": "...",
        "x": piksel,
        "y": piksel,
        "width": piksel,
        "height": piksel
    }},
    "confidence": 0.0-1.0,
    "alternatives": []
}}

Element bulunamadıysa found: false döndür."""
        else:
            prompt = f"""Find the '{description}' element in this screenshot.

Respond in JSON format with found, element coordinates, confidence."""
        
        response = self.analyze_image(image, prompt)
        
        try:
            # Try to parse JSON from response
            # Handle markdown code blocks
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]
            
            return json.loads(response.strip())
        except (json.JSONDecodeError, IndexError):
            logger.warning(f"Could not parse element response: {response[:100]}")
            return {"found": False, "raw_response": response}
    
    def understand_error(
        self,
        image: Union[ImageContent, bytes, Path, str] = None,
    ) -> str:
        """
        Understand error dialog/message on screen.
        
        Args:
            image: Screenshot (captures current screen if None)
            
        Returns:
            Error explanation and suggestions
        """
        if image is None:
            from bantz.vision.capture import capture_screen
            capture = capture_screen()
            image = capture.image_bytes
        
        if self.default_language == "tr":
            prompt = """Bu ekran görüntüsünde hata mesajı var mı?

Varsa:
1. Hata mesajının tam metni
2. Hatanın olası sebebi
3. Çözüm önerileri

Yoksa: "Hata mesajı görünmüyor" yaz."""
        else:
            prompt = """Is there an error message in this screenshot?

If yes:
1. Full error message text
2. Possible cause
3. Solution suggestions

If no: Write "No error message visible"."""
        
        return self.analyze_image(image, prompt)
    
    def compare_images(
        self,
        image1: Union[ImageContent, bytes, Path, str],
        image2: Union[ImageContent, bytes, Path, str],
        focus: Optional[str] = None,
    ) -> str:
        """
        Compare two images and describe differences.
        
        Args:
            image1: First image
            image2: Second image
            focus: What to focus on (optional)
            
        Returns:
            Comparison description
        """
        # Create message with both images
        message = VisionMessage(text="")
        message.add_image(image1)
        message.add_image(image2)
        
        if self.default_language == "tr":
            if focus:
                prompt = f"Bu iki resmi karşılaştır. {focus} açısından farklılıkları belirt."
            else:
                prompt = "Bu iki resmi karşılaştır. Benzerlikler ve farklılıklar neler?"
        else:
            if focus:
                prompt = f"Compare these two images. Focus on differences in {focus}."
            else:
                prompt = "Compare these two images. What are the similarities and differences?"
        
        message.text = prompt
        return self._query([message])
    
    def chat(
        self,
        message: str,
        image: Optional[Union[ImageContent, bytes, Path, str]] = None,
    ) -> str:
        """
        Continue a conversation with optional image.
        
        Args:
            message: User message
            image: Optional image to include
            
        Returns:
            Assistant response
        """
        msg = VisionMessage(text=message)
        if image:
            msg.add_image(image)
        
        self._conversation.append(msg)
        
        response = self._query(self._conversation)
        
        self._conversation.append(VisionMessage(
            text=response,
            role="assistant",
        ))
        
        return response
    
    def clear_conversation(self) -> None:
        """Clear conversation history."""
        self._conversation = []
    
    def _query(
        self,
        messages: List[VisionMessage],
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Query the vision LLM.
        
        Args:
            messages: List of messages with images
            system_prompt: Optional system prompt
            
        Returns:
            Model response
        """
        try:
            import urllib.request
            import urllib.error
            
            # Build request
            ollama_messages = []
            
            if system_prompt:
                ollama_messages.append({
                    "role": "system",
                    "content": system_prompt,
                })
            
            for msg in messages:
                ollama_messages.append(msg.to_ollama_format())
            
            payload = {
                "model": self.model,
                "messages": ollama_messages,
                "stream": False,
            }
            
            url = f"{self.base_url}/api/chat"
            
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            
            logger.debug(f"Querying vision LLM: {self.model}")
            
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            
            return result.get("message", {}).get("content", "")
            
        except urllib.error.URLError as e:
            logger.error(f"Failed to connect to Ollama: {e}")
            raise ConnectionError(f"Could not connect to Ollama at {self.base_url}") from e
        except Exception as e:
            logger.error(f"Vision LLM query failed: {e}")
            raise
    
    def is_available(self) -> bool:
        """Check if the vision model is available."""
        try:
            import urllib.request
            
            url = f"{self.base_url}/api/tags"
            with urllib.request.urlopen(url, timeout=5) as response:
                result = json.loads(response.read().decode("utf-8"))
            
            models = [m.get("name", "") for m in result.get("models", [])]
            return any(self.model in m for m in models)
            
        except Exception:
            return False
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the current model."""
        try:
            import urllib.request
            
            url = f"{self.base_url}/api/show"
            payload = {"name": self.model}
            
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
                
        except Exception as e:
            logger.error(f"Failed to get model info: {e}")
            return {"error": str(e)}


# =============================================================================
# Mock Implementation for Testing
# =============================================================================


class MockVisionLLM(VisionLLM):
    """Mock Vision LLM for testing."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._responses: Dict[str, str] = {}
        self._query_count = 0
        self._last_query: Optional[str] = None
    
    def set_response(self, pattern: str, response: str) -> None:
        """Set a mock response for queries containing pattern."""
        self._responses[pattern] = response
    
    def _query(
        self,
        messages: List[VisionMessage],
        system_prompt: Optional[str] = None,
    ) -> str:
        """Mock query."""
        self._query_count += 1
        
        # Get the last message text
        if messages:
            self._last_query = messages[-1].text
            
            # Check for matching patterns
            for pattern, response in self._responses.items():
                if pattern.lower() in self._last_query.lower():
                    return response
        
        # Default mock responses
        if self._last_query and "hata" in self._last_query.lower():
            return "Ekranda hata mesajı görünmüyor."
        elif self._last_query and "ui" in self._last_query.lower():
            return json.dumps({
                "elements": [
                    {"type": "button", "text": "Submit", "location": "bottom-right"},
                    {"type": "input", "text": "", "location": "center"},
                ],
                "current_focus": "input field",
            })
        elif self._last_query and "bul" in self._last_query.lower():
            return json.dumps({
                "found": True,
                "element": {"type": "button", "text": "OK", "x": 500, "y": 300},
                "confidence": 0.85,
            })
        else:
            return "Mock vision analysis: Ekranda bir masaüstü ortamı görünüyor. " \
                   "Birkaç uygulama penceresi açık. Sol tarafta bir dosya yöneticisi, " \
                   "sağ tarafta bir terminal penceresi var."
    
    def is_available(self) -> bool:
        """Mock always returns True."""
        return True
