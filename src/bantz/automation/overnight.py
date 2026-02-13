"""Otonom Gece Modu — Kendi Kendine Çalışan Agent (Issue #836).

"Bantz gece şunu yap" dendiğinde görevleri sıraya alır, otonom çalışır,
checkpoint ile hata durumunda kaldığı yerden devam eder ve sabah raporu üretir.

Architecture:
    - OvernightTask: Tek bir gece görevi
    - OvernightState: Tüm gece seansının durumu (JSON serializable)
    - OvernightRunner: Ana runner — task queue, checkpoint, rate limiting
    - OvernightFailSafe: Karar gereken durumlarda WAITING_HUMAN kuyruğu
    - Morning report: Inbox'a sabah özeti gönderir

Checkpoint dosyası: ~/.bantz/overnight_checkpoint.json
Sabah raporu: EventBus + InboxStore üzerinden

Usage:
    runner = OvernightRunner(bantz_server)
    runner.add_task("AI konferanslarını araştır")
    runner.add_task("Haftalık AI haberlerini özetle")
    runner.run()  # Blocking, otonom çalışır
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────
CHECKPOINT_DIR = Path.home() / ".bantz"
CHECKPOINT_FILE = CHECKPOINT_DIR / "overnight_checkpoint.json"

# Rate limiting defaults
DEFAULT_TASK_DELAY_SECONDS = 5.0
DEFAULT_API_COOLDOWN_SECONDS = 2.0
MAX_CONSECUTIVE_ERRORS = 3


# ─────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    """Status of a single overnight task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_HUMAN = "waiting_human"


