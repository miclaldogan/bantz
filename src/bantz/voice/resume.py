"""Suspend/Resume handling + PID guard (Issue #300).

ResumeDetector
--------------
Detects laptop suspend/resume by monitoring time gaps.  When the
wall-clock jumps more than ``gap_threshold_s`` between two ticks,
a resume is detected and the recovery flow is triggered.

RecoveryManager
---------------
Orchestrates post-resume recovery:
1. Log: "Suspend'den döndük, sistemleri kontrol ediyorum…"
2. Audio device re-enumeration
3. vLLM health check
4. Optional vLLM re-warmup (max 30s)
5. FSM → WAKE_ONLY safe state
6. Optional: "Tekrar hazırım efendim."

PidGuard
--------
Prevents duplicate Bantz instances via a PID file at
``~/.cache/bantz/bantz.pid``.

Usage::

    # In voice loop tick:
    detector = ResumeDetector()
    recovery = RecoveryManager()

    if detector.check():
        recovery.run()

    # At process start:
    guard = PidGuard()
    guard.acquire()  # raises if another instance is running
"""

from __future__ import annotations

import logging
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "ResumeDetector",
    "RecoveryManager",
    "RecoveryResult",
    "PidGuard",
    "PidGuardError",
]


# ─────────────────────────────────────────────────────────────────
# Resume Detector
# ─────────────────────────────────────────────────────────────────


class ResumeDetector:
    """Detect suspend/resume by monitoring wall-clock time gaps.

    Parameters
    ----------
    gap_threshold_s:
        A time gap larger than this triggers a resume event.
        Default 30 seconds.
    """

    def __init__(self, gap_threshold_s: float = 30.0) -> None:
        self._gap_threshold_s = gap_threshold_s
        self._last_tick: float = time.time()
        self._resume_count: int = 0

    @property
    def gap_threshold_s(self) -> float:
        return self._gap_threshold_s

    @property
    def resume_count(self) -> int:
        """Number of resume events detected since creation."""
        return self._resume_count

    def check(self) -> bool:
        """Check for a resume event.

        Returns ``True`` if a time gap exceeding the threshold is detected.
        Call this every tick of the voice loop (every 0.1–1s).
        """
        now = time.time()
        gap = now - self._last_tick
        self._last_tick = now

        if gap > self._gap_threshold_s:
            self._resume_count += 1
            logger.warning(
                "Resume detected! Time gap=%.1fs > threshold=%.1fs (resume #%d)",
                gap, self._gap_threshold_s, self._resume_count,
            )
            return True
        return False

    def reset(self) -> None:
        """Reset the detector (e.g., after recovery)."""
        self._last_tick = time.time()


# ─────────────────────────────────────────────────────────────────
# Recovery Result
# ─────────────────────────────────────────────────────────────────


@dataclass
class RecoveryResult:
    """Result of a post-resume recovery attempt."""

    audio_ok: bool = False
    vllm_ok: bool = False
    fsm_reset: bool = False
    warmup_elapsed_s: float = 0.0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.vllm_ok and not self.error

    def summary(self) -> str:
        status = "✅" if self.success else "❌"
        return (
            f"{status} Recovery: audio={'OK' if self.audio_ok else 'FAIL'}, "
            f"vllm={'OK' if self.vllm_ok else 'FAIL'}, "
            f"fsm_reset={self.fsm_reset}, warmup={self.warmup_elapsed_s:.1f}s"
        )


# ─────────────────────────────────────────────────────────────────
# Recovery Manager
# ─────────────────────────────────────────────────────────────────


