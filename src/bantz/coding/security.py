"""Security rules for coding agent (Issue #4).

Implements:
- Command deny list (NEVER_ALLOW)
- Confirmation required patterns (REQUIRE_CONFIRM)
- Path sandboxing (ALLOWED_PATHS)
- File type restrictions
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class SecurityError(Exception):
    """Raised when a security rule is violated."""
    pass


class ConfirmationRequired(Exception):
    """Raised when user confirmation is needed."""
    
    def __init__(self, message: str, command: str = "", reason: str = ""):
        super().__init__(message)
        self.command = command
        self.reason = reason


@dataclass
class SecurityPolicy:
    """Security policy for coding operations.
    
    Features:
    - Command blacklist (never execute)
    - Command greylist (require confirmation)
    - Path sandbox (restrict file access)
    - File type restrictions
    """
    
    workspace_root: Path
    extra_allowed_paths: list[Path] = field(default_factory=list)
    
    # ─────────────────────────────────────────────────────────────────
    # NEVER ALLOW - These commands are blocked unconditionally
    # ─────────────────────────────────────────────────────────────────
    NEVER_ALLOW_PATTERNS: tuple[str, ...] = (
        r"rm\s+-rf\s+/\s*$",                    # rm -rf /
        r"rm\s+-rf\s+/\*",                      # rm -rf /*
        r"rm\s+-rf\s+~\s*$",                    # rm -rf ~
        r"rm\s+-rf\s+\$HOME",                   # rm -rf $HOME
        r">\s*/dev/sd[a-z]",                    # Write to disk device
        r"dd\s+if=.*of=/dev/sd[a-z]",           # dd to disk
        r"mkfs\.",                              # Format filesystem
        r"chmod\s+-R\s+777\s+/\s*$",            # chmod -R 777 /
        r"chmod\s+-R\s+777\s+/\*",              # chmod -R 777 /*
        r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;", # Fork bomb
        r"curl.*\|\s*(?:ba)?sh",                # Pipe curl to shell
        r"wget.*\|\s*(?:ba)?sh",                # Pipe wget to shell
        r"/dev/null\s*>\s*/etc/passwd",         # Destroy passwd
        r">\s*/etc/passwd",                     # Overwrite passwd
        r">\s*/etc/shadow",                     # Overwrite shadow
        r"shutdown\s",                          # Shutdown system
        r"reboot\s*$",                          # Reboot system
        r"init\s+[06]",                         # Init runlevel change
        r"systemctl\s+(?:poweroff|halt)",       # Systemd shutdown
    )
    
    # ─────────────────────────────────────────────────────────────────
    # REQUIRE CONFIRMATION - These commands need user approval
    # ─────────────────────────────────────────────────────────────────
    CONFIRM_PATTERNS: tuple[str, ...] = (
        r"\brm\s+",                             # Any rm command
        r"\bsudo\s+",                           # Sudo commands
        r"\bapt\s+(?:install|remove|purge)",    # Apt install/remove
        r"\bapt-get\s+(?:install|remove)",      # Apt-get
        r"\bpip\s+install",                     # Pip install
        r"\bpip3?\s+uninstall",                 # Pip uninstall
        r"\bnpm\s+install",                     # Npm install
        r"\bnpm\s+uninstall",                   # Npm uninstall
        r"\byarn\s+add",                        # Yarn add
        r"\bgit\s+push",                        # Git push
        r"\bgit\s+reset\s+--hard",              # Git reset --hard
        r"\bgit\s+checkout\s+--\s+\.",          # Git checkout all
        r"\bgit\s+clean\s+-[fd]",               # Git clean
        r"\bmv\s+",                             # Move files
        r"\bcp\s+-r",                           # Recursive copy
        r"\bchmod\s+",                          # Change permissions
        r"\bchown\s+",                          # Change ownership
        r"\bkill\s+",                           # Kill process
        r"\bpkill\s+",                          # Kill by name
        r"\bkillall\s+",                        # Kill all
        r"\bsystemctl\s+(?:start|stop|restart)", # Systemd control
        r"\bservice\s+.*(?:start|stop|restart)", # Service control
        r"\bdocker\s+(?:rm|rmi|stop|kill)",     # Docker destructive
        r"\bcurl\s+.*-o",                       # Curl download
        r"\bwget\s+",                           # Wget download
    )
    
    # ─────────────────────────────────────────────────────────────────
    # FILE RESTRICTIONS
    # ─────────────────────────────────────────────────────────────────
    NEVER_WRITE_PATTERNS: tuple[str, ...] = (
        r"^/etc/",                              # System config
        r"^/boot/",                             # Boot files
        r"^/sys/",                              # Sysfs
        r"^/proc/",                             # Procfs
        r"^/dev/",                              # Devices
        r"^/usr/",                              # System binaries
        r"^/bin/",                              # Core binaries
        r"^/sbin/",                             # System binaries
        r"^/lib/",                              # Libraries
        r"^/var/log/",                          # System logs
        r"\.ssh/",                              # SSH keys
        r"\.gnupg/",                            # GPG keys
        r"\.aws/",                              # AWS credentials
        r"\.kube/",                             # Kubernetes config
        r"id_rsa",                              # SSH private key
        r"\.pem$",                              # Certificate files
        r"\.key$",                              # Key files
    )
    
    NEVER_READ_PATTERNS: tuple[str, ...] = (
        r"\.ssh/id_",                           # SSH private keys
        r"\.gnupg/",                            # GPG keys
        r"\.aws/credentials",                   # AWS credentials
        r"/etc/shadow",                         # Shadow file
        r"/etc/gshadow",                        # Group shadow
    )
    
    # File extensions that are safe to edit
    SAFE_EXTENSIONS: frozenset[str] = frozenset({
        ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml",
        ".toml", ".ini", ".cfg", ".conf", ".md", ".txt", ".rst",
        ".html", ".css", ".scss", ".less", ".xml", ".svg",
        ".sh", ".bash", ".zsh", ".fish",
        ".rs", ".go", ".java", ".kt", ".scala", ".c", ".cpp", ".h", ".hpp",
        ".rb", ".php", ".pl", ".lua", ".vim", ".sql",
        ".dockerfile", ".gitignore", ".gitattributes", ".editorconfig",
        ".env.example", ".env.sample", ".env.template",
        "Makefile", "Dockerfile", "Procfile", "Gemfile", "Rakefile",
    })
    
    # Binary/dangerous extensions
    NEVER_EDIT_EXTENSIONS: frozenset[str] = frozenset({
        ".exe", ".dll", ".so", ".dylib", ".a", ".o", ".obj",
        ".pyc", ".pyo", ".class", ".jar", ".war",
        ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
        ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".flac",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".db", ".sqlite", ".sqlite3",
        ".pem", ".key", ".crt", ".cer",
    })
    
    # ─────────────────────────────────────────────────────────────────
    # Compiled patterns (lazy)
    # ─────────────────────────────────────────────────────────────────
    _never_allow_re: Optional[re.Pattern] = field(default=None, repr=False)
    _confirm_re: Optional[re.Pattern] = field(default=None, repr=False)
    _never_write_re: Optional[re.Pattern] = field(default=None, repr=False)
    _never_read_re: Optional[re.Pattern] = field(default=None, repr=False)
    
    def __post_init__(self):
        self._never_allow_re = re.compile("|".join(f"({p})" for p in self.NEVER_ALLOW_PATTERNS), re.IGNORECASE)
        self._confirm_re = re.compile("|".join(f"({p})" for p in self.CONFIRM_PATTERNS), re.IGNORECASE)
        self._never_write_re = re.compile("|".join(f"({p})" for p in self.NEVER_WRITE_PATTERNS))
        self._never_read_re = re.compile("|".join(f"({p})" for p in self.NEVER_READ_PATTERNS))
    
    # ─────────────────────────────────────────────────────────────────
    # Command Checks
    # ─────────────────────────────────────────────────────────────────
    def check_command(self, command: str, *, confirmed: bool = False) -> tuple[bool, str]:
        """Check if a command is allowed.
        
        Returns:
            (allowed, reason)
        """
        cmd = command.strip()
        
        # Check deny list
        if self._never_allow_re and self._never_allow_re.search(cmd):
            return False, "command_denied"
        
        # Check confirmation required
        if not confirmed and self._confirm_re and self._confirm_re.search(cmd):
            return False, "confirmation_required"
        
        return True, "allowed"
    
    def is_command_denied(self, command: str) -> bool:
        """Check if command is in deny list."""
        return bool(self._never_allow_re and self._never_allow_re.search(command.strip()))
    
    def needs_confirmation(self, command: str) -> bool:
        """Check if command needs user confirmation."""
        if self.is_command_denied(command):
            return False  # Denied, not confirmable
        return bool(self._confirm_re and self._confirm_re.search(command.strip()))
    
    # ─────────────────────────────────────────────────────────────────
    # Path Checks
    # ─────────────────────────────────────────────────────────────────
    def is_path_allowed(self, path: str | Path, *, for_write: bool = False) -> tuple[bool, str]:
        """Check if a path is within the sandbox.
        
        Args:
            path: File or directory path
            for_write: Whether this is a write operation
            
        Returns:
            (allowed, reason)
        """
        try:
            p = Path(path).resolve()
        except Exception:
            return False, "invalid_path"
        
        path_str = str(p)
        
        # Check never-read patterns
        if self._never_read_re and self._never_read_re.search(path_str):
            return False, "path_forbidden_read"
        
        # Check never-write patterns (for write ops)
        if for_write and self._never_write_re and self._never_write_re.search(path_str):
            return False, "path_forbidden_write"
        
        # Check sandbox
        allowed_roots = [self.workspace_root.resolve()] + [
            ap.resolve() for ap in self.extra_allowed_paths
        ]
        
        # Also allow ~/.config/bantz
        bantz_config = Path.home() / ".config" / "bantz"
        if bantz_config.exists() or not for_write:
            allowed_roots.append(bantz_config.resolve())
        
        for root in allowed_roots:
            try:
                p.relative_to(root)
                return True, "allowed"
            except ValueError:
                continue
        
        return False, "path_outside_sandbox"
    
    def is_path_writable(self, path: str | Path) -> tuple[bool, str]:
        """Check if path can be written to."""
        return self.is_path_allowed(path, for_write=True)
    
    def is_path_readable(self, path: str | Path) -> tuple[bool, str]:
        """Check if path can be read."""
        return self.is_path_allowed(path, for_write=False)
    
    # ─────────────────────────────────────────────────────────────────
    # File Extension Checks
    # ─────────────────────────────────────────────────────────────────
    def can_edit_file(self, path: str | Path) -> tuple[bool, str]:
        """Check if file type is safe to edit."""
        p = Path(path)
        name = p.name.lower()
        suffix = p.suffix.lower()
        
        # Check banned extensions
        if suffix in self.NEVER_EDIT_EXTENSIONS:
            return False, f"binary_file:{suffix}"
        
        # Dotfiles without extension need special handling
        if name.startswith(".") and not suffix:
            # Allow common dotfiles
            if name in {".gitignore", ".editorconfig", ".eslintrc", ".prettierrc", 
                       ".env.example", ".dockerignore", ".npmrc", ".yarnrc"}:
                return True, "allowed_dotfile"
            # Block sensitive dotfiles
            if name in {".bash_history", ".zsh_history", ".netrc", ".npmrc"}:
                return False, "sensitive_dotfile"
        
        # Check safe extensions
        if suffix in self.SAFE_EXTENSIONS or name in self.SAFE_EXTENSIONS:
            return True, "safe_extension"
        
        # Allow files without extension in workspace (likely scripts)
        if not suffix:
            return True, "no_extension"
        
        # Unknown extension - allow with caution
        return True, "unknown_extension"
    
    # ─────────────────────────────────────────────────────────────────
    # Convenience Methods
    # ─────────────────────────────────────────────────────────────────
    def validate_file_operation(
        self,
        path: str | Path,
        operation: str,  # "read" | "write" | "delete" | "create"
        *,
        confirmed: bool = False,
    ) -> None:
        """Validate a file operation, raising on failure.
        
        Raises:
            SecurityError: If operation is denied
            ConfirmationRequired: If confirmation is needed
        """
        p = Path(path)
        
        # Path sandbox check
        for_write = operation in {"write", "delete", "create"}
        allowed, reason = self.is_path_allowed(p, for_write=for_write)
        if not allowed:
            raise SecurityError(f"Path not allowed: {path} ({reason})")
        
        # File type check for edits
        if operation in {"write", "create"}:
            can_edit, edit_reason = self.can_edit_file(p)
            if not can_edit:
                raise SecurityError(f"Cannot edit file type: {path} ({edit_reason})")
        
        # Delete requires confirmation
        if operation == "delete" and not confirmed:
            raise ConfirmationRequired(
                f"Delete operation requires confirmation: {path}",
                command=f"delete:{path}",
                reason="delete_confirmation",
            )
    
    def validate_command(self, command: str, *, confirmed: bool = False) -> None:
        """Validate a terminal command, raising on failure.
        
        Raises:
            SecurityError: If command is denied
            ConfirmationRequired: If confirmation is needed
        """
        allowed, reason = self.check_command(command, confirmed=confirmed)
        
        if reason == "command_denied":
            raise SecurityError(f"Command denied: {command}")
        
        if reason == "confirmation_required":
            raise ConfirmationRequired(
                f"Command requires confirmation: {command}",
                command=command,
                reason="command_confirmation",
            )
