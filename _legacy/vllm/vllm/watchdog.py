#!/usr/bin/env python3
"""vLLM watchdog (Issue #181).

Periodically checks a vLLM OpenAI-compatible endpoint and restarts it when unhealthy.

Default behavior targets the 3B server on port 8001 via the existing scripts:
  - scripts/vllm/stop.sh
  - scripts/vllm/start_3b.sh

Outputs crash/restart context into:
  artifacts/logs/vllm/watchdog/

Usage:
  python3 scripts/vllm/watchdog.py --port 8001
  python3 scripts/vllm/watchdog.py --port 8001 --interval 10 --fail-threshold 3
  python3 scripts/vllm/watchdog.py --once  # single healthcheck + exit code

Notes:
  - This script is intentionally conservative: it only restarts after N consecutive
    failures and enforces a cooldown between restarts.
  - It does best-effort log capture; it will not crash if log files or tools are missing.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


@dataclass(frozen=True)
class HealthResult:
    base_url: str
    port: int
    status: str  # healthy|offline|timeout|error
    model_id: str | None
    response_time_ms: float | None
    error: str | None


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _env_str(name: str, default: str) -> str:
    v = str(os.getenv(name, "")).strip()
    return v or default


def _healthcheck(*, port: int, timeout_s: float) -> HealthResult:
    base_url = f"http://localhost:{int(port)}"
    url = f"{base_url}/v1/models"

    t0 = time.perf_counter()
    try:
        r = requests.get(url, timeout=float(timeout_s))
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if r.status_code != 200:
            return HealthResult(
                base_url=base_url,
                port=int(port),
                status="error",
                model_id=None,
                response_time_ms=round(elapsed_ms, 1),
                error=f"HTTP {r.status_code}",
            )

        data = r.json() or {}
        items = data.get("data") or []
        model_id = None
        if isinstance(items, list) and items and isinstance(items[0], dict):
            model_id = str(items[0].get("id") or "").strip() or None

        if not model_id:
            return HealthResult(
                base_url=base_url,
                port=int(port),
                status="error",
                model_id=None,
                response_time_ms=round(elapsed_ms, 1),
                error="No models in /v1/models",
            )

        return HealthResult(
            base_url=base_url,
            port=int(port),
            status="healthy",
            model_id=model_id,
            response_time_ms=round(elapsed_ms, 1),
            error=None,
        )

    except requests.exceptions.ConnectionError:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return HealthResult(
            base_url=base_url,
            port=int(port),
            status="offline",
            model_id=None,
            response_time_ms=round(elapsed_ms, 1),
            error="Connection refused",
        )
    except requests.exceptions.Timeout:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return HealthResult(
            base_url=base_url,
            port=int(port),
            status="timeout",
            model_id=None,
            response_time_ms=round(elapsed_ms, 1),
            error=f"Request timeout ({timeout_s}s)",
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return HealthResult(
            base_url=base_url,
            port=int(port),
            status="error",
            model_id=None,
            response_time_ms=round(elapsed_ms, 1),
            error=str(e),
        )


def _read_tail(path: Path, *, max_bytes: int = 64_000) -> str:
    try:
        if not path.exists():
            return ""
        data = path.read_bytes()
        if len(data) > max_bytes:
            data = data[-max_bytes:]
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return data.decode(errors="replace")
    except Exception:
        return ""


def _detect_oom(log_tail: str) -> bool:
    t = (log_tail or "").lower()
    if "out of memory" in t:
        return True
    if "cuda out of memory" in t:
        return True
    if "cublas" in t and "alloc" in t and "failed" in t:
        return True
    return False


def _run_cmd(cmd: list[str], *, cwd: Path, timeout_s: float | None) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=None if timeout_s is None else float(timeout_s),
            text=True,
            check=False,
        )
        return int(p.returncode), str(p.stdout or "")
    except subprocess.TimeoutExpired as e:
        out = "".join([str(x or "") for x in (e.stdout, e.stderr)])
        return 124, out
    except Exception as e:
        return 127, str(e)


def _ensure_exec(path: Path) -> list[str]:
    """Return a command list that can execute path on Linux."""
    if not path.exists():
        raise FileNotFoundError(str(path))
    # Prefer direct execution when executable bit is set.
    if os.access(path, os.X_OK):
        return [str(path)]
    # Fallback for repos where executable bit was lost.
    return ["bash", str(path)]


def main() -> int:
    parser = argparse.ArgumentParser(description="vLLM watchdog (auto-recovery)")
    parser.add_argument("--port", type=int, default=int(os.getenv("BANTZ_VLLM_3B_PORT", "8001")))
    parser.add_argument("--timeout", type=float, default=3.0, help="Healthcheck timeout seconds")
    parser.add_argument("--interval", type=float, default=10.0, help="Healthcheck interval seconds")
    parser.add_argument("--fail-threshold", type=int, default=3, help="Consecutive failures to trigger restart")
    parser.add_argument(
        "--cooldown",
        type=float,
        default=120.0,
        help="Minimum seconds between restarts",
    )
    parser.add_argument(
        "--stop-script",
        default="scripts/vllm/stop.sh",
        help="Stop script path (repo-relative)",
    )
    parser.add_argument(
        "--start-script",
        default="scripts/vllm/start_3b.sh",
        help="Start script path (repo-relative)",
    )
    parser.add_argument(
        "--log-dir",
        default=_env_str("BANTZ_VLLM_LOG_DIR", "artifacts/logs/vllm"),
        help="vLLM log dir (default: BANTZ_VLLM_LOG_DIR or artifacts/logs/vllm)",
    )
    parser.add_argument(
        "--watchdog-dir",
        default="artifacts/logs/vllm/watchdog",
        help="Output dir for watchdog restart logs",
    )
    parser.add_argument("--once", action="store_true", help="Run one healthcheck and exit")
    parser.add_argument("--dry-run", action="store_true", help="Do not execute stop/start scripts")

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    stop_path = (repo_root / str(args.stop_script)).resolve()
    start_path = (repo_root / str(args.start_script)).resolve()

    watchdog_dir = (repo_root / str(args.watchdog_dir)).resolve()
    watchdog_dir.mkdir(parents=True, exist_ok=True)

    vllm_log_dir = (repo_root / str(args.log_dir)).resolve()
    vllm_log_file = vllm_log_dir / f"vllm_{int(args.port)}.log"

    consecutive_failures = 0
    last_restart_ts = 0.0

    def report(h: HealthResult) -> None:
        line = {
            "ts": _utc_stamp(),
            "status": h.status,
            "port": h.port,
            "base_url": h.base_url,
            "model_id": h.model_id,
            "rt_ms": h.response_time_ms,
            "error": h.error,
            "consecutive_failures": consecutive_failures,
        }
        print(json.dumps(line, ensure_ascii=False))

    while True:
        h = _healthcheck(port=int(args.port), timeout_s=float(args.timeout))

        if h.status == "healthy":
            consecutive_failures = 0
        else:
            consecutive_failures += 1

        report(h)

        if args.once:
            return 0 if h.status == "healthy" else 1

        should_restart = consecutive_failures >= int(args.fail_threshold)
        cooldown_ok = (time.time() - last_restart_ts) >= float(args.cooldown)

        if should_restart and cooldown_ok:
            stamp = _utc_stamp()
            tail = _read_tail(vllm_log_file)
            oom = _detect_oom(tail)

            ctx: dict[str, Any] = {
                "ts": stamp,
                "port": int(args.port),
                "health": {
                    "status": h.status,
                    "error": h.error,
                    "rt_ms": h.response_time_ms,
                },
                "log_file": str(vllm_log_file),
                "log_tail_bytes": len(tail.encode("utf-8", errors="replace")) if tail else 0,
                "oom_suspected": bool(oom),
                "dry_run": bool(args.dry_run),
            }

            out_prefix = watchdog_dir / f"restart_{int(args.port)}_{stamp}"
            (out_prefix.with_suffix(".json")).write_text(
                json.dumps(ctx, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            if tail:
                (out_prefix.with_suffix(".logtail.txt")).write_text(tail, encoding="utf-8")

            if not args.dry_run:
                stop_cmd = _ensure_exec(stop_path)
                start_cmd = _ensure_exec(start_path)

                rc1, out1 = _run_cmd(stop_cmd, cwd=repo_root, timeout_s=60.0)
                (out_prefix.with_suffix(".stop.txt")).write_text(out1, encoding="utf-8")

                # Always attempt start even if stop fails; pkill races are common.
                rc2, out2 = _run_cmd(start_cmd, cwd=repo_root, timeout_s=600.0)
                (out_prefix.with_suffix(".start.txt")).write_text(out2, encoding="utf-8")

                ctx["stop_rc"] = rc1
                ctx["start_rc"] = rc2
                (out_prefix.with_suffix(".json")).write_text(
                    json.dumps(ctx, indent=2, ensure_ascii=False), encoding="utf-8"
                )

            last_restart_ts = time.time()
            consecutive_failures = 0

        time.sleep(float(args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
