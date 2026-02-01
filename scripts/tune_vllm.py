#!/usr/bin/env python3
"""vLLM tuning loop helper.

Runs the Issue #180 benchmark in a couple of fixed "profiles" so you can iterate
on server flags (e.g., max-num-seqs / max-num-batched-tokens / max-model-len)
and quickly spot regressions.

This does NOT change vLLM flags itself — you tweak server start scripts/env vars,
restart vLLM, and use this script to measure before/after.

Examples:
  # Run both profiles against local 8001
  python3 scripts/tune_vllm.py

  # Compare to baselines and fail if >10% regression
  python3 scripts/tune_vllm.py --baseline-dir artifacts/results/baselines --fail-regression-pct 10

  # Create/refresh baselines
  python3 scripts/tune_vllm.py --baseline-dir artifacts/results/baselines --write-baseline

  # Run only the router-like profile
  python3 scripts/tune_vllm.py --profile router
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Profile:
    name: str
    num_requests: int
    concurrency: int
    max_tokens: int
    timeout_s: float
    temperature: float


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _run(cmd: list[str], *, cwd: Path) -> int:
    p = subprocess.run(cmd, cwd=str(cwd))
    return int(p.returncode)


def _bench_cmd(
    *,
    targets: list[str],
    model: str,
    profile: Profile,
    out_json: Path,
    out_md: Path,
    baseline: Path | None,
    fail_regression_pct: float | None,
) -> list[str]:
    cmd = [
        "python3",
        "scripts/bench_vllm.py",
        *sum([["--target", t] for t in targets], []),
        "--model",
        model,
        "--num-requests",
        str(profile.num_requests),
        "--concurrency",
        str(profile.concurrency),
        "--max-tokens",
        str(profile.max_tokens),
        "--temperature",
        str(profile.temperature),
        "--timeout",
        str(profile.timeout_s),
        "--out-json",
        str(out_json),
        "--out-md",
        str(out_md),
    ]
    if baseline is not None and baseline.exists():
        cmd.extend(["--baseline", str(baseline)])
    if fail_regression_pct is not None:
        cmd.extend(["--fail-regression-pct", str(fail_regression_pct)])
    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(description="Run vLLM tuning benchmarks")
    parser.add_argument(
        "--target",
        action="append",
        default=["local=http://127.0.0.1:8001"],
        help="Benchmark target in LABEL=URL form. Repeatable.",
    )
    parser.add_argument("--model", default="auto")
    parser.add_argument(
        "--profile",
        choices=["router", "generation", "both"],
        default="both",
        help="Which benchmark profile(s) to run",
    )
    parser.add_argument(
        "--out-dir",
        default="artifacts/results/tuning",
        help="Output directory (JSON + MD per profile)",
    )
    parser.add_argument(
        "--baseline-dir",
        default="",
        help="Directory containing per-profile baselines (router.json, generation.json)",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="After a successful run, write/refresh baselines in --baseline-dir",
    )
    parser.add_argument(
        "--fail-regression-pct",
        type=float,
        default=None,
        help="Fail if completion tok/s regresses more than this percent vs baseline",
    )

    args = parser.parse_args()

    profiles = {
        # Router-like: keep replies short, drive concurrency.
        "router": Profile(
            name="router",
            num_requests=256,
            concurrency=64,
            max_tokens=96,
            timeout_s=20.0,
            temperature=0.2,
        ),
        # Generation-like: typical assistant replies.
        "generation": Profile(
            name="generation",
            num_requests=128,
            concurrency=32,
            max_tokens=256,
            timeout_s=60.0,
            temperature=0.2,
        ),
    }

    selected: list[Profile]
    if args.profile == "both":
        selected = [profiles["router"], profiles["generation"]]
    else:
        selected = [profiles[str(args.profile)]]

    root = _repo_root()
    out_dir = (root / str(args.out_dir)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline_dir = (root / str(args.baseline_dir)).resolve() if args.baseline_dir else None
    if args.write_baseline and not baseline_dir:
        print("--write-baseline requires --baseline-dir", file=sys.stderr)
        return 2
    if baseline_dir is not None:
        baseline_dir.mkdir(parents=True, exist_ok=True)

    stamp = _utc_stamp()

    for p in selected:
        out_json = out_dir / f"bench_vllm_{p.name}_{stamp}.json"
        out_md = out_dir / f"bench_vllm_{p.name}_{stamp}.md"

        baseline = (baseline_dir / f"{p.name}.json") if baseline_dir is not None else None

        cmd = _bench_cmd(
            targets=list(args.target),
            model=str(args.model),
            profile=p,
            out_json=out_json,
            out_md=out_md,
            baseline=baseline,
            fail_regression_pct=args.fail_regression_pct,
        )

        print(f"\n== running profile={p.name} ==")
        print(" ".join(cmd))

        rc = _run(cmd, cwd=root)
        if rc != 0:
            return rc

        if args.write_baseline and baseline_dir is not None:
            shutil.copyfile(out_json, baseline_dir / f"{p.name}.json")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
