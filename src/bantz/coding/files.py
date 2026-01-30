"""File operations with backup support (Issue #4).

Features:
- Read files with line range
- Write files with automatic backup
- Edit files (string replacement)
- Create/delete files safely
- Directory listing and search
- Undo support via backups
"""
from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .security import SecurityPolicy, SecurityError, ConfirmationRequired


@dataclass
class FileEdit:
    """Represents a file edit operation for undo/redo."""
    file_path: str
    old_content: str
    new_content: str
    timestamp: float = field(default_factory=time.time)
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    edit_type: str = "replace"  # replace | insert | delete | create | full


@dataclass
class FileInfo:
    """File metadata."""
    path: str
    name: str
    size: int
    is_dir: bool
    is_file: bool
    extension: str
    modified_at: float
    created_at: float
    readable: bool
    writable: bool
    
    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "name": self.name,
            "size": self.size,
            "is_dir": self.is_dir,
            "is_file": self.is_file,
            "extension": self.extension,
            "modified_at": self.modified_at,
            "created_at": self.created_at,
            "readable": self.readable,
            "writable": self.writable,
        }


class FileManager:
    """Safe file operations with backup and undo support.
    
    Features:
    - All operations respect SecurityPolicy sandbox
    - Automatic backups before modifications
    - Undo via backup restoration
    - Line-range reads
    - String replacement edits (Copilot-style)
    """
    
    def __init__(
        self,
        workspace_root: Path,
        *,
        backup_enabled: bool = True,
        max_backups_per_file: int = 10,
        security: Optional[SecurityPolicy] = None,
    ):
        self.root = Path(workspace_root).resolve()
        self.backup_enabled = backup_enabled
        self.max_backups = max_backups_per_file
        self._backup_dir = self.root / ".bantz_backups"
        self._security = security or SecurityPolicy(workspace_root=self.root)
        self._edit_history: list[FileEdit] = []
    
    def _resolve_path(self, path: str | Path) -> Path:
        """Resolve path relative to workspace root."""
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        return p.resolve()
    
    def _ensure_backup_dir(self) -> Path:
        """Create backup directory if needed."""
        if not self._backup_dir.exists():
            self._backup_dir.mkdir(parents=True, exist_ok=True)
            # Add to gitignore
            gitignore = self.root / ".gitignore"
            if gitignore.exists():
                content = gitignore.read_text()
                if ".bantz_backups" not in content:
                    with gitignore.open("a") as f:
                        f.write("\n# Bantz backups\n.bantz_backups/\n")
        return self._backup_dir
    
    def _create_backup(self, file_path: Path) -> Optional[Path]:
        """Create a backup of a file."""
        if not self.backup_enabled or not file_path.exists():
            return None
        
        backup_dir = self._ensure_backup_dir()
        
        # Create backup filename with timestamp
        rel_path = file_path.relative_to(self.root) if file_path.is_relative_to(self.root) else file_path.name
        safe_name = str(rel_path).replace("/", "__").replace("\\", "__")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_name = f"{safe_name}.{timestamp}.bak"
        backup_path = backup_dir / backup_name
        
        shutil.copy2(file_path, backup_path)
        
        # Cleanup old backups
        self._cleanup_old_backups(safe_name)
        
        return backup_path
    
    def _cleanup_old_backups(self, base_name: str) -> None:
        """Keep only the most recent backups for a file."""
        if not self._backup_dir.exists():
            return
        
        pattern = f"{base_name}.*.bak"
        backups = sorted(
            self._backup_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        
        for old_backup in backups[self.max_backups:]:
            try:
                old_backup.unlink()
            except Exception:
                pass
    
    def _get_latest_backup(self, file_path: Path) -> Optional[Path]:
        """Get the most recent backup of a file."""
        if not self._backup_dir.exists():
            return None
        
        rel_path = file_path.relative_to(self.root) if file_path.is_relative_to(self.root) else file_path.name
        safe_name = str(rel_path).replace("/", "__").replace("\\", "__")
        pattern = f"{safe_name}.*.bak"
        
        backups = sorted(
            self._backup_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        
        return backups[0] if backups else None
    
    # ─────────────────────────────────────────────────────────────────
    # Read Operations
    # ─────────────────────────────────────────────────────────────────
    def read_file(
        self,
        path: str,
        start_line: int = 1,
        end_line: int = -1,
    ) -> str:
        """Read file content with optional line range.
        
        Args:
            path: File path (relative or absolute)
            start_line: First line to read (1-indexed, default 1)
            end_line: Last line to read (1-indexed, -1 for EOF)
            
        Returns:
            File content (or line range)
            
        Raises:
            SecurityError: If path is not allowed
            FileNotFoundError: If file doesn't exist
        """
        file_path = self._resolve_path(path)
        
        # Security check
        self._security.validate_file_operation(file_path, "read")
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        if not file_path.is_file():
            raise ValueError(f"Not a file: {path}")
        
        content = file_path.read_text(encoding="utf-8", errors="replace")
        
        # Apply line range
        if start_line > 1 or end_line != -1:
            lines = content.splitlines(keepends=True)
            start_idx = max(0, start_line - 1)
            end_idx = len(lines) if end_line == -1 else min(len(lines), end_line)
            content = "".join(lines[start_idx:end_idx])
        
        return content
    
    def read_lines(self, path: str) -> list[str]:
        """Read file as list of lines."""
        content = self.read_file(path)
        return content.splitlines()
    
    def get_file_info(self, path: str) -> FileInfo:
        """Get file metadata."""
        file_path = self._resolve_path(path)
        
        # Security check (read)
        self._security.validate_file_operation(file_path, "read")
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        stat = file_path.stat()
        
        return FileInfo(
            path=str(file_path),
            name=file_path.name,
            size=stat.st_size,
            is_dir=file_path.is_dir(),
            is_file=file_path.is_file(),
            extension=file_path.suffix,
            modified_at=stat.st_mtime,
            created_at=stat.st_ctime,
            readable=os.access(file_path, os.R_OK),
            writable=os.access(file_path, os.W_OK),
        )
    
    def file_exists(self, path: str) -> bool:
        """Check if file exists."""
        try:
            file_path = self._resolve_path(path)
            return file_path.exists()
        except Exception:
            return False
    
    # ─────────────────────────────────────────────────────────────────
    # Write Operations
    # ─────────────────────────────────────────────────────────────────
    def write_file(
        self,
        path: str,
        content: str,
        *,
        create_backup: bool = True,
        confirmed: bool = False,
    ) -> bool:
        """Write content to file (full replacement).
        
        Args:
            path: File path
            content: New content
            create_backup: Whether to backup existing file
            confirmed: Whether user has confirmed (for overwrites)
            
        Returns:
            True if successful
        """
        file_path = self._resolve_path(path)
        
        # Security check
        self._security.validate_file_operation(file_path, "write", confirmed=confirmed)
        
        # Backup existing file
        old_content = ""
        if file_path.exists():
            old_content = file_path.read_text(encoding="utf-8", errors="replace")
            if create_backup:
                self._create_backup(file_path)
        
        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write new content
        file_path.write_text(content, encoding="utf-8")
        
        # Record edit for undo
        self._edit_history.append(FileEdit(
            file_path=str(file_path),
            old_content=old_content,
            new_content=content,
            edit_type="full",
        ))
        
        return True
    
    def edit_file(
        self,
        path: str,
        old_str: str,
        new_str: str,
        *,
        create_backup: bool = True,
        occurrence: int = 1,  # Which occurrence to replace (1-indexed, 0 for all)
    ) -> bool:
        """Edit file by replacing old_str with new_str (Copilot-style).
        
        Args:
            path: File path
            old_str: Exact string to find
            new_str: Replacement string
            create_backup: Whether to backup
            occurrence: Which match to replace (1 for first, 0 for all)
            
        Returns:
            True if successful
            
        Raises:
            ValueError: If old_str not found
        """
        file_path = self._resolve_path(path)
        
        # Security check
        self._security.validate_file_operation(file_path, "write")
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        old_content = file_path.read_text(encoding="utf-8", errors="replace")
        
        # Check if old_str exists
        count = old_content.count(old_str)
        if count == 0:
            raise ValueError(f"String not found in file: {old_str[:50]}...")
        
        # Replace
        if occurrence == 0:
            # Replace all
            new_content = old_content.replace(old_str, new_str)
        else:
            # Replace specific occurrence
            if occurrence > count:
                raise ValueError(f"Only {count} occurrences found, requested #{occurrence}")
            
            # Find and replace the nth occurrence
            idx = -1
            for _ in range(occurrence):
                idx = old_content.find(old_str, idx + 1)
            
            new_content = old_content[:idx] + new_str + old_content[idx + len(old_str):]
        
        # Backup
        if create_backup:
            self._create_backup(file_path)
        
        # Write
        file_path.write_text(new_content, encoding="utf-8")
        
        # Record edit
        self._edit_history.append(FileEdit(
            file_path=str(file_path),
            old_content=old_content,
            new_content=new_content,
            edit_type="replace",
        ))
        
        return True
    
    def create_file(
        self,
        path: str,
        content: str = "",
        *,
        overwrite: bool = False,
        confirmed: bool = False,
    ) -> bool:
        """Create a new file.
        
        Args:
            path: File path
            content: Initial content
            overwrite: Whether to overwrite existing
            confirmed: User confirmation for overwrite
            
        Returns:
            True if successful
        """
        file_path = self._resolve_path(path)
        
        # Security check
        self._security.validate_file_operation(file_path, "create")
        
        if file_path.exists() and not overwrite:
            raise FileExistsError(f"File already exists: {path}")
        
        if file_path.exists() and overwrite:
            if not confirmed:
                raise ConfirmationRequired(
                    f"Overwrite existing file: {path}?",
                    command=f"create:{path}",
                    reason="overwrite_confirmation",
                )
            self._create_backup(file_path)
        
        # Ensure parent exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create file
        file_path.write_text(content, encoding="utf-8")
        
        # Record
        self._edit_history.append(FileEdit(
            file_path=str(file_path),
            old_content="",
            new_content=content,
            edit_type="create",
        ))
        
        return True
    
    def delete_file(self, path: str, *, confirmed: bool = False) -> bool:
        """Delete a file (moves to backup first).
        
        Args:
            path: File path
            confirmed: User confirmation required
            
        Returns:
            True if successful
        """
        file_path = self._resolve_path(path)
        
        # Security check (delete requires confirmation)
        self._security.validate_file_operation(file_path, "delete", confirmed=confirmed)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        # Backup before delete
        old_content = ""
        if file_path.is_file():
            old_content = file_path.read_text(encoding="utf-8", errors="replace")
            self._create_backup(file_path)
        
        # Delete
        if file_path.is_dir():
            shutil.rmtree(file_path)
        else:
            file_path.unlink()
        
        # Record
        self._edit_history.append(FileEdit(
            file_path=str(file_path),
            old_content=old_content,
            new_content="",
            edit_type="delete",
        ))
        
        return True
    
    # ─────────────────────────────────────────────────────────────────
    # Directory Operations
    # ─────────────────────────────────────────────────────────────────
    def list_directory(
        self,
        path: str = ".",
        *,
        include_hidden: bool = False,
        recursive: bool = False,
        max_depth: int = 3,
    ) -> list[dict]:
        """List directory contents.
        
        Args:
            path: Directory path
            include_hidden: Include dotfiles
            recursive: List recursively
            max_depth: Max depth for recursive listing
            
        Returns:
            List of file/directory info dicts
        """
        dir_path = self._resolve_path(path)
        
        # Security check
        self._security.validate_file_operation(dir_path, "read")
        
        if not dir_path.exists():
            raise FileNotFoundError(f"Directory not found: {path}")
        
        if not dir_path.is_dir():
            raise ValueError(f"Not a directory: {path}")
        
        results: list[dict] = []
        
        def scan(p: Path, depth: int):
            if depth > max_depth:
                return
            
            try:
                entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except PermissionError:
                return
            
            for entry in entries:
                # Skip hidden unless requested
                if entry.name.startswith(".") and not include_hidden:
                    # Always skip .git and .bantz_backups
                    continue
                
                # Skip backup dir
                if entry == self._backup_dir:
                    continue
                
                try:
                    stat = entry.stat()
                    rel_path = entry.relative_to(self.root) if entry.is_relative_to(self.root) else entry
                    
                    results.append({
                        "path": str(rel_path),
                        "name": entry.name,
                        "type": "directory" if entry.is_dir() else "file",
                        "size": stat.st_size if entry.is_file() else 0,
                        "extension": entry.suffix if entry.is_file() else "",
                        "depth": depth,
                    })
                    
                    if recursive and entry.is_dir():
                        scan(entry, depth + 1)
                except Exception:
                    pass
        
        scan(dir_path, 0)
        return results
    
    def search_files(
        self,
        pattern: str = "*",
        *,
        content_pattern: Optional[str] = None,
        extensions: Optional[list[str]] = None,
        max_results: int = 100,
    ) -> list[str]:
        """Search for files by name pattern and/or content.
        
        Args:
            pattern: Glob pattern for filenames
            content_pattern: Regex pattern to search in content
            extensions: Filter by extensions (e.g., [".py", ".js"])
            max_results: Maximum results to return
            
        Returns:
            List of matching file paths (relative to workspace)
        """
        import re
        
        results: list[str] = []
        content_re = re.compile(content_pattern) if content_pattern else None
        
        for p in self.root.rglob(pattern):
            if len(results) >= max_results:
                break
            
            # Skip hidden/backup
            rel_parts = p.relative_to(self.root).parts
            if any(part.startswith(".") for part in rel_parts):
                continue
            
            if not p.is_file():
                continue
            
            # Extension filter
            if extensions and p.suffix.lower() not in [e.lower() for e in extensions]:
                continue
            
            # Content search
            if content_re:
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    if not content_re.search(text):
                        continue
                except Exception:
                    continue
            
            rel_path = p.relative_to(self.root)
            results.append(str(rel_path))
        
        return results
    
    def create_directory(self, path: str) -> bool:
        """Create a directory."""
        dir_path = self._resolve_path(path)
        
        # Security check
        self._security.validate_file_operation(dir_path, "create")
        
        dir_path.mkdir(parents=True, exist_ok=True)
        return True
    
    # ─────────────────────────────────────────────────────────────────
    # Undo Operations
    # ─────────────────────────────────────────────────────────────────
    def undo_last_edit(self) -> Optional[FileEdit]:
        """Undo the last file edit.
        
        Returns:
            The undone edit, or None if no edits to undo
        """
        if not self._edit_history:
            return None
        
        edit = self._edit_history.pop()
        file_path = Path(edit.file_path)
        
        if edit.edit_type == "delete":
            # Restore from backup
            backup = self._get_latest_backup(file_path)
            if backup:
                shutil.copy2(backup, file_path)
        elif edit.edit_type == "create":
            # Delete the created file
            if file_path.exists():
                file_path.unlink()
        else:
            # Restore old content
            file_path.write_text(edit.old_content, encoding="utf-8")
        
        return edit
    
    def restore_from_backup(self, path: str) -> bool:
        """Restore a file from its latest backup.
        
        Args:
            path: File path to restore
            
        Returns:
            True if restored successfully
        """
        file_path = self._resolve_path(path)
        backup = self._get_latest_backup(file_path)
        
        if not backup:
            raise ValueError(f"No backup found for: {path}")
        
        shutil.copy2(backup, file_path)
        return True
    
    def list_backups(self, path: str) -> list[dict]:
        """List available backups for a file.
        
        Args:
            path: File path
            
        Returns:
            List of backup info dicts
        """
        file_path = self._resolve_path(path)
        
        if not self._backup_dir.exists():
            return []
        
        rel_path = file_path.relative_to(self.root) if file_path.is_relative_to(self.root) else file_path.name
        safe_name = str(rel_path).replace("/", "__").replace("\\", "__")
        pattern = f"{safe_name}.*.bak"
        
        backups = sorted(
            self._backup_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        
        results = []
        for b in backups:
            stat = b.stat()
            results.append({
                "path": str(b),
                "name": b.name,
                "size": stat.st_size,
                "created_at": stat.st_mtime,
            })
        
        return results
    
    def get_edit_history(self, limit: int = 10) -> list[dict]:
        """Get recent edit history.
        
        Args:
            limit: Max number of edits to return
            
        Returns:
            List of edit info dicts
        """
        edits = self._edit_history[-limit:] if limit > 0 else self._edit_history
        return [
            {
                "file_path": e.file_path,
                "edit_type": e.edit_type,
                "timestamp": e.timestamp,
                "old_length": len(e.old_content),
                "new_length": len(e.new_content),
            }
            for e in reversed(edits)
        ]
