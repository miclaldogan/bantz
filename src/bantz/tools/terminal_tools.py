"""Terminal runtime tool handlers — policy-enforced command execution.

Issue #845: Planner-Runtime Tool Gap Kapatma
─────────────────────────────────────────────
Provides runtime handlers for 4 terminal tools with policy.json enforcement:
- Deny dangerous patterns (rm -rf, dd, mkfs, etc.)
- Confirm patterns (sudo, apt, kill, chmod, etc.)
- Timeout protection
- Background process management
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Background processes registry
_background_processes: dict[int, dict] = {}
_bg_counter = 0
_bg_lock = threading.Lock()

# Policy cache
_policy: dict | None = None


def _load_policy() -> dict:
    """Load policy.json — cached after first load."""
    global _policy
    if _policy is not None:
        return _policy

    policy_paths = [
        Path(__file__).parent.parent.parent.parent / "config" / "policy.json",
        Path.home() / ".config" / "bantz" / "policy.json",
    ]

    for pp in policy_paths:
        if pp.exists():
            try:
                _policy = json.loads(pp.read_text())
                logger.info(f"[Terminal] Policy loaded from {pp}")
                return _policy
            except Exception as e:
                logger.warning(f"[Terminal] Failed to load policy {pp}: {e}")

    # Fallback minimal policy
    _policy = {
        "deny_patterns": [
            "rm -rf /",
            "rm -rf ~",
            "dd if=",
            "mkfs",
            ":(){ :|:& };:",
            "shutdown",
            "reboot",
            "init 0",
            "init 6",
        ],
        "confirm_patterns": [
            "sudo",
            "apt",
            "kill",
            "chmod",
            "chown",
            "mv /",
        ],
    }
    return _policy


def _check_command(command: str) -> tuple[str, bool]:
    """Check command against policy.

    Patterns in policy.json are treated as regex when they contain
    regex metacharacters (\\b, \\s, etc.), otherwise as plain substrings.

    Returns:
        (status, needs_confirm) where status is "allow", "deny", or "confirm"
    """
    import re as _re

    policy = _load_policy()
    cmd_lower = command.lower().strip()

    def _matches(pattern: str, text: str) -> bool:
        """Match pattern as regex first, fall back to substring."""
        try:
            if _re.search(pattern, text, _re.IGNORECASE):
                return True
        except _re.error:
            pass
        return pattern.lower() in text

    # Check deny patterns
    for dp in policy.get("deny_patterns", []):
        if _matches(dp, cmd_lower):
            return "deny", False

    # Check for pipes/semicolons if denied
    deny_chars = policy.get("deny_chars", [])
    for dc in deny_chars:
        if dc in command:
            return "deny", False

    # Check confirm patterns
    for cp in policy.get("confirm_patterns", []):
        if _matches(cp, cmd_lower):
            return "confirm", True

    return "allow", False


# ── terminal_run ────────────────────────────────────────────────────

def terminal_run_tool(*, command: str = "", timeout: int = 60, **_: Any) -> Dict[str, Any]:
    """Run a shell command with policy enforcement."""
    if not command:
        return {"ok": False, "error": "command_required"}

    # Policy check
    status, needs_confirm = _check_command(command)
    if status == "deny":
        return {
            "ok": False,
            "error": "command_denied_by_policy",
            "command": command,
            "policy": "deny",
        }

    # Cap timeout
    timeout = max(1, min(timeout, 300))

    try:
        # Sanitize environment
        env = os.environ.copy()
        # Remove sensitive vars
        for key in list(env.keys()):
            if any(s in key.upper() for s in ("SECRET", "PASSWORD", "TOKEN", "API_KEY", "PRIVATE")):
                del env[key]

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(Path.home()),
        )

        output = ""
        if result.stdout:
            output += result.stdout[:10000]
        if result.stderr:
            if output:
                output += "\n--- STDERR ---\n"
            output += result.stderr[:5000]

        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "output": output,
            "command": command,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout_after_{timeout}s", "command": command}
    except Exception as e:
        return {"ok": False, "error": str(e), "command": command}


# ── terminal_background ────────────────────────────────────────────

def terminal_background_tool(*, command: str = "", **_: Any) -> Dict[str, Any]:
    """Start a command in the background."""
    global _bg_counter

    if not command:
        return {"ok": False, "error": "command_required"}

    status, _ = _check_command(command)
    if status == "deny":
        return {"ok": False, "error": "command_denied_by_policy", "command": command}

    try:
        env = os.environ.copy()
        for key in list(env.keys()):
            if any(s in key.upper() for s in ("SECRET", "PASSWORD", "TOKEN", "API_KEY", "PRIVATE")):
                del env[key]

        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd=str(Path.home()),
            preexec_fn=os.setsid,
        )

        with _bg_lock:
            _bg_counter += 1
            bg_id = _bg_counter
            _background_processes[bg_id] = {
                "id": bg_id,
                "command": command,
                "pid": proc.pid,
                "process": proc,
            }

        return {
            "ok": True,
            "id": bg_id,
            "pid": proc.pid,
            "command": command,
            "started": True,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "command": command}


# ── terminal_background_list ───────────────────────────────────────

def terminal_background_list_tool(**_: Any) -> Dict[str, Any]:
    """List all running background processes."""
    with _bg_lock:
        processes = []
        for bg_id, info in _background_processes.items():
            proc = info["process"]
            running = proc.poll() is None
            entry = {
                "id": bg_id,
                "pid": info["pid"],
                "command": info["command"],
                "running": running,
            }
            if not running:
                entry["exit_code"] = proc.returncode
            processes.append(entry)

    return {
        "ok": True,
        "count": len(processes),
        "processes": processes,
    }


# ── terminal_background_kill ───────────────────────────────────────

def terminal_background_kill_tool(*, id: int = 0, **_: Any) -> Dict[str, Any]:
    """Kill a background process by ID."""
    with _bg_lock:
        info = _background_processes.get(id)

    if info is None:
        return {"ok": False, "error": f"process_not_found: {id}"}

    proc = info["process"]
    if proc.poll() is not None:
        # Already dead
        with _bg_lock:
            _background_processes.pop(id, None)
        return {"ok": True, "id": id, "already_exited": True, "exit_code": proc.returncode}

    try:
        # Kill the process group
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait(timeout=2)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    with _bg_lock:
        _background_processes.pop(id, None)

    return {"ok": True, "id": id, "killed": True, "pid": info["pid"]}
