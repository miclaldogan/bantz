"""Voice pipeline heartbeat + log rotation (Issue #301).

Heartbeat
---------
The :class:`Heartbeat` writes ``time.time()`` to
``~/.cache/bantz/voice_heartbeat`` on every :meth:`tick`.
:meth:`is_stale` returns ``True`` when the file is older than
``max_age_s`` (default 30 seconds) — the watchdog script uses this
to decide whether to restart the voice service.

Log Rotation
------------
:class:`LogRotator` keeps voice logs tidy:
- Max ``max_files`` rotated copies (default 7).
- Max ``max_size_mb`` per file (default 10 MB).
- :meth:`rotate_if_needed` is called from the voice loop.

Usage::

    hb = Heartbeat()
    hb.tick()                   # called every 5-10s from voice loop
    Heartbeat.is_stale()        # → True if no tick in 30s

    rotator = LogRotator()
    rotator.rotate_if_needed()  # called once per voice loop iteration
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["Heartbeat", "LogRotator"]


# ─────────────────────────────────────────────────────────────────
# Heartbeat
# ─────────────────────────────────────────────────────────────────

# Default heartbeat file path
_DEFAULT_HB_PATH = Path.home() / ".cache" / "bantz" / "voice_heartbeat"

# Default log directory
_DEFAULT_LOG_DIR = Path.home() / ".cache" / "bantz" / "logs"


class Heartbeat:
    """Voice loop heartbeat — proves the loop is alive.

    Parameters
    ----------
    path:
        Heartbeat file path.  Defaults to ``~/.cache/bantz/voice_heartbeat``.
    max_age_s:
        Staleness threshold in seconds.  Default 30.
    """

    def __init__(
        self,
        path: Optional[str | Path] = None,
        max_age_s: float = 30.0,
    ) -> None:
        self._path = Path(path) if path else _DEFAULT_HB_PATH
        self._max_age_s = max_age_s
        self._last_tick: float = 0.0

    @property
    def path(self) -> Path:
        return self._path

    @property
    def max_age_s(self) -> float:
        return self._max_age_s

    def tick(self) -> None:
        """Write current timestamp to the heartbeat file.

        Called every 5–10 seconds from the voice loop.  Creates
        parent directories if needed.  Failures are logged but
        never propagated.
        """
        now = time.time()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(str(now))
            self._last_tick = now
            logger.debug("Heartbeat tick: %.1f → %s", now, self._path)
        except OSError as exc:
            logger.warning("Heartbeat tick failed: %s", exc)

    def is_stale(self, max_age_s: Optional[float] = None) -> bool:
        """Check if the heartbeat is stale.

        Parameters
        ----------
        max_age_s:
            Override the default staleness threshold.

        Returns
        -------
        bool
            ``True`` if the heartbeat file is missing, unreadable,
            or older than *max_age_s*.
        """
        threshold = max_age_s if max_age_s is not None else self._max_age_s
        try:
            ts = float(self._path.read_text().strip())
            age = time.time() - ts
            stale = age > threshold
            if stale:
                logger.warning(
                    "Heartbeat stale: age=%.1fs > threshold=%.1fs (%s)",
                    age, threshold, self._path,
                )
            return stale
        except FileNotFoundError:
            logger.warning("Heartbeat file not found: %s — treating as stale", self._path)
            return True
        except (ValueError, OSError) as exc:
            logger.warning("Heartbeat check error: %s — treating as stale", exc)
            return True

    @property
    def last_tick(self) -> float:
        """Monotonic timestamp of last successful tick (0 if never ticked)."""
        return self._last_tick

    def clear(self) -> None:
        """Remove the heartbeat file (for tests / clean shutdown)."""
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass

    def __repr__(self) -> str:
        return f"Heartbeat(path={self._path}, max_age_s={self._max_age_s})"


# ─────────────────────────────────────────────────────────────────
# Log Rotation
# ─────────────────────────────────────────────────────────────────


@dataclass
class LogRotator:
    """Voice log rotation — keeps disk usage bounded.

    Parameters
    ----------
    log_dir:
        Directory containing voice logs.
        Default ``~/.cache/bantz/logs/``.
    log_name:
        Base log filename.  Default ``voice.log``.
    max_files:
        Maximum number of rotated files to keep.  Default 7.
    max_size_mb:
        Maximum size of the current log before rotation.  Default 10.
    """

    log_dir: Path = field(default_factory=lambda: _DEFAULT_LOG_DIR)
    log_name: str = "voice.log"
    max_files: int = 7
    max_size_mb: float = 10.0

    @property
    def current_log(self) -> Path:
        return self.log_dir / self.log_name

    def rotate_if_needed(self) -> bool:
        """Rotate the current log if it exceeds ``max_size_mb``.

        Returns ``True`` if rotation occurred.
        """
        current = self.current_log
        if not current.exists():
            return False

        size_mb = current.stat().st_size / (1024 * 1024)
        if size_mb < self.max_size_mb:
            return False

        return self._rotate()

    def _rotate(self) -> bool:
        """Perform the actual rotation.

        voice.log   → voice.log.1
        voice.log.1 → voice.log.2
        ...
        voice.log.N → deleted (if N >= max_files)
        """
        try:
            # Delete oldest if at limit
            for i in range(self.max_files, 0, -1):
                src = self.log_dir / f"{self.log_name}.{i}"
                if i == self.max_files and src.exists():
                    src.unlink()
                    logger.debug("Deleted oldest log: %s", src)
                elif src.exists():
                    dst = self.log_dir / f"{self.log_name}.{i + 1}"
                    shutil.move(str(src), str(dst))
                    logger.debug("Rotated %s → %s", src, dst)

            # Current → .1
            current = self.current_log
            if current.exists():
                dst = self.log_dir / f"{self.log_name}.1"
                shutil.move(str(current), str(dst))
                logger.debug("Rotated %s → %s", current, dst)

            logger.info("Log rotation complete for %s", self.log_name)
            return True

        except OSError as exc:
            logger.warning("Log rotation failed: %s", exc)
            return False

    def cleanup_old(self) -> int:
        """Delete rotated logs beyond ``max_files``.

        Returns the number of files deleted.
        """
        deleted = 0
        for i in range(self.max_files + 1, self.max_files + 100):
            path = self.log_dir / f"{self.log_name}.{i}"
            if not path.exists():
                break
            try:
                path.unlink()
                deleted += 1
                logger.debug("Cleaned up old log: %s", path)
            except OSError:
                pass
        return deleted

    def list_logs(self) -> list[Path]:
        """Return all existing log files, sorted by index."""
        logs: list[Path] = []
        current = self.current_log
        if current.exists():
            logs.append(current)
        for i in range(1, self.max_files + 1):
            p = self.log_dir / f"{self.log_name}.{i}"
            if p.exists():
                logs.append(p)
        return logs

    def total_size_mb(self) -> float:
        """Total size of all log files in MB."""
        return sum(p.stat().st_size for p in self.list_logs()) / (1024 * 1024)
