"""Intelligent code editor with diff support (Issue #4).

Features:
- Apply unified diffs
- Replace entire functions/classes
- Insert/delete lines
- Auto-formatting (black, prettier, etc.)
- Multi-file edits
"""
from __future__ import annotations

import re
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .files import FileManager


@dataclass
class DiffHunk:
    """A single hunk from a unified diff."""
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]


@dataclass
class DiffResult:
    """Result of applying a diff."""
    success: bool
    file_path: str
    hunks_applied: int
    hunks_failed: int
    message: str = ""


class CodeEditor:
    """Intelligent code editing with diff support.
    
    Features:
    - Parse and apply unified diffs
    - Replace functions/classes by name
    - Insert content at specific lines
    - Delete line ranges
    - Auto-format code (black, prettier, eslint --fix)
    """
    
    def __init__(self, file_manager: FileManager):
        self.fm = file_manager
    
    # ─────────────────────────────────────────────────────────────────
    # Diff Operations
    # ─────────────────────────────────────────────────────────────────
    def apply_diff(self, file_path: str, diff: str) -> DiffResult:
        """Apply a unified diff to a file.
        
        Args:
            file_path: Target file
            diff: Unified diff content
            
        Returns:
            DiffResult with success status
        """
        try:
            content = self.fm.read_file(file_path)
            lines = content.splitlines(keepends=True)
            
            # Parse hunks
            hunks = self._parse_diff(diff)
            
            if not hunks:
                return DiffResult(
                    success=False,
                    file_path=file_path,
                    hunks_applied=0,
                    hunks_failed=0,
                    message="No valid hunks found in diff",
                )
            
            # Apply hunks in reverse order (to preserve line numbers)
            hunks_applied = 0
            hunks_failed = 0
            
            for hunk in reversed(hunks):
                try:
                    lines = self._apply_hunk(lines, hunk)
                    hunks_applied += 1
                except Exception as e:
                    hunks_failed += 1
            
            # Write result
            new_content = "".join(lines)
            self.fm.write_file(file_path, new_content)
            
            return DiffResult(
                success=hunks_failed == 0,
                file_path=file_path,
                hunks_applied=hunks_applied,
                hunks_failed=hunks_failed,
                message=f"Applied {hunks_applied} hunks" + (f", {hunks_failed} failed" if hunks_failed else ""),
            )
            
        except Exception as e:
            return DiffResult(
                success=False,
                file_path=file_path,
                hunks_applied=0,
                hunks_failed=0,
                message=str(e),
            )
    
    def _parse_diff(self, diff: str) -> list[DiffHunk]:
        """Parse unified diff into hunks."""
        hunks = []
        current_hunk: Optional[DiffHunk] = None
        
        # Regex for hunk header: @@ -old_start,old_count +new_start,new_count @@
        hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
        
        for line in diff.splitlines(keepends=True):
            # Skip file headers
            if line.startswith("---") or line.startswith("+++"):
                continue
            
            match = hunk_re.match(line)
            if match:
                # Save previous hunk
                if current_hunk:
                    hunks.append(current_hunk)
                
                # Start new hunk
                old_start = int(match.group(1))
                old_count = int(match.group(2) or 1)
                new_start = int(match.group(3))
                new_count = int(match.group(4) or 1)
                
                current_hunk = DiffHunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    lines=[],
                )
                continue
            
            # Add line to current hunk
            if current_hunk is not None:
                if line.startswith(" ") or line.startswith("-") or line.startswith("+"):
                    current_hunk.lines.append(line)
                elif line.startswith("\\"):
                    # "\ No newline at end of file"
                    pass
        
        # Save last hunk
        if current_hunk:
            hunks.append(current_hunk)
        
        return hunks
    
    def _apply_hunk(self, lines: list[str], hunk: DiffHunk) -> list[str]:
        """Apply a single hunk to lines."""
        # Find the position to apply (0-indexed)
        start_idx = hunk.old_start - 1
        
        # Collect removed and added lines
        removed = []
        added = []
        context_before = []
        context_after = []
        in_change = False
        
        for line in hunk.lines:
            content = line[1:] if len(line) > 1 else "\n"
            if not content.endswith("\n"):
                content += "\n"
            
            if line.startswith("-"):
                removed.append(content)
                in_change = True
            elif line.startswith("+"):
                added.append(content)
                in_change = True
            elif line.startswith(" "):
                if not in_change:
                    context_before.append(content)
                else:
                    context_after.append(content)
        
        # Build new content
        before = lines[:start_idx]
        after = lines[start_idx + len(context_before) + len(removed) + len(context_after):]
        
        new_lines = before + context_before + added + context_after + after
        
        return new_lines
    
    def create_diff(self, file_path: str, old_content: str, new_content: str) -> str:
        """Create a unified diff between old and new content.
        
        Args:
            file_path: File path for diff header
            old_content: Original content
            new_content: New content
            
        Returns:
            Unified diff string
        """
        import difflib
        
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )
        
        return "".join(diff)
    
    # ─────────────────────────────────────────────────────────────────
    # Function/Class Replacement
    # ─────────────────────────────────────────────────────────────────
    def replace_function(
        self,
        file_path: str,
        func_name: str,
        new_code: str,
        *,
        language: Optional[str] = None,
    ) -> bool:
        """Replace an entire function definition.
        
        Args:
            file_path: Target file
            func_name: Name of function to replace
            new_code: New function code (complete definition)
            language: Programming language (auto-detected if None)
            
        Returns:
            True if successful
        """
        content = self.fm.read_file(file_path)
        
        # Auto-detect language from extension
        if language is None:
            ext = Path(file_path).suffix.lower()
            language = self._detect_language(ext)
        
        # Find function boundaries
        start_line, end_line = self._find_function_bounds(content, func_name, language)
        
        if start_line is None:
            raise ValueError(f"Function not found: {func_name}")
        
        # Replace
        lines = content.splitlines(keepends=True)
        
        # Ensure new_code ends with newline
        if not new_code.endswith("\n"):
            new_code += "\n"
        
        # Build new content
        before = lines[:start_line - 1]
        after = lines[end_line:]
        
        new_content = "".join(before) + new_code + "".join(after)
        
        self.fm.write_file(file_path, new_content)
        return True
    
    def replace_class(
        self,
        file_path: str,
        class_name: str,
        new_code: str,
        *,
        language: Optional[str] = None,
    ) -> bool:
        """Replace an entire class definition.
        
        Similar to replace_function but for classes.
        """
        content = self.fm.read_file(file_path)
        
        if language is None:
            ext = Path(file_path).suffix.lower()
            language = self._detect_language(ext)
        
        start_line, end_line = self._find_class_bounds(content, class_name, language)
        
        if start_line is None:
            raise ValueError(f"Class not found: {class_name}")
        
        lines = content.splitlines(keepends=True)
        
        if not new_code.endswith("\n"):
            new_code += "\n"
        
        before = lines[:start_line - 1]
        after = lines[end_line:]
        
        new_content = "".join(before) + new_code + "".join(after)
        
        self.fm.write_file(file_path, new_content)
        return True
    
    def _detect_language(self, ext: str) -> str:
        """Detect language from file extension."""
        mapping = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".php": "php",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
        }
        return mapping.get(ext, "unknown")
    
    def _find_function_bounds(
        self,
        content: str,
        func_name: str,
        language: str,
    ) -> tuple[Optional[int], Optional[int]]:
        """Find start and end lines of a function."""
        lines = content.splitlines()
        
        # Language-specific patterns
        if language == "python":
            # Python: def func_name( or async def func_name(
            pattern = re.compile(rf"^(\s*)(async\s+)?def\s+{re.escape(func_name)}\s*\(")
        elif language in {"javascript", "typescript"}:
            # JS/TS: function name(, const name = function, const name = (
            pattern = re.compile(
                rf"^(\s*)(export\s+)?(async\s+)?function\s+{re.escape(func_name)}\s*\(|"
                rf"^(\s*)(export\s+)?(const|let|var)\s+{re.escape(func_name)}\s*=\s*(async\s+)?(?:function|\()"
            )
        else:
            # Generic: type name(
            pattern = re.compile(rf"^\s*\w+\s+{re.escape(func_name)}\s*\(")
        
        start_line = None
        indent = 0
        
        for i, line in enumerate(lines, 1):
            if start_line is None:
                match = pattern.match(line)
                if match:
                    start_line = i
                    # Get indentation
                    indent = len(line) - len(line.lstrip())
                    continue
            else:
                # Find end: next definition at same or less indent, or end of file
                stripped = line.rstrip()
                if not stripped:
                    continue
                
                current_indent = len(line) - len(line.lstrip())
                
                # Python: next def/class at same indent
                if language == "python":
                    if current_indent <= indent and (
                        stripped.startswith("def ") or
                        stripped.startswith("async def ") or
                        stripped.startswith("class ") or
                        stripped.startswith("@")
                    ):
                        return start_line, i - 1
                else:
                    # Other languages: closing brace at same indent
                    if current_indent == indent and stripped == "}":
                        return start_line, i
        
        # If we found start but not end, go to EOF
        if start_line is not None:
            return start_line, len(lines)
        
        return None, None
    
    def _find_class_bounds(
        self,
        content: str,
        class_name: str,
        language: str,
    ) -> tuple[Optional[int], Optional[int]]:
        """Find start and end lines of a class."""
        lines = content.splitlines()
        
        if language == "python":
            pattern = re.compile(rf"^(\s*)class\s+{re.escape(class_name)}\s*[\(:]")
        elif language in {"javascript", "typescript"}:
            pattern = re.compile(rf"^(\s*)(export\s+)?(default\s+)?class\s+{re.escape(class_name)}\s*")
        else:
            pattern = re.compile(rf"^\s*class\s+{re.escape(class_name)}\s*")
        
        start_line = None
        indent = 0
        
        for i, line in enumerate(lines, 1):
            if start_line is None:
                match = pattern.match(line)
                if match:
                    start_line = i
                    indent = len(line) - len(line.lstrip())
                    continue
            else:
                stripped = line.rstrip()
                if not stripped:
                    continue
                
                current_indent = len(line) - len(line.lstrip())
                
                if language == "python":
                    if current_indent <= indent and (
                        stripped.startswith("class ") or
                        stripped.startswith("def ") or
                        stripped.startswith("@")
                    ):
                        return start_line, i - 1
                else:
                    if current_indent == indent and stripped == "}":
                        return start_line, i
        
        if start_line is not None:
            return start_line, len(lines)
        
        return None, None
    
    # ─────────────────────────────────────────────────────────────────
    # Line Operations
    # ─────────────────────────────────────────────────────────────────
    def insert_at_line(
        self,
        file_path: str,
        line_num: int,
        content: str,
        *,
        after: bool = False,
    ) -> bool:
        """Insert content at a specific line.
        
        Args:
            file_path: Target file
            line_num: Line number (1-indexed)
            content: Content to insert
            after: If True, insert after line_num; else before
            
        Returns:
            True if successful
        """
        file_content = self.fm.read_file(file_path)
        lines = file_content.splitlines(keepends=True)
        
        # Ensure content ends with newline
        if not content.endswith("\n"):
            content += "\n"
        
        # Calculate insert position
        if after:
            insert_idx = min(line_num, len(lines))
        else:
            insert_idx = max(0, line_num - 1)
        
        # Split content into lines for insertion
        new_lines = content.splitlines(keepends=True)
        
        # Insert
        result_lines = lines[:insert_idx] + new_lines + lines[insert_idx:]
        
        new_content = "".join(result_lines)
        self.fm.write_file(file_path, new_content)
        
        return True
    
    def delete_lines(
        self,
        file_path: str,
        start: int,
        end: int,
    ) -> bool:
        """Delete a range of lines.
        
        Args:
            file_path: Target file
            start: First line to delete (1-indexed, inclusive)
            end: Last line to delete (1-indexed, inclusive)
            
        Returns:
            True if successful
        """
        content = self.fm.read_file(file_path)
        lines = content.splitlines(keepends=True)
        
        # Convert to 0-indexed
        start_idx = max(0, start - 1)
        end_idx = min(len(lines), end)
        
        # Remove lines
        result_lines = lines[:start_idx] + lines[end_idx:]
        
        new_content = "".join(result_lines)
        self.fm.write_file(file_path, new_content)
        
        return True
    
    def replace_lines(
        self,
        file_path: str,
        start: int,
        end: int,
        new_content: str,
    ) -> bool:
        """Replace a range of lines with new content.
        
        Args:
            file_path: Target file
            start: First line to replace (1-indexed, inclusive)
            end: Last line to replace (1-indexed, inclusive)
            new_content: Replacement content
            
        Returns:
            True if successful
        """
        content = self.fm.read_file(file_path)
        lines = content.splitlines(keepends=True)
        
        start_idx = max(0, start - 1)
        end_idx = min(len(lines), end)
        
        if not new_content.endswith("\n"):
            new_content += "\n"
        
        new_lines = new_content.splitlines(keepends=True)
        
        result_lines = lines[:start_idx] + new_lines + lines[end_idx:]
        
        result = "".join(result_lines)
        self.fm.write_file(file_path, result)
        
        return True
    
    # ─────────────────────────────────────────────────────────────────
    # Code Formatting
    # ─────────────────────────────────────────────────────────────────
    def format_code(
        self,
        file_path: str,
        *,
        formatter: Optional[str] = None,
    ) -> bool:
        """Auto-format a code file.
        
        Args:
            file_path: File to format
            formatter: Specific formatter to use (auto-detect if None)
            
        Returns:
            True if formatted successfully
        """
        resolved = self.fm._resolve_path(file_path)
        ext = resolved.suffix.lower()
        
        # Auto-detect formatter
        if formatter is None:
            if ext == ".py":
                formatter = "black"
            elif ext in {".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".html", ".md"}:
                formatter = "prettier"
            elif ext == ".go":
                formatter = "gofmt"
            elif ext == ".rs":
                formatter = "rustfmt"
            else:
                return False  # No formatter available
        
        # Check if formatter is available
        formatters = {
            "black": ["black", str(resolved)],
            "prettier": ["npx", "prettier", "--write", str(resolved)],
            "gofmt": ["gofmt", "-w", str(resolved)],
            "rustfmt": ["rustfmt", str(resolved)],
            "isort": ["isort", str(resolved)],
            "autopep8": ["autopep8", "--in-place", str(resolved)],
            "eslint": ["npx", "eslint", "--fix", str(resolved)],
        }
        
        cmd = formatters.get(formatter)
        if not cmd:
            raise ValueError(f"Unknown formatter: {formatter}")
        
        # Check if command exists
        if not shutil.which(cmd[0]):
            # Try without npx for prettier/eslint
            if cmd[0] == "npx" and len(cmd) > 1:
                if not shutil.which(cmd[1]):
                    raise ValueError(f"Formatter not installed: {formatter}")
                cmd = cmd[1:]
            else:
                raise ValueError(f"Formatter not installed: {formatter}")
        
        # Backup before formatting
        self.fm._create_backup(resolved)
        
        # Run formatter
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.fm.root),
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def format_python_imports(self, file_path: str) -> bool:
        """Sort Python imports using isort.
        
        Args:
            file_path: Python file to sort imports
            
        Returns:
            True if successful
        """
        return self.format_code(file_path, formatter="isort")
    
    # ─────────────────────────────────────────────────────────────────
    # Multi-file Operations
    # ─────────────────────────────────────────────────────────────────
    def batch_edit(
        self,
        edits: list[dict],
    ) -> list[dict]:
        """Apply multiple edits across files.
        
        Args:
            edits: List of edit dicts with keys:
                - file_path: Target file
                - old_str: String to find
                - new_str: Replacement string
                
        Returns:
            List of result dicts
        """
        results = []
        
        for edit in edits:
            file_path = edit.get("file_path", "")
            old_str = edit.get("old_str", "")
            new_str = edit.get("new_str", "")
            
            try:
                self.fm.edit_file(file_path, old_str, new_str)
                results.append({
                    "file_path": file_path,
                    "success": True,
                    "message": "OK",
                })
            except Exception as e:
                results.append({
                    "file_path": file_path,
                    "success": False,
                    "message": str(e),
                })
        
        return results
    
    def search_and_replace(
        self,
        pattern: str,
        replacement: str,
        *,
        file_pattern: str = "*.py",
        is_regex: bool = False,
        max_files: int = 100,
    ) -> list[dict]:
        """Search and replace across multiple files.
        
        Args:
            pattern: Text or regex pattern to find
            replacement: Replacement text
            file_pattern: Glob pattern for files
            is_regex: Whether pattern is a regex
            max_files: Maximum files to modify
            
        Returns:
            List of modified files with change counts
        """
        import re as regex_module
        
        files = self.fm.search_files(file_pattern, max_results=max_files)
        results = []
        
        search_re = regex_module.compile(pattern) if is_regex else None
        
        for file_path in files:
            try:
                content = self.fm.read_file(file_path)
                
                if is_regex and search_re:
                    count = len(search_re.findall(content))
                    if count > 0:
                        new_content = search_re.sub(replacement, content)
                        self.fm.write_file(file_path, new_content)
                        results.append({
                            "file_path": file_path,
                            "replacements": count,
                            "success": True,
                        })
                else:
                    count = content.count(pattern)
                    if count > 0:
                        new_content = content.replace(pattern, replacement)
                        self.fm.write_file(file_path, new_content)
                        results.append({
                            "file_path": file_path,
                            "replacements": count,
                            "success": True,
                        })
            except Exception as e:
                results.append({
                    "file_path": file_path,
                    "replacements": 0,
                    "success": False,
                    "error": str(e),
                })
        
        return results
