#!/usr/bin/env python3
"""Hybrid vs 3B-only Benchmark (Issue #161).

Compares performance between:
- 3B-only: Single Qwen 2.5 3B model for all tasks
- 3B+7B Hybrid: 3B router + 7B finalizer for quality responses

Metrics:
- Accuracy: Tool call correctness
- Naturalness: Response quality (manual rating or LLM-as-judge)
- TTFT/Latency: Time-to-first-token and total latency
- Token Usage: Input/output token counts
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import statistics
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

from bantz.agent.tools import ToolRegistry
from bantz.brain.flexible_hybrid_orchestrator import create_flexible_hybrid_orchestrator
from bantz.brain.gemini_hybrid_orchestrator import create_gemini_hybrid_orchestrator
from bantz.brain.orchestrator_state import OrchestratorState
from bantz.llm.vllm_openai_client import VLLMOpenAIClient
from bantz.llm.ttft_monitor import TTFTMonitor
from bantz.tools.registry import register_web_tools

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Results from a single test case."""
    
    test_id: str
    category: str
    difficulty: str
    input: str
    
    # Outputs
    route: str
    intent: str
    tools_called: list[str]
    response: str
    
    # Performance
    ttft_router_ms: Optional[float]
    ttft_finalizer_ms: Optional[float]
    total_latency_ms: float
    
    # Token usage
    input_tokens: int
    output_tokens: int
    total_tokens: int
    
    # Accuracy
    route_correct: bool
    intent_correct: bool
    tools_correct: bool
    overall_correct: bool
    
    # Quality (manual or LLM-as-judge)
    naturalness_score: Optional[float] = None  # 1-5 scale
    
    # Metadata
    error: Optional[str] = None
    trace: Optional[dict] = None


@dataclass
class BenchmarkSummary:
    """Summary statistics for a benchmark run."""
    
    mode: str  # "3b_only" or "hybrid"
    total_cases: int
    successful_cases: int
    failed_cases: int
    
    # Accuracy metrics
    route_accuracy: float
    intent_accuracy: float
    tools_accuracy: float
    overall_accuracy: float
    
    # Performance metrics
    ttft_p50_ms: float
    ttft_p95_ms: float
    ttft_p99_ms: float
    latency_mean_ms: float
    latency_p95_ms: float
    
    # Token usage
    total_input_tokens: int
    total_output_tokens: int
    avg_tokens_per_case: float
    
    # Quality (if available)
    avg_naturalness: Optional[float] = None
    
    # Results by category
    accuracy_by_category: dict[str, float] = None
    latency_by_category: dict[str, float] = None


