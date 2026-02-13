"""File system runtime tool handlers — sandboxed file operations.

Issue #845: Planner-Runtime Tool Gap Kapatma
─────────────────────────────────────────────
Provides runtime handlers for 6 file tools with sandbox protection:
- Path validation (no traversal outside workspace)
- Automatic backups before writes
- Configurable workspace root
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Default workspace root — can be overridden
_WORKSPACE_ROOT: Path | None = None
_BACKUP_DIR: Path | None = None

# Max file size for read (10 MB)
_MAX_READ_SIZE = 10 * 1024 * 1024
# Max file size for write (5 MB)
_MAX_WRITE_SIZE = 5 * 1024 * 1024
# Max search results
_MAX_SEARCH_RESULTS = 100


def configure_workspace(root: str | Path | None = None) -> None:
    """Configure the workspace root for file operations."""
    global _WORKSPACE_ROOT, _BACKUP_DIR
    if root is None:
        root = Path.home()
    _WORKSPACE_ROOT = Path(root).resolve()
    _BACKUP_DIR = _WORKSPACE_ROOT / ".bantz" / "backups"
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _get_workspace() -> Path:
    """Get workspace root, initializing if needed."""
    if _WORKSPACE_ROOT is None:
        configure_workspace()
    return _WORKSPACE_ROOT  # type: ignore[return-value]


def _validate_path(path_str: str) -> tuple[Path | None, str | None]:
    """Validate and resolve a path within the workspace.

    Returns (resolved_path, error_message).
    """
    ws = _get_workspace()
    try:
        p = Path(path_str).expanduser()
        if not p.is_absolute():
            p = ws / p
        p = p.resolve()

        # Sandbox: must be within workspace or home
        home = Path.home().resolve()
        if not (str(p).startswith(str(ws)) or str(p).startswith(str(home))):
            return None, f"path_outside_sandbox: {p}"

        # Block sensitive paths
        blocked = [".ssh", ".gnupg", ".config/bantz/secrets", ".env"]
        for b in blocked:
            if (home / b) == p or str(p).startswith(str(home / b)):
                return None, f"blocked_sensitive_path: {p}"

        return p, None
    except Exception as e:
        return None, f"invalid_path: {e}"


def _make_backup(path: Path) -> str | None:
    """Create a backup of a file. Returns backup path or None."""
    if not path.exists():
        return None
    try:
        if _BACKUP_DIR is None:
            configure_workspace()
        bdir = _BACKUP_DIR or Path.home() / ".bantz" / "backups"
        bdir.mkdir(parents=True, exist_ok=True)

        import time
        ts = int(time.time())
        backup_name = f"{path.name}.{ts}.bak"
        backup_path = bdir / backup_name
        shutil.copy2(str(path), str(backup_path))
        return str(backup_path)
    except Exception as e:
        logger.warning(f"Backup failed for {path}: {e}")
        return None


# ── file_read ───────────────────────────────────────────────────────

def file_read_tool(*, path: str = "", start_line: int | None = None, end_line: int | None = None, **_: Any) -> Dict[str, Any]:
    """Read file contents, optionally a specific line range."""
    if not path:
        return {"ok": False, "error": "path_required"}

    resolved, err = _validate_path(path)
    if err:
        return {"ok": False, "error": err}

    if not resolved.exists():  # type: ignore[union-attr]
        return {"ok": False, "error": f"file_not_found: {path}"}

    if not resolved.is_file():  # type: ignore[union-attr]
        return {"ok": False, "error": f"not_a_file: {path}"}

    try:
        size = resolved.stat().st_size  # type: ignore[union-attr]
        if size > _MAX_READ_SIZE:
            return {"ok": False, "error": f"file_too_large: {size} bytes (max {_MAX_READ_SIZE})"}

        content = resolved.read_text(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        lines = content.splitlines(keepends=True)

        if start_line is not None and end_line is not None:
            # 1-indexed
            start_line = max(1, start_line)
            end_line = min(len(lines), end_line)
            selected = lines[start_line - 1 : end_line]
            content = "".join(selected)
            return {
                "ok": True,
                "path": str(resolved),
                "content": content,
                "start_line": start_line,
                "end_line": end_line,
                "total_lines": len(lines),
            }

        return {
            "ok": True,
            "path": str(resolved),
            "content": content[:50000],  # Truncate for LLM
            "total_lines": len(lines),
            "truncated": len(content) > 50000,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── file_write ──────────────────────────────────────────────────────

def file_write_tool(*, path: str = "", content: str = "", **_: Any) -> Dict[str, Any]:
    """Write content to a file. Creates backup automatically."""
    if not path:
        return {"ok": False, "error": "path_required"}

    resolved, err = _validate_path(path)
    if err:
        return {"ok": False, "error": err}

    if len(content.encode("utf-8")) > _MAX_WRITE_SIZE:
        return {"ok": False, "error": f"content_too_large (max {_MAX_WRITE_SIZE} bytes)"}

    try:
        backup = None
        if resolved.exists():  # type: ignore[union-attr]
            backup = _make_backup(resolved)  # type: ignore[arg-type]

        resolved.parent.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
        resolved.write_text(content, encoding="utf-8")  # type: ignore[union-attr]

        return {
            "ok": True,
            "path": str(resolved),
            "written": True,
            "size_bytes": len(content.encode("utf-8")),
            "backup": backup,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── file_edit ───────────────────────────────────────────────────────

def file_edit_tool(*, path: str = "", old_string: str = "", new_string: str = "", **_: Any) -> Dict[str, Any]:
    """Replace a specific string in a file."""
    if not path or not old_string:
        return {"ok": False, "error": "path_and_old_string_required"}

    resolved, err = _validate_path(path)
    if err:
        return {"ok": False, "error": err}

    if not resolved.exists():  # type: ignore[union-attr]
        return {"ok": False, "error": f"file_not_found: {path}"}

    try:
        content = resolved.read_text(encoding="utf-8")  # type: ignore[union-attr]

        if old_string not in content:
            return {"ok": False, "error": "old_string_not_found"}

        count = content.count(old_string)
        if count > 1:
            return {"ok": False, "error": f"ambiguous_match: {count} occurrences found"}

        backup = _make_backup(resolved)  # type: ignore[arg-type]
        new_content = content.replace(old_string, new_string, 1)
        resolved.write_text(new_content, encoding="utf-8")  # type: ignore[union-attr]

        return {
            "ok": True,
            "path": str(resolved),
            "edited": True,
            "backup": backup,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── file_create ─────────────────────────────────────────────────────

def file_create_tool(*, path: str = "", content: str = "", **_: Any) -> Dict[str, Any]:
    """Create a new file with optional content."""
    if not path:
        return {"ok": False, "error": "path_required"}

    resolved, err = _validate_path(path)
    if err:
        return {"ok": False, "error": err}

    if resolved.exists():  # type: ignore[union-attr]
        return {"ok": False, "error": f"file_already_exists: {path}"}

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)  # type: ignore[union-attr]
        resolved.write_text(content or "", encoding="utf-8")  # type: ignore[union-attr]
        return {
            "ok": True,
            "path": str(resolved),
            "created": True,
            "size_bytes": len((content or "").encode("utf-8")),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── file_undo ───────────────────────────────────────────────────────

def file_undo_tool(*, path: str = "", **_: Any) -> Dict[str, Any]:
    """Undo the last edit by restoring from backup."""
    if not path:
        return {"ok": False, "error": "path_required"}

    resolved, err = _validate_path(path)
    if err:
        return {"ok": False, "error": err}

    if _BACKUP_DIR is None:
        configure_workspace()

    bdir = _BACKUP_DIR or Path.home() / ".bantz" / "backups"
    if not bdir.exists():
        return {"ok": False, "error": "no_backups_found"}

    # Find latest backup for this file
    fname = resolved.name  # type: ignore[union-attr]
    backups = sorted(
        [f for f in bdir.iterdir() if f.name.startswith(f"{fname}.")],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    if not backups:
        return {"ok": False, "error": f"no_backup_for: {fname}"}

    latest = backups[0]
    try:
        shutil.copy2(str(latest), str(resolved))
        latest.unlink()  # Remove used backup
        return {
            "ok": True,
            "path": str(resolved),
            "restored_from": str(latest),
            "undone": True,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── file_search ─────────────────────────────────────────────────────

def file_search_tool(*, pattern: str = "", content: str | None = None, path: str = ".", **_: Any) -> Dict[str, Any]:
    """Search for files by name pattern, optionally matching content."""
    if not pattern:
        return {"ok": False, "error": "pattern_required"}

    resolved, err = _validate_path(path)
    if err:
        return {"ok": False, "error": err}

    if not resolved.is_dir():  # type: ignore[union-attr]
        return {"ok": False, "error": f"not_a_directory: {path}"}

    try:
        matches = []
        content_re = re.compile(content, re.IGNORECASE) if content else None

        for root, dirs, files in os.walk(str(resolved)):
            # Skip hidden/venv/node_modules
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "venv", ".venv")]

            for f in files:
                if len(matches) >= _MAX_SEARCH_RESULTS:
                    break

                if fnmatch.fnmatch(f, pattern):
                    fpath = os.path.join(root, f)

                    if content_re:
                        try:
                            text = Path(fpath).read_text(encoding="utf-8", errors="ignore")[:100_000]
                            if content_re.search(text):
                                matches.append(fpath)
                        except Exception:
                            pass
                    else:
                        matches.append(fpath)

        return {
            "ok": True,
            "pattern": pattern,
            "content_filter": content,
            "count": len(matches),
            "files": matches,
            "truncated": len(matches) >= _MAX_SEARCH_RESULTS,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
