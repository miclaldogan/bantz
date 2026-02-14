"""TerminalExecutor deep tests (Issue #854).

Covers:
- Synchronous command execution
- Security enforcement (deny/confirm)
- Timeout handling
- Background processes
- Command history
- Working directory management
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from bantz.coding.security import ConfirmationRequired, SecurityError, SecurityPolicy
from bantz.coding.terminal import BackgroundProcess, CommandResult, TerminalExecutor


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def terminal(workspace):
    policy = SecurityPolicy(workspace_root=workspace)
    return TerminalExecutor(workspace, security=policy)


# ─────────────────────────────────────────────────────────────────
# CommandResult dataclass
# ─────────────────────────────────────────────────────────────────

class TestCommandResult:

    def test_ok_property(self):
        r = CommandResult(command="echo", stdout="hi", stderr="", return_code=0, duration_ms=10)
        assert r.ok is True

    def test_not_ok_nonzero(self):
        r = CommandResult(command="fail", stdout="", stderr="err", return_code=1, duration_ms=10)
        assert r.ok is False

    def test_not_ok_timeout(self):
        r = CommandResult(command="sleep", stdout="", stderr="", return_code=0, duration_ms=10, timed_out=True)
        assert r.ok is False

    def test_not_ok_killed(self):
        r = CommandResult(command="x", stdout="", stderr="", return_code=-9, duration_ms=10, killed=True)
        assert r.ok is False

    def test_output_combines(self):
        r = CommandResult(command="x", stdout="out", stderr="err", return_code=0, duration_ms=10)
        assert "out" in r.output
        assert "[stderr]" in r.output
        assert "err" in r.output

    def test_output_empty(self):
        r = CommandResult(command="x", stdout="", stderr="", return_code=0, duration_ms=10)
        assert r.output == ""

    def test_to_dict(self):
        r = CommandResult(command="echo", stdout="x", stderr="", return_code=0, duration_ms=5.5, pid=1234)
        d = r.to_dict()
        assert d["command"] == "echo"
        assert d["return_code"] == 0
        assert d["pid"] == 1234
        assert d["ok"] is True


# ─────────────────────────────────────────────────────────────────
# Synchronous execution
# ─────────────────────────────────────────────────────────────────

class TestSyncExecution:

    def test_run_echo(self, terminal):
        result = terminal.run("echo hello")
        assert result.ok
        assert "hello" in result.stdout

    def test_run_exit_code(self, terminal):
        result = terminal.run("exit 42")
        assert result.return_code == 42
        assert not result.ok

    def test_run_stderr(self, terminal):
        result = terminal.run("echo error >&2")
        assert "error" in result.stderr

    def test_run_with_env(self, terminal):
        result = terminal.run("echo $MY_VAR", env={"MY_VAR": "bantz_test"})
        assert "bantz_test" in result.stdout

    def test_run_cwd_override(self, workspace, terminal):
        sub = workspace / "subdir"
        sub.mkdir()
        result = terminal.run("pwd", cwd=str(sub))
        assert str(sub) in result.stdout

    def test_run_records_history(self, terminal):
        terminal.run("echo 1")
        terminal.run("echo 2")
        history = terminal.get_history()
        assert len(history) == 2

    def test_run_multiline(self, terminal):
        result = terminal.run("echo line1 && echo line2")
        assert "line1" in result.stdout
        assert "line2" in result.stdout


# ─────────────────────────────────────────────────────────────────
# Security enforcement
# ─────────────────────────────────────────────────────────────────

class TestSecurityEnforcement:

    def test_denied_command_raises(self, terminal):
        with pytest.raises(SecurityError):
            terminal.run("rm -rf /")

    def test_denied_fork_bomb(self, terminal):
        with pytest.raises(SecurityError):
            terminal.run(":(){ :|:& };")

    def test_confirm_required_raises(self, terminal):
        with pytest.raises(ConfirmationRequired):
            terminal.run("rm tmpfile.txt")

    def test_confirm_allows(self, terminal):
        # rm on nonexistent file: exit 1 but no security exception
        result = terminal.run("rm nonexistent_xyz_test", confirmed=True)
        # Should not raise ConfirmationRequired

    def test_sudo_needs_confirm(self, terminal):
        with pytest.raises(ConfirmationRequired):
            terminal.run("sudo ls")

    def test_git_push_needs_confirm(self, terminal):
        with pytest.raises(ConfirmationRequired):
            terminal.run("git push origin main")


# ─────────────────────────────────────────────────────────────────
# Timeout handling
# ─────────────────────────────────────────────────────────────────

class TestTimeout:

    def test_timeout_triggers(self, terminal):
        result = terminal.run("sleep 30", timeout=1)
        assert result.timed_out

    def test_fast_command_no_timeout(self, terminal):
        result = terminal.run("echo fast", timeout=10)
        assert not result.timed_out
        assert result.ok

    def test_default_timeout(self, workspace):
        policy = SecurityPolicy(workspace_root=workspace)
        t = TerminalExecutor(workspace, security=policy, timeout=2)
        result = t.run("sleep 30")  # uses default timeout of 2
        assert result.timed_out


# ─────────────────────────────────────────────────────────────────
# Background processes
# ─────────────────────────────────────────────────────────────────

class TestBackgroundProcesses:

    def test_run_background(self, terminal):
        bg_id = terminal.run_background("sleep 60", confirmed=True)
        assert bg_id >= 1
        assert terminal.is_background_running(bg_id)
        terminal.kill_background(bg_id)

    def test_kill_background(self, terminal):
        bg_id = terminal.run_background("sleep 60", confirmed=True)
        killed = terminal.kill_background(bg_id)
        assert killed
        # Wait briefly for cleanup
        time.sleep(0.2)
        assert not terminal.is_background_running(bg_id)

    def test_list_background(self, terminal):
        bg_id = terminal.run_background("sleep 60", confirmed=True)
        procs = terminal.list_background()
        assert len(procs) >= 1
        assert any(p["id"] == bg_id for p in procs)
        terminal.kill_background(bg_id)

    def test_background_nonexistent_returns_false(self, terminal):
        assert terminal.is_background_running(9999) is False
        assert terminal.kill_background(9999) is False

    def test_get_background_output_nonexistent(self, terminal):
        assert terminal.get_background_output(9999) is None

    def test_background_denied_command(self, terminal):
        with pytest.raises(SecurityError):
            terminal.run_background("rm -rf /")


# ─────────────────────────────────────────────────────────────────
# History & Utility
# ─────────────────────────────────────────────────────────────────

class TestHistory:

    def test_get_history(self, terminal):
        terminal.run("echo a")
        terminal.run("echo b")
        terminal.run("echo c")
        history = terminal.get_history(limit=2)
        assert len(history) == 2

    def test_clear_history(self, terminal):
        terminal.run("echo x")
        terminal.clear_history()
        assert terminal.get_history() == []


class TestUtility:

    def test_which_python(self, terminal):
        path = terminal.which("python3")
        assert path is not None
        assert "python" in path

    def test_which_nonexistent(self, terminal):
        path = terminal.which("nonexistent_binary_xyz_777")
        assert path is None

    def test_set_working_directory(self, terminal, workspace):
        sub = workspace / "mydir"
        sub.mkdir()
        terminal.set_working_directory(str(sub))
        assert terminal.get_working_directory() == str(sub)

    def test_set_working_directory_outside_sandbox(self, terminal):
        with pytest.raises(SecurityError):
            terminal.set_working_directory("/etc")

    def test_set_working_directory_nonexistent(self, terminal):
        with pytest.raises((FileNotFoundError, SecurityError)):
            terminal.set_working_directory("/tmp/nonexistent_xyz_test_dir")

    def test_get_environment_variable(self, terminal):
        import os
        os.environ["BANTZ_TEST_VAR"] = "hello"
        val = terminal.get_environment_variable("BANTZ_TEST_VAR")
        assert val == "hello"
        del os.environ["BANTZ_TEST_VAR"]

    def test_get_environment_variable_missing(self, terminal):
        val = terminal.get_environment_variable("NONEXISTENT_VAR_XYZ")
        assert val is None
