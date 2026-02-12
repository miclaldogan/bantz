"""Bantz Reminder Manager - SQLite backed reminder system."""
from __future__ import annotations

import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
import re


# Default database path
DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "bantz" / "reminders.db"


class ReminderManager:
    """SQLite-backed reminder manager with background scheduler."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._scheduler_thread: Optional[threading.Thread] = None
        self._running = False

    def _init_db(self) -> None:
        """Initialize SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    repeat_interval TEXT DEFAULT NULL,
                    snoozed_until TEXT DEFAULT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_remind_at ON reminders(remind_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON reminders(status)
            """)
            conn.commit()

    def _parse_time(self, time_str: str) -> Optional[datetime]:
        """Parse time string like '20:00', 'yarın 9:00', '5 dakika sonra'."""
        time_str = time_str.strip().lower()
        now = datetime.now()
        
        # "5 dakika sonra", "10 dk sonra", "1 saat sonra"
        delta_match = re.match(r'(\d+)\s*(dakika|dk|saat|sa|saniye|sn)\s*sonra', time_str)
        if delta_match:
            amount = int(delta_match.group(1))
            unit = delta_match.group(2)
            if unit in ('dakika', 'dk'):
                return now + timedelta(minutes=amount)
            elif unit in ('saat', 'sa'):
                return now + timedelta(hours=amount)
            elif unit in ('saniye', 'sn'):
                return now + timedelta(seconds=amount)
        
        # "yarın 9:00", "yarın 09:00"
        tomorrow_match = re.match(r'yarın\s*(\d{1,2})[:\.](\d{2})', time_str)
        if tomorrow_match:
            hour, minute = int(tomorrow_match.group(1)), int(tomorrow_match.group(2))
            tomorrow = now + timedelta(days=1)
            return tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        # "bugün 20:00", "20:00"
        time_match = re.match(r'(?:bugün\s*)?(\d{1,2})[:\.](\d{2})', time_str)
        if time_match:
            hour, minute = int(time_match.group(1)), int(time_match.group(2))
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            # If time is past, assume tomorrow
            if target <= now:
                target += timedelta(days=1)
            return target
        
        return None

    def add_reminder(self, time_str: str, message: str) -> Dict[str, Any]:
        """Add a new reminder."""
        remind_at = self._parse_time(time_str)
        if not remind_at:
            return {
                "ok": False,
                "text": f"Zamanı anlayamadım: '{time_str}'. Örnek: '20:00', 'yarın 9:00', '5 dakika sonra'"
            }
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO reminders (message, remind_at, created_at) VALUES (?, ?, ?)",
                (message, remind_at.isoformat(), datetime.now().isoformat())
            )
            reminder_id = cursor.lastrowid
            conn.commit()
        
        # Format time nicely
        if remind_at.date() == datetime.now().date():
            time_display = f"bugün {remind_at.strftime('%H:%M')}"
        elif remind_at.date() == (datetime.now() + timedelta(days=1)).date():
            time_display = f"yarın {remind_at.strftime('%H:%M')}"
        else:
            time_display = remind_at.strftime('%d/%m %H:%M')
        
        return {
            "ok": True,
            "text": f"✅ Hatırlatma #{reminder_id} eklendi: {time_display} - \"{message}\""
        }

    def list_reminders(self, include_done: bool = False) -> Dict[str, Any]:
        """List all reminders."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if include_done:
                rows = conn.execute(
                    "SELECT * FROM reminders ORDER BY remind_at"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM reminders WHERE status = 'pending' ORDER BY remind_at"
                ).fetchall()
        
        if not rows:
            return {"ok": True, "text": "📭 Bekleyen hatırlatma yok."}
        
        lines = ["📋 Hatırlatmalar:"]
        now = datetime.now()
        
        for row in rows:
            remind_at = datetime.fromisoformat(row['remind_at'])
            status_icon = "⏰" if row['status'] == 'pending' else "✅"
            
            # Time display
            if remind_at.date() == now.date():
                time_str = f"bugün {remind_at.strftime('%H:%M')}"
            elif remind_at.date() == (now + timedelta(days=1)).date():
                time_str = f"yarın {remind_at.strftime('%H:%M')}"
            else:
                time_str = remind_at.strftime('%d/%m %H:%M')
            
            lines.append(f"  {status_icon} [{row['id']}] {time_str} - {row['message']}")
        
        return {"ok": True, "text": "\n".join(lines)}

    def delete_reminder(self, reminder_id: int) -> Dict[str, Any]:
        """Delete a reminder by ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM reminders WHERE id = ?", (reminder_id,)
            )
            conn.commit()
            if cursor.rowcount == 0:
                return {"ok": False, "text": f"❌ Hatırlatma #{reminder_id} bulunamadı."}
        
        return {"ok": True, "text": f"🗑️ Hatırlatma #{reminder_id} silindi."}

    def snooze_reminder(self, reminder_id: int, minutes: int = 10) -> Dict[str, Any]:
        """Snooze a reminder by N minutes."""
        new_time = datetime.now() + timedelta(minutes=minutes)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE reminders SET remind_at = ?, status = 'pending' WHERE id = ?",
                (new_time.isoformat(), reminder_id)
            )
            conn.commit()
            if cursor.rowcount == 0:
                return {"ok": False, "text": f"❌ Hatırlatma #{reminder_id} bulunamadı."}
        
        return {
            "ok": True,
            "text": f"⏰ Hatırlatma #{reminder_id} {minutes} dakika ertelendi ({new_time.strftime('%H:%M')})"
        }

    def _send_notification(self, message: str, reminder_id: int) -> None:
        """Send desktop notification."""
        try:
            subprocess.run([
                "notify-send",
                "-u", "critical",  # High priority
                "-i", "appointment-soon",  # Icon
                "🔔 Bantz Hatırlatma",
                f"[#{reminder_id}] {message}"
            ], check=False)
        except Exception as e:
            print(f"Notification error: {e}")

    def _publish_event(self, reminder_id: int, message: str, remind_at: datetime) -> None:
        """Publish reminder_fired event to event bus."""
        try:
            from bantz.core.events import get_event_bus
            bus = get_event_bus()
            
            # Publish reminder_fired event
            bus.publish(
                event_type="reminder_fired",
                data={
                    "id": reminder_id,
                    "message": message,
                    "time": remind_at.isoformat(),
                },
                source="scheduler"
            )
            
            # Also publish a bantz_message for proactive UI
            bus.publish(
                event_type="bantz_message",
                data={
                    "text": f"🔔 Hatırlatma: {message}",
                    "intent": "reminder_fired",
                    "proactive": True,
                    "reminder_id": reminder_id,
                },
                source="scheduler"
            )
        except Exception as e:
            print(f"Event publish error: {e}")

    # Issue #1018: Recurring reminder interval parser
    _INTERVAL_MAP: dict[str, timedelta] = {
        "hourly": timedelta(hours=1),
        "saatlik": timedelta(hours=1),
        "daily": timedelta(days=1),
        "günlük": timedelta(days=1),
        "weekly": timedelta(weeks=1),
        "haftalık": timedelta(weeks=1),
        "monthly": timedelta(days=30),
        "aylık": timedelta(days=30),
    }

    @classmethod
    def _compute_next_occurrence(
        cls, last_fire: datetime, interval: str
    ) -> Optional[datetime]:
        """Compute the next fire time for a recurring reminder.

        Args:
            last_fire: The time the reminder last fired.
            interval: One of 'hourly', 'daily', 'weekly', 'monthly'
                      (Turkish equivalents also accepted), or a string
                      like '2h', '30m', '3d'.

        Returns:
            The next ``datetime``, or ``None`` if *interval* is not recognised.
        """
        key = (interval or "").strip().lower()
        if key in cls._INTERVAL_MAP:
            return last_fire + cls._INTERVAL_MAP[key]

        # Try shorthand: '2h', '30m', '3d', '1w'
        m = re.match(r"^(\d+)\s*([mhdw])$", key)
        if m:
            amount = int(m.group(1))
            unit = m.group(2)
            deltas = {
                "m": timedelta(minutes=amount),
                "h": timedelta(hours=amount),
                "d": timedelta(days=amount),
                "w": timedelta(weeks=amount),
            }
            return last_fire + deltas[unit]

        return None

    def _check_reminders(self) -> None:
        """Check and trigger due reminders."""
        now = datetime.now()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Get pending reminders that are due
            rows = conn.execute(
                "SELECT * FROM reminders WHERE status = 'pending' AND remind_at <= ?",
                (now.isoformat(),)
            ).fetchall()
            
            for row in rows:
                remind_at = datetime.fromisoformat(row['remind_at'])
                
                # Send desktop notification
                self._send_notification(row['message'], row['id'])
                
                # Publish event to event bus (for CLI, browser panel, logging)
                self._publish_event(row['id'], row['message'], remind_at)
                
                # Mark as done (or reschedule if repeat)
                if row['repeat_interval']:
                    # Issue #1018: Reschedule recurring reminders
                    next_time = self._compute_next_occurrence(
                        remind_at, row['repeat_interval']
                    )
                    if next_time is not None:
                        conn.execute(
                            "UPDATE reminders SET remind_at = ?, status = 'pending' WHERE id = ?",
                            (next_time.isoformat(), row['id']),
                        )
                    else:
                        # Unrecognised interval — mark done, log warning
                        conn.execute(
                            "UPDATE reminders SET status = 'done' WHERE id = ?",
                            (row['id'],),
                        )
                else:
                    conn.execute(
                        "UPDATE reminders SET status = 'done' WHERE id = ?",
                        (row['id'],)
                    )
            
            conn.commit()

    def _check_checkins(self) -> None:
        """Check and trigger due check-ins."""
        try:
            from bantz.scheduler.checkin import get_checkin_manager
            from bantz.core.events import get_event_bus
            
            checkin_mgr = get_checkin_manager()
            bus = get_event_bus()
            
            due_checkins = checkin_mgr.get_due_checkins()
            
            for checkin in due_checkins:
                checkin_id = checkin['id']
                prompt = checkin['prompt']
                
                # Send notification
                self._send_checkin_notification(prompt, checkin_id)
                
                # Publish events
                bus.publish(
                    event_type="checkin_fired",
                    data={
                        "id": checkin_id,
                        "prompt": prompt,
                        "schedule": checkin['schedule'],
                    },
                    source="scheduler"
                )
                
                bus.publish(
                    event_type="bantz_message",
                    data={
                        "text": f"[Check-in] {prompt}",
                        "intent": "checkin_fired",
                        "proactive": True,
                        "kind": "checkin",
                        "checkin_id": checkin_id,
                        "hint": "(cevap yazabilirsin / 'sonra' de geç)",
                    },
                    source="scheduler"
                )
                
                # Mark as fired (handles recurring vs one-time)
                checkin_mgr.mark_fired(checkin_id)
                
        except Exception as e:
            print(f"Check-in error: {e}")

    def _send_checkin_notification(self, prompt: str, checkin_id: int) -> None:
        """Send desktop notification for check-in."""
        try:
            import subprocess
            subprocess.run([
                "notify-send",
                "-u", "normal",
                "-i", "dialog-question",
                "🔔 Bantz Check-in",
                f"[#{checkin_id}] {prompt}"
            ], check=False)
        except Exception as e:
            print(f"Check-in notification error: {e}")

    def start_scheduler(self) -> None:
        """Start background scheduler thread."""
        if self._running:
            return
        
        self._running = True
        
        def scheduler_loop():
            while self._running:
                try:
                    self._check_reminders()
                    self._check_checkins()
                except Exception as e:
                    print(f"Scheduler error: {e}")
                time.sleep(10)  # Check every 10 seconds
        
        self._scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        print("[Scheduler] Background scheduler started (reminders + check-ins)")

    def stop_scheduler(self) -> None:
        """Stop background scheduler."""
        self._running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
            self._scheduler_thread = None


# Singleton instance
_manager: Optional[ReminderManager] = None


def get_reminder_manager() -> ReminderManager:
    """Get or create singleton reminder manager."""
    global _manager
    if _manager is None:
        _manager = ReminderManager()
    return _manager
