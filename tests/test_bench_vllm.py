from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_bench_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "bench_vllm.py"
    spec = importlib.util.spec_from_file_location("bench_vllm", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Dataclasses may inspect sys.modules[cls.__module__] for string annotations.
    sys.modules["bench_vllm"] = module
    spec.loader.exec_module(module)
    return module


def test_v1_base_url_normalization():
    m = _load_bench_module()
    assert m._v1_base_url("http://127.0.0.1:8001") == "http://127.0.0.1:8001/v1"
    assert m._v1_base_url("http://127.0.0.1:8001/") == "http://127.0.0.1:8001/v1"
    assert m._v1_base_url("http://127.0.0.1:8001/v1") == "http://127.0.0.1:8001/v1"


def test_percentile_basic():
    m = _load_bench_module()
    vals = [1.0, 2.0, 3.0, 4.0]
    assert m._percentile(vals, 0) == 1.0
    assert m._percentile(vals, 100) == 4.0
    # Median between 2 and 3
    assert m._percentile(vals, 50) == 2.5


def test_parse_targets():
    m = _load_bench_module()
    assert m._parse_targets(["awq=http://localhost:8001"]) == [("awq", "http://localhost:8001")]


def test_regression_detection():
    m = _load_bench_module()

    baseline = m.BenchmarkRun(
        generated_at="t0",
        script="scripts/bench_vllm.py",
        targets=[
            m.TargetSummary(
                label="local",
                base_url="http://127.0.0.1:8001",
                model="m",
                num_requests=10,
                concurrency=2,
                max_tokens=16,
                temperature=0.0,
                duration_sec=1.0,
                total_prompt_tokens=0,
                total_completion_tokens=0,
                total_tokens=0,
                throughput_total_tok_s=100.0,
                throughput_completion_tok_s=100.0,
                latency_p50_ms=10.0,
                latency_p95_ms=20.0,
                latency_p99_ms=30.0,
                ok_rate=1.0,
            )
        ],
    )

    current = m.BenchmarkRun(
        generated_at="t1",
        script="scripts/bench_vllm.py",
        targets=[
            m.TargetSummary(
                label="local",
                base_url="http://127.0.0.1:8001",
                model="m",
                num_requests=10,
                concurrency=2,
                max_tokens=16,
                temperature=0.0,
                duration_sec=1.0,
                total_prompt_tokens=0,
                total_completion_tokens=0,
                total_tokens=0,
                throughput_total_tok_s=89.0,
                throughput_completion_tok_s=89.0,
                latency_p50_ms=10.0,
                latency_p95_ms=20.0,
                latency_p99_ms=30.0,
                ok_rate=1.0,
            )
        ],
    )

    regs = m._find_regressions(current=current, baseline=baseline, fail_regression_pct=10.0)
    assert regs, "Expected a regression when drop exceeds threshold"


def test_markdown_renders_table():
    m = _load_bench_module()
    run = m.BenchmarkRun(
        generated_at="t",
        script="scripts/bench_vllm.py",
        targets=[
            m.TargetSummary(
                label="local",
                base_url="http://127.0.0.1:8001",
                model="m",
                num_requests=1,
                concurrency=1,
                max_tokens=1,
                temperature=0.0,
                duration_sec=1.0,
                total_prompt_tokens=1,
                total_completion_tokens=1,
                total_tokens=2,
                throughput_total_tok_s=2.0,
                throughput_completion_tok_s=1.0,
                latency_p50_ms=10.0,
                latency_p95_ms=10.0,
                latency_p99_ms=10.0,
                ok_rate=1.0,
            )
        ],
    )

    md = m._render_markdown(run)
    assert "# vLLM Benchmark Results" in md
    assert "| Target | Model |" in md
    assert "| local | m |" in md