class HybridBenchmark:
    """Benchmark runner for hybrid vs 3B-only comparison."""
    
    def __init__(
        self,
        mode: str = "hybrid",  # "hybrid" or "3b_only"
        router_url: str = "http://localhost:8001",
        finalizer_url: str = "http://localhost:8002",
        use_gemini: bool = False,
        gemini_api_key: Optional[str] = None,
    ):
        self.mode = mode
        self.results: list[BenchmarkResult] = []
        
        # Initialize tools
        self.tools = ToolRegistry()
        register_web_tools(self.tools)
        
        # Initialize orchestrator based on mode
        if mode == "3b_only":
            self.orchestrator = self._create_3b_only_orchestrator(router_url)
        elif mode == "hybrid":
            if use_gemini:
                self.orchestrator = self._create_gemini_hybrid(router_url, gemini_api_key)
            else:
                self.orchestrator = self._create_vllm_hybrid(router_url, finalizer_url)
        else:
            raise ValueError(f"Invalid mode: {mode}")
        
        logger.info(f"Initialized {mode} orchestrator")
    
    def _create_3b_only_orchestrator(self, url: str):
        """Create 3B-only orchestrator (no finalizer)."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        
        router = VLLMOpenAIClient(
            base_url=url,
            model="Qwen/Qwen2.5-3B-Instruct",
            track_ttft=True,
            ttft_phase="router",
        )
        
        return JarvisLLMOrchestrator(llm_client=router)
    
    def _create_vllm_hybrid(self, router_url: str, finalizer_url: str):
        """Create 3B+7B vLLM hybrid orchestrator."""
        router = VLLMOpenAIClient(
            base_url=router_url,
            model="Qwen/Qwen2.5-3B-Instruct",
            track_ttft=True,
            ttft_phase="router",
        )
        
        finalizer = VLLMOpenAIClient(
            base_url=finalizer_url,
            model="Qwen/Qwen2.5-7B-Instruct",
            track_ttft=True,
            ttft_phase="finalizer",
        )
        
        return create_flexible_hybrid_orchestrator(
            router_client=router,
            finalizer_client=finalizer,
        )
    
    def _create_gemini_hybrid(self, router_url: str, api_key: Optional[str]):
        """Create 3B+Gemini hybrid orchestrator."""
        router = VLLMOpenAIClient(
            base_url=router_url,
            model="Qwen/Qwen2.5-3B-Instruct",
            track_ttft=True,
            ttft_phase="router",
        )
        
        return create_gemini_hybrid_orchestrator(
            router_client=router,
            gemini_api_key=api_key,
        )
    
    def run_test_case(self, test_case: dict) -> BenchmarkResult:
        """Run a single test case."""
        test_id = test_case["id"]
        logger.info(f"Running {test_id}: {test_case['input']}")
        
        start_time = time.time()
        
        try:
            # Clear TTFT monitor before test
            monitor = TTFTMonitor.get_instance()
            monitor.clear_all()
            
            # Run orchestrator with keyword arguments
            # Use empty session_context (dict) for benchmarking
            output, _ = self.orchestrator.route(user_input=test_case["input"], session_context={})
            
            # Calculate latency
            total_latency_ms = (time.time() - start_time) * 1000
            
            # Get TTFT metrics
            router_stats = monitor.get_statistics("router")
            finalizer_stats = monitor.get_statistics("finalizer")
            
            ttft_router_ms = router_stats.last_ttft_ms if router_stats else None
            ttft_finalizer_ms = finalizer_stats.last_ttft_ms if finalizer_stats else None
            
            # Get token usage (approximate)
            input_tokens = len(test_case["input"].split()) * 1.3  # rough estimate
            output_tokens = len(output.assistant_reply.split()) * 1.3 if output.assistant_reply else 0
            
            # Check accuracy
            expected = test_case
            route_correct = output.route == expected.get("expected_route")
            intent_correct = (
                output.calendar_intent == expected.get("expected_intent") if "expected_intent" in expected else True
            )
            tools_correct = set(output.tool_plan or []) == set(expected.get("expected_tools", []))
            overall_correct = route_correct and intent_correct and tools_correct
            
            return BenchmarkResult(
                test_id=test_id,
                category=test_case.get("category", "unknown"),
                difficulty=test_case.get("difficulty", "unknown"),
                input=test_case["input"],
                route=output.route,
                intent=output.calendar_intent or "",
                tools_called=output.tool_plan or [],
                response=output.assistant_reply or "",
                ttft_router_ms=ttft_router_ms,
                ttft_finalizer_ms=ttft_finalizer_ms,
                total_latency_ms=total_latency_ms,
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
                total_tokens=int(input_tokens + output_tokens),
                route_correct=route_correct,
                intent_correct=intent_correct,
                tools_correct=tools_correct,
                overall_correct=overall_correct,
                trace={"output": asdict(output)} if hasattr(output, "__dict__") else None,
            )
        
        except Exception as e:
            logger.error(f"Test {test_id} failed: {e}")
            return BenchmarkResult(
                test_id=test_id,
                category=test_case.get("category", "unknown"),
                difficulty=test_case.get("difficulty", "unknown"),
                input=test_case["input"],
                route="error",
                intent="error",
                tools_called=[],
                response="",
                ttft_router_ms=None,
                ttft_finalizer_ms=None,
                total_latency_ms=(time.time() - start_time) * 1000,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                route_correct=False,
                intent_correct=False,
                tools_correct=False,
                overall_correct=False,
                error=str(e),
            )
    
    def run_scenario_file(self, scenario_file: Path) -> list[BenchmarkResult]:
        """Run all test cases from a scenario file."""
        logger.info(f"Loading scenarios from {scenario_file}")
        
        with scenario_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        
        results = []
        for test_case in data.get("cases", []):
            result = self.run_test_case(test_case)
            results.append(result)
            self.results.append(result)
        
        return results
    
    def generate_summary(self) -> BenchmarkSummary:
        """Generate summary statistics."""
        if not self.results:
            raise ValueError("No results to summarize")
        
        successful = [r for r in self.results if r.error is None]
        failed = [r for r in self.results if r.error is not None]
        
        # Accuracy metrics
        route_accuracy = sum(1 for r in self.results if r.route_correct) / len(self.results)
        intent_accuracy = sum(1 for r in self.results if r.intent_correct) / len(self.results)
        tools_accuracy = sum(1 for r in self.results if r.tools_correct) / len(self.results)
        overall_accuracy = sum(1 for r in self.results if r.overall_correct) / len(self.results)
        
        # TTFT metrics (router)
        ttft_values = [r.ttft_router_ms for r in successful if r.ttft_router_ms is not None]
        if ttft_values:
            ttft_p50 = statistics.median(ttft_values)
            ttft_p95 = statistics.quantiles(ttft_values, n=20)[18]  # 95th percentile
            ttft_p99 = statistics.quantiles(ttft_values, n=100)[98] if len(ttft_values) >= 100 else max(ttft_values)
        else:
            ttft_p50 = ttft_p95 = ttft_p99 = 0
        
        # Latency metrics
        latency_values = [r.total_latency_ms for r in successful]
        latency_mean = statistics.mean(latency_values) if latency_values else 0
        latency_p95 = statistics.quantiles(latency_values, n=20)[18] if len(latency_values) >= 20 else max(latency_values or [0])
        
        # Token usage
        total_input = sum(r.input_tokens for r in successful)
        total_output = sum(r.output_tokens for r in successful)
        avg_tokens = (total_input + total_output) / len(successful) if successful else 0
        
        # Accuracy by category
        accuracy_by_cat = {}
        latency_by_cat = {}
        for category in set(r.category for r in self.results):
            cat_results = [r for r in self.results if r.category == category]
            accuracy_by_cat[category] = sum(1 for r in cat_results if r.overall_correct) / len(cat_results)
            cat_latencies = [r.total_latency_ms for r in cat_results if r.error is None]
            latency_by_cat[category] = statistics.mean(cat_latencies) if cat_latencies else 0
        
        return BenchmarkSummary(
            mode=self.mode,
            total_cases=len(self.results),
            successful_cases=len(successful),
            failed_cases=len(failed),
            route_accuracy=route_accuracy,
            intent_accuracy=intent_accuracy,
            tools_accuracy=tools_accuracy,
            overall_accuracy=overall_accuracy,
            ttft_p50_ms=ttft_p50,
            ttft_p95_ms=ttft_p95,
            ttft_p99_ms=ttft_p99,
            latency_mean_ms=latency_mean,
            latency_p95_ms=latency_p95,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            avg_tokens_per_case=avg_tokens,
            accuracy_by_category=accuracy_by_cat,
            latency_by_category=latency_by_cat,
        )
    
    def save_results(self, output_file: Path) -> None:
        """Save detailed results to JSON."""
        summary = self.generate_summary()
        
        data = {
            "summary": asdict(summary),
            "results": [asdict(r) for r in self.results],
        }
        
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Results saved to {output_file}")
    
    def print_summary(self) -> None:
        """Print summary to console."""
        summary = self.generate_summary()
        
        print("\n" + "=" * 60)
        print(f"Benchmark Summary: {summary.mode.upper()}")
        print("=" * 60)
        print(f"Total Cases: {summary.total_cases}")
        print(f"Success: {summary.successful_cases} | Failed: {summary.failed_cases}")
        print()
        print("Accuracy Metrics:")
        print(f"  Route: {summary.route_accuracy:.1%}")
        print(f"  Intent: {summary.intent_accuracy:.1%}")
        print(f"  Tools: {summary.tools_accuracy:.1%}")
        print(f"  Overall: {summary.overall_accuracy:.1%}")
        print()
        print("Performance Metrics:")
        print(f"  TTFT p50: {summary.ttft_p50_ms:.0f}ms")
        print(f"  TTFT p95: {summary.ttft_p95_ms:.0f}ms")
        print(f"  Latency mean: {summary.latency_mean_ms:.0f}ms")
        print(f"  Latency p95: {summary.latency_p95_ms:.0f}ms")
        print()
        print("Token Usage:")
        print(f"  Input: {summary.total_input_tokens}")
        print(f"  Output: {summary.total_output_tokens}")
        print(f"  Avg/case: {summary.avg_tokens_per_case:.0f}")
        print()
        print("Accuracy by Category:")
        for cat, acc in sorted(summary.accuracy_by_category.items()):
            print(f"  {cat}: {acc:.1%}")
        print("=" * 60)


def main():
    # Load env vars from .env / BANTZ_ENV_FILE (Issue #216).
    try:
        from bantz.security.env_loader import load_env

        load_env()
    except Exception:
        pass

    # Redact secrets from any logs emitted by this script.
    try:
        from bantz.security.secrets import install_secrets_redaction_filter

        install_secrets_redaction_filter()
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Hybrid vs 3B-only benchmark")
    parser.add_argument(
        "--mode",
        choices=["3b_only", "hybrid", "both"],
        default="both",
        help="Benchmark mode",
    )
    parser.add_argument(
        "--router-url",
        default="http://localhost:8001",
        help="vLLM router URL (3B model)",
    )
    parser.add_argument(
        "--finalizer-url",
        default="http://localhost:8002",
        help="vLLM finalizer URL (7B model, hybrid mode)",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        help="Scenario files to run (default: all in tests/scenarios/)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/results"),
        help="Output directory for results",
    )
    parser.add_argument(
        "--use-gemini",
        action="store_true",
        help="Use Gemini as finalizer (hybrid mode)",
    )
    parser.add_argument(
        "--gemini-api-key",
        help=(
            "Gemini API key (discouraged: prefer GEMINI_API_KEY/GOOGLE_API_KEY env or .env via BANTZ_ENV_FILE)"
        ),
    )
    
    args = parser.parse_args()
    
    # Find scenario files
    if args.scenarios:
        scenario_files = [Path(s) for s in args.scenarios]
    else:
        scenarios_dir = Path("tests/scenarios")
        scenario_files = list(scenarios_dir.glob("*.json"))
    
    if not scenario_files:
        logger.error("No scenario files found")
        return 1
    
    logger.info(f"Found {len(scenario_files)} scenario files")
    
    # Run benchmarks
    modes = ["3b_only", "hybrid"] if args.mode == "both" else [args.mode]
    
    for mode in modes:
        logger.info(f"\n{'='*60}")
        logger.info(f"Running benchmark: {mode.upper()}")
        logger.info(f"{'='*60}\n")

        if args.use_gemini and not args.gemini_api_key:
            args.gemini_api_key = (
                os.getenv("GEMINI_API_KEY")
                or os.getenv("GOOGLE_API_KEY")
                or os.getenv("BANTZ_GEMINI_API_KEY")
            )
        
        benchmark = HybridBenchmark(
            mode=mode,
            router_url=args.router_url,
            finalizer_url=args.finalizer_url,
            use_gemini=args.use_gemini,
            gemini_api_key=args.gemini_api_key,
        )
        
        # Run all scenarios
        for scenario_file in scenario_files:
            benchmark.run_scenario_file(scenario_file)
        
        # Save results
        output_file = args.output_dir / f"bench_hybrid_{mode}.json"
        benchmark.save_results(output_file)
        
        # Print summary
        benchmark.print_summary()
    
    logger.info("\nBenchmark complete!")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
