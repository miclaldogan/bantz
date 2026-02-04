from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class JsonlLogger:
    path: str

    def log(self, request: str, result: dict[str, Any], **fields: Any) -> None:
        record: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "request": request,
            "result": result,
        }
        if fields:
            record.update(fields)

        # Best-effort secret masking (Issue #216).
        try:
            from bantz.security.secrets import sanitize

            record = sanitize(record)
        except Exception:
            pass

        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("", encoding="utf-8")
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    def log_tool_execution(
        self,
        tool_name: str,
        risk_level: str,
        success: bool,
        confirmed: bool = False,
        error: str | None = None,
        params: dict[str, Any] | None = None,
        result: Any = None,
        **extra_fields: Any,
    ) -> None:
        """Log tool execution with risk level and confirmation status (Issue #160).
        
        Args:
            tool_name: Name of the tool executed
            risk_level: Risk level (safe/moderate/destructive)
            success: Whether execution succeeded
            confirmed: Whether user confirmed (for destructive tools)
            error: Error message if failed
            params: Tool parameters
            result: Tool result (truncated)
            **extra_fields: Additional audit fields
        """
        record: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "event_type": "tool_execution",
            "tool_name": tool_name,
            "risk_level": risk_level,
            "success": success,
            "confirmed": confirmed,
        }
        
        if error:
            record["error"] = error
        if params:
            record["params"] = params
        if result:
            # Truncate result to 500 chars for logging
            result_str = str(result)
            record["result"] = result_str[:500] + "..." if len(result_str) > 500 else result_str
        
        record.update(extra_fields)

        # Best-effort secret masking (Issue #216).
        try:
            from bantz.security.secrets import sanitize

            record = sanitize(record)
        except Exception:
            pass
        
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text("", encoding="utf-8")
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def tail(self, n: int = 20) -> list[dict[str, Any]]:
        p = Path(self.path)
        if not p.exists():
            return []
        # simple tail: read all and slice (fine for v0.1)
        lines = p.read_text(encoding="utf-8").splitlines()
        out: list[dict[str, Any]] = []
        for line in lines[-max(1, n) :]:
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
        return out
