"""
Auto-start Configuration.

Manages auto-start on login via XDG autostart specification.
Creates/manages .desktop files in ~/.config/autostart/
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any
import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)


@dataclass
class AutoStartConfig:
    """Configuration for auto-start entry."""
    
    name: str = "Bantz Assistant"
    comment: str = "Personal AI Assistant"
    executable: str = "bantz"
    icon: str = ""
    terminal: bool = False
    categories: str = "Utility;Accessibility;"
    startup_notify: bool = False
    gnome_autostart_enabled: bool = True
    hidden: bool = False
    extra_args: str = ""
    working_directory: str = ""
    environment: Dict[str, str] = field(default_factory=dict)
    
    def to_desktop_entry(self) -> str:
        """Generate .desktop file content."""
        lines = [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={self.name}",
            f"Comment={self.comment}",
        ]
        
        # Build exec line
        exec_cmd = self.executable
        if self.extra_args:
            exec_cmd = f"{exec_cmd} {self.extra_args}"
        lines.append(f"Exec={exec_cmd}")
        
        if self.icon:
            lines.append(f"Icon={self.icon}")
        
        lines.extend([
            f"Terminal={'true' if self.terminal else 'false'}",
            f"Categories={self.categories}",
            f"StartupNotify={'true' if self.startup_notify else 'false'}",
            f"X-GNOME-Autostart-enabled={'true' if self.gnome_autostart_enabled else 'false'}",
        ])
        
        if self.hidden:
            lines.append("Hidden=true")
        
        if self.working_directory:
            lines.append(f"Path={self.working_directory}")
        
        # Add environment variables
        for key, value in self.environment.items():
            lines.append(f"X-Env-{key}={value}")
        
        return "\n".join(lines) + "\n"


class AutoStart:
    """
    Configure auto-start on login.
    
    Uses XDG autostart specification:
    - ~/.config/autostart/ for user-specific autostart
    - /etc/xdg/autostart/ for system-wide autostart
    
    Example:
        # Enable auto-start
        AutoStart.enable()
        
        # Check status
        if AutoStart.is_enabled():
            print("Auto-start is enabled")
        
        # Disable
        AutoStart.disable()
    """
    
    DESKTOP_FILENAME = "bantz.desktop"
    DEFAULT_EXECUTABLE = "bantz"
    
    @classmethod
    def get_autostart_dir(cls, system_wide: bool = False) -> Path:
        """
        Get autostart directory path.
        
        Args:
            system_wide: If True, return system directory
            
        Returns:
            Path to autostart directory
        """
        if system_wide:
            return Path("/etc/xdg/autostart")
        else:
            # User directory
            xdg_config = os.environ.get("XDG_CONFIG_HOME")
            if xdg_config:
                return Path(xdg_config) / "autostart"
            else:
                return Path.home() / ".config" / "autostart"
    
    @classmethod
    def get_desktop_file_path(cls, system_wide: bool = False) -> Path:
        """Get path to .desktop file."""
        return cls.get_autostart_dir(system_wide) / cls.DESKTOP_FILENAME
    
    @classmethod
    def enable(
        cls,
        config: Optional[AutoStartConfig] = None,
        executable_path: Optional[str] = None,
        icon_path: Optional[str] = None,
    ) -> bool:
        """
        Enable auto-start on login.
        
        Args:
            config: Full configuration (if provided, other args ignored)
            executable_path: Path to executable
            icon_path: Path to icon
            
        Returns:
            True if successful
        """
        if config is None:
            config = AutoStartConfig()
            if executable_path:
                config.executable = executable_path
            if icon_path:
                config.icon = icon_path
        
        try:
            # Ensure autostart directory exists
            autostart_dir = cls.get_autostart_dir()
            autostart_dir.mkdir(parents=True, exist_ok=True)
            
            # Write desktop file
            desktop_file = autostart_dir / cls.DESKTOP_FILENAME
            desktop_file.write_text(config.to_desktop_entry())
            
            # Make executable (not strictly required but good practice)
            desktop_file.chmod(0o644)
            
            logger.info(f"Auto-start enabled: {desktop_file}")
            return True
            
        except PermissionError:
            logger.error("Permission denied writing autostart file")
            return False
        except Exception as e:
            logger.error(f"Failed to enable auto-start: {e}")
            return False
    
    @classmethod
    def disable(cls) -> bool:
        """
        Disable auto-start.
        
        Returns:
            True if successful
        """
        try:
            desktop_file = cls.get_desktop_file_path()
            
            if desktop_file.exists():
                desktop_file.unlink()
                logger.info(f"Auto-start disabled: {desktop_file}")
            else:
                logger.debug("Auto-start was not enabled")
            
            return True
            
        except PermissionError:
            logger.error("Permission denied removing autostart file")
            return False
        except Exception as e:
            logger.error(f"Failed to disable auto-start: {e}")
            return False
    
    @classmethod
    def is_enabled(cls) -> bool:
        """
        Check if auto-start is enabled.
        
        Returns:
            True if auto-start is configured
        """
        desktop_file = cls.get_desktop_file_path()
        
        if not desktop_file.exists():
            return False
        
        # Check if explicitly disabled via Hidden or X-GNOME-Autostart-enabled
        try:
            content = desktop_file.read_text()
            
            if "Hidden=true" in content:
                return False
            
            if "X-GNOME-Autostart-enabled=false" in content:
                return False
            
            return True
            
        except Exception:
            return False
    
    @classmethod
    def get_config(cls) -> Optional[AutoStartConfig]:
        """
        Get current auto-start configuration.
        
        Returns:
            AutoStartConfig if enabled, None otherwise
        """
        desktop_file = cls.get_desktop_file_path()
        
        if not desktop_file.exists():
            return None
        
        try:
            content = desktop_file.read_text()
            return cls._parse_desktop_file(content)
        except Exception as e:
            logger.error(f"Failed to read autostart config: {e}")
            return None
    
    @classmethod
    def _parse_desktop_file(cls, content: str) -> AutoStartConfig:
        """Parse .desktop file content into config."""
        config = AutoStartConfig()
        
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("["):
                continue
            
            if "=" not in line:
                continue
            
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            
            if key == "Name":
                config.name = value
            elif key == "Comment":
                config.comment = value
            elif key == "Exec":
                # Parse exec and extra args
                parts = value.split(" ", 1)
                config.executable = parts[0]
                if len(parts) > 1:
                    config.extra_args = parts[1]
            elif key == "Icon":
                config.icon = value
            elif key == "Terminal":
                config.terminal = value.lower() == "true"
            elif key == "Categories":
                config.categories = value
            elif key == "StartupNotify":
                config.startup_notify = value.lower() == "true"
            elif key == "X-GNOME-Autostart-enabled":
                config.gnome_autostart_enabled = value.lower() == "true"
            elif key == "Hidden":
                config.hidden = value.lower() == "true"
            elif key == "Path":
                config.working_directory = value
            elif key.startswith("X-Env-"):
                env_key = key[6:]  # Remove "X-Env-" prefix
                config.environment[env_key] = value
        
        return config
    
    @classmethod
    def set_enabled(cls, enabled: bool, **kwargs) -> bool:
        """
        Set auto-start enabled/disabled.
        
        Args:
            enabled: Whether to enable auto-start
            **kwargs: Passed to enable() if enabling
            
        Returns:
            True if successful
        """
        if enabled:
            return cls.enable(**kwargs)
        else:
            return cls.disable()
    
    @classmethod
    def toggle(cls) -> bool:
        """
        Toggle auto-start state.
        
        Returns:
            New enabled state
        """
        if cls.is_enabled():
            cls.disable()
            return False
        else:
            cls.enable()
            return True
    
    @classmethod
    def find_executable(cls) -> Optional[str]:
        """
        Find the Bantz executable path.
        
        Returns:
            Path to executable or None
        """
        # Try which command
        try:
            result = subprocess.run(
                ["which", "bantz"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        
        # Try common locations
        common_paths = [
            Path.home() / ".local" / "bin" / "bantz",
            Path("/usr/local/bin/bantz"),
            Path("/usr/bin/bantz"),
        ]
        
        for path in common_paths:
            if path.exists() and os.access(path, os.X_OK):
                return str(path)
        
        # Try pip show
        try:
            result = subprocess.run(
                ["pip", "show", "-f", "bantz"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                # Parse output for script location
                for line in result.stdout.split("\n"):
                    if "bantz" in line and "bin" in line:
                        return line.strip()
        except Exception:
            pass
        
        return None
    
    @classmethod
    def verify_executable(cls, path: str) -> bool:
        """
        Verify that path is a valid executable.
        
        Args:
            path: Path to check
            
        Returns:
            True if valid executable
        """
        path_obj = Path(path)
        return path_obj.exists() and os.access(path_obj, os.X_OK)
    
    @classmethod
    def backup_existing(cls) -> Optional[Path]:
        """
        Backup existing autostart file.
        
        Returns:
            Path to backup file or None
        """
        desktop_file = cls.get_desktop_file_path()
        
        if not desktop_file.exists():
            return None
        
        try:
            backup_path = desktop_file.with_suffix(".desktop.bak")
            shutil.copy2(desktop_file, backup_path)
            return backup_path
        except Exception as e:
            logger.error(f"Failed to backup autostart file: {e}")
            return None
    
    @classmethod
    def restore_backup(cls) -> bool:
        """
        Restore from backup.
        
        Returns:
            True if successful
        """
        desktop_file = cls.get_desktop_file_path()
        backup_path = desktop_file.with_suffix(".desktop.bak")
        
        if not backup_path.exists():
            logger.warning("No backup file found")
            return False
        
        try:
            shutil.copy2(backup_path, desktop_file)
            return True
        except Exception as e:
            logger.error(f"Failed to restore backup: {e}")
            return False