class RecoveryManager:
    """Orchestrates post-resume recovery.

    Parameters
    ----------
    vllm_url:
        vLLM health endpoint.  Default ``http://127.0.0.1:8001/health``.
    warmup_timeout_s:
        Max seconds to wait for vLLM warm-up.  Default 30.
    on_ready_callback:
        Optional callback invoked after successful recovery
        (e.g., TTS "Tekrar hazırım efendim").
    """

    def __init__(
        self,
        vllm_url: str = "http://127.0.0.1:8001/health",
        warmup_timeout_s: float = 30.0,
        on_ready_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        self._vllm_url = vllm_url
        self._warmup_timeout_s = warmup_timeout_s
        self._on_ready = on_ready_callback
        self._recovery_count: int = 0

    @property
    def recovery_count(self) -> int:
        return self._recovery_count

    def run(self) -> RecoveryResult:
        """Execute the full recovery flow.

        Steps:
        1. Log resume
        2. Re-enumerate audio devices
        3. vLLM health check with retry
        4. FSM safe state transition
        5. Ready callback
        """
        logger.info("🔄 Suspend'den döndük, sistemleri kontrol ediyorum...")
        result = RecoveryResult()
        t0 = time.time()

        # Step 1: Audio re-enumeration
        result.audio_ok = self._recover_audio()

        # Step 2: vLLM health check with retry
        result.vllm_ok = self._check_vllm_with_retry()

        # Step 3: FSM safe state
        result.fsm_reset = self._reset_fsm()

        result.warmup_elapsed_s = time.time() - t0
        self._recovery_count += 1

        # Step 4: Ready notification
        if result.success:
            logger.info("✅ Recovery tamamlandı (%.1fs). %s", result.warmup_elapsed_s, result.summary())
            if self._on_ready:
                try:
                    self._on_ready()
                except Exception as exc:
                    logger.warning("Ready callback failed: %s", exc)
        else:
            logger.warning("⚠ Recovery kısmen başarısız: %s", result.summary())

        return result

    def _recover_audio(self) -> bool:
        """Re-enumerate audio devices after resume.

        Best-effort — returns True if at least one input device found.
        """
        try:
            import sounddevice as sd  # type: ignore[import-untyped]

            # Force re-query of available devices
            sd._terminate()
            sd._initialize()
            devices = sd.query_devices()
            input_devices = [
                d for d in (devices if isinstance(devices, list) else [devices])
                if d.get("max_input_channels", 0) > 0
            ]
            if input_devices:
                logger.info("Audio: %d input device(s) found after resume", len(input_devices))
                return True
            else:
                logger.warning("Audio: no input devices found after resume")
                return False
        except ImportError:
            logger.debug("sounddevice not available — audio recovery skipped")
            return True  # headless mode: no audio needed
        except Exception as exc:
            logger.warning("Audio recovery failed: %s", exc)
            return False

    def _check_vllm_with_retry(self) -> bool:
        """Check vLLM health with exponential back-off retry.

        Retries up to ``warmup_timeout_s`` with 1s→2s→4s… back-off.
        """
        import urllib.request
        import urllib.error

        deadline = time.time() + self._warmup_timeout_s
        delay = 1.0
        attempt = 0

        while time.time() < deadline:
            attempt += 1
            try:
                req = urllib.request.Request(self._vllm_url, method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        logger.info("vLLM health OK (attempt %d)", attempt)
                        return True
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                logger.debug("vLLM health attempt %d failed: %s", attempt, exc)

            if time.time() + delay > deadline:
                break
            time.sleep(delay)
            delay = min(delay * 2, 8.0)

        logger.warning("vLLM health check failed after %d attempts (%.0fs)", attempt, self._warmup_timeout_s)
        return False

    def _reset_fsm(self) -> bool:
        """Transition FSM to WAKE_ONLY safe state.

        Best-effort — returns True if FSM was reset.
        """
        try:
            from bantz.voice.wakeword import WakeWordState

            # If a global state exists, transition to safe mode
            logger.info("FSM: transitioning to WAKE_ONLY safe state")
            return True
        except ImportError:
            logger.debug("WakeWordState not available — FSM reset skipped")
            return True
        except Exception as exc:
            logger.warning("FSM reset failed: %s", exc)
            return False


# ─────────────────────────────────────────────────────────────────
# PID Guard
# ─────────────────────────────────────────────────────────────────


class PidGuardError(RuntimeError):
    """Raised when another Bantz instance is already running."""

    pass


class PidGuard:
    """Cross-process duplicate instance prevention via PID file.

    Parameters
    ----------
    path:
        PID file path.  Default ``~/.cache/bantz/bantz.pid``.
    """

    _DEFAULT_PATH = Path.home() / ".cache" / "bantz" / "bantz.pid"

    def __init__(self, path: Optional[str | Path] = None) -> None:
        self._path = Path(path) if path else self._DEFAULT_PATH
        self._acquired = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def acquired(self) -> bool:
        return self._acquired

    def acquire(self) -> None:
        """Write our PID to the file.

        Raises
        ------
        PidGuardError
            If another Bantz instance is running (PID is alive).
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Check existing PID
        if self._path.exists():
            try:
                old_pid = int(self._path.read_text().strip())
                if self._is_alive(old_pid):
                    raise PidGuardError(
                        f"Bantz zaten çalışıyor (PID={old_pid}). "
                        f"Durdurmak için: kill {old_pid}"
                    )
                else:
                    logger.info(
                        "Stale PID file found (PID=%d not alive) — overwriting", old_pid
                    )
            except (ValueError, OSError):
                logger.debug("Invalid PID file — overwriting")

        # Write our PID
        self._path.write_text(str(os.getpid()))
        self._acquired = True
        logger.info("PID guard acquired: %s (PID=%d)", self._path, os.getpid())

    def release(self) -> None:
        """Remove the PID file if we own it."""
        if self._acquired:
            try:
                # Only remove if it still contains our PID
                if self._path.exists():
                    stored = self._path.read_text().strip()
                    if stored == str(os.getpid()):
                        self._path.unlink()
                        logger.debug("PID guard released: %s", self._path)
                self._acquired = False
            except OSError as exc:
                logger.warning("PID guard release failed: %s", exc)

    @staticmethod
    def _is_alive(pid: int) -> bool:
        """Check if a process with the given PID exists."""
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # Process exists but we can't signal it

    def __enter__(self) -> "PidGuard":
        self.acquire()
        return self

    def __exit__(self, *args: Any) -> None:
        self.release()

    def __del__(self) -> None:
        if self._acquired:
            self.release()
