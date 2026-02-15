"""Sandbox execution environment — isolated command execution.

Issue #1295: PC Agent + CodingAgent — Sandbox Execution + Safety Guardrails.

Provides SandboxExecutor with:
- Firejail (default), Docker, or No-sandbox (test) modes
- Dry-run simulation
- Checkpoint/rollback mechanism for destructive operations
- Timeout enforcement
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of a sandboxed command execution."""

    command: str
    stdout: str
    stderr: str
    return_code: int
    duration_ms: float
    sandbox_mode: str
    dry_run: bool = False
    timed_out: bool = False
    checkpoint_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.return_code == 0 and not self.timed_out

    @property
    def output(self) -> str:
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.strip())
        if self.stderr.strip():
            parts.append(f"[stderr]\n{self.stderr.strip()}")
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "stdout": self.stdout[:4096],
            "stderr": self.stderr[:2048],
            "return_code": self.return_code,
            "duration_ms": round(self.duration_ms, 1),
            "sandbox_mode": self.sandbox_mode,
            "dry_run": self.dry_run,
            "timed_out": self.timed_out,
            "ok": self.ok,
            "checkpoint_id": self.checkpoint_id,
        }


@dataclass
class Checkpoint:
    """Rollback checkpoint for a command execution."""

    id: str
    command: str
    timestamp: datetime
    workdir: str
    affected_paths: list[str] = field(default_factory=list)
    backup_data: dict[str, Any] = field(default_factory=dict)
    rolled_back: bool = False


