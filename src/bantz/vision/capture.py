"""
Screen Capture Module.

Provides screen capture functionality for vision analysis:
- Full screen capture
- Region capture
- Window capture
- Active window capture
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Union
from pathlib import Path
import logging
import io
import base64
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ScreenInfo:
    """Information about a screen/monitor."""
    
    index: int
    width: int
    height: int
    x: int = 0
    y: int = 0
    is_primary: bool = False
    name: str = ""
    
    @property
    def size(self) -> Tuple[int, int]:
        return (self.width, self.height)
    
    @property
    def position(self) -> Tuple[int, int]:
        return (self.x, self.y)
    
    @property
    def bounds(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)


@dataclass
class CaptureResult:
    """Result of a screen capture operation."""
    
    image_bytes: bytes
    width: int
    height: int
    format: str = "PNG"
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "screen"  # screen, region, window
    metadata: dict = field(default_factory=dict)
    
    @property
    def size(self) -> Tuple[int, int]:
        return (self.width, self.height)
    
    def to_base64(self) -> str:
        """Convert to base64 string."""
        return base64.b64encode(self.image_bytes).decode("utf-8")
    
    def to_data_uri(self) -> str:
        """Convert to data URI for HTML/browser."""
        mime = f"image/{self.format.lower()}"
        return f"data:{mime};base64,{self.to_base64()}"
    
    def save(self, path: Union[str, Path]) -> Path:
        """Save to file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.image_bytes)
        logger.info(f"Saved screenshot to {path}")
        return path
    
    @classmethod
    def from_pil_image(cls, image, format: str = "PNG", **kwargs) -> "CaptureResult":
        """Create from PIL Image."""
        buffer = io.BytesIO()
        image.save(buffer, format=format)
        return cls(
            image_bytes=buffer.getvalue(),
            width=image.width,
            height=image.height,
            format=format,
            **kwargs,
        )


def get_screen_info() -> List[ScreenInfo]:
    """
    Get information about all screens/monitors.
    
    Returns:
        List of ScreenInfo for each monitor
    """
    screens = []
    
    try:
        # Try mss first (cross-platform)
        try:
            import mss
            with mss.mss() as sct:
                for i, monitor in enumerate(sct.monitors[1:], start=0):  # Skip "all monitors"
                    screens.append(ScreenInfo(
                        index=i,
                        width=monitor["width"],
                        height=monitor["height"],
                        x=monitor["left"],
                        y=monitor["top"],
                        is_primary=(i == 0),
                        name=f"Monitor {i}",
                    ))
            return screens
        except ImportError:
            pass
        
        # Try Pillow ImageGrab
        try:
            from PIL import ImageGrab
            # Single screen info
            img = ImageGrab.grab()
            screens.append(ScreenInfo(
                index=0,
                width=img.width,
                height=img.height,
                is_primary=True,
                name="Primary",
            ))
            return screens
        except ImportError:
            pass
        
        # Fallback: X11
        try:
            import subprocess
            result = subprocess.run(
                ["xrandr", "--query"],
                capture_output=True,
                text=True,
            )
            # Parse xrandr output
            for i, line in enumerate(result.stdout.split("\n")):
                if " connected" in line:
                    parts = line.split()
                    for part in parts:
                        if "x" in part and "+" in part:
                            # Format: 1920x1080+0+0
                            res = part.split("+")
                            size = res[0].split("x")
                            screens.append(ScreenInfo(
                                index=len(screens),
                                width=int(size[0]),
                                height=int(size[1]),
                                x=int(res[1]) if len(res) > 1 else 0,
                                y=int(res[2]) if len(res) > 2 else 0,
                                is_primary=("primary" in line.lower()),
                                name=parts[0],
                            ))
                            break
            return screens
        except Exception:
            pass
        
        # Default fallback
        logger.warning("Could not detect screens, using default")
        return [ScreenInfo(
            index=0,
            width=1920,
            height=1080,
            is_primary=True,
            name="Unknown",
        )]
        
    except Exception as e:
        logger.error(f"Error getting screen info: {e}")
        return [ScreenInfo(
            index=0,
            width=1920,
            height=1080,
            is_primary=True,
            name="Default",
        )]


