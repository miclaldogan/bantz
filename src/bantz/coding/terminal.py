"""Safe terminal command execution (Issue #4).

Features:
- Command deny list (dangerous commands blocked)
- Confirmation required for risky commands
- Timeout support
- Background process management
- Command history
"""
from __future__ import annotations

import asyncio
import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .security import SecurityPolicy, SecurityError, ConfirmationRequired


@dataclass
class CommandResult:
    """Result of a terminal command execution."""
    command: str
    stdout: str
    stderr: str
    return_code: int
    duration_ms: float
    timed_out: bool = False
    killed: bool = False
    pid: Optional[int] = None
    
    @property
    def ok(self) -> bool:
        """Check if command succeeded."""
        return self.return_code == 0 and not self.timed_out and not self.killed
    
    @property
    def output(self) -> str:
        """Combined stdout and stderr."""
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.strip())
        if self.stderr.strip():
            parts.append(f"[stderr]\n{self.stderr.strip()}")
        return "\n".join(parts)
    
    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "return_code": self.return_code,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "killed": self.killed,
            "pid": self.pid,
            "ok": self.ok,
        }


@dataclass
class BackgroundProcess:
    """Tracks a background process."""
    pid: int
    command: str
    started_at: float
    process: subprocess.Popen
    output_buffer: list[str] = field(default_factory=list)
    finished: bool = False
    return_code: Optional[int] = None