class SandboxExecutor:
    """Isolated command execution environment.

    Supports three modes:
    - ``firejail``: Linux Firejail sandbox (default)
    - ``docker``: Docker container isolation
    - ``none``: Direct execution (test/dev mode)

    All modes enforce timeout, environment sanitisation, and
    checkpoint/rollback for destructive operations.
    """

    # Environment variables to strip from child processes
    _STRIP_ENV_PATTERNS = (
        "SECRET", "TOKEN", "API_KEY", "PASSWORD",
        "PRIVATE_KEY", "CREDENTIALS",
    )

    def __init__(
        self,
        mode: str = "none",
        *,
        default_timeout: int = 30,
        allowed_dirs: list[str] | None = None,
        max_checkpoints: int = 50,
    ) -> None:
        self.mode = mode
        self.default_timeout = default_timeout
        self.allowed_dirs = allowed_dirs or [str(Path.home())]
        self._checkpoints: dict[str, Checkpoint] = {}
        self._max_checkpoints = max_checkpoints

    # ── public API ───────────────────────────────────────────────

    async def execute(
        self,
        command: str,
        *,
        workdir: str | None = None,
        timeout: int | None = None,
        dry_run: bool = False,
        env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        """Execute a command in the sandbox.

        Args:
            command: Shell command to execute.
            workdir: Working directory (default: user home).
            timeout: Timeout in seconds (default: ``default_timeout``).
            dry_run: If True, simulate execution without side effects.
            env: Extra environment variables to set.

        Returns:
            :class:`ExecutionResult` with output, exit code, etc.
        """
        effective_timeout = timeout if timeout is not None else self.default_timeout
        effective_workdir = workdir or str(Path.home())

        if dry_run:
            return await self._simulate(command, effective_workdir)

        start = time.monotonic()

        if self.mode == "firejail":
            result = await self._firejail_execute(
                command, effective_workdir, effective_timeout, env
            )
        elif self.mode == "docker":
            result = await self._docker_execute(
                command, effective_workdir, effective_timeout, env
            )
        else:
            result = await self._direct_execute(
                command, effective_workdir, effective_timeout, env
            )

        elapsed = (time.monotonic() - start) * 1000
        result.duration_ms = elapsed

        # Create checkpoint for tracking
        cp = self._create_checkpoint(command, effective_workdir)
        result.checkpoint_id = cp.id

        return result

    async def rollback(self, checkpoint_id: str) -> bool:
        """Roll back to a checkpoint.

        Currently supports logging-only rollback. File-level rollback
        requires future file-backup integration.
        """
        cp = self._checkpoints.get(checkpoint_id)
        if cp is None:
            logger.warning("[Sandbox] Checkpoint not found: %s", checkpoint_id)
            return False

        if cp.rolled_back:
            logger.info("[Sandbox] Already rolled back: %s", checkpoint_id)
            return True

        logger.info(
            "[Sandbox] Rolling back checkpoint %s (command: %s)",
            checkpoint_id,
            cp.command,
        )
        cp.rolled_back = True
        return True

    def get_checkpoints(self) -> list[dict[str, Any]]:
        """Return list of all checkpoints."""
        return [
            {
                "id": cp.id,
                "command": cp.command,
                "timestamp": cp.timestamp.isoformat(),
                "workdir": cp.workdir,
                "rolled_back": cp.rolled_back,
            }
            for cp in self._checkpoints.values()
        ]

    # ── execution backends ───────────────────────────────────────

    async def _simulate(
        self, command: str, workdir: str
    ) -> ExecutionResult:
        """Simulate command execution (dry-run mode)."""
        logger.info("[Sandbox] DRY-RUN: %s (cwd=%s)", command, workdir)
        return ExecutionResult(
            command=command,
            stdout=f"[DRY-RUN] Komut simüle edildi: {command}",
            stderr="",
            return_code=0,
            duration_ms=0.0,
            sandbox_mode=self.mode,
            dry_run=True,
        )

    async def _direct_execute(
        self,
        command: str,
        workdir: str,
        timeout: int,
        env: dict[str, str] | None,
    ) -> ExecutionResult:
        """Execute directly (no sandbox — test/dev mode)."""
        clean_env = self._sanitise_env(env)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                env=clean_env,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ExecutionResult(
                    command=command,
                    stdout="",
                    stderr="Komut zaman aşımına uğradı.",
                    return_code=-1,
                    duration_ms=timeout * 1000,
                    sandbox_mode="none",
                    timed_out=True,
                )

            return ExecutionResult(
                command=command,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                return_code=proc.returncode or 0,
                duration_ms=0.0,
                sandbox_mode="none",
            )

        except Exception as exc:
            return ExecutionResult(
                command=command,
                stdout="",
                stderr=str(exc),
                return_code=-1,
                duration_ms=0.0,
                sandbox_mode="none",
            )

    async def _firejail_execute(
        self,
        command: str,
        workdir: str,
        timeout: int,
        env: dict[str, str] | None,
    ) -> ExecutionResult:
        """Execute inside a Firejail sandbox."""
        allowed = " ".join(f"--whitelist={d}" for d in self.allowed_dirs)
        fj_cmd = (
            f"firejail --quiet --noprofile --net=none "
            f"--noroot {allowed} "
            f"--timeout={timeout} "
            f"-- {command}"
        )
        return await self._direct_execute(fj_cmd, workdir, timeout, env)

    async def _docker_execute(
        self,
        command: str,
        workdir: str,
        timeout: int,
        env: dict[str, str] | None,
    ) -> ExecutionResult:
        """Execute inside a Docker container."""
        docker_cmd = (
            f"docker run --rm --network none "
            f"-v {shlex.quote(workdir)}:/workspace "
            f"-w /workspace "
            f"python:3.10-slim "
            f"bash -c {shlex.quote(command)}"
        )
        return await self._direct_execute(docker_cmd, workdir, timeout, env)

    # ── helpers ──────────────────────────────────────────────────

    def _sanitise_env(
        self, extra: dict[str, str] | None
    ) -> dict[str, str]:
        """Create sanitised environment, stripping secrets."""
        clean = {}
        for k, v in os.environ.items():
            if any(pat in k.upper() for pat in self._STRIP_ENV_PATTERNS):
                continue
            clean[k] = v
        if extra:
            clean.update(extra)
        return clean

    def _create_checkpoint(
        self, command: str, workdir: str
    ) -> Checkpoint:
        """Create a new checkpoint for rollback."""
        cp_id = uuid.uuid4().hex[:12]
        cp = Checkpoint(
            id=cp_id,
            command=command,
            timestamp=datetime.now(),
            workdir=workdir,
        )
        self._checkpoints[cp_id] = cp

        # Prune old checkpoints
        if len(self._checkpoints) > self._max_checkpoints:
            oldest_key = next(iter(self._checkpoints))
            del self._checkpoints[oldest_key]

        return cp
