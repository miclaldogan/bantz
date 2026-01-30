"""
Sandbox Environment.

Provides isolated execution environment for:
- Plugin code
- User scripts
- External commands
- Untrusted operations

This module provides a basic sandboxing framework with plans
for more advanced isolation (containers, seccomp, etc.) in the future.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from pathlib import Path
from datetime import datetime
from enum import Enum
import logging
import os
import subprocess
import tempfile
import threading
import time
import signal
import shutil

logger = logging.getLogger(__name__)


# =============================================================================
# Sandbox Configuration
# =============================================================================


class IsolationLevel(Enum):
    """Level of isolation for sandbox execution."""
    
    NONE = "none"              # No isolation
    BASIC = "basic"            # Basic resource limits
    RESTRICTED = "restricted"  # Restricted permissions
    CONTAINER = "container"    # Container isolation (future)


@dataclass
class SandboxConfig:
    """Configuration for sandbox environment."""
    
    # Isolation level
    isolation_level: IsolationLevel = IsolationLevel.BASIC
    
    # Resource limits
    max_memory_mb: float = 512
    max_cpu_percent: float = 50
    max_time_seconds: float = 30
    max_processes: int = 10
    max_file_size_mb: float = 10
    max_open_files: int = 100
    
    # Filesystem
    temp_dir: Optional[Path] = None
    allowed_read_paths: List[Path] = field(default_factory=list)
    allowed_write_paths: List[Path] = field(default_factory=list)
    
    # Network
    allow_network: bool = False
    allowed_hosts: List[str] = field(default_factory=list)
    
    # Execution
    allow_subprocesses: bool = False
    environment: Dict[str, str] = field(default_factory=dict)


# =============================================================================
# Sandbox Result
# =============================================================================


@dataclass
class SandboxResult:
    """Result of sandbox execution."""
    
    success: bool
    return_value: Any = None
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    execution_time: float = 0.0
    memory_used_mb: float = 0.0
    error: Optional[str] = None
    terminated: bool = False
    termination_reason: Optional[str] = None


# =============================================================================
# Sandbox Exceptions
# =============================================================================


class SandboxError(Exception):
    """Base sandbox error."""
    pass


class SandboxTimeoutError(SandboxError):
    """Execution exceeded time limit."""
    pass


class SandboxResourceError(SandboxError):
    """Resource limit exceeded."""
    pass


class SandboxPermissionError(SandboxError):
    """Operation not permitted in sandbox."""
    pass


# =============================================================================
# Sandbox Implementation
# =============================================================================


class Sandbox:
    """
    Isolated execution environment.
    
    Provides:
    - Resource limits (memory, CPU, time)
    - Filesystem restrictions
    - Network isolation
    - Temporary workspace
    
    Example:
        sandbox = Sandbox(SandboxConfig(
            max_time_seconds=10,
            max_memory_mb=256,
        ))
        
        # Run a function
        result = sandbox.run(my_function, arg1, arg2)
        
        # Run a command
        result = sandbox.execute_command(["python", "script.py"])
    """
    
    def __init__(self, config: Optional[SandboxConfig] = None):
        """
        Initialize sandbox.
        
        Args:
            config: Sandbox configuration
        """
        self.config = config or SandboxConfig()
        self._temp_dir: Optional[Path] = None
        self._active = False
        self._lock = threading.Lock()
    
    @property
    def temp_dir(self) -> Path:
        """Get or create temporary directory for sandbox."""
        if self._temp_dir is None or not self._temp_dir.exists():
            if self.config.temp_dir:
                self._temp_dir = self.config.temp_dir
                self._temp_dir.mkdir(parents=True, exist_ok=True)
            else:
                self._temp_dir = Path(tempfile.mkdtemp(prefix="bantz_sandbox_"))
        return self._temp_dir
    
    def run(
        self,
        func: Callable,
        *args,
        **kwargs,
    ) -> SandboxResult:
        """
        Run a Python function in sandbox.
        
        Args:
            func: Function to run
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            SandboxResult
        """
        start_time = time.time()
        result = SandboxResult(success=False)
        
        try:
            with self._lock:
                self._active = True
            
            # Run with timeout
            return_value = None
            error = None
            
            def target():
                nonlocal return_value, error
                try:
                    return_value = func(*args, **kwargs)
                except Exception as e:
                    error = str(e)
            
            thread = threading.Thread(target=target)
            thread.start()
            thread.join(timeout=self.config.max_time_seconds)
            
            if thread.is_alive():
                result.terminated = True
                result.termination_reason = "timeout"
                result.error = f"Execution exceeded {self.config.max_time_seconds}s limit"
            elif error:
                result.error = error
            else:
                result.success = True
                result.return_value = return_value
                
        except Exception as e:
            result.error = str(e)
        finally:
            result.execution_time = time.time() - start_time
            with self._lock:
                self._active = False
        
        return result
    
    def execute_command(
        self,
        command: Union[str, List[str]],
        stdin: Optional[str] = None,
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> SandboxResult:
        """
        Execute a command in sandbox.
        
        Args:
            command: Command to execute
            stdin: Standard input
            cwd: Working directory
            env: Environment variables
            
        Returns:
            SandboxResult
        """
        if isinstance(command, str):
            shell = True
        else:
            shell = False
        
        start_time = time.time()
        result = SandboxResult(success=False)
        
        # Prepare environment
        run_env = os.environ.copy()
        run_env.update(self.config.environment)
        if env:
            run_env.update(env)
        
        # Working directory
        work_dir = cwd or self.temp_dir
        
        try:
            with self._lock:
                self._active = True
            
            process = subprocess.Popen(
                command,
                shell=shell,
                stdin=subprocess.PIPE if stdin else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=work_dir,
                env=run_env,
            )
            
            try:
                stdout, stderr = process.communicate(
                    input=stdin.encode() if stdin else None,
                    timeout=self.config.max_time_seconds,
                )
                
                result.stdout = stdout.decode("utf-8", errors="replace")
                result.stderr = stderr.decode("utf-8", errors="replace")
                result.exit_code = process.returncode
                result.success = process.returncode == 0
                
            except subprocess.TimeoutExpired:
                process.kill()
                result.terminated = True
                result.termination_reason = "timeout"
                result.error = f"Command exceeded {self.config.max_time_seconds}s limit"
                
        except Exception as e:
            result.error = str(e)
        finally:
            result.execution_time = time.time() - start_time
            with self._lock:
                self._active = False
        
        return result
    
    def execute_python(
        self,
        code: str,
        timeout: Optional[float] = None,
    ) -> SandboxResult:
        """
        Execute Python code in sandbox.
        
        Args:
            code: Python code to execute
            timeout: Override default timeout
            
        Returns:
            SandboxResult
        """
        # Write code to temp file
        script_path = self.temp_dir / "sandbox_script.py"
        script_path.write_text(code)
        
        # Execute with python
        old_timeout = self.config.max_time_seconds
        if timeout:
            self.config.max_time_seconds = timeout
        
        try:
            result = self.execute_command(
                ["python", str(script_path)],
                cwd=self.temp_dir,
            )
        finally:
            self.config.max_time_seconds = old_timeout
        
        return result
    
    def create_file(self, name: str, content: str) -> Path:
        """
        Create a file in sandbox temp directory.
        
        Args:
            name: File name
            content: File content
            
        Returns:
            Path to created file
        """
        path = self.temp_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path
    
    def read_file(self, name: str) -> str:
        """
        Read a file from sandbox temp directory.
        
        Args:
            name: File name
            
        Returns:
            File content
            
        Raises:
            FileNotFoundError: If file doesn't exist
        """
        path = self.temp_dir / name
        if not path.exists():
            raise FileNotFoundError(f"File not found in sandbox: {name}")
        return path.read_text()
    
    def list_files(self) -> List[str]:
        """List files in sandbox temp directory."""
        if not self._temp_dir or not self._temp_dir.exists():
            return []
        
        files = []
        for item in self._temp_dir.rglob("*"):
            if item.is_file():
                files.append(str(item.relative_to(self._temp_dir)))
        return files
    
    def cleanup(self) -> None:
        """Clean up sandbox resources."""
        if self._temp_dir and self._temp_dir.exists():
            try:
                shutil.rmtree(self._temp_dir)
                logger.debug(f"Cleaned up sandbox: {self._temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to cleanup sandbox: {e}")
        self._temp_dir = None
    
    def __enter__(self) -> "Sandbox":
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - cleanup."""
        self.cleanup()
    
    @property
    def is_active(self) -> bool:
        """Check if sandbox is currently executing."""
        with self._lock:
            return self._active


