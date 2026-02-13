from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import json
import os


class VisionQuotaExceeded(RuntimeError):
    pass


def _month_key(now: datetime) -> str:
    return f"{now.year:04d}-{now.month:02d}"


def _default_quota_path() -> Path:
    base = Path(os.path.expanduser(os.getenv("XDG_CONFIG_HOME", "~/.config"))).expanduser()
    return (base / "bantz" / "vision" / "quota.json").resolve()


@dataclass
class MonthlyQuotaLimiter:
    """Persisted monthly quota limiter.

    This is meant for low-volume paid APIs (e.g. Google Vision free tier).
    """

    max_requests_per_month: int = 1000
    quota_path: Path = _default_quota_path()

    @classmethod
    def from_env(cls) -> "MonthlyQuotaLimiter":
        raw_max = os.getenv("BANTZ_VISION_MONTHLY_QUOTA")
        raw_path = os.getenv("BANTZ_VISION_QUOTA_PATH")

        max_requests = 1000
        if raw_max:
            try:
                max_requests = int(raw_max)
            except ValueError:
                max_requests = 1000

        quota_path = Path(os.path.expanduser(raw_path)).resolve() if raw_path else _default_quota_path()
        return cls(max_requests_per_month=max_requests, quota_path=quota_path)

    def _read_state(self) -> dict[str, Any]:
        if not self.quota_path.exists():
            return {}
        try:
            return json.loads(self.quota_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_state(self, data: dict[str, Any]) -> None:
        self.quota_path.parent.mkdir(parents=True, exist_ok=True)
        self.quota_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def check_and_increment(self, *, units: int = 1, now: Optional[datetime] = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        key = _month_key(now)

        data = self._read_state()
        month = data.get(key) or {"used": 0, "updated_at": None}

        used = int(month.get("used") or 0)
        if used + units > self.max_requests_per_month:
            raise VisionQuotaExceeded(
                f"Monthly vision quota exceeded ({used}/{self.max_requests_per_month}). "
                "Set BANTZ_VISION_MONTHLY_QUOTA to override, or wait until next month."
            )

        month["used"] = used + units
        month["updated_at"] = now.isoformat()
        data[key] = month
        self._write_state(data)

        return {"month": key, "used": month["used"], "max": self.max_requests_per_month}
