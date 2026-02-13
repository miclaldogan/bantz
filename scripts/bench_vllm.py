#!/usr/bin/env python3
"""vLLM micro-benchmark (Issue #180).

Goal: measure vLLM throughput (tokens/sec) and basic latency under concurrent load,
and optionally compare against a baseline to catch regressions.

This script targets vLLM's OpenAI-compatible HTTP API:
  - GET  /v1/models
  - POST /v1/chat/completions

Examples:
  # Single target (default http://127.0.0.1:8001)
  python3 scripts/bench_vllm.py

  # Compare AWQ vs GPTQ endpoints (you start the servers)
  python3 scripts/bench_vllm.py \
    --target awq=http://127.0.0.1:8001 \
    --target gptq=http://127.0.0.1:8003 \
    --num-requests 256 --concurrency 32 --max-tokens 256

  # Regression gate: fail if tok/s drops by more than 10% vs baseline
  python3 scripts/bench_vllm.py --baseline artifacts/results/bench_vllm_latest.json \
    --fail-regression-pct 10

Notes:
  - "Batch size" here refers to benchmark load (num-requests + concurrency). Real
    batching happens server-side via vLLM's continuous batching.
  - KV-cache / quantization / speculative decoding are server-side. This script
    helps you measure the impact of changing those flags.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import requests


# -----------------------------
# Data models
# -----------------------------


@dataclass(frozen=True)
class SingleCall:
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class TargetSummary:
    label: str
    base_url: str
    model: str
    num_requests: int
    concurrency: int
    max_tokens: int
    temperature: float
    duration_sec: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    throughput_total_tok_s: float
    throughput_completion_tok_s: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    ok_rate: float


@dataclass(frozen=True)
class BenchmarkRun:
    generated_at: str
    script: str
    targets: list[TargetSummary]


# -----------------------------
# Helpers
# -----------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _v1_base_url(base_url: str) -> str:
    u = (base_url or "").strip().rstrip("/")
    if not u:
        raise ValueError("base_url is empty")
    if u.endswith("/v1"):
        return u
    return u + "/v1"


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if p <= 0:
        return float(min(values))
    if p >= 100:
        return float(max(values))
    values_sorted = sorted(values)
    k = (len(values_sorted) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(values_sorted) - 1)
    if f == c:
        return float(values_sorted[f])
    d0 = values_sorted[f] * (c - k)
    d1 = values_sorted[c] * (k - f)
    return float(d0 + d1)


def _safe_int(v: Any, default: int = -1) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _get_model_id(v1_base: str, *, timeout_s: float) -> str:
    r = requests.get(f"{v1_base}/models", timeout=timeout_s)
    r.raise_for_status()
    data = r.json() or {}
    items = data.get("data") or []
    if not items or not isinstance(items, list) or not isinstance(items[0], dict):
        raise RuntimeError("/v1/models returned no model ids")
    model_id = str(items[0].get("id") or "").strip()
    if not model_id:
        raise RuntimeError("/v1/models returned empty model id")
    return model_id


def _post_chat_completion(
    v1_base: str,
    *,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    timeout_s: float,
) -> SingleCall:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a concise helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "stream": False,
    }

    t0 = time.perf_counter()
    try:
        r = requests.post(
            f"{v1_base}/chat/completions",
            json=payload,
            timeout=timeout_s,
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        if r.status_code >= 400:
            return SingleCall(
                latency_ms=elapsed_ms,
                prompt_tokens=-1,
                completion_tokens=-1,
                total_tokens=-1,
                ok=False,
                error=f"HTTP {r.status_code}: {r.text[:200]}",
            )

        data = r.json() or {}
        usage = data.get("usage") or {}
        prompt_tokens = _safe_int(usage.get("prompt_tokens"), -1)
        completion_tokens = _safe_int(usage.get("completion_tokens"), -1)
        total_tokens = _safe_int(usage.get("total_tokens"), -1)

        # Some servers omit 'usage' for non-streaming. Best-effort fallback.
        if total_tokens < 0:
            total_tokens = max(prompt_tokens, 0) + max(completion_tokens, 0)

        return SingleCall(
            latency_ms=elapsed_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            ok=True,
        )

    except requests.Timeout:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return SingleCall(
            latency_ms=elapsed_ms,
            prompt_tokens=-1,
            completion_tokens=-1,
            total_tokens=-1,
            ok=False,
            error="timeout",
        )
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return SingleCall(
            latency_ms=elapsed_ms,
            prompt_tokens=-1,
            completion_tokens=-1,
            total_tokens=-1,
            ok=False,
            error=str(e)[:200],
        )


def _default_prompts() -> list[str]:
    # Keep prompts short-ish to focus on decode throughput.
    return [
        "Write 5 bullet points about why continuous batching helps throughput.",
        "Summarize: KV cache helps autoregressive decoding by storing attention keys/values.",
        "Explain AWQ vs GPTQ quantization in 6 sentences.",
        "Generate a short email asking to reschedule a meeting.",
    ]


def run_target(
    *,
    label: str,
    base_url: str,
    model: str,
    num_requests: int,
    concurrency: int,
    max_tokens: int,
    temperature: float,
    timeout_s: float,
    prompts: list[str],
) -> TargetSummary:
    v1_base = _v1_base_url(base_url)

    resolved_model = model.strip() if model else ""
    if not resolved_model or resolved_model.lower() == "auto":
        resolved_model = _get_model_id(v1_base, timeout_s=timeout_s)

    calls: list[SingleCall] = []

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=int(concurrency)) as ex:
        futures = []
        for i in range(int(num_requests)):
            prompt = prompts[i % len(prompts)]
            futures.append(
                ex.submit(
                    _post_chat_completion,
                    v1_base,
                    model=resolved_model,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout_s=timeout_s,
                )
            )

        for f in as_completed(futures):
            calls.append(f.result())

    duration = max(time.perf_counter() - t0, 1e-9)

    ok_calls = [c for c in calls if c.ok]
    ok_rate = (len(ok_calls) / len(calls)) if calls else 0.0

    latencies = [float(c.latency_ms) for c in ok_calls if c.latency_ms >= 0]

    total_prompt = sum(max(c.prompt_tokens, 0) for c in ok_calls)
    total_completion = sum(max(c.completion_tokens, 0) for c in ok_calls)
    total_tokens = sum(max(c.total_tokens, 0) for c in ok_calls)

    throughput_total = (total_tokens / duration) if duration > 0 else 0.0
    throughput_completion = (total_completion / duration) if duration > 0 else 0.0

    return TargetSummary(
        label=label,
        base_url=base_url,
        model=resolved_model,
        num_requests=int(num_requests),
        concurrency=int(concurrency),
        max_tokens=int(max_tokens),
        temperature=float(temperature),
        duration_sec=float(duration),
        total_prompt_tokens=int(total_prompt),
        total_completion_tokens=int(total_completion),
        total_tokens=int(total_tokens),
        throughput_total_tok_s=float(throughput_total),
        throughput_completion_tok_s=float(throughput_completion),
        latency_p50_ms=_percentile(latencies, 50),
        latency_p95_ms=_percentile(latencies, 95),
        latency_p99_ms=_percentile(latencies, 99),
        ok_rate=float(ok_rate),
    )


def _render_markdown(run: BenchmarkRun, *, baseline: BenchmarkRun | None = None) -> str:
    lines: list[str] = []
    lines.append("# vLLM Benchmark Results")
    lines.append("")
    lines.append(f"**Generated:** {run.generated_at}")
    lines.append("")

    lines.append("## Results")
    lines.append("")
    lines.append(
        "| Target | Model | Completion tok/s | Total tok/s | p50 latency (ms) | p95 latency (ms) | OK rate |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|")

    for t in run.targets:
        lines.append(
            "| {label} | {model} | {ctps:.2f} | {ttps:.2f} | {p50:.1f} | {p95:.1f} | {ok:.1f}% |".format(
                label=t.label,
                model=t.model,
                ctps=t.throughput_completion_tok_s,
                ttps=t.throughput_total_tok_s,
                p50=t.latency_p50_ms,
                p95=t.latency_p95_ms,
                ok=100.0 * t.ok_rate,
            )
        )

    if baseline is not None:
        base_by_label = {t.label: t for t in baseline.targets}
        lines.append("")
        lines.append("## Baseline comparison")
        lines.append("")
        lines.append("| Target | Baseline completion tok/s | Current completion tok/s | Δ tok/s | Δ % |")
        lines.append("|---|---:|---:|---:|---:|")

        for t in run.targets:
            b = base_by_label.get(t.label)
            if b is None:
                continue
            delta = t.throughput_completion_tok_s - b.throughput_completion_tok_s
            pct = 0.0
            if b.throughput_completion_tok_s > 0:
                pct = (delta / b.throughput_completion_tok_s) * 100.0
            lines.append(
                "| {label} | {b:.2f} | {c:.2f} | {d:+.2f} | {p:+.1f}% |".format(
                    label=t.label,
                    b=b.throughput_completion_tok_s,
                    c=t.throughput_completion_tok_s,
                    d=delta,
                    p=pct,
                )
            )

    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Concurrency exercises vLLM continuous batching.")
    lines.append("- KV-cache tuning / quantization / speculative decoding are server flags; use this to measure impact.")
    lines.append("")

    return "\n".join(lines)


def _load_run(path: Path) -> BenchmarkRun:
    data = json.loads(path.read_text(encoding="utf-8"))
    targets = []
    for t in data.get("targets") or []:
        targets.append(TargetSummary(**t))
    return BenchmarkRun(
        generated_at=str(data.get("generated_at") or ""),
        script=str(data.get("script") or ""),
        targets=targets,
    )


def _parse_targets(args_targets: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for raw in args_targets:
        if "=" not in raw:
            raise ValueError(f"Invalid --target '{raw}'. Expected LABEL=URL")
        label, url = raw.split("=", 1)
        label = label.strip()
        url = url.strip()
        if not label or not url:
            raise ValueError(f"Invalid --target '{raw}'. Expected LABEL=URL")
        out.append((label, url))
    return out


def _write_outputs(run: BenchmarkRun, *, out_json: Path, out_md: Path, baseline: BenchmarkRun | None) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    out_json.write_text(
        json.dumps(asdict(run), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    out_md.write_text(_render_markdown(run, baseline=baseline), encoding="utf-8")


def _find_regressions(
    *,
    current: BenchmarkRun,
    baseline: BenchmarkRun,
    fail_regression_pct: float,
) -> list[str]:
    base_by_label = {t.label: t for t in baseline.targets}
    regressions: list[str] = []
    for t in current.targets:
        b = base_by_label.get(t.label)
        if b is None:
            continue
        if b.throughput_completion_tok_s <= 0:
            continue
        drop_pct = (1.0 - (t.throughput_completion_tok_s / b.throughput_completion_tok_s)) * 100.0
        if drop_pct > fail_regression_pct:
            regressions.append(
                f"{t.label}: completion tok/s dropped {drop_pct:.1f}% (baseline {b.throughput_completion_tok_s:.2f} → current {t.throughput_completion_tok_s:.2f})"
            )
    return regressions


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="vLLM throughput benchmark (Issue #180)")
    p.add_argument(
        "--target",
        action="append",
        default=[],
        help="Benchmark target in LABEL=URL form. Repeatable. Default: local=http://127.0.0.1:8001",
    )
    p.add_argument("--model", default="auto", help="Model id to pass to /chat/completions (default: auto from /v1/models)")
    p.add_argument("--num-requests", type=int, default=256, help="Total requests (default: 256)")
    p.add_argument("--concurrency", type=int, default=32, help="Concurrent in-flight requests (default: 32)")
    p.add_argument("--max-tokens", type=int, default=256, help="max_tokens per request (default: 256)")
    p.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature")
    p.add_argument("--timeout", type=float, default=240.0, help="Per-request timeout seconds")
    p.add_argument(
        "--baseline",
        type=str,
        default="",
        help="Path to a previous bench_vllm JSON output for before/after comparison",
    )
    p.add_argument(
        "--fail-regression-pct",
        type=float,
        default=0.0,
        help="Fail (exit 2) if completion tok/s drops more than this percent vs baseline",
    )
    p.add_argument(
        "--out-json",
        type=str,
        default="",
        help="Output JSON path (default: artifacts/results/bench_vllm_<timestamp>.json)",
    )
    p.add_argument(
        "--out-md",
        type=str,
        default="",
        help="Output Markdown path (default: artifacts/results/bench_vllm_<timestamp>.md)",
    )

    args = p.parse_args(argv)

    targets = _parse_targets(args.target) if args.target else [("local", "http://127.0.0.1:8001")]

    prompts = _default_prompts()

    baseline_run: BenchmarkRun | None = None
    if args.baseline:
        baseline_run = _load_run(Path(args.baseline))

    summaries: list[TargetSummary] = []
    for label, url in targets:
        s = run_target(
            label=label,
            base_url=url,
            model=str(args.model),
            num_requests=int(args.num_requests),
            concurrency=int(args.concurrency),
            max_tokens=int(args.max_tokens),
            temperature=float(args.temperature),
            timeout_s=float(args.timeout),
            prompts=prompts,
        )
        summaries.append(s)
        print(
            f"[{label}] model={s.model} completion_tok_s={s.throughput_completion_tok_s:.2f} total_tok_s={s.throughput_total_tok_s:.2f} p50_ms={s.latency_p50_ms:.1f} ok={s.ok_rate*100:.1f}%"
        )

    run = BenchmarkRun(
        generated_at=_utc_now_iso(),
        script="scripts/bench_vllm.py",
        targets=summaries,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = Path(args.out_json) if args.out_json else Path(f"artifacts/results/bench_vllm_{ts}.json")
    out_md = Path(args.out_md) if args.out_md else Path(f"artifacts/results/bench_vllm_{ts}.md")

    _write_outputs(run, out_json=out_json, out_md=out_md, baseline=baseline_run)
    print(f"Wrote: {out_json}")
    print(f"Wrote: {out_md}")

    if baseline_run is not None and args.fail_regression_pct and args.fail_regression_pct > 0:
        regressions = _find_regressions(
            current=run,
            baseline=baseline_run,
            fail_regression_pct=float(args.fail_regression_pct),
        )
        if regressions:
            for r in regressions:
                print(f"REGRESSION: {r}", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
