"""
XDG Desktop Integration.

Provides integration with Linux desktop environments:
- Desktop file installation
- MIME handler registration
- Protocol handler (bantz://)
- Desktop shortcuts
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any
import logging
import os
import subprocess
import shutil

logger = logging.getLogger(__name__)


@dataclass
class XDGPaths:
    """XDG Base Directory paths."""
    
    config_home: Path = field(default_factory=lambda: Path(
        os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    ))
    data_home: Path = field(default_factory=lambda: Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    ))
    cache_home: Path = field(default_factory=lambda: Path(
        os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
    ))
    state_home: Path = field(default_factory=lambda: Path(
        os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")
    ))
    
    @property
    def applications_dir(self) -> Path:
        """Get applications directory."""
        return self.data_home / "applications"
    
    @property
    def icons_dir(self) -> Path:
        """Get icons directory."""
        return self.data_home / "icons"
    
    @property
    def mime_dir(self) -> Path:
        """Get MIME directory."""
        return self.data_home / "mime"
    
    @property
    def autostart_dir(self) -> Path:
        """Get autostart directory."""
        return self.config_home / "autostart"
    
    def ensure_dirs(self) -> None:
        """Ensure all XDG directories exist."""
        for path in [
            self.config_home,
            self.data_home,
            self.cache_home,
            self.state_home,
            self.applications_dir,
            self.icons_dir,
            self.autostart_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)


@dataclass
class MimeHandler:
    """MIME type handler registration."""
    
    mime_type: str
    name: str
    exec_command: str
    icon: str = ""
    comment: str = ""
    
    def to_desktop_entry(self) -> str:
        """Generate .desktop file content."""
        lines = [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={self.name}",
            f"Exec={self.exec_command}",
            f"MimeType={self.mime_type}",
            "Terminal=false",
            "NoDisplay=true",
        ]
        
        if self.icon:
            lines.append(f"Icon={self.icon}")
        if self.comment:
            lines.append(f"Comment={self.comment}")
        
        return "\n".join(lines) + "\n"


class DesktopIntegration:
    """
    XDG desktop integration utilities.
    
    Provides:
    - Desktop file installation for application menu
    - Protocol handler registration (bantz://)
    - MIME type handler registration
    - Desktop shortcut creation
    - Icon installation
    
    Example:
        integration = DesktopIntegration()
        integration.install_desktop_file()
        integration.register_protocol_handler()
    """
    
    APP_ID = "com.bantz.assistant"
    APP_NAME = "Bantz Assistant"
    APP_COMMENT = "Personal AI Assistant"
    PROTOCOL = "bantz"
    
    DESKTOP_ENTRY_TEMPLATE = """[Desktop Entry]
Version=1.1
Type=Application
Name={name}
GenericName=AI Assistant
Comment={comment}
Exec={executable} %u
Icon={icon}
Terminal=false
Categories=Utility;Accessibility;
Keywords=assistant;ai;voice;automation;
StartupNotify=true
StartupWMClass=bantz
Actions=voice;text;settings;

[Desktop Action voice]
Name=Sesli Komut
Exec={executable} --voice

[Desktop Action text]
Name=Yazılı Komut
Exec={executable} --text

[Desktop Action settings]
Name=Ayarlar
Exec={executable} --settings
"""
    
    PROTOCOL_HANDLER_TEMPLATE = """[Desktop Entry]
Type=Application
Name=Bantz Protocol Handler
Exec={executable} --uri %u
MimeType=x-scheme-handler/{protocol};
NoDisplay=true
"""
    
    def __init__(
        self,
        executable: Optional[str] = None,
        icon_path: Optional[str] = None,
    ):
        """
        Initialize desktop integration.
        
        Args:
            executable: Path to Bantz executable
            icon_path: Path to icon file
        """
        self.executable = executable or "bantz"
        self.icon_path = icon_path or ""
        self.xdg = XDGPaths()
    
    def install_desktop_file(self) -> bool:
        """
        Install .desktop file for application menu.
        
        Returns:
            True if successful
        """
        try:
            self.xdg.ensure_dirs()
            
            content = self.DESKTOP_ENTRY_TEMPLATE.format(
                name=self.APP_NAME,
                comment=self.APP_COMMENT,
                executable=self.executable,
                icon=self.icon_path or self.APP_ID,
            )
            
            desktop_file = self.xdg.applications_dir / f"{self.APP_ID}.desktop"
            desktop_file.write_text(content)
            desktop_file.chmod(0o755)
            
            # Update desktop database
            self._update_desktop_database()
            
            logger.info(f"Desktop file installed: {desktop_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to install desktop file: {e}")
            return False
    
    def uninstall_desktop_file(self) -> bool:
        """Remove .desktop file."""
        try:
            desktop_file = self.xdg.applications_dir / f"{self.APP_ID}.desktop"
            
            if desktop_file.exists():
                desktop_file.unlink()
                self._update_desktop_database()
                logger.info(f"Desktop file removed: {desktop_file}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to uninstall desktop file: {e}")
            return False
    
    def register_protocol_handler(self) -> bool:
        """
        Register as handler for bantz:// protocol.
        
        Returns:
            True if successful
        """
        try:
            self.xdg.ensure_dirs()
            
            content = self.PROTOCOL_HANDLER_TEMPLATE.format(
                executable=self.executable,
                protocol=self.PROTOCOL,
            )
            
            desktop_file = self.xdg.applications_dir / f"{self.APP_ID}-handler.desktop"
            desktop_file.write_text(content)
            
            # Register as default handler
            self._set_default_handler(f"x-scheme-handler/{self.PROTOCOL}", desktop_file.name)
            
            # Update MIME database
            self._update_mime_database()
            
            logger.info(f"Protocol handler registered: {self.PROTOCOL}://")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register protocol handler: {e}")
            return False
    
    def unregister_protocol_handler(self) -> bool:
        """Unregister protocol handler."""
        try:
            desktop_file = self.xdg.applications_dir / f"{self.APP_ID}-handler.desktop"
            
            if desktop_file.exists():
                desktop_file.unlink()
                self._update_mime_database()
                logger.info("Protocol handler unregistered")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to unregister protocol handler: {e}")
            return False
    
    def register_mime_handler(self, handler: MimeHandler) -> bool:
        """
        Register as handler for a MIME type.
        
        Args:
            handler: MIME handler configuration
            
        Returns:
            True if successful
        """
        try:
            self.xdg.ensure_dirs()
            
            # Create .desktop file for handler
            filename = f"{self.APP_ID}-{handler.mime_type.replace('/', '-')}.desktop"
            desktop_file = self.xdg.applications_dir / filename
            desktop_file.write_text(handler.to_desktop_entry())
            
            # Set as default handler
            self._set_default_handler(handler.mime_type, filename)
            self._update_mime_database()
            
            logger.info(f"MIME handler registered: {handler.mime_type}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register MIME handler: {e}")
            return False
    
    def install_icon(
        self,
        source_path: str,
        sizes: Optional[List[int]] = None,
    ) -> bool:
        """
        Install application icon.
        
        Args:
            source_path: Path to source icon (PNG or SVG)
            sizes: Icon sizes to install (default: [16, 24, 32, 48, 64, 128, 256])
            
        Returns:
            True if successful
        """
        if sizes is None:
            sizes = [16, 24, 32, 48, 64, 128, 256]
        
        source = Path(source_path)
        if not source.exists():
            logger.error(f"Icon source not found: {source_path}")
            return False
        
        try:
            self.xdg.ensure_dirs()
            
            is_svg = source.suffix.lower() == ".svg"
            
            if is_svg:
                # Install SVG to scalable
                scalable_dir = self.xdg.icons_dir / "hicolor" / "scalable" / "apps"
                scalable_dir.mkdir(parents=True, exist_ok=True)
                
                dest = scalable_dir / f"{self.APP_ID}.svg"
                shutil.copy2(source, dest)
                logger.debug(f"Installed scalable icon: {dest}")
            else:
                # Install PNG at various sizes
                for size in sizes:
                    size_dir = self.xdg.icons_dir / "hicolor" / f"{size}x{size}" / "apps"
                    size_dir.mkdir(parents=True, exist_ok=True)
                    
                    dest = size_dir / f"{self.APP_ID}.png"
                    
                    # Try to resize if pillow is available
                    try:
                        from PIL import Image
                        with Image.open(source) as img:
                            resized = img.resize((size, size), Image.LANCZOS)
                            resized.save(dest)
                    except ImportError:
                        # Just copy the original
                        shutil.copy2(source, dest)
                    
                    logger.debug(f"Installed {size}x{size} icon: {dest}")
            
            # Update icon cache
            self._update_icon_cache()
            
            logger.info(f"Icons installed for {self.APP_ID}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to install icon: {e}")
            return False
    
    def create_desktop_shortcut(self, desktop_path: Optional[Path] = None) -> bool:
        """
        Create desktop shortcut.
        
        Args:
            desktop_path: Path to desktop folder (auto-detected if None)
            
        Returns:
            True if successful
        """
        try:
            # Find desktop folder
            if desktop_path is None:
                desktop_path = self._find_desktop_folder()
            
            if not desktop_path:
                logger.error("Could not find desktop folder")
                return False
            
            # Ensure desktop file exists
            source = self.xdg.applications_dir / f"{self.APP_ID}.desktop"
            if not source.exists():
                self.install_desktop_file()
            
            # Copy to desktop
            dest = desktop_path / f"{self.APP_ID}.desktop"
            shutil.copy2(source, dest)
            dest.chmod(0o755)
            
            # Mark as trusted (GNOME)
            self._trust_desktop_file(dest)
            
            logger.info(f"Desktop shortcut created: {dest}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create desktop shortcut: {e}")
            return False
    
    def remove_desktop_shortcut(self, desktop_path: Optional[Path] = None) -> bool:
        """Remove desktop shortcut."""
        try:
            if desktop_path is None:
                desktop_path = self._find_desktop_folder()
            
            if not desktop_path:
                return True
            
            shortcut = desktop_path / f"{self.APP_ID}.desktop"
            if shortcut.exists():
                shortcut.unlink()
                logger.info("Desktop shortcut removed")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove desktop shortcut: {e}")
            return False
    
    def is_installed(self) -> Dict[str, bool]:
        """
        Check installation status.
        
        Returns:
            Dict with status of each component
        """
        desktop_file = self.xdg.applications_dir / f"{self.APP_ID}.desktop"
        handler_file = self.xdg.applications_dir / f"{self.APP_ID}-handler.desktop"
        
        # Check for icon
        icon_exists = False
        for subdir in ["scalable/apps", "48x48/apps", "256x256/apps"]:
            icon_dir = self.xdg.icons_dir / "hicolor" / subdir
            if (icon_dir / f"{self.APP_ID}.svg").exists() or \
               (icon_dir / f"{self.APP_ID}.png").exists():
                icon_exists = True
                break
        
        desktop_shortcut = False
        desktop_folder = self._find_desktop_folder()
        if desktop_folder:
            desktop_shortcut = (desktop_folder / f"{self.APP_ID}.desktop").exists()
        
        return {
            "desktop_file": desktop_file.exists(),
            "protocol_handler": handler_file.exists(),
            "icon": icon_exists,
            "desktop_shortcut": desktop_shortcut,
        }
    
    def install_all(self, icon_source: Optional[str] = None) -> bool:
        """
        Install all desktop integrations.
        
        Args:
            icon_source: Path to icon file
            
        Returns:
            True if all successful
        """
        success = True
        
        success = self.install_desktop_file() and success
        success = self.register_protocol_handler() and success
        
        if icon_source:
            success = self.install_icon(icon_source) and success
        
        return success
    
    def uninstall_all(self) -> bool:
        """Remove all desktop integrations."""
        success = True
        
        success = self.uninstall_desktop_file() and success
        success = self.unregister_protocol_handler() and success
        success = self.remove_desktop_shortcut() and success
        
        return success
    
    def _find_desktop_folder(self) -> Optional[Path]:
        """Find the user's desktop folder."""
        # Try XDG user dirs
        try:
            result = subprocess.run(
                ["xdg-user-dir", "DESKTOP"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                path = Path(result.stdout.strip())
                if path.exists():
                    return path
        except Exception:
            pass
        
        # Common fallbacks
        for name in ["Desktop", "Masaüstü", "Escritorio", "Bureau"]:
            path = Path.home() / name
            if path.exists():
                return path
        
        return None
    
    def _update_desktop_database(self) -> None:
        """Update desktop file database."""
        try:
            subprocess.run(
                ["update-desktop-database", str(self.xdg.applications_dir)],
                capture_output=True,
            )
        except Exception as e:
            logger.debug(f"Could not update desktop database: {e}")
    
    def _update_mime_database(self) -> None:
        """Update MIME database."""
        try:
            subprocess.run(
                ["update-mime-database", str(self.xdg.mime_dir)],
                capture_output=True,
            )
        except Exception as e:
            logger.debug(f"Could not update MIME database: {e}")
    
    def _update_icon_cache(self) -> None:
        """Update icon cache."""
        try:
            subprocess.run(
                ["gtk-update-icon-cache", "-f", "-t", str(self.xdg.icons_dir / "hicolor")],
                capture_output=True,
            )
        except Exception as e:
            logger.debug(f"Could not update icon cache: {e}")
    
    def _set_default_handler(self, mime_type: str, desktop_file: str) -> None:
        """Set default handler for MIME type."""
        try:
            subprocess.run(
                ["xdg-mime", "default", desktop_file, mime_type],
                capture_output=True,
            )
        except Exception as e:
            logger.debug(f"Could not set default handler: {e}")
    
    def _trust_desktop_file(self, path: Path) -> None:
        """Mark desktop file as trusted (GNOME)."""
        try:
            subprocess.run(
                ["gio", "set", str(path), "metadata::trusted", "true"],
                capture_output=True,
            )
        except Exception as e:
            logger.debug(f"Could not trust desktop file: {e}")


class MockDesktopIntegration(DesktopIntegration):
    """Mock desktop integration for testing."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._installed_files: List[str] = []
        self._handlers: Dict[str, str] = {}
        self._icons: List[str] = []
    
    def install_desktop_file(self) -> bool:
        self._installed_files.append("desktop")
        return True
    
    def uninstall_desktop_file(self) -> bool:
        if "desktop" in self._installed_files:
            self._installed_files.remove("desktop")
        return True
    
    def register_protocol_handler(self) -> bool:
        self._handlers[self.PROTOCOL] = self.executable
        return True
    
    def unregister_protocol_handler(self) -> bool:
        self._handlers.pop(self.PROTOCOL, None)
        return True
    
    def register_mime_handler(self, handler: MimeHandler) -> bool:
        self._handlers[handler.mime_type] = handler.exec_command
        return True
    
    def install_icon(self, source_path: str, sizes: Optional[List[int]] = None) -> bool:
        self._icons.append(source_path)
        return True
    
    def create_desktop_shortcut(self, desktop_path: Optional[Path] = None) -> bool:
        self._installed_files.append("shortcut")
        return True
    
    def remove_desktop_shortcut(self, desktop_path: Optional[Path] = None) -> bool:
        if "shortcut" in self._installed_files:
            self._installed_files.remove("shortcut")
        return True
    
    def is_installed(self) -> Dict[str, bool]:
        return {
            "desktop_file": "desktop" in self._installed_files,
            "protocol_handler": self.PROTOCOL in self._handlers,
            "icon": len(self._icons) > 0,
            "desktop_shortcut": "shortcut" in self._installed_files,
        }
