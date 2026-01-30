"""Coding Agent Tools - Register with Agent Framework (Issue #4).

These tools enable vibe coding capabilities:
- File read/write/edit with undo
- Terminal command execution  
- Code editing with diff support
- Project context understanding
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from bantz.agent.tools import Tool, ToolRegistry
from bantz.coding.security import SecurityPolicy, ConfirmationRequired
from bantz.coding.files import FileManager
from bantz.coding.terminal import TerminalExecutor
from bantz.coding.editor import CodeEditor
from bantz.coding.context import ProjectContext


def register_coding_tools(
    registry: ToolRegistry,
    workspace_root: Optional[Path] = None,
    security_policy: Optional[SecurityPolicy] = None,
) -> dict[str, Any]:
    """Register all coding tools with an existing ToolRegistry.
    
    Args:
        registry: The ToolRegistry to add tools to
        workspace_root: Project root for sandboxing (defaults to cwd)
        security_policy: Custom security policy (defaults to standard)
        
    Returns:
        Dict with initialized tool executors for use by router
    """
    if workspace_root is None:
        workspace_root = Path.cwd()
    
    if security_policy is None:
        security_policy = SecurityPolicy(sandbox_root=workspace_root)
    
    # Initialize executors
    file_manager = FileManager(security=security_policy)
    terminal = TerminalExecutor(security=security_policy, working_directory=workspace_root)
    editor = CodeEditor(file_manager=file_manager)
    context = ProjectContext(workspace_root)
    
    # ──────────────────────────────────────────────────────────────
    # FILE TOOLS
    # ──────────────────────────────────────────────────────────────
    
    registry.register(
        Tool(
            name="file_read",
            description="Read contents of a file. Can read specific line ranges.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path (absolute or relative to workspace)"},
                    "start_line": {"type": "integer", "description": "Starting line (1-indexed, optional)"},
                    "end_line": {"type": "integer", "description": "Ending line (inclusive, optional)"},
                },
                "required": ["path"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="file_write",
            description="Write content to a file. Creates backup automatically.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "File content"},
                    "create_dirs": {"type": "boolean", "description": "Create parent dirs if needed"},
                },
                "required": ["path", "content"],
            },
            requires_confirmation=True,
        )
    )
    
    registry.register(
        Tool(
            name="file_edit",
            description="Replace a specific string in a file. Include enough context for unique match.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "old_string": {"type": "string", "description": "Exact text to find (include context lines)"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="file_create",
            description="Create a new file with optional initial content.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "Initial content (optional)"},
                },
                "required": ["path"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="file_delete",
            description="Delete a file (requires confirmation).",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to delete"},
                },
                "required": ["path"],
            },
            requires_confirmation=True,
        )
    )
    
    registry.register(
        Tool(
            name="file_undo",
            description="Undo the last edit to a file by restoring from backup.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                },
                "required": ["path"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="file_list",
            description="List directory contents. Can list recursively.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"},
                    "recursive": {"type": "boolean", "description": "List recursively"},
                    "max_depth": {"type": "integer", "description": "Max depth for recursive"},
                },
                "required": ["path"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="file_search",
            description="Search for files by name pattern, optionally matching content.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g. '*.py')"},
                    "content": {"type": "string", "description": "Search within file content (regex)"},
                    "path": {"type": "string", "description": "Directory to search in"},
                },
                "required": ["pattern"],
            },
        )
    )
    
    # ──────────────────────────────────────────────────────────────
    # TERMINAL TOOLS
    # ──────────────────────────────────────────────────────────────
    
    registry.register(
        Tool(
            name="terminal_run",
            description="Run a shell command. Some commands require confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 60)"},
                    "cwd": {"type": "string", "description": "Working directory"},
                },
                "required": ["command"],
            },
            requires_confirmation=True,
        )
    )
    
    registry.register(
        Tool(
            name="terminal_background",
            description="Start a command in background (returns immediately). For servers, watch, etc.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command"},
                    "cwd": {"type": "string", "description": "Working directory"},
                },
                "required": ["command"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="terminal_background_output",
            description="Get output from a background process by ID.",
            parameters={
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "Background process ID"},
                },
                "required": ["id"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="terminal_background_kill",
            description="Kill a background process by ID.",
            parameters={
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "Background process ID"},
                },
                "required": ["id"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="terminal_background_list",
            description="List all running background processes.",
            parameters={"type": "object", "properties": {}},
        )
    )
    
    # ──────────────────────────────────────────────────────────────
    # CODE EDITOR TOOLS
    # ──────────────────────────────────────────────────────────────
    
    registry.register(
        Tool(
            name="code_apply_diff",
            description="Apply a unified diff to a file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "diff": {"type": "string", "description": "Unified diff content"},
                },
                "required": ["path", "diff"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="code_replace_function",
            description="Replace an entire function in a file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "function_name": {"type": "string", "description": "Function name to replace"},
                    "new_code": {"type": "string", "description": "New function code"},
                    "language": {"type": "string", "description": "Language (python, javascript, etc.)"},
                },
                "required": ["path", "function_name", "new_code"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="code_replace_class",
            description="Replace an entire class in a file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "class_name": {"type": "string", "description": "Class name to replace"},
                    "new_code": {"type": "string", "description": "New class code"},
                    "language": {"type": "string", "description": "Language"},
                },
                "required": ["path", "class_name", "new_code"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="code_insert_lines",
            description="Insert lines at a specific position.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "line": {"type": "integer", "description": "Line number (1-indexed)"},
                    "content": {"type": "string", "description": "Content to insert"},
                },
                "required": ["path", "line", "content"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="code_delete_lines",
            description="Delete a range of lines from a file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "start_line": {"type": "integer", "description": "Starting line (1-indexed)"},
                    "end_line": {"type": "integer", "description": "Ending line (inclusive)"},
                },
                "required": ["path", "start_line", "end_line"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="code_format",
            description="Format code using appropriate formatter (black, prettier, etc.).",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "formatter": {"type": "string", "description": "Formatter name (auto if not specified)"},
                },
                "required": ["path"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="code_search_replace",
            description="Search and replace across multiple files.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern (regex)"},
                    "replacement": {"type": "string", "description": "Replacement string"},
                    "file_pattern": {"type": "string", "description": "File glob pattern (e.g. '*.py')"},
                    "root": {"type": "string", "description": "Root directory to search"},
                },
                "required": ["pattern", "replacement"],
            },
        )
    )
    
    # ──────────────────────────────────────────────────────────────
    # PROJECT CONTEXT TOOLS
    # ──────────────────────────────────────────────────────────────
    
    registry.register(
        Tool(
            name="project_info",
            description="Get project information (type, name, dependencies).",
            parameters={"type": "object", "properties": {}},
        )
    )
    
    registry.register(
        Tool(
            name="project_tree",
            description="Get project file tree structure.",
            parameters={
                "type": "object",
                "properties": {
                    "max_depth": {"type": "integer", "description": "Max depth (default 3)"},
                    "include_hidden": {"type": "boolean", "description": "Include hidden files"},
                    "extensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by extensions (e.g. ['.py', '.js'])"
                    },
                },
            },
        )
    )
    
    registry.register(
        Tool(
            name="project_symbols",
            description="Get symbols (functions, classes) from a file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                },
                "required": ["path"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="project_search_symbol",
            description="Search for a symbol across the project.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Symbol name (partial match)"},
                    "type": {"type": "string", "description": "Filter by type (function, class, etc.)"},
                },
                "required": ["name"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="project_related_files",
            description="Find files related to a given file (tests, imports, etc.).",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                },
                "required": ["path"],
            },
        )
    )
    
    registry.register(
        Tool(
            name="project_imports",
            description="Get list of imports from a Python file.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                },
                "required": ["path"],
            },
        )
    )
    
    # Return executors for router to use
    return {
        "file_manager": file_manager,
        "terminal": terminal,
        "editor": editor,
        "context": context,
        "security": security_policy,
    }


class CodingToolExecutor:
    """Execute coding tools with proper error handling.
    
    This class bridges the Tool definitions above with actual execution.
    The router calls execute() with tool name and params.
    """
    
    def __init__(
        self,
        workspace_root: Optional[Path] = None,
        security_policy: Optional[SecurityPolicy] = None,
    ):
        if workspace_root is None:
            workspace_root = Path.cwd()
        
        if security_policy is None:
            security_policy = SecurityPolicy(workspace_root=workspace_root)
        
        self.workspace_root = workspace_root
        self.security = security_policy
        self.file_manager = FileManager(workspace_root=workspace_root, security=security_policy)
        self.terminal = TerminalExecutor(workspace_root, security=security_policy)
        self.editor = CodeEditor(file_manager=self.file_manager)
        self.context = ProjectContext(workspace_root)
        
        # Pending confirmations
        self._pending_confirmations: dict[str, dict] = {}
    
    def _resolve_path(self, path: str) -> Path:
        """Resolve path relative to workspace root."""
        p = Path(path)
        if not p.is_absolute():
            p = self.workspace_root / p
        return p.resolve()
    
    async def execute(
        self,
        tool_name: str,
        params: dict,
        *,
        user_confirmed: bool = False,
    ) -> tuple[bool, str]:
        """Execute a coding tool.
        
        Args:
            tool_name: Name of the tool
            params: Tool parameters
            user_confirmed: If True, skip confirmation for destructive ops
            
        Returns:
            (success, result_or_error)
        """
        try:
            return await self._execute_internal(tool_name, params, user_confirmed)
        except ConfirmationRequired as e:
            # Store pending confirmation
            import uuid
            conf_id = str(uuid.uuid4())[:8]
            self._pending_confirmations[conf_id] = {
                "tool": tool_name,
                "params": params,
                "message": str(e),
            }
            return False, f"⚠️ Onay gerekli: {e}\n\nOnaylamak için: confirm {conf_id}"
        except Exception as e:
            return False, f"❌ Hata: {e}"
    
    async def confirm_pending(self, conf_id: str) -> tuple[bool, str]:
        """Confirm and execute a pending operation."""
        pending = self._pending_confirmations.pop(conf_id, None)
        if not pending:
            return False, f"❌ Onay bulunamadı: {conf_id}"
        
        return await self.execute(
            pending["tool"],
            pending["params"],
            user_confirmed=True,
        )
    
    async def _execute_internal(
        self,
        tool_name: str,
        params: dict,
        confirmed: bool,
    ) -> tuple[bool, str]:
        """Internal execution logic."""
        
        # ─────────────────── FILE TOOLS ───────────────────
        
        if tool_name == "file_read":
            path = self._resolve_path(params["path"])
            start = params.get("start_line")
            end = params.get("end_line")
            
            if start is not None and end is not None:
                content = self.file_manager.read_lines(path, start, end)
            else:
                content = self.file_manager.read_file(path)
            
            return True, content
        
        elif tool_name == "file_write":
            path = self._resolve_path(params["path"])
            content = params["content"]
            create_dirs = params.get("create_dirs", True)
            
            self.file_manager.write_file(path, content, create_dirs=create_dirs)
            return True, f"✅ Dosya yazıldı: {path}"
        
        elif tool_name == "file_edit":
            path = self._resolve_path(params["path"])
            old_str = params["old_string"]
            new_str = params["new_string"]
            
            result = self.file_manager.edit_file(path, old_str, new_str)
            return True, f"✅ Düzenlendi: {path}\n{result.to_dict()}"
        
        elif tool_name == "file_create":
            path = self._resolve_path(params["path"])
            content = params.get("content", "")
            
            self.file_manager.create_file(path, content)
            return True, f"✅ Dosya oluşturuldu: {path}"
        
        elif tool_name == "file_delete":
            path = self._resolve_path(params["path"])
            
            self.file_manager.delete_file(path, confirmed=confirmed)
            return True, f"✅ Dosya silindi: {path}"
        
        elif tool_name == "file_undo":
            path = self._resolve_path(params["path"])
            
            if self.file_manager.undo_last_edit(path):
                return True, f"✅ Geri alındı: {path}"
            else:
                return False, f"❌ Geri alınacak değişiklik yok: {path}"
        
        elif tool_name == "file_list":
            path = self._resolve_path(params["path"])
            recursive = params.get("recursive", False)
            max_depth = params.get("max_depth", 2)
            
            entries = self.file_manager.list_directory(path, recursive=recursive, max_depth=max_depth)
            result = "\n".join(entries)
            return True, result
        
        elif tool_name == "file_search":
            pattern = params["pattern"]
            content = params.get("content")
            path = self._resolve_path(params.get("path", "."))
            
            files = self.file_manager.search_files(path, pattern, content_pattern=content)
            result = "\n".join(files)
            return True, result or "Dosya bulunamadı"
        
        # ─────────────────── TERMINAL TOOLS ───────────────────
        
        elif tool_name == "terminal_run":
            command = params["command"]
            timeout = params.get("timeout", 60)
            cwd = params.get("cwd")
            if cwd:
                cwd = self._resolve_path(cwd)
            
            result = self.terminal.run(command, confirmed=confirmed, timeout=timeout, cwd=cwd)
            
            output = f"Exit code: {result.exit_code}\n"
            if result.stdout:
                output += f"\n--- STDOUT ---\n{result.stdout}"
            if result.stderr:
                output += f"\n--- STDERR ---\n{result.stderr}"
            
            return result.exit_code == 0, output
        
        elif tool_name == "terminal_background":
            command = params["command"]
            cwd = params.get("cwd")
            if cwd:
                cwd = self._resolve_path(cwd)
            
            bg_id = self.terminal.run_background(command, cwd=cwd)
            return True, f"✅ Arka plan işlemi başlatıldı (ID: {bg_id})"
        
        elif tool_name == "terminal_background_output":
            bg_id = params["id"]
            output = self.terminal.get_background_output(bg_id)
            return True, output
        
        elif tool_name == "terminal_background_kill":
            bg_id = params["id"]
            success = self.terminal.kill_background(bg_id)
            if success:
                return True, f"✅ İşlem sonlandırıldı: {bg_id}"
            else:
                return False, f"❌ İşlem bulunamadı: {bg_id}"
        
        elif tool_name == "terminal_background_list":
            processes = self.terminal.list_background()
            result = "\n".join(
                f"[{p['id']}] {p['command']} (running={p['running']})"
                for p in processes
            )
            return True, result or "Çalışan işlem yok"
        
        # ─────────────────── CODE EDITOR TOOLS ───────────────────
        
        elif tool_name == "code_apply_diff":
            path = self._resolve_path(params["path"])
            diff = params["diff"]
            
            result = self.editor.apply_diff(path, diff)
            return result.success, result.message
        
        elif tool_name == "code_replace_function":
            path = self._resolve_path(params["path"])
            func_name = params["function_name"]
            new_code = params["new_code"]
            language = params.get("language")
            
            success = self.editor.replace_function(path, func_name, new_code, language=language)
            if success:
                return True, f"✅ Fonksiyon değiştirildi: {func_name}"
            else:
                return False, f"❌ Fonksiyon bulunamadı: {func_name}"
        
        elif tool_name == "code_replace_class":
            path = self._resolve_path(params["path"])
            class_name = params["class_name"]
            new_code = params["new_code"]
            language = params.get("language")
            
            success = self.editor.replace_class(path, class_name, new_code, language=language)
            if success:
                return True, f"✅ Class değiştirildi: {class_name}"
            else:
                return False, f"❌ Class bulunamadı: {class_name}"
        
        elif tool_name == "code_insert_lines":
            path = self._resolve_path(params["path"])
            line = params["line"]
            content = params["content"]
            
            self.editor.insert_at_line(path, line, content)
            return True, f"✅ Satır eklendi: {path}:{line}"
        
        elif tool_name == "code_delete_lines":
            path = self._resolve_path(params["path"])
            start = params["start_line"]
            end = params["end_line"]
            
            self.editor.delete_lines(path, start, end)
            return True, f"✅ Satırlar silindi: {path}:{start}-{end}"
        
        elif tool_name == "code_format":
            path = self._resolve_path(params["path"])
            formatter = params.get("formatter")
            
            success, msg = self.editor.format_code(path, formatter=formatter)
            return success, msg
        
        elif tool_name == "code_search_replace":
            pattern = params["pattern"]
            replacement = params["replacement"]
            file_pattern = params.get("file_pattern", "*")
            root = params.get("root")
            if root:
                root = self._resolve_path(root)
            else:
                root = self.workspace_root
            
            count = self.editor.search_and_replace(pattern, replacement, file_pattern, root=root)
            return True, f"✅ {count} dosyada değişiklik yapıldı"
        
        # ─────────────────── PROJECT CONTEXT TOOLS ───────────────────
        
        elif tool_name == "project_info":
            info = self.context.get_project_info()
            return True, str(info.to_dict())
        
        elif tool_name == "project_tree":
            max_depth = params.get("max_depth", 3)
            include_hidden = params.get("include_hidden", False)
            extensions = params.get("extensions")
            
            tree = self.context.get_file_tree(
                max_depth=max_depth,
                include_hidden=include_hidden,
                extensions=extensions,
            )
            
            # Format tree as text
            def format_tree(node: dict, indent: int = 0) -> str:
                prefix = "  " * indent
                if node["type"] == "directory":
                    result = f"{prefix}📁 {node['name']}/\n"
                    for child in node.get("children", []):
                        result += format_tree(child, indent + 1)
                    return result
                else:
                    return f"{prefix}📄 {node['name']}\n"
            
            return True, format_tree(tree)
        
        elif tool_name == "project_symbols":
            path = self._resolve_path(params["path"])
            
            symbols = self.context.get_symbols(str(path))
            result = "\n".join(
                f"{s.line:4d}: {s.type:10s} {s.name}"
                + (f" ({s.parent})" if s.parent else "")
                for s in symbols
            )
            return True, result or "Sembol bulunamadı"
        
        elif tool_name == "project_search_symbol":
            name = params["name"]
            symbol_type = params.get("type")
            
            results = self.context.search_symbol(name, symbol_type=symbol_type)
            output = "\n".join(
                f"{r['file']}:{r['line']} - {r['type']} {r['name']}"
                for r in results
            )
            return True, output or "Sembol bulunamadı"
        
        elif tool_name == "project_related_files":
            path = self._resolve_path(params["path"])
            
            related = self.context.find_related_files(str(path))
            return True, "\n".join(related) or "İlişkili dosya bulunamadı"
        
        elif tool_name == "project_imports":
            path = self._resolve_path(params["path"])
            
            imports = self.context.get_imports(str(path))
            return True, "\n".join(imports) or "Import bulunamadı"
        
        # ─────────────────── UNKNOWN TOOL ───────────────────
        
        else:
            return False, f"❌ Bilinmeyen tool: {tool_name}"