def capture_screen(
    monitor: int = 0,
    format: str = "PNG",
) -> CaptureResult:
    """
    Capture the entire screen.
    
    Args:
        monitor: Monitor index (0 = primary)
        format: Image format (PNG, JPEG)
        
    Returns:
        CaptureResult with image data
    """
    logger.debug(f"Capturing screen {monitor}")
    
    try:
        # Try mss first (fastest, cross-platform)
        try:
            import mss
            with mss.mss() as sct:
                monitors = sct.monitors
                if monitor + 1 >= len(monitors):
                    monitor = 0
                mon = monitors[monitor + 1]  # +1 because 0 is "all monitors"
                
                screenshot = sct.grab(mon)
                
                # Convert to PNG bytes
                from PIL import Image
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                
                return CaptureResult.from_pil_image(
                    img,
                    format=format,
                    source="screen",
                    metadata={"monitor": monitor},
                )
        except ImportError:
            pass
        
        # Try PIL ImageGrab
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            return CaptureResult.from_pil_image(
                img,
                format=format,
                source="screen",
                metadata={"monitor": monitor, "method": "PIL"},
            )
        except ImportError:
            pass
        
        # Try PyAutoGUI
        try:
            import pyautogui
            img = pyautogui.screenshot()
            return CaptureResult.from_pil_image(
                img,
                format=format,
                source="screen",
                metadata={"monitor": monitor, "method": "pyautogui"},
            )
        except ImportError:
            pass
        
        # X11 fallback using subprocess
        try:
            import subprocess
            import tempfile
            
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                temp_path = f.name
            
            subprocess.run(
                ["import", "-window", "root", temp_path],
                check=True,
            )
            
            from PIL import Image
            img = Image.open(temp_path)
            result = CaptureResult.from_pil_image(
                img,
                format=format,
                source="screen",
                metadata={"monitor": monitor, "method": "import"},
            )
            
            Path(temp_path).unlink(missing_ok=True)
            return result
        except Exception:
            pass
        
        raise RuntimeError("No screen capture method available")
        
    except Exception as e:
        logger.error(f"Screen capture failed: {e}")
        raise


def capture_region(
    x: int,
    y: int,
    width: int,
    height: int,
    format: str = "PNG",
) -> CaptureResult:
    """
    Capture a specific region of the screen.
    
    Args:
        x: Left position
        y: Top position
        width: Region width
        height: Region height
        format: Image format
        
    Returns:
        CaptureResult with image data
    """
    logger.debug(f"Capturing region ({x}, {y}, {width}, {height})")
    
    try:
        # Try mss first
        try:
            import mss
            with mss.mss() as sct:
                region = {
                    "left": x,
                    "top": y,
                    "width": width,
                    "height": height,
                }
                screenshot = sct.grab(region)
                
                from PIL import Image
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                
                return CaptureResult.from_pil_image(
                    img,
                    format=format,
                    source="region",
                    metadata={"x": x, "y": y, "width": width, "height": height},
                )
        except ImportError:
            pass
        
        # Try PIL ImageGrab
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=(x, y, x + width, y + height))
            return CaptureResult.from_pil_image(
                img,
                format=format,
                source="region",
                metadata={"x": x, "y": y, "width": width, "height": height},
            )
        except ImportError:
            pass
        
        # Capture full screen and crop
        full = capture_screen(format=format)
        from PIL import Image
        img = Image.open(io.BytesIO(full.image_bytes))
        cropped = img.crop((x, y, x + width, y + height))
        return CaptureResult.from_pil_image(
            cropped,
            format=format,
            source="region",
            metadata={"x": x, "y": y, "width": width, "height": height},
        )
        
    except Exception as e:
        logger.error(f"Region capture failed: {e}")
        raise


def capture_window(
    window_id: Optional[int] = None,
    window_name: Optional[str] = None,
    format: str = "PNG",
) -> CaptureResult:
    """
    Capture a specific window.
    
    Args:
        window_id: Window ID (X11)
        window_name: Window name/title to search
        format: Image format
        
    Returns:
        CaptureResult with image data
    """
    logger.debug(f"Capturing window: id={window_id}, name={window_name}")
    
    try:
        # Try to find window by name if no ID provided
        if window_id is None and window_name:
            window_id = _find_window_by_name(window_name)
        
        if window_id is None:
            logger.warning("No window specified, capturing active window")
            return capture_active_window(format=format)
        
        # X11 window capture
        try:
            import subprocess
            import tempfile
            
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                temp_path = f.name
            
            subprocess.run(
                ["import", "-window", str(window_id), temp_path],
                check=True,
            )
            
            from PIL import Image
            img = Image.open(temp_path)
            result = CaptureResult.from_pil_image(
                img,
                format=format,
                source="window",
                metadata={"window_id": window_id, "window_name": window_name},
            )
            
            Path(temp_path).unlink(missing_ok=True)
            return result
        except Exception as e:
            logger.warning(f"X11 window capture failed: {e}")
        
        # Fallback to active window
        return capture_active_window(format=format)
        
    except Exception as e:
        logger.error(f"Window capture failed: {e}")
        raise


