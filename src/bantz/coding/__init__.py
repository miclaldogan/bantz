"""Coding Agent - File Operations & Terminal (Issue #4).

This package provides vibe coding capabilities:
- File read/write/edit with backup
- Safe terminal command execution
- Diff-based code editing
- Project context understanding
"""

from .security import SecurityPolicy, SecurityError, ConfirmationRequired
from .files import FileManager, FileEdit
from .terminal import TerminalExecutor, CommandResult
from .editor import CodeEditor
from .context import ProjectContext, ProjectInfo, Symbol, Dependency
from .tools import register_coding_tools, CodingToolExecutor

__all__ = [
    "SecurityPolicy",
    "SecurityError",
    "ConfirmationRequired",
    "FileManager",
    "FileEdit",
    "TerminalExecutor",
    "CommandResult",
    "CodeEditor",
    "ProjectContext",
    "ProjectInfo",
    "Symbol",
    "Dependency",
    "register_coding_tools",
    "CodingToolExecutor",
]
