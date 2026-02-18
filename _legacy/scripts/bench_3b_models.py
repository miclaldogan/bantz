#!/usr/bin/env python3
"""3B Model Benchmark CLI.

Issue #239: Evaluate best 3B-class model for Turkish + router use case.

Usage:
    python scripts/bench_3b_models.py                  # Run with mock (no vLLM)
    python scripts/bench_3b_models.py --live           # Run against live vLLM
    python scripts/bench_3b_models.py --output report.md
    python scripts/bench_3b_models.py --format json
    python scripts/bench_3b_models.py --list-candidates
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bantz.llm.model_benchmark import (
    DEFAULT_CANDIDATES,
    DEFAULT_REPORT_PATH,
    DEFAULT_VLLM_BASE,
    ModelBenchmark,
    ModelBenchmarkResult,
    generate_report,
    run_mock_benchmark,
)


def list_candidates() -> None:
    """List available model candidates."""
    print("Available Model Candidates:")
    print("=" * 60)
    
    for i, c in enumerate(DEFAULT_CANDIDATES, 1):
        print(f"\n{i}. {c.name}")
        print(f"   HuggingFace: {c.hf_id}")
        print(f"   Quantization: {c.quantization}")
        print(f"   Notes: {c.notes}")


def run_live_benchmark(
    vllm_base: str,
) -> list[ModelBenchmarkResult]:
    """Run benchmark against live vLLM instance.
    
    Note: This only tests the currently loaded model.
    For full comparison, models need to be loaded separately.
    """
    import requests
    
    # Check vLLM availability
    try:
        resp = requests.get(f"{vllm_base}/health", timeout=5)
        if resp.status_code != 200:
            print(f"vLLM not healthy at {vllm_base}")
            return []
    except Exception as e:
        print(f"Cannot connect to vLLM at {vllm_base}: {e}")
        return []
    
    # Get current model info
    try:
        resp = requests.get(f"{vllm_base}/v1/models", timeout=5)
        models_data = resp.json()
        model_id = models_data.get("data", [{}])[0].get("id", "unknown")
    except Exception:
        model_id = "unknown"
    
    print(f"Testing model: {model_id}")
    print("-" * 40)
    
    # Create candidate for current model
    from bantz.llm.model_benchmark import ModelCandidate
    
    current = ModelCandidate(
        name=model_id.split("/")[-1] if "/" in model_id else model_id,
        hf_id=model_id,
        quantization="unknown",
        notes="Currently loaded model",
    )
    
    # Run benchmark
    benchmark = ModelBenchmark(vllm_base=vllm_base)
    result = benchmark.run_benchmark(current)
    
    return [result]


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark 3B models for Turkish + router use case",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run against live vLLM instance (tests current model only)",
    )
    parser.add_argument(
        "--vllm-base",
        default=DEFAULT_VLLM_BASE,
        help=f"vLLM API base URL (default: {DEFAULT_VLLM_BASE})",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_REPORT_PATH,
        help=f"Output report path (default: {DEFAULT_REPORT_PATH})",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "text"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--list-candidates",
        action="store_true",
        help="List available model candidates",
    )
    
    args = parser.parse_args()
    
    if args.list_candidates:
        list_candidates()
        return 0
    
    # Run benchmark
    if args.live:
        print("Running live benchmark against vLLM...")
        results = run_live_benchmark(args.vllm_base)
        if not results:
            print("No results - vLLM may not be available")
            return 1
    else:
        print("Running mock benchmark (use --live for actual testing)...")
        results = run_mock_benchmark()
    
    # Output results
    if args.format == "json":
        output = json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False)
        print(output)
        
        # Also save to file
        json_path = args.output.replace(".md", ".json")
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\nSaved to: {json_path}")
        
    elif args.format == "text":
        print("\n" + "=" * 60)
        print("BENCHMARK RESULTS")
        print("=" * 60)
        
        for r in sorted(results, key=lambda x: x.overall_score, reverse=True):
            print(f"\n{r.model.name}")
            print(f"  JSON Compliance: {r.json_compliance_rate*100:.1f}%")
            print(f"  Route Accuracy:  {r.route_accuracy*100:.1f}%")
            print(f"  Smalltalk:       {r.smalltalk_quality*100:.1f}%")
            print(f"  Latency:         {r.avg_latency_ms:.0f}ms (p95: {r.p95_latency_ms:.0f}ms)")
            print(f"  Throughput:      {r.avg_tokens_per_sec:.0f} tok/s")
            print(f"  Overall Score:   {r.overall_score*100:.1f}%")
        
        if results:
            best = max(results, key=lambda x: x.overall_score)
            print(f"\n✅ Recommended: {best.model.name}")
    
    else:  # markdown
        report = generate_report(results, args.output)
        print(report)
        print(f"\nSaved to: {args.output}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
