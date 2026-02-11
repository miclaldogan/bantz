"""Code editing & project context runtime tool handlers.

Issue #845: Planner-Runtime Tool Gap Kapatma
─────────────────────────────────────────────
Provides runtime handlers for 6 code/project tools.
Bridges to CodingToolExecutor where available, with standalone
fallbacks for simpler operations.
"""

from __future__ import annotations

import ast
import fnmatch
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _workspace_root() -> Path:
    """Best-effort workspace root detection."""
    # Try env var first
    ws = os.environ.get("BANTZ_WORKSPACE")
    if ws:
        return Path(ws).resolve()
    # Walk up from this file to find pyproject.toml
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


# ── code_format ─────────────────────────────────────────────────────

def code_format_tool(*, path: str = "", **_: Any) -> Dict[str, Any]:
    """Format code using appropriate formatter (black for Python)."""
    if not path:
        return {"ok": False, "error": "path_required"}

    fpath = Path(path)
    if not fpath.is_absolute():
        fpath = _workspace_root() / fpath
    fpath = fpath.resolve()

    if not fpath.exists():
        return {"ok": False, "error": f"file_not_found: {path}"}

    suffix = fpath.suffix.lower()

    try:
        if suffix == ".py":
            # Try black
            if shutil.which("black"):
                result = subprocess.run(
                    ["black", "--quiet", str(fpath)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    return {"ok": True, "path": str(fpath), "formatter": "black", "formatted": True}
                return {"ok": False, "error": f"black_error: {result.stderr.strip()[:200]}"}

            # Fallback: autopep8
            if shutil.which("autopep8"):
                result = subprocess.run(
                    ["autopep8", "--in-place", str(fpath)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    return {"ok": True, "path": str(fpath), "formatter": "autopep8", "formatted": True}

            return {"ok": False, "error": "no_python_formatter_installed (try: pip install black)"}

        elif suffix in (".js", ".ts", ".jsx", ".tsx", ".json", ".css", ".html"):
            if shutil.which("prettier"):
                result = subprocess.run(
                    ["prettier", "--write", str(fpath)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    return {"ok": True, "path": str(fpath), "formatter": "prettier", "formatted": True}
            return {"ok": False, "error": "prettier_not_installed"}

        else:
            return {"ok": False, "error": f"no_formatter_for: {suffix}"}

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "formatter_timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── code_replace_function ──────────────────────────────────────────

def code_replace_function_tool(*, path: str = "", function_name: str = "", new_code: str = "", **_: Any) -> Dict[str, Any]:
    """Replace an entire function in a file."""
    if not path or not function_name or not new_code:
        return {"ok": False, "error": "path_function_name_new_code_required"}

    fpath = Path(path)
    if not fpath.is_absolute():
        fpath = _workspace_root() / fpath
    fpath = fpath.resolve()

    if not fpath.exists():
        return {"ok": False, "error": f"file_not_found: {path}"}

    try:
        content = fpath.read_text(encoding="utf-8")
        lines = content.split("\n")

        # Parse Python AST to find function boundaries
        if fpath.suffix == ".py":
            try:
                tree = ast.parse(content)
            except SyntaxError as e:
                return {"ok": False, "error": f"syntax_error: {e}"}

            func_node = None
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name == function_name:
                        func_node = node
                        break

            if func_node is None:
                return {"ok": False, "error": f"function_not_found: {function_name}"}

            start_line = func_node.lineno - 1  # 0-indexed
            end_line = func_node.end_lineno  # Already 1-indexed, exclusive

            if end_line is None:
                return {"ok": False, "error": "cannot_determine_function_end"}

            # Replace
            new_lines = lines[:start_line] + [new_code] + lines[end_line:]
            new_content = "\n".join(new_lines)

            fpath.write_text(new_content, encoding="utf-8")
            return {
                "ok": True,
                "path": str(fpath),
                "function": function_name,
                "replaced": True,
                "old_lines": f"{start_line + 1}-{end_line}",
            }
        else:
            # Generic regex-based approach for other languages
            pattern = rf"(def|function|fn|func)\s+{re.escape(function_name)}\s*\("
            match = re.search(pattern, content)
            if not match:
                return {"ok": False, "error": f"function_not_found: {function_name}"}

            return {"ok": False, "error": "non_python_function_replace_not_yet_supported"}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── project_info ────────────────────────────────────────────────────

def project_info_tool(**_: Any) -> Dict[str, Any]:
    """Get project information (type, name, dependencies)."""
    ws = _workspace_root()

    info: Dict[str, Any] = {
        "ok": True,
        "workspace_root": str(ws),
        "type": "unknown",
        "name": ws.name,
    }

    # Detect project type
    if (ws / "pyproject.toml").exists():
        info["type"] = "python"
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore[no-redef]
            except ImportError:
                tomllib = None  # type: ignore[assignment]

        if tomllib:
            try:
                data = tomllib.loads((ws / "pyproject.toml").read_text())
                info["name"] = data.get("project", {}).get("name", ws.name)
                info["version"] = data.get("project", {}).get("version", "unknown")
                info["python_requires"] = data.get("project", {}).get("requires-python", "")
            except Exception:
                pass

    elif (ws / "package.json").exists():
        info["type"] = "node"
        try:
            import json
            pkg = json.loads((ws / "package.json").read_text())
            info["name"] = pkg.get("name", ws.name)
            info["version"] = pkg.get("version", "unknown")
        except Exception:
            pass

    elif (ws / "Cargo.toml").exists():
        info["type"] = "rust"

    elif (ws / "go.mod").exists():
        info["type"] = "go"

    # Count files
    py_count = sum(1 for _ in ws.rglob("*.py"))
    info["python_files"] = py_count

    return info


# ── project_tree ────────────────────────────────────────────────────

def project_tree_tool(*, max_depth: int = 3, **_: Any) -> Dict[str, Any]:
    """Get project file tree structure."""
    ws = _workspace_root()
    max_depth = max(1, min(max_depth, 5))

    skip_dirs = {
        ".git", "__pycache__", "node_modules", ".venv", "venv",
        ".mypy_cache", ".pytest_cache", ".tox", "dist", "build",
        ".eggs", "*.egg-info",
    }

    def build_tree(root: Path, depth: int) -> list[str]:
        if depth > max_depth:
            return []

        entries = []
        try:
            items = sorted(root.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            return []

        for item in items:
            if item.name.startswith(".") and item.name not in (".env.example",):
                continue
            if item.name in skip_dirs:
                continue

            indent = "  " * depth
            if item.is_dir():
                entries.append(f"{indent}📁 {item.name}/")
                entries.extend(build_tree(item, depth + 1))
            else:
                entries.append(f"{indent}📄 {item.name}")

        return entries

    tree_lines = build_tree(ws, 0)

    return {
        "ok": True,
        "workspace": str(ws),
        "tree": "\n".join(tree_lines[:500]),
        "truncated": len(tree_lines) > 500,
    }


# ── project_symbols ─────────────────────────────────────────────────

def project_symbols_tool(*, path: str = "", **_: Any) -> Dict[str, Any]:
    """Get symbols (functions, classes) from a Python file."""
    if not path:
        return {"ok": False, "error": "path_required"}

    fpath = Path(path)
    if not fpath.is_absolute():
        fpath = _workspace_root() / fpath
    fpath = fpath.resolve()

    if not fpath.exists():
        return {"ok": False, "error": f"file_not_found: {path}"}

    if fpath.suffix != ".py":
        return {"ok": False, "error": "only_python_files_supported"}

    try:
        content = fpath.read_text(encoding="utf-8")
        tree = ast.parse(content)

        symbols = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                symbols.append({
                    "name": node.name,
                    "type": "class",
                    "line": node.lineno,
                    "end_line": node.end_lineno,
                })
                # Class methods
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append({
                            "name": f"{node.name}.{item.name}",
                            "type": "method",
                            "line": item.lineno,
                            "end_line": item.end_lineno,
                            "parent": node.name,
                        })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Top-level function (not inside a class)
                if not any(
                    isinstance(p, ast.ClassDef)
                    for p in ast.walk(tree)
                    if hasattr(p, "body") and node in getattr(p, "body", [])
                ):
                    symbols.append({
                        "name": node.name,
                        "type": "function",
                        "line": node.lineno,
                        "end_line": node.end_lineno,
                    })

        return {
            "ok": True,
            "path": str(fpath),
            "symbol_count": len(symbols),
            "symbols": symbols,
        }
    except SyntaxError as e:
        return {"ok": False, "error": f"syntax_error: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── project_search_symbol ──────────────────────────────────────────

def project_search_symbol_tool(*, name: str = "", type: str | None = None, **_: Any) -> Dict[str, Any]:
    """Search for a symbol across the project."""
    if not name:
        return {"ok": False, "error": "name_required"}

    ws = _workspace_root()
    name_lower = name.lower()
    results = []

    skip_dirs = {"__pycache__", "node_modules", ".venv", "venv", ".git"}

    for py_file in ws.rglob("*.py"):
        # Skip excluded dirs
        if any(sd in py_file.parts for sd in skip_dirs):
            continue

        if len(results) >= 50:
            break

        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and name_lower in node.name.lower():
                    if type and type.lower() != "class":
                        continue
                    results.append({
                        "file": str(py_file.relative_to(ws)),
                        "name": node.name,
                        "type": "class",
                        "line": node.lineno,
                    })
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and name_lower in node.name.lower():
                    if type and type.lower() not in ("function", "method"):
                        continue
                    results.append({
                        "file": str(py_file.relative_to(ws)),
                        "name": node.name,
                        "type": "function",
                        "line": node.lineno,
                    })
        except Exception:
            continue

    return {
        "ok": True,
        "query": name,
        "type_filter": type,
        "count": len(results),
        "results": results,
    }