class OvernightStatus(str, Enum):
    """Status of the entire overnight session."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OvernightTask:
    """A single task in the overnight queue."""
    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 0
    result: Optional[str] = None
    error: Optional[str] = None
    human_question: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: float = 0.0
    retry_count: int = 0
    max_retries: int = 2
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, description: str, priority: int = 0) -> OvernightTask:
        return cls(
            id=str(uuid.uuid4())[:12],
            description=description,
            priority=priority,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            TaskStatus.COMPLETED, TaskStatus.FAILED,
            TaskStatus.SKIPPED, TaskStatus.WAITING_HUMAN,
        )

    @property
    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority,
            "result": self.result,
            "error": self.error,
            "human_question": self.human_question,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> OvernightTask:
        task = cls(
            id=data["id"],
            description=data["description"],
            priority=data.get("priority", 0),
            result=data.get("result"),
            error=data.get("error"),
            human_question=data.get("human_question"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            duration_ms=data.get("duration_ms", 0.0),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 2),
            metadata=data.get("metadata", {}),
        )
        task.status = TaskStatus(data.get("status", "pending"))
        return task


@dataclass
class OvernightState:
    """Full state of an overnight session — JSON-serializable for checkpoint/resume."""
    session_id: str
    status: OvernightStatus = OvernightStatus.IDLE
    tasks: List[OvernightTask] = field(default_factory=list)
    current_task_index: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    human_decisions_pending: List[Dict[str, Any]] = field(default_factory=list)
    morning_report: Optional[str] = None
    error_log: List[str] = field(default_factory=list)

    @classmethod
    def create(cls, tasks: List[str]) -> OvernightState:
        return cls(
            session_id=str(uuid.uuid4())[:12],
            tasks=[OvernightTask.create(desc, priority=len(tasks) - i)
                   for i, desc in enumerate(tasks)],
        )

    @property
    def total_tasks(self) -> int:
        return len(self.tasks)

    @property
    def completed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.COMPLETED)

    @property
    def failed_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.FAILED)

    @property
    def waiting_human_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == TaskStatus.WAITING_HUMAN)

    @property
    def progress_percent(self) -> float:
        if not self.tasks:
            return 0.0
        done = sum(1 for t in self.tasks if t.is_terminal)
        return (done / len(self.tasks)) * 100

    @property
    def next_pending_task(self) -> Optional[OvernightTask]:
        for task in self.tasks:
            if task.status == TaskStatus.PENDING:
                return task
        return None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "status": self.status.value,
            "tasks": [t.to_dict() for t in self.tasks],
            "current_task_index": self.current_task_index,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "human_decisions_pending": self.human_decisions_pending,
            "morning_report": self.morning_report,
            "error_log": self.error_log,
        }

    @classmethod
    def from_dict(cls, data: dict) -> OvernightState:
        state = cls(
            session_id=data["session_id"],
            tasks=[OvernightTask.from_dict(t) for t in data.get("tasks", [])],
            current_task_index=data.get("current_task_index", 0),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            human_decisions_pending=data.get("human_decisions_pending", []),
            morning_report=data.get("morning_report"),
            error_log=data.get("error_log", []),
        )
        state.status = OvernightStatus(data.get("status", "idle"))
        return state


# ─────────────────────────────────────────────────────────────────
# Checkpoint persistence
# ─────────────────────────────────────────────────────────────────

def save_checkpoint(state: OvernightState, path: Path = CHECKPOINT_FILE) -> None:
    """Save overnight state to disk for resume after crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)
        tmp.replace(path)
        logger.debug("Checkpoint saved: %s", path)
    except Exception as exc:
        logger.error("Checkpoint save failed: %s", exc)
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def load_checkpoint(path: Path = CHECKPOINT_FILE) -> Optional[OvernightState]:
    """Load overnight state from checkpoint file."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        state = OvernightState.from_dict(data)
        logger.info("Checkpoint loaded: session=%s, progress=%.1f%%",
                     state.session_id, state.progress_percent)
        return state
    except Exception as exc:
        logger.error("Checkpoint load failed: %s", exc)
        return None


def clear_checkpoint(path: Path = CHECKPOINT_FILE) -> None:
    """Remove checkpoint file."""
    path.unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────
# Overnight FailSafe — queues decisions instead of voice
# ─────────────────────────────────────────────────────────────────

class OvernightFailSafe:
    """Fail-safe handler for overnight mode.

    Instead of asking via TTS/ASR (interactive), queues the decision
    as WAITING_HUMAN. The user reviews pending decisions in the morning.
    """

    def __init__(self, max_consecutive_failures: int = MAX_CONSECUTIVE_ERRORS):
        self.max_consecutive_failures = max_consecutive_failures
        self._pending_decisions: List[Dict[str, Any]] = []

    def should_wait_for_human(self, consecutive_failures: int) -> bool:
        """Check if we should stop and wait for human."""
        return consecutive_failures >= self.max_consecutive_failures

    def queue_decision(
        self,
        task: OvernightTask,
        error: str,
        question: str,
    ) -> None:
        """Queue a decision for the user to review in the morning."""
        decision = {
            "task_id": task.id,
            "task_description": task.description,
            "error": error,
            "question": question,
            "queued_at": datetime.now().isoformat(),
        }
        self._pending_decisions.append(decision)
        task.status = TaskStatus.WAITING_HUMAN
        task.human_question = question
        logger.info("WAITING_HUMAN: task=%s question=%s", task.id, question)

    @property
    def pending_decisions(self) -> List[Dict[str, Any]]:
        return list(self._pending_decisions)

    def clear(self) -> None:
        self._pending_decisions.clear()


# ─────────────────────────────────────────────────────────────────
# Resource Awareness
# ─────────────────────────────────────────────────────────────────

class ResourceMonitor:
    """Monitors resource usage to adjust overnight pacing."""

    def __init__(
        self,
        task_delay: float = DEFAULT_TASK_DELAY_SECONDS,
        api_cooldown: float = DEFAULT_API_COOLDOWN_SECONDS,
    ):
        self.task_delay = task_delay
        self.api_cooldown = api_cooldown
        self._last_api_call = 0.0
        self._consecutive_rate_limits = 0

    def wait_between_tasks(self) -> None:
        """Wait between tasks to avoid overloading resources."""
        time.sleep(self.task_delay)

    def wait_for_api_cooldown(self) -> None:
        """Wait for API rate limit cooldown."""
        elapsed = time.time() - self._last_api_call
        remaining = self.api_cooldown - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_api_call = time.time()

    def report_rate_limit(self) -> None:
        """Report a rate limit hit — increases cooldown."""
        self._consecutive_rate_limits += 1
        # Exponential backoff: 2s → 4s → 8s → 16s (max 60s)
        self.api_cooldown = min(
            DEFAULT_API_COOLDOWN_SECONDS * (2 ** self._consecutive_rate_limits),
            60.0,
        )
        logger.warning(
            "Rate limit hit (#%d) — cooldown increased to %.1fs",
            self._consecutive_rate_limits, self.api_cooldown,
        )

    def report_success(self) -> None:
        """Report successful API call — resets cooldown."""
        self._consecutive_rate_limits = 0
        self.api_cooldown = DEFAULT_API_COOLDOWN_SECONDS


# ─────────────────────────────────────────────────────────────────
# Morning Report Generator
# ─────────────────────────────────────────────────────────────────

def generate_morning_report(state: OvernightState) -> str:
    """Generate a morning report from the overnight session.

    Returns:
        Markdown-formatted morning report string.
    """
    lines = []
    lines.append("☀️ **Günaydın! Gece Modu Raporu**")
    lines.append(f"Oturum: {state.session_id}")

    if state.started_at:
        lines.append(f"Başlangıç: {state.started_at}")
    if state.completed_at:
        lines.append(f"Bitiş: {state.completed_at}")

    lines.append("")
    lines.append(f"📊 **Özet**: {state.completed_count}/{state.total_tasks} görev tamamlandı")

    if state.failed_count:
        lines.append(f"❌ {state.failed_count} görev başarısız")
    if state.waiting_human_count:
        lines.append(f"⚠️ {state.waiting_human_count} görev kararınızı bekliyor")

    lines.append("")
    lines.append("---")

    for i, task in enumerate(state.tasks, 1):
        icon = {
            TaskStatus.COMPLETED: "✅",
            TaskStatus.FAILED: "❌",
            TaskStatus.SKIPPED: "⏭️",
            TaskStatus.WAITING_HUMAN: "⚠️",
            TaskStatus.PENDING: "⏳",
            TaskStatus.RUNNING: "🔄",
        }.get(task.status, "•")

        lines.append(f"{i}. {icon} **{task.description}**")
        if task.result:
            # Truncate long results
            result_preview = task.result[:300]
            if len(task.result) > 300:
                result_preview += "..."
            lines.append(f"   → {result_preview}")
        if task.error:
            lines.append(f"   ❌ Hata: {task.error}")
        if task.human_question:
            lines.append(f"   ❓ Kararınız gerekiyor: {task.human_question}")
        if task.duration_ms > 0:
            secs = task.duration_ms / 1000
            lines.append(f"   ⏱ {secs:.1f}s")

    if state.human_decisions_pending:
        lines.append("")
        lines.append("---")
        lines.append("🤔 **Bekleyen Kararlar**:")
        for d in state.human_decisions_pending:
            lines.append(f"  • {d['task_description']}: {d['question']}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# OvernightRunner — the main orchestrator
# ─────────────────────────────────────────────────────────────────

class OvernightRunner:
    """Autonomous overnight task runner.

    Accepts a task list, runs them sequentially with checkpoint/resume,
    rate limiting, and produces a morning report.

    Parameters
    ----------
    bantz_server:
        BantzServer instance for executing commands via handle_command().
    resource_monitor:
        Resource monitor for rate limiting / pacing.
    failsafe:
        Overnight fail-safe handler.
    checkpoint_path:
        Path for checkpoint file.
    """

    def __init__(
        self,
        bantz_server: Any = None,
        resource_monitor: Optional[ResourceMonitor] = None,
        failsafe: Optional[OvernightFailSafe] = None,
        checkpoint_path: Path = CHECKPOINT_FILE,
    ):
        self._server = bantz_server
        self._resources = resource_monitor or ResourceMonitor()
        self._failsafe = failsafe or OvernightFailSafe()
        self._checkpoint_path = checkpoint_path
        self._state: Optional[OvernightState] = None
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._event_bus = None

    @property
    def state(self) -> Optional[OvernightState]:
        return self._state

    def _get_event_bus(self):
        if self._event_bus is None:
            try:
                from bantz.core.events import get_event_bus
                self._event_bus = get_event_bus()
            except Exception:
                self._event_bus = None
        return self._event_bus

    def _emit(self, event_type: str, data: dict) -> None:
        bus = self._get_event_bus()
        if bus:
            bus.publish(event_type, data, source="overnight")

    # ── Task Management ──────────────────────────────────────────

    def add_task(self, description: str, priority: int = 0) -> OvernightTask:
        """Add a task to the queue."""
        if self._state is None:
            self._state = OvernightState(session_id=str(uuid.uuid4())[:12])
        task = OvernightTask.create(description, priority)
        self._state.tasks.append(task)
        return task

    def add_tasks(self, descriptions: List[str]) -> List[OvernightTask]:
        """Add multiple tasks."""
        return [self.add_task(desc, priority=len(descriptions) - i)
                for i, desc in enumerate(descriptions)]

    def set_state(self, state: OvernightState) -> None:
        """Set the state directly (for resume from checkpoint)."""
        self._state = state

    # ── Main Loop ────────────────────────────────────────────────

    def run(self) -> OvernightState:
        """Run all tasks sequentially. Blocking.

        Returns the final OvernightState with results and morning report.
        """
        if self._state is None or not self._state.tasks:
            logger.warning("No tasks to run in overnight mode")
            return self._state or OvernightState(session_id="empty")

        state = self._state
        state.status = OvernightStatus.RUNNING
        state.started_at = datetime.now().isoformat()

        self._emit("overnight.started", {
            "session_id": state.session_id,
            "task_count": state.total_tasks,
            "tasks": [t.description for t in state.tasks],
        })

        logger.info(
            "🌙 Gece modu başlatıldı — %d görev, session=%s",
            state.total_tasks, state.session_id,
        )
        self._print_banner(state)

        consecutive_errors = 0

        while True:
            if self._cancel_event.is_set():
                state.status = OvernightStatus.CANCELLED
                logger.info("Overnight cancelled by user")
                break

            task = state.next_pending_task
            if task is None:
                # All tasks processed
                break

            state.current_task_index = state.tasks.index(task)

            # Rate limiting pause between tasks
            if state.current_task_index > 0:
                self._resources.wait_between_tasks()

            # Execute task
            success = self._execute_task(task, state)

            if success:
                consecutive_errors = 0
                self._resources.report_success()
            else:
                consecutive_errors += 1
                if self._failsafe.should_wait_for_human(consecutive_errors):
                    self._failsafe.queue_decision(
                        task,
                        error=task.error or "Unknown error",
                        question=f"'{task.description}' görevi {task.retry_count} kez başarısız oldu. Tekrar deneyelim mi, atlayalım mı?",
                    )
                    consecutive_errors = 0  # Reset after queueing
                elif task.can_retry:
                    # Auto-retry
                    task.retry_count += 1
                    task.status = TaskStatus.PENDING
                    task.error = None
                    logger.info("Auto-retry task %s (attempt %d)", task.id, task.retry_count + 1)
                    continue
                else:
                    task.status = TaskStatus.FAILED

            # Checkpoint after every task
            save_checkpoint(state, self._checkpoint_path)
            self._emit("overnight.checkpoint", {
                "session_id": state.session_id,
                "progress": state.progress_percent,
                "completed": state.completed_count,
                "total": state.total_tasks,
            })

        # Finalize
        state.status = OvernightStatus.COMPLETED if state.status == OvernightStatus.RUNNING else state.status
        state.completed_at = datetime.now().isoformat()
        state.human_decisions_pending = self._failsafe.pending_decisions

        # Generate morning report
        report = generate_morning_report(state)
        state.morning_report = report

        # Deliver morning report via inbox
        self._deliver_morning_report(state, report)

        # Final checkpoint
        save_checkpoint(state, self._checkpoint_path)

        self._emit("overnight.completed", {
            "session_id": state.session_id,
            "completed": state.completed_count,
            "failed": state.failed_count,
            "waiting_human": state.waiting_human_count,
        })

        logger.info(
            "☀️ Gece modu tamamlandı — %d/%d başarılı, %d başarısız, %d karar bekliyor",
            state.completed_count, state.total_tasks,
            state.failed_count, state.waiting_human_count,
        )

        return state

    def cancel(self) -> None:
        """Cancel the running overnight session."""
        self._cancel_event.set()

    # ── Task Execution ───────────────────────────────────────────

    def _execute_task(self, task: OvernightTask, state: OvernightState) -> bool:
        """Execute a single task via BantzServer.handle_command().

        Returns True on success, False on failure.
        """
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now().isoformat()

        self._emit("overnight.task.started", {
            "session_id": state.session_id,
            "task_id": task.id,
            "description": task.description,
        })

        logger.info(
            "🔄 [%d/%d] Görev başlatılıyor: %s",
            state.current_task_index + 1, state.total_tasks, task.description,
        )

        start = time.time()

        try:
            self._resources.wait_for_api_cooldown()

            if self._server is None:
                raise RuntimeError("BantzServer not initialized")

            result = self._server.handle_command(task.description)

            elapsed_ms = (time.time() - start) * 1000
            task.duration_ms = elapsed_ms

            if result.get("ok"):
                task.status = TaskStatus.COMPLETED
                task.result = result.get("text", "Tamamlandı")
                task.completed_at = datetime.now().isoformat()

                self._emit("overnight.task.completed", {
                    "session_id": state.session_id,
                    "task_id": task.id,
                    "description": task.description,
                    "duration_ms": elapsed_ms,
                })

                logger.info(
                    "✅ [%d/%d] Görev tamamlandı (%.1fs): %s",
                    state.current_task_index + 1, state.total_tasks,
                    elapsed_ms / 1000, task.description,
                )
                return True

            else:
                task.error = result.get("text", "Bilinmeyen hata")
                task.completed_at = datetime.now().isoformat()

                # Check for rate limiting
                error_text = (task.error or "").lower()
                if "rate" in error_text and "limit" in error_text:
                    self._resources.report_rate_limit()

                self._emit("overnight.task.failed", {
                    "session_id": state.session_id,
                    "task_id": task.id,
                    "description": task.description,
                    "error": task.error,
                })

                logger.warning(
                    "❌ [%d/%d] Görev başarısız: %s — %s",
                    state.current_task_index + 1, state.total_tasks,
                    task.description, task.error,
                )
                return False

        except Exception as exc:
            elapsed_ms = (time.time() - start) * 1000
            task.duration_ms = elapsed_ms
            task.error = str(exc)
            task.completed_at = datetime.now().isoformat()
            state.error_log.append(f"[{task.id}] {exc}")

            self._emit("overnight.task.failed", {
                "session_id": state.session_id,
                "task_id": task.id,
                "error": str(exc),
            })

            logger.exception("Task %s raised exception", task.id)
            return False

    # ── Morning Report Delivery ──────────────────────────────────

    def _deliver_morning_report(self, state: OvernightState, report: str) -> None:
        """Deliver morning report via EventBus and InboxStore."""
        # Publish as bantz_message for inbox
        self._emit("bantz_message", {
            "text": report,
            "intent": "overnight_report",
            "proactive": True,
            "source": "overnight",
        })

        self._emit("overnight.morning_report", {
            "session_id": state.session_id,
            "report": report,
            "completed": state.completed_count,
            "failed": state.failed_count,
            "waiting_human": state.waiting_human_count,
        })

        logger.info("☀️ Sabah raporu teslim edildi")

    # ── UI Helpers ───────────────────────────────────────────────

    def _print_banner(self, state: OvernightState) -> None:
        """Print overnight mode banner."""
        print("\n╭──────────────────────────────────────────────────╮")
        print("│  🌙 BANTZ Gece Modu                              │")
        print(f"│  Session:  {state.session_id:<38} │")
        print(f"│  Görevler: {state.total_tasks:<38} │")
        print("│  Mode:     Otonom (sabah raporu üretilecek)       │")
        print("╰──────────────────────────────────────────────────╯\n")
        for i, task in enumerate(state.tasks, 1):
            print(f"  {i}. ⏳ {task.description}")
        print()


# ─────────────────────────────────────────────────────────────────
# Resume from checkpoint
# ─────────────────────────────────────────────────────────────────

def resume_overnight(
    bantz_server: Any = None,
    checkpoint_path: Path = CHECKPOINT_FILE,
) -> Optional[OvernightState]:
    """Resume an interrupted overnight session from checkpoint.

    Returns the final state, or None if no checkpoint exists.
    """
    state = load_checkpoint(checkpoint_path)
    if state is None:
        logger.info("No overnight checkpoint found — nothing to resume")
        return None

    if state.status in (OvernightStatus.COMPLETED, OvernightStatus.CANCELLED):
        logger.info("Overnight session %s already completed", state.session_id)
        return state

    # Reset running tasks back to pending
    for task in state.tasks:
        if task.status == TaskStatus.RUNNING:
            task.status = TaskStatus.PENDING

    logger.info(
        "Resuming overnight session %s — %d/%d tasks remaining",
        state.session_id,
        sum(1 for t in state.tasks if t.status == TaskStatus.PENDING),
        state.total_tasks,
    )

    try:
        from bantz.core.events import get_event_bus
        event_bus = get_event_bus()
        event_bus.publish("overnight.resumed", {
            "session_id": state.session_id,
            "progress": state.progress_percent,
        }, source="overnight")
    except Exception:
        pass

    runner = OvernightRunner(
        bantz_server=bantz_server,
        checkpoint_path=checkpoint_path,
    )
    runner.set_state(state)
    return runner.run()


# ─────────────────────────────────────────────────────────────────
# Convenience: parse "gece şunu yap" style commands
# ─────────────────────────────────────────────────────────────────

OVERNIGHT_TRIGGERS = [
    "gece şunu yap",
    "gece şunları yap",
    "gece boyunca",
    "sabaha kadar",
    "overnight",
    "uyurken şunu yap",
    "uyurken şunları yap",
]


def is_overnight_request(text: str) -> bool:
    """Check if a text is an overnight task request."""
    text_lower = text.lower().strip()
    return any(trigger in text_lower for trigger in OVERNIGHT_TRIGGERS)


def parse_overnight_tasks(text: str) -> List[str]:
    """Parse individual tasks from an overnight request.

    Handles:
        "gece şunları yap: 1. X  2. Y  3. Z"
        "gece şunları yap:\\n- X\\n- Y\\n- Z"
        "gece şunu yap: X"
    """
    import re

    # Remove trigger phrases
    clean = text
    for trigger in OVERNIGHT_TRIGGERS:
        clean = re.sub(re.escape(trigger), "", clean, flags=re.IGNORECASE)

    # Remove leading colon, dash
    clean = clean.strip().lstrip(":").lstrip("-").strip()

    if not clean:
        return []

    # Try numbered list: "1. X  2. Y"
    numbered = re.findall(r'\d+\.\s*(.+?)(?=\d+\.|$)', clean, re.DOTALL)
    if numbered:
        return [t.strip().rstrip(",").rstrip(";") for t in numbered if t.strip()]

    # Try bullet list: "- X\n- Y"
    bullets = re.findall(r'[-•]\s*(.+)', clean)
    if bullets:
        return [t.strip() for t in bullets if t.strip()]

    # Try newline-separated
    lines = [l.strip() for l in clean.split("\n") if l.strip()]
    if len(lines) > 1:
        return lines

    # Single task
    return [clean]
