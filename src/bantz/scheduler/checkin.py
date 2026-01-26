"""Bantz Check-in Manager - Proactive "yoklama" system.

Check-ins are different from reminders:
- Reminders: one-shot notifications about tasks
- Check-ins: Bantz proactively starts a conversation ("Nasılsın?", "Devam ediyor musun?")

Schedule formats:
- "in 5 minutes" / "5 dakika sonra"
- "daily 21:00" / "her gün 21:00"
- "once 2026-01-19 21:00" (one-time at specific datetime)
"""
from __future__ import annotations

import sqlite3
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any


# Use same DB as reminders
DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "bantz" / "reminders.db"


class CheckinManager:
    """SQLite-backed check-in manager for proactive conversations."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize checkins table."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    next_run_at TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    last_fired_at TEXT DEFAULT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_checkin_next_run ON checkins(next_run_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_checkin_status ON checkins(status)
            """)
            conn.commit()

    def _parse_schedule(self, schedule_str: str) -> tuple[Optional[datetime], str]:
        """Parse schedule string and return (next_run_at, normalized_schedule).
        
        Returns:
            (datetime, schedule_type) or (None, error_message)
        """
        s = schedule_str.strip().lower()
        now = datetime.now()
        
        # "5 dakika sonra", "10 dk sonra", "1 saat sonra", "30 saniye sonra"
        delta_match = re.match(r'(\d+)\s*(dakika|dk|saat|sa|saniye|sn)\s*sonra', s)
        if delta_match:
            amount = int(delta_match.group(1))
            unit = delta_match.group(2)
            if unit in ('dakika', 'dk'):
                next_run = now + timedelta(minutes=amount)
            elif unit in ('saat', 'sa'):
                next_run = now + timedelta(hours=amount)
            elif unit in ('saniye', 'sn'):
                next_run = now + timedelta(seconds=amount)
            else:
                return None, f"Bilinmeyen zaman birimi: {unit}"
            return next_run, f"once {next_run.isoformat()}"
        
        # "in 5 minutes"
        in_match = re.match(r'in\s+(\d+)\s*(minutes?|hours?|seconds?)', s)
        if in_match:
            amount = int(in_match.group(1))
            unit = in_match.group(2)
            if unit.startswith('minute'):
                next_run = now + timedelta(minutes=amount)
            elif unit.startswith('hour'):
                next_run = now + timedelta(hours=amount)
            elif unit.startswith('second'):
                next_run = now + timedelta(seconds=amount)
            else:
                return None, f"Unknown time unit: {unit}"
            return next_run, f"once {next_run.isoformat()}"
        
        # "her gün 21:00", "daily 21:00"
        daily_match = re.match(r'(?:her\s*g[uü]n|daily)\s*(\d{1,2})[:\.](\d{2})', s)
        if daily_match:
            hour, minute = int(daily_match.group(1)), int(daily_match.group(2))
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            return next_run, f"daily {hour:02d}:{minute:02d}"
        
        # "yarın 9:00"
        tomorrow_match = re.match(r'yar[ıi]n\s*(\d{1,2})[:\.](\d{2})', s)
        if tomorrow_match:
            hour, minute = int(tomorrow_match.group(1)), int(tomorrow_match.group(2))
            tomorrow = now + timedelta(days=1)
            next_run = tomorrow.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return next_run, f"once {next_run.isoformat()}"
        
        # "20:00" (today or tomorrow)
        time_match = re.match(r'(\d{1,2})[:\.](\d{2})', s)
        if time_match:
            hour, minute = int(time_match.group(1)), int(time_match.group(2))
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            return next_run, f"once {next_run.isoformat()}"
        
        return None, f"Zamanlama formatını anlayamadım: '{schedule_str}'"

    def _calculate_next_run(self, schedule: str, last_fired: Optional[datetime] = None) -> Optional[datetime]:
        """Calculate next run time based on schedule type."""
        now = datetime.now()
        
        # "once YYYY-MM-DDTHH:MM:SS" - one time
        if schedule.startswith("once "):
            return datetime.fromisoformat(schedule[5:])
        
        # "daily HH:MM" - recurring
        if schedule.startswith("daily "):
            time_part = schedule[6:]
            hour, minute = map(int, time_part.split(":"))
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            return next_run
        
        return None

    def add_checkin(self, schedule_str: str, prompt: str) -> Dict[str, Any]:
        """Add a new check-in."""
        next_run, schedule = self._parse_schedule(schedule_str)
        if next_run is None:
            return {"ok": False, "text": schedule}  # schedule contains error message
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO checkins (prompt, schedule, next_run_at, created_at, status) 
                   VALUES (?, ?, ?, ?, 'active')""",
                (prompt, schedule, next_run.isoformat(), datetime.now().isoformat())
            )
            checkin_id = cursor.lastrowid
            conn.commit()
        
        # Format time display
        if next_run.date() == datetime.now().date():
            time_display = f"bugün {next_run.strftime('%H:%M')}"
        elif next_run.date() == (datetime.now() + timedelta(days=1)).date():
            time_display = f"yarın {next_run.strftime('%H:%M')}"
        else:
            time_display = next_run.strftime('%d/%m %H:%M')
        
        schedule_type = "Tek seferlik" if schedule.startswith("once") else "Günlük"
        
        return {
            "ok": True,
            "text": f"✅ Check-in #{checkin_id} eklendi: {time_display} ({schedule_type})\n   → \"{prompt}\""
        }

    def list_checkins(self, include_done: bool = False) -> Dict[str, Any]:
        """List all check-ins."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if include_done:
                rows = conn.execute(
                    "SELECT * FROM checkins ORDER BY next_run_at"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM checkins WHERE status IN ('active', 'paused') ORDER BY next_run_at"
                ).fetchall()
        
        if not rows:
            return {"ok": True, "text": "📭 Aktif check-in yok."}
        
        lines = ["📋 Check-in'ler:"]
        now = datetime.now()
        
        for row in rows:
            next_run = datetime.fromisoformat(row['next_run_at'])
            status_icon = "⏸️" if row['status'] == 'paused' else "🔔"
            
            # Time display
            if next_run.date() == now.date():
                time_str = f"bugün {next_run.strftime('%H:%M')}"
            elif next_run.date() == (now + timedelta(days=1)).date():
                time_str = f"yarın {next_run.strftime('%H:%M')}"
            else:
                time_str = next_run.strftime('%d/%m %H:%M')
            
            # Schedule type
            schedule_type = "📅" if row['schedule'].startswith('daily') else "🎯"
            
            prompt_preview = row['prompt'][:30] + "..." if len(row['prompt']) > 30 else row['prompt']
            lines.append(f"  {status_icon} [{row['id']}] {time_str} {schedule_type} \"{prompt_preview}\"")
        
        return {"ok": True, "text": "\n".join(lines)}

    def delete_checkin(self, checkin_id: int) -> Dict[str, Any]:
        """Delete a check-in by ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM checkins WHERE id = ?", (checkin_id,)
            )
            conn.commit()
            if cursor.rowcount == 0:
                return {"ok": False, "text": f"❌ Check-in #{checkin_id} bulunamadı."}
        
        return {"ok": True, "text": f"🗑️ Check-in #{checkin_id} silindi."}

    def pause_checkin(self, checkin_id: int) -> Dict[str, Any]:
        """Pause a check-in."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE checkins SET status = 'paused' WHERE id = ? AND status = 'active'",
                (checkin_id,)
            )
            conn.commit()
            if cursor.rowcount == 0:
                return {"ok": False, "text": f"❌ Check-in #{checkin_id} bulunamadı veya zaten durdurulmuş."}
        
        return {"ok": True, "text": f"⏸️ Check-in #{checkin_id} durduruldu."}

    def resume_checkin(self, checkin_id: int) -> Dict[str, Any]:
        """Resume a paused check-in."""
        with sqlite3.connect(self.db_path) as conn:
            # First get the schedule to recalculate next_run
            row = conn.execute(
                "SELECT schedule FROM checkins WHERE id = ? AND status = 'paused'",
                (checkin_id,)
            ).fetchone()
            
            if not row:
                return {"ok": False, "text": f"❌ Check-in #{checkin_id} bulunamadı veya zaten aktif."}
            
            # Recalculate next run time
            next_run = self._calculate_next_run(row[0])
            if next_run is None:
                return {"ok": False, "text": f"❌ Check-in #{checkin_id} için zamanlama hesaplanamadı."}
            
            conn.execute(
                "UPDATE checkins SET status = 'active', next_run_at = ? WHERE id = ?",
                (next_run.isoformat(), checkin_id)
            )
            conn.commit()
        
        return {"ok": True, "text": f"▶️ Check-in #{checkin_id} tekrar aktif."}

    def get_due_checkins(self) -> List[Dict[str, Any]]:
        """Get check-ins that are due to fire."""
        now = datetime.now()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM checkins WHERE status = 'active' AND next_run_at <= ?",
                (now.isoformat(),)
            ).fetchall()
        
        return [dict(row) for row in rows]

    def mark_fired(self, checkin_id: int) -> None:
        """Mark a check-in as fired and update next_run for recurring ones."""
        now = datetime.now()
        
        with sqlite3.connect(self.db_path) as conn:
            # Get the schedule
            row = conn.execute(
                "SELECT schedule FROM checkins WHERE id = ?", (checkin_id,)
            ).fetchone()
            
            if not row:
                return
            
            schedule = row[0]
            
            if schedule.startswith("once"):
                # One-time check-in - mark as done
                conn.execute(
                    "UPDATE checkins SET status = 'done', last_fired_at = ? WHERE id = ?",
                    (now.isoformat(), checkin_id)
                )
            else:
                # Recurring - calculate next run
                next_run = self._calculate_next_run(schedule)
                if next_run:
                    conn.execute(
                        "UPDATE checkins SET next_run_at = ?, last_fired_at = ? WHERE id = ?",
                        (next_run.isoformat(), now.isoformat(), checkin_id)
                    )
            
            conn.commit()


# Singleton instance
_checkin_manager: Optional[CheckinManager] = None


def get_checkin_manager() -> CheckinManager:
    """Get or create singleton check-in manager."""
    global _checkin_manager
    if _checkin_manager is None:
        _checkin_manager = CheckinManager()
    return _checkin_manager
