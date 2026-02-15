"""PC Agent — file operations, app management, clipboard, system info.

Issue #1295: PC Agent + CodingAgent — bilgisayar yönetim agent'ı.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from bantz.agent.safety import SafetyGuardrails
from bantz.agent.sandbox import SandboxExecutor

logger = logging.getLogger(__name__)


@dataclass
class FileInfo:
    """Information about a file or directory."""

    path: str
    name: str
    is_dir: bool
    size: int
    modified: str
    extension: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "is_dir": self.is_dir,
            "size": self.size,
            "modified": self.modified,
            "extension": self.extension,
        }


class PCAgent:
    """PC management agent — file, application, clipboard, system info.

    All destructive operations go through the SandboxExecutor for
    safety and rollback support.
    """

    def __init__(
        self,
        sandbox: SandboxExecutor | None = None,
        guardrails: SafetyGuardrails | None = None,
    ) -> None:
        self._sandbox = sandbox or SandboxExecutor(mode="none")
        self._guardrails = guardrails or SafetyGuardrails()

    # ── File Operations ──────────────────────────────────────────

    async def list_files(
        self,
        path: str,
        *,
        pattern: str = "*",
        recursive: bool = False,
        include_hidden: bool = False,
    ) -> list[FileInfo]:
        """List files in a directory.

        Args:
            path: Directory path to list.
            pattern: Glob pattern filter (default: all files).
            recursive: Whether to list recursively.
            include_hidden: Whether to include hidden files.

        Returns:
            List of :class:`FileInfo` objects.
        """
        target = Path(path).expanduser().resolve()
        if not target.is_dir():
            logger.warning("[PCAgent] Not a directory: %s", target)
            return []

        glob_fn = target.rglob if recursive else target.glob
        results: list[FileInfo] = []

        try:
            for entry in glob_fn(pattern):
                if not include_hidden and entry.name.startswith("."):
                    continue
                try:
                    stat = entry.stat()
                    results.append(FileInfo(
                        path=str(entry),
                        name=entry.name,
                        is_dir=entry.is_dir(),
                        size=stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        extension=entry.suffix,
                    ))
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError) as exc:
            logger.error("[PCAgent] list_files error: %s", exc)

        return sorted(results, key=lambda f: f.name)

    async def search_files(
        self,
        directory: str,
        query: str,
        *,
        max_results: int = 50,
    ) -> list[FileInfo]:
        """Search for files matching a query in a directory."""
        all_files = await self.list_files(
            directory, pattern=f"*{query}*", recursive=True
        )
        return all_files[:max_results]

    async def file_info(self, path: str) -> dict[str, Any]:
        """Get detailed information about a file."""
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return {"ok": False, "error": f"Dosya bulunamadı: {path}"}

        try:
            stat = target.stat()
            return {
                "ok": True,
                "path": str(target),
                "name": target.name,
                "is_dir": target.is_dir(),
                "size": stat.st_size,
                "size_human": self._human_size(stat.st_size),
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "extension": target.suffix,
                "permissions": oct(stat.st_mode)[-3:],
            }
        except (OSError, PermissionError) as exc:
            return {"ok": False, "error": str(exc)}

    async def organize_files(
        self,
        source_dir: str,
        *,
        by: str = "extension",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Organize files in a directory by extension or date.

        Default is dry-run mode — shows what would be moved.
        """
        target = Path(source_dir).expanduser().resolve()
        if not target.is_dir():
            return {"ok": False, "error": f"Dizin bulunamadı: {source_dir}"}

        moves: list[dict[str, str]] = []
        for entry in target.iterdir():
            if entry.is_dir() or entry.name.startswith("."):
                continue

            if by == "extension":
                ext = entry.suffix.lstrip(".") or "other"
                dest_dir = target / ext
            else:
                mtime = datetime.fromtimestamp(entry.stat().st_mtime)
                dest_dir = target / mtime.strftime("%Y-%m")

            moves.append({
                "from": str(entry),
                "to": str(dest_dir / entry.name),
                "dest_dir": str(dest_dir),
            })

        if not dry_run:
            moved = 0
            for move in moves:
                dest_dir = Path(move["dest_dir"])
                dest_dir.mkdir(exist_ok=True)
                try:
                    shutil.move(move["from"], move["to"])
                    moved += 1
                except (OSError, shutil.Error) as exc:
                    logger.warning("[PCAgent] Move failed: %s", exc)
            return {"ok": True, "moved": moved, "total": len(moves)}

        return {
            "ok": True,
            "dry_run": True,
            "planned_moves": len(moves),
            "preview": moves[:10],
        }

    # ── App Launcher ─────────────────────────────────────────────

    async def launch_app(
        self, app_name: str, args: list[str] | None = None
    ) -> dict[str, Any]:
        """Launch a desktop application."""
        cmd_parts = [app_name] + (args or [])
        cmd = " ".join(cmd_parts)

        safety = self._guardrails.check(cmd)
        if safety.blocked:
            return {"ok": False, "error": safety.reason}

        result = await self._sandbox.execute(
            cmd, timeout=5, dry_run=False
        )
        return {
            "ok": result.ok,
            "app": app_name,
            "stdout": result.stdout[:500],
            "error": result.stderr[:500] if not result.ok else None,
        }

    # ── Clipboard ────────────────────────────────────────────────

    async def clipboard_get(self) -> dict[str, Any]:
        """Get current clipboard content."""
        try:
            result = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return {"ok": True, "content": result.stdout}
            return {"ok": False, "error": "Panoya erişilemedi."}
        except FileNotFoundError:
            return {"ok": False, "error": "xclip kurulu değil."}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Pano zaman aşımı."}

    async def clipboard_set(self, content: str) -> dict[str, Any]:
        """Set clipboard content."""
        try:
            proc = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
            )
            proc.communicate(input=content.encode("utf-8"), timeout=5)
            return {"ok": True, "length": len(content)}
        except FileNotFoundError:
            return {"ok": False, "error": "xclip kurulu değil."}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Pano zaman aşımı."}

    # ── System Info ──────────────────────────────────────────────

    async def system_info(self) -> dict[str, Any]:
        """Get system information: CPU, RAM, disk, OS."""
        info: dict[str, Any] = {"ok": True}

        try:
            import psutil

            info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            info["ram_total_gb"] = round(mem.total / (1024 ** 3), 1)
            info["ram_used_gb"] = round(mem.used / (1024 ** 3), 1)
            info["ram_percent"] = mem.percent

            disk = psutil.disk_usage("/")
            info["disk_total_gb"] = round(disk.total / (1024 ** 3), 1)
            info["disk_used_gb"] = round(disk.used / (1024 ** 3), 1)
            info["disk_percent"] = round(disk.percent, 1)
        except ImportError:
            info["note"] = "psutil not installed — limited info"

        info["hostname"] = os.uname().nodename
        info["os"] = f"{os.uname().sysname} {os.uname().release}"

        return info

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _human_size(size: int) -> str:
        """Convert bytes to human-readable size."""
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