class TerminalExecutor:
    """Safe terminal command execution with security checks.
    
    Features:
    - Blocks dangerous commands (rm -rf /, fork bombs, etc.)
    - Requires confirmation for risky commands (sudo, rm, git push)
    - Configurable timeout
    - Background process support
    - Command history tracking
    """
    
    def __init__(
        self,
        working_dir: Path,
        *,
        timeout: float = 30.0,
        max_output_size: int = 1024 * 1024,  # 1MB
        security: Optional[SecurityPolicy] = None,
        shell: str = "/bin/bash",
    ):
        self.cwd = Path(working_dir).resolve()
        self.timeout = timeout
        self.max_output_size = max_output_size
        self._security = security or SecurityPolicy(workspace_root=self.cwd)
        self.shell = shell
        
        self.history: list[CommandResult] = []
        self._background_processes: dict[int, BackgroundProcess] = {}
        self._next_bg_id = 1
    
    # ─────────────────────────────────────────────────────────────────
    # Synchronous Execution
    # ─────────────────────────────────────────────────────────────────
    def run(
        self,
        command: str,
        *,
        confirmed: bool = False,
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        env: Optional[dict] = None,
    ) -> CommandResult:
        """Run a terminal command synchronously.
        
        Args:
            command: Shell command to execute
            confirmed: Whether user has confirmed (for risky commands)
            timeout: Command timeout in seconds (default: self.timeout)
            cwd: Working directory override
            env: Environment variables to add
            
        Returns:
            CommandResult with stdout, stderr, return code
            
        Raises:
            SecurityError: If command is denied
            ConfirmationRequired: If command needs confirmation
        """
        # Security check
        self._security.validate_command(command, confirmed=confirmed)
        
        # Prepare execution
        effective_timeout = timeout if timeout is not None else self.timeout
        effective_cwd = Path(cwd).resolve() if cwd else self.cwd
        
        # Ensure cwd exists
        if not effective_cwd.exists():
            effective_cwd.mkdir(parents=True, exist_ok=True)
        
        # Prepare environment
        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)
        
        # Execute
        start_time = time.time()
        timed_out = False
        killed = False
        pid = None
        
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                executable=self.shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(effective_cwd),
                env=proc_env,
                text=True,
                preexec_fn=os.setsid if os.name != "nt" else None,
            )
            pid = proc.pid
            
            try:
                stdout, stderr = proc.communicate(timeout=effective_timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                # Kill process group
                try:
                    if os.name != "nt":
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    else:
                        proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    killed = True
                stdout, stderr = proc.communicate()
            
            # Truncate output if too large
            if len(stdout) > self.max_output_size:
                stdout = stdout[:self.max_output_size] + f"\n... [truncated, {len(stdout)} bytes total]"
            if len(stderr) > self.max_output_size:
                stderr = stderr[:self.max_output_size] + f"\n... [truncated, {len(stderr)} bytes total]"
            
            duration_ms = (time.time() - start_time) * 1000
            
            result = CommandResult(
                command=command,
                stdout=stdout,
                stderr=stderr,
                return_code=proc.returncode,
                duration_ms=duration_ms,
                timed_out=timed_out,
                killed=killed,
                pid=pid,
            )
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            result = CommandResult(
                command=command,
                stdout="",
                stderr=str(e),
                return_code=-1,
                duration_ms=duration_ms,
                timed_out=False,
                killed=False,
                pid=pid,
            )
        
        # Record history
        self.history.append(result)
        
        return result
    
    # ─────────────────────────────────────────────────────────────────
    # Async Execution
    # ─────────────────────────────────────────────────────────────────
    async def run_async(
        self,
        command: str,
        *,
        confirmed: bool = False,
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
    ) -> CommandResult:
        """Run a terminal command asynchronously.
        
        Same as run() but non-blocking.
        """
        # Security check
        self._security.validate_command(command, confirmed=confirmed)
        
        effective_timeout = timeout if timeout is not None else self.timeout
        effective_cwd = Path(cwd).resolve() if cwd else self.cwd
        
        start_time = time.time()
        timed_out = False
        killed = False
        
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(effective_cwd),
            )
            
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                timed_out = True
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except Exception:
                    proc.kill()
                    killed = True
                stdout_bytes, stderr_bytes = b"", b""
            
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            
            # Truncate
            if len(stdout) > self.max_output_size:
                stdout = stdout[:self.max_output_size] + "\n... [truncated]"
            if len(stderr) > self.max_output_size:
                stderr = stderr[:self.max_output_size] + "\n... [truncated]"
            
            duration_ms = (time.time() - start_time) * 1000
            
            result = CommandResult(
                command=command,
                stdout=stdout,
                stderr=stderr,
                return_code=proc.returncode or 0,
                duration_ms=duration_ms,
                timed_out=timed_out,
                killed=killed,
                pid=proc.pid,
            )
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            result = CommandResult(
                command=command,
                stdout="",
                stderr=str(e),
                return_code=-1,
                duration_ms=duration_ms,
                timed_out=False,
                killed=False,
            )
        
        self.history.append(result)
        return result
    
    # ─────────────────────────────────────────────────────────────────
    # Background Process Management
    # ─────────────────────────────────────────────────────────────────
    def run_background(
        self,
        command: str,
        *,
        confirmed: bool = False,
        cwd: Optional[str] = None,
    ) -> int:
        """Run command in background, return process ID.
        
        Args:
            command: Shell command to execute
            confirmed: User confirmation for risky commands
            cwd: Working directory
            
        Returns:
            Internal process ID (not system PID)
        """
        # Security check
        self._security.validate_command(command, confirmed=confirmed)
        
        effective_cwd = Path(cwd).resolve() if cwd else self.cwd
        
        proc = subprocess.Popen(
            command,
            shell=True,
            executable=self.shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(effective_cwd),
            text=True,
            preexec_fn=os.setsid if os.name != "nt" else None,
        )
        
        bg_id = self._next_bg_id
        self._next_bg_id += 1
        
        self._background_processes[bg_id] = BackgroundProcess(
            pid=proc.pid,
            command=command,
            started_at=time.time(),
            process=proc,
        )
        
        return bg_id
    
    def get_background_output(self, bg_id: int, *, wait: bool = False) -> Optional[str]:
        """Get output from a background process.
        
        Args:
            bg_id: Background process ID
            wait: Whether to wait for process to finish
            
        Returns:
            Output string, or None if process not found
        """
        if bg_id not in self._background_processes:
            return None
        
        bg = self._background_processes[bg_id]
        
        if wait:
            stdout, _ = bg.process.communicate()
            bg.output_buffer.append(stdout)
            bg.finished = True
            bg.return_code = bg.process.returncode
        else:
            # Non-blocking read
            if bg.process.stdout:
                try:
                    # Read available data
                    import select
                    if hasattr(select, "select"):
                        readable, _, _ = select.select([bg.process.stdout], [], [], 0)
                        if readable:
                            data = bg.process.stdout.read(4096)
                            if data:
                                bg.output_buffer.append(data)
                except Exception:
                    pass
            
            # Check if finished
            ret = bg.process.poll()
            if ret is not None:
                bg.finished = True
                bg.return_code = ret
        
        return "".join(bg.output_buffer)
    
    def is_background_running(self, bg_id: int) -> bool:
        """Check if background process is still running."""
        if bg_id not in self._background_processes:
            return False
        
        bg = self._background_processes[bg_id]
        if bg.finished:
            return False
        
        ret = bg.process.poll()
        if ret is not None:
            bg.finished = True
            bg.return_code = ret
            return False
        
        return True
    
    def kill_background(self, bg_id: int) -> bool:
        """Kill a background process.
        
        Args:
            bg_id: Background process ID
            
        Returns:
            True if killed successfully
        """
        if bg_id not in self._background_processes:
            return False
        
        bg = self._background_processes[bg_id]
        
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(bg.process.pid), signal.SIGTERM)
            else:
                bg.process.terminate()
            bg.process.wait(timeout=5)
        except Exception:
            try:
                bg.process.kill()
            except Exception:
                return False
        
        bg.finished = True
        return True
    
    def list_background(self) -> list[dict]:
        """List all background processes."""
        results = []
        for bg_id, bg in self._background_processes.items():
            # Update status
            if not bg.finished:
                ret = bg.process.poll()
                if ret is not None:
                    bg.finished = True
                    bg.return_code = ret
            
            results.append({
                "id": bg_id,
                "pid": bg.pid,
                "command": bg.command[:50] + ("..." if len(bg.command) > 50 else ""),
                "running": not bg.finished,
                "return_code": bg.return_code,
                "started_at": bg.started_at,
                "duration_seconds": time.time() - bg.started_at,
            })
        
        return results
    
    # ─────────────────────────────────────────────────────────────────
    # Utility Methods
    # ─────────────────────────────────────────────────────────────────
    def get_history(self, limit: int = 10) -> list[dict]:
        """Get recent command history."""
        history = self.history[-limit:] if limit > 0 else self.history
        return [r.to_dict() for r in reversed(history)]
    
    def clear_history(self) -> None:
        """Clear command history."""
        self.history.clear()
    
    def which(self, program: str) -> Optional[str]:
        """Find program in PATH."""
        result = self.run(f"which {shlex.quote(program)}", confirmed=True)
        if result.ok:
            return result.stdout.strip()
        return None
    
    def get_environment_variable(self, name: str) -> Optional[str]:
        """Get environment variable value."""
        return os.environ.get(name)
    
    def set_working_directory(self, path: str) -> bool:
        """Change working directory."""
        new_cwd = Path(path).resolve()
        
        # Security check
        allowed, _ = self._security.is_path_allowed(new_cwd)
        if not allowed:
            raise SecurityError(f"Cannot change to directory outside sandbox: {path}")
        
        if not new_cwd.exists():
            raise FileNotFoundError(f"Directory not found: {path}")
        
        if not new_cwd.is_dir():
            raise ValueError(f"Not a directory: {path}")
        
        self.cwd = new_cwd
        return True
    
    def get_working_directory(self) -> str:
        """Get current working directory."""
        return str(self.cwd)