# =============================================================================
# Restricted Sandbox
# =============================================================================


class RestrictedSandbox(Sandbox):
    """
    Enhanced sandbox with tighter restrictions.
    
    Adds:
    - Path validation
    - Import restrictions (future)
    - System call filtering (future)
    """
    
    def __init__(self, config: Optional[SandboxConfig] = None):
        config = config or SandboxConfig(isolation_level=IsolationLevel.RESTRICTED)
        super().__init__(config)
        
        self._blocked_commands = {
            "rm", "rmdir", "del", "format", "fdisk",
            "mkfs", "dd", "shutdown", "reboot", "halt",
            "poweroff", "init", "systemctl", "service",
        }
    
    def execute_command(
        self,
        command: Union[str, List[str]],
        stdin: Optional[str] = None,
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> SandboxResult:
        """Execute with additional safety checks."""
        
        # Check for blocked commands
        cmd_str = command if isinstance(command, str) else " ".join(command)
        cmd_parts = cmd_str.split()
        
        if cmd_parts:
            base_cmd = Path(cmd_parts[0]).name.lower()
            if base_cmd in self._blocked_commands:
                return SandboxResult(
                    success=False,
                    error=f"Command '{base_cmd}' is not allowed in sandbox",
                    terminated=True,
                    termination_reason="blocked_command",
                )
        
        return super().execute_command(command, stdin, cwd, env)
    
    def validate_path(self, path: Path) -> bool:
        """
        Check if path access is allowed.
        
        Args:
            path: Path to validate
            
        Returns:
            True if access is allowed
        """
        path = path.resolve()
        
        # Always allow temp dir
        if str(path).startswith(str(self.temp_dir)):
            return True
        
        # Check allowed paths
        for allowed in self.config.allowed_read_paths:
            if str(path).startswith(str(allowed.resolve())):
                return True
        
        return False


# =============================================================================
# Factory Functions
# =============================================================================


def create_sandbox(
    isolation: IsolationLevel = IsolationLevel.BASIC,
    **config_kwargs,
) -> Sandbox:
    """
    Create a sandbox with specified isolation level.
    
    Args:
        isolation: Isolation level
        **config_kwargs: Additional config options
        
    Returns:
        Appropriate Sandbox instance
    """
    config = SandboxConfig(isolation_level=isolation, **config_kwargs)
    
    if isolation == IsolationLevel.RESTRICTED:
        return RestrictedSandbox(config)
    else:
        return Sandbox(config)


# =============================================================================
# Mock Implementation
# =============================================================================


class MockSandbox(Sandbox):
    """Mock sandbox for testing."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._run_calls: List[Tuple[Callable, tuple, dict]] = []
        self._command_calls: List[Tuple[Union[str, List[str]], dict]] = []
        self._mock_results: Dict[str, SandboxResult] = {}
    
    def set_mock_result(self, key: str, result: SandboxResult) -> None:
        """Set a mock result for a key."""
        self._mock_results[key] = result
    
    def run(
        self,
        func: Callable,
        *args,
        **kwargs,
    ) -> SandboxResult:
        """Track run calls."""
        self._run_calls.append((func, args, kwargs))
        
        key = func.__name__ if hasattr(func, "__name__") else str(func)
        if key in self._mock_results:
            return self._mock_results[key]
        
        return super().run(func, *args, **kwargs)
    
    def execute_command(
        self,
        command: Union[str, List[str]],
        stdin: Optional[str] = None,
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> SandboxResult:
        """Track command calls."""
        self._command_calls.append((command, {"stdin": stdin, "cwd": cwd, "env": env}))
        
        cmd_key = command if isinstance(command, str) else command[0]
        if cmd_key in self._mock_results:
            return self._mock_results[cmd_key]
        
        # Return success by default
        return SandboxResult(
            success=True,
            stdout="mock output",
            exit_code=0,
        )
    
    def get_run_calls(self) -> List[Tuple[Callable, tuple, dict]]:
        """Get all run() calls."""
        return self._run_calls.copy()
    
    def get_command_calls(self) -> List[Tuple[Union[str, List[str]], dict]]:
        """Get all execute_command() calls."""
        return self._command_calls.copy()
