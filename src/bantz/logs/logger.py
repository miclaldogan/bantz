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
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "request": request,
            "result": result,
        }
        if fields:
            record.update(fields)
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