def capture_active_window(format: str = "PNG") -> CaptureResult:
    """
    Capture the currently active/focused window.
    
    Args:
        format: Image format
        
    Returns:
        CaptureResult with image data
    """
    logger.debug("Capturing active window")
    
    try:
        # Try X11
        try:
            import subprocess
            
            # Get active window ID
            result = subprocess.run(
                ["xdotool", "getactivewindow"],
                capture_output=True,
                text=True,
            )
            window_id = result.stdout.strip()
            
            # Get window geometry
            result = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", window_id],
                capture_output=True,
                text=True,
            )
            
            geometry = {}
            for line in result.stdout.strip().split("\n"):
                if "=" in line:
                    key, value = line.split("=")
                    geometry[key] = int(value)
            
            # Capture using import
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                temp_path = f.name
            
            subprocess.run(
                ["import", "-window", window_id, temp_path],
                check=True,
            )
            
            from PIL import Image
            img = Image.open(temp_path)
            result = CaptureResult.from_pil_image(
                img,
                format=format,
                source="active_window",
                metadata={
                    "window_id": window_id,
                    "geometry": geometry,
                },
            )
            
            Path(temp_path).unlink(missing_ok=True)
            return result
            
        except Exception as e:
            logger.debug(f"X11 active window capture failed: {e}")
        
        # macOS
        try:
            import subprocess
            import tempfile
            
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                temp_path = f.name
            
            subprocess.run(
                ["screencapture", "-l", "$(osascript -e 'tell app \"System Events\" to id of first window of (first process whose frontmost is true)')", temp_path],
                shell=True,
                check=True,
            )
            
            from PIL import Image
            img = Image.open(temp_path)
            result = CaptureResult.from_pil_image(
                img,
                format=format,
                source="active_window",
            )
            
            Path(temp_path).unlink(missing_ok=True)
            return result
            
        except Exception:
            pass
        
        # Fallback to full screen
        logger.warning("Active window capture not supported, capturing full screen")
        return capture_screen(format=format)
        
    except Exception as e:
        logger.error(f"Active window capture failed: {e}")
        raise


def _find_window_by_name(name: str) -> Optional[int]:
    """Find window ID by name/title."""
    try:
        import subprocess
        
        # Use xdotool to search
        result = subprocess.run(
            ["xdotool", "search", "--name", name],
            capture_output=True,
            text=True,
        )
        
        windows = result.stdout.strip().split("\n")
        if windows and windows[0]:
            return int(windows[0])
        
        return None
        
    except Exception:
        return None


# =============================================================================
# Mock Implementation for Testing
# =============================================================================


class MockScreenCapture:
    """Mock screen capture for testing."""
    
    def __init__(self, width: int = 1920, height: int = 1080):
        self.width = width
        self.height = height
        self._capture_count = 0
    
    def capture_screen(self, monitor: int = 0, format: str = "PNG") -> CaptureResult:
        """Mock screen capture."""
        self._capture_count += 1
        return self._create_mock_result("screen", format)
    
    def capture_region(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        format: str = "PNG",
    ) -> CaptureResult:
        """Mock region capture."""
        self._capture_count += 1
        return CaptureResult(
            image_bytes=self._create_mock_image(width, height, format),
            width=width,
            height=height,
            format=format,
            source="region",
            metadata={"x": x, "y": y, "mock": True},
        )
    
    def capture_active_window(self, format: str = "PNG") -> CaptureResult:
        """Mock active window capture."""
        self._capture_count += 1
        return self._create_mock_result("active_window", format, width=800, height=600)
    
    def get_screen_info(self) -> List[ScreenInfo]:
        """Mock screen info."""
        return [
            ScreenInfo(
                index=0,
                width=self.width,
                height=self.height,
                is_primary=True,
                name="Mock Monitor",
            ),
        ]
    
    def _create_mock_result(
        self,
        source: str,
        format: str,
        width: int = None,
        height: int = None,
    ) -> CaptureResult:
        """Create mock capture result."""
        w = width or self.width
        h = height or self.height
        return CaptureResult(
            image_bytes=self._create_mock_image(w, h, format),
            width=w,
            height=h,
            format=format,
            source=source,
            metadata={"mock": True, "capture_count": self._capture_count},
        )
    
    def _create_mock_image(self, width: int, height: int, format: str) -> bytes:
        """Create a mock image."""
        try:
            from PIL import Image
            img = Image.new("RGB", (width, height), color=(100, 100, 100))
            buffer = io.BytesIO()
            img.save(buffer, format=format)
            return buffer.getvalue()
        except ImportError:
            # Return minimal PNG header if PIL not available
            return b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
