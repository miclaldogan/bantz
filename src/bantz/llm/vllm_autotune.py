"""vLLM Auto-tune Framework.

Issue #240: Auto-tune vLLM flags for router vs generation profiles.

This module provides:
- Profile definitions for router and generation
- Grid search over vLLM configuration parameters
- Objective functions for latency and throughput
- Configuration recommendation
- Report generation
"""

from __future__ import annotations

import json
import os
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Literal, Optional, Tuple

import requests


# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_VLLM_BASE = os.getenv("BANTZ_VLLM_BASE", "http://localhost:8001")
DEFAULT_REPORT_PATH = str(
    Path(__file__).resolve().parent.parent / "artifacts" / "results" / "tune_report.md"
)


# ============================================================================
# PROFILE DEFINITIONS
# ============================================================================

ProfileType = Literal["router", "generation"]


@dataclass
class TuneProfile:
    """Profile for vLLM tuning."""
    
    name: ProfileType
    description: str
    
    # Test parameters
    num_requests: int = 100
    concurrency: int = 32
    max_tokens: int = 128
    temperature: float = 0.1
    timeout_s: float = 30.0
    
    # Objective weights (0-1)
    latency_weight: float = 0.7
    throughput_weight: float = 0.3
    
    # Targets
    target_p95_latency_ms: float = 100.0  # p95 latency target
    target_tokens_per_sec: float = 100.0  # throughput target
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)


# Default profiles
PROFILES = {
    "router": TuneProfile(
        name="router",
        description="Short JSON responses, low latency, high concurrency",
        num_requests=200,
        concurrency=64,
        max_tokens=96,
        temperature=0.1,
        latency_weight=0.8,
        throughput_weight=0.2,
        target_p95_latency_ms=80.0,
        target_tokens_per_sec=150.0,
    ),
    "generation": TuneProfile(
        name="generation",
        description="Longer responses, stable throughput",
        num_requests=100,
        concurrency=32,
        max_tokens=256,
        temperature=0.2,
        latency_weight=0.5,
        throughput_weight=0.5,
        target_p95_latency_ms=200.0,
        target_tokens_per_sec=80.0,
    ),
}


# ============================================================================
# VLLM CONFIGURATION
# ============================================================================

@dataclass
class VLLMConfig:
    """vLLM server configuration."""
    
    # Model
    model: str = "Qwen/Qwen2.5-3B-Instruct-AWQ"
    quantization: str = "awq"
    
    # Memory
    gpu_memory_utilization: float = 0.85
    max_model_len: int = 4096
    
    # Batching
    max_num_seqs: int = 256
    max_num_batched_tokens: Optional[int] = None
    
    # KV Cache
    kv_cache_dtype: str = "auto"
    
    # Performance flags
    enable_prefix_caching: bool = False
    enable_chunked_prefill: bool = False
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        result = asdict(self)
        # Remove None values
        return {k: v for k, v in result.items() if v is not None}
    
    def to_cli_args(self) -> list[str]:
        """Convert to CLI arguments for vLLM serve."""
        args = [
            "--model", self.model,
            "--quantization", self.quantization,
            "--gpu-memory-utilization", str(self.gpu_memory_utilization),
            "--max-model-len", str(self.max_model_len),
            "--max-num-seqs", str(self.max_num_seqs),
            "--kv-cache-dtype", self.kv_cache_dtype,
        ]
        
        if self.max_num_batched_tokens:
            args.extend(["--max-num-batched-tokens", str(self.max_num_batched_tokens)])
        
        if self.enable_prefix_caching:
            args.append("--enable-prefix-caching")
        
        if self.enable_chunked_prefill:
            args.append("--enable-chunked-prefill")
        
        return args
    
    @classmethod
    def from_dict(cls, data: dict) -> "VLLMConfig":
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ============================================================================
# GRID SEARCH PARAMETERS
# ============================================================================

@dataclass
class TuneGridParams:
    """Parameters for grid search."""
    
    # These are lists of values to try
    gpu_memory_utilization: List[float] = field(
        default_factory=lambda: [0.80, 0.85, 0.90]
    )
    max_model_len: List[int] = field(
        default_factory=lambda: [2048, 4096]
    )
    max_num_seqs: List[int] = field(
        default_factory=lambda: [128, 256, 512]
    )
    enable_prefix_caching: List[bool] = field(
        default_factory=lambda: [False, True]
    )
    
    def config_count(self) -> int:
        """Count total configurations."""
        return (
            len(self.gpu_memory_utilization) *
            len(self.max_model_len) *
            len(self.max_num_seqs) *
            len(self.enable_prefix_caching)
        )
    
    def iter_configs(self, base: VLLMConfig) -> Iterator[VLLMConfig]:
        """Iterate over all configuration combinations."""
        for gpu_mem, model_len, num_seqs, prefix_cache in product(
            self.gpu_memory_utilization,
            self.max_model_len,
            self.max_num_seqs,
            self.enable_prefix_caching,
        ):
            yield VLLMConfig(
                model=base.model,
                quantization=base.quantization,
                gpu_memory_utilization=gpu_mem,
                max_model_len=model_len,
                max_num_seqs=num_seqs,
                enable_prefix_caching=prefix_cache,
                kv_cache_dtype=base.kv_cache_dtype,
            )


# Reduced grid for quick tuning
QUICK_GRID = TuneGridParams(
    gpu_memory_utilization=[0.85],
    max_model_len=[2048, 4096],
    max_num_seqs=[256, 512],
    enable_prefix_caching=[False],
)

# Full grid for comprehensive tuning
FULL_GRID = TuneGridParams(
    gpu_memory_utilization=[0.80, 0.85, 0.90],
    max_model_len=[2048, 4096, 8192],
    max_num_seqs=[128, 256, 512, 1024],
    enable_prefix_caching=[False, True],
)


# ============================================================================
# BENCHMARK RESULTS
# ============================================================================

@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""
    
    config: VLLMConfig
    profile: TuneProfile
    
    # Latency metrics (ms)
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    
    # Throughput metrics
    total_tokens: int = 0
    total_time_s: float = 0.0
    tokens_per_sec: float = 0.0
    requests_per_sec: float = 0.0
    
    # Success metrics
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 1.0
    
    # Objective score
    objective_score: float = 0.0
    
    # Raw latencies for percentile calculation
    latencies: List[float] = field(default_factory=list)
    
    def calculate_objective(self) -> float:
        """Calculate objective score based on profile weights.
        
        Higher is better.
        """
        # Latency score (lower is better, invert)
        latency_target = self.profile.target_p95_latency_ms
        if self.p95_latency_ms > 0:
            latency_score = min(1.0, latency_target / self.p95_latency_ms)
        else:
            latency_score = 0.0
        
        # Throughput score (higher is better)
        throughput_target = self.profile.target_tokens_per_sec
        if throughput_target > 0:
            throughput_score = min(1.0, self.tokens_per_sec / throughput_target)
        else:
            throughput_score = 0.0
        
        # Penalty for failures
        success_penalty = self.success_rate
        
        # Weighted objective
        self.objective_score = (
            self.profile.latency_weight * latency_score +
            self.profile.throughput_weight * throughput_score
        ) * success_penalty
        
        return self.objective_score
    
    def to_dict(self) -> dict:
        """Convert to dictionary (without large latencies list)."""
        return {
            "config": self.config.to_dict(),
            "profile": self.profile.name,
            "avg_latency_ms": self.avg_latency_ms,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "tokens_per_sec": self.tokens_per_sec,
            "requests_per_sec": self.requests_per_sec,
            "success_rate": self.success_rate,
            "objective_score": self.objective_score,
        }


# ============================================================================
# BENCHMARK ENGINE
# ============================================================================

class VLLMBenchmark:
    """Benchmark engine for vLLM."""
    
    def __init__(
        self,
        vllm_base: str = DEFAULT_VLLM_BASE,
        timeout: float = 30.0,
    ):
        """Initialize benchmark.
        
        Args:
            vllm_base: vLLM API base URL
            timeout: Request timeout in seconds
        """
        self.vllm_base = vllm_base
        self.timeout = timeout
    
    def check_health(self) -> bool:
        """Check if vLLM is healthy."""
        try:
            resp = requests.get(f"{self.vllm_base}/health", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False
    
    def _send_request(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> Tuple[bool, float, int]:
        """Send a single request.
        
        Returns:
            (success, latency_ms, tokens_generated)
        """
        url = f"{self.vllm_base}/v1/chat/completions"
        
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        try:
            start = time.perf_counter()
            resp = requests.post(url, json=payload, timeout=self.timeout)
            latency_ms = (time.perf_counter() - start) * 1000
            
            if resp.status_code != 200:
                return False, latency_ms, 0
            
            data = resp.json()
            tokens = data.get("usage", {}).get("completion_tokens", 0)
            
            return True, latency_ms, tokens
            
        except Exception:
            return False, 0.0, 0
    
    def run_benchmark(
        self,
        config: VLLMConfig,
        profile: TuneProfile,
        prompts: Optional[List[str]] = None,
    ) -> BenchmarkResult:
        """Run benchmark with given config and profile.
        
        Note: This assumes the vLLM server is already running with the given config.
        
        Args:
            config: vLLM configuration (for recording)
            profile: Benchmark profile
            prompts: Test prompts (defaults to generated prompts)
            
        Returns:
            BenchmarkResult
        """
        if prompts is None:
            prompts = self._generate_prompts(profile.num_requests)
        
        result = BenchmarkResult(config=config, profile=profile)
        
        # Simple sequential benchmark (for accuracy)
        # For production, use concurrent benchmark
        start_time = time.perf_counter()
        
        for prompt in prompts[:profile.num_requests]:
            success, latency, tokens = self._send_request(
                prompt=prompt,
                max_tokens=profile.max_tokens,
                temperature=profile.temperature,
            )
            
            if success:
                result.success_count += 1
                result.latencies.append(latency)
                result.total_tokens += tokens
            else:
                result.failure_count += 1
        
        result.total_time_s = time.perf_counter() - start_time
        
        # Calculate metrics
        total_requests = result.success_count + result.failure_count
        if total_requests > 0:
            result.success_rate = result.success_count / total_requests
        
        if result.latencies:
            result.avg_latency_ms = statistics.mean(result.latencies)
            sorted_lat = sorted(result.latencies)
            n = len(sorted_lat)
            result.p50_latency_ms = sorted_lat[int(n * 0.50)]
            result.p95_latency_ms = sorted_lat[min(int(n * 0.95), n - 1)]
            result.p99_latency_ms = sorted_lat[min(int(n * 0.99), n - 1)]
        
        if result.total_time_s > 0:
            result.tokens_per_sec = result.total_tokens / result.total_time_s
            result.requests_per_sec = result.success_count / result.total_time_s
        
        # Calculate objective
        result.calculate_objective()
        
        return result
    
    def _generate_prompts(self, count: int) -> List[str]:
        """Generate test prompts."""
        # Mix of router-like and generation-like prompts
        router_prompts = [
            "saat kaç",
            "yarın toplantım var mı",
            "son mailimi oku",
            "merhaba nasılsın",
            "hava durumu ne",
            "cpu kullanımı",
            "takvimime bak",
            "teşekkür ederim",
            "bugün ne var",
            "mail gönder",
        ]
        
        generation_prompts = [
            "Bana bugünkü planımı özetle ve önerilerde bulun",
            "Yarınki toplantı için hazırlık listesi çıkar",
            "Son beş mailimi özetle ve önceliklendir",
            "Bu hafta için görev listesi oluştur",
            "Proje durumunu anlat ve sonraki adımları öner",
        ]
        
        prompts = []
        for i in range(count):
            if i % 3 == 0:
                prompts.append(generation_prompts[i % len(generation_prompts)])
            else:
                prompts.append(router_prompts[i % len(router_prompts)])
        
        return prompts


# ============================================================================
# TUNER
# ============================================================================

@dataclass
class TuneResult:
    """Result of tuning session."""
    
    profile: TuneProfile
    baseline: Optional[BenchmarkResult] = None
    best: Optional[BenchmarkResult] = None
    all_results: List[BenchmarkResult] = field(default_factory=list)
    
    # Improvement metrics
    latency_improvement_pct: float = 0.0
    throughput_improvement_pct: float = 0.0
    
    def calculate_improvement(self) -> None:
        """Calculate improvement over baseline."""
        if self.baseline and self.best:
            if self.baseline.p95_latency_ms > 0:
                self.latency_improvement_pct = (
                    (self.baseline.p95_latency_ms - self.best.p95_latency_ms) /
                    self.baseline.p95_latency_ms * 100
                )
            
            if self.baseline.tokens_per_sec > 0:
                self.throughput_improvement_pct = (
                    (self.best.tokens_per_sec - self.baseline.tokens_per_sec) /
                    self.baseline.tokens_per_sec * 100
                )
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "profile": self.profile.name,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "best": self.best.to_dict() if self.best else None,
            "latency_improvement_pct": self.latency_improvement_pct,
            "throughput_improvement_pct": self.throughput_improvement_pct,
            "configs_tested": len(self.all_results),
        }


class VLLMTuner:
    """Auto-tuner for vLLM configuration.
    
    Note: This is designed for simulation/analysis. Actual config changes
    require restarting vLLM server.
    """
    
    def __init__(
        self,
        benchmark: VLLMBenchmark,
    ):
        """Initialize tuner.
        
        Args:
            benchmark: Benchmark engine
        """
        self.benchmark = benchmark
    
    def run_baseline(
        self,
        config: VLLMConfig,
        profile: TuneProfile,
    ) -> BenchmarkResult:
        """Run baseline benchmark.
        
        Args:
            config: Current vLLM configuration
            profile: Benchmark profile
            
        Returns:
            Baseline result
        """
        return self.benchmark.run_benchmark(config, profile)
    
    def tune(
        self,
        base_config: VLLMConfig,
        profile: TuneProfile,
        grid: TuneGridParams = QUICK_GRID,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> TuneResult:
        """Run tuning with grid search.
        
        Note: This simulates different configs. In practice, you'd need to
        restart vLLM for each config. This implementation is for analysis
        and recommendation generation.
        
        Args:
            base_config: Base configuration
            profile: Tune profile
            grid: Grid search parameters
            progress_callback: Callback(current, total) for progress
            
        Returns:
            TuneResult with best configuration
        """
        result = TuneResult(profile=profile)
        
        # Run baseline with current config
        result.baseline = self.benchmark.run_benchmark(base_config, profile)
        result.all_results.append(result.baseline)
        
        # Note: In simulation mode, we can't actually test different configs
        # without restarting vLLM. This is a framework for when that's possible.
        # For now, we return baseline as best.
        result.best = result.baseline
        
        result.calculate_improvement()
        
        return result
    
    def generate_recommendations(
        self,
        profile: TuneProfile,
        baseline: BenchmarkResult,
    ) -> List[VLLMConfig]:
        """Generate configuration recommendations based on profile.
        
        Args:
            profile: Tune profile
            baseline: Baseline benchmark result
            
        Returns:
            List of recommended configurations
        """
        recommendations = []
        base = baseline.config
        
        if profile.name == "router":
            # Router: prioritize low latency
            recommendations.append(VLLMConfig(
                model=base.model,
                quantization=base.quantization,
                gpu_memory_utilization=0.85,
                max_model_len=2048,  # Smaller for faster KV cache
                max_num_seqs=512,    # More concurrent sequences
                enable_prefix_caching=True,  # Help with repeated prompts
            ))
            
            recommendations.append(VLLMConfig(
                model=base.model,
                quantization=base.quantization,
                gpu_memory_utilization=0.90,
                max_model_len=2048,
                max_num_seqs=256,
                enable_prefix_caching=False,
            ))
        
        else:  # generation
            # Generation: balance latency and throughput
            recommendations.append(VLLMConfig(
                model=base.model,
                quantization=base.quantization,
                gpu_memory_utilization=0.85,
                max_model_len=4096,
                max_num_seqs=256,
                enable_prefix_caching=False,
            ))
            
            recommendations.append(VLLMConfig(
                model=base.model,
                quantization=base.quantization,
                gpu_memory_utilization=0.80,
                max_model_len=4096,
                max_num_seqs=128,
                enable_prefix_caching=True,
            ))
        
        return recommendations


# ============================================================================
# REPORT GENERATION
# ============================================================================

def generate_tune_report(
    results: Dict[str, TuneResult],
    output_path: str = DEFAULT_REPORT_PATH,
) -> str:
    """Generate markdown tuning report.
    
    Args:
        results: Dict of profile name -> TuneResult
        output_path: Output file path
        
    Returns:
        Markdown report string
    """
    lines = [
        "# vLLM Auto-tune Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Summary",
        "",
    ]
    
    for profile_name, result in results.items():
        lines.extend([
            f"### {profile_name.title()} Profile",
            "",
            f"**Description:** {result.profile.description}",
            "",
        ])
        
        if result.baseline:
            lines.extend([
                "**Baseline Metrics:**",
                f"- p95 Latency: {result.baseline.p95_latency_ms:.1f} ms",
                f"- Throughput: {result.baseline.tokens_per_sec:.1f} tok/s",
                f"- Success Rate: {result.baseline.success_rate*100:.1f}%",
                "",
            ])
        
        if result.best and result.best != result.baseline:
            lines.extend([
                "**Best Configuration:**",
                f"- p95 Latency: {result.best.p95_latency_ms:.1f} ms",
                f"- Throughput: {result.best.tokens_per_sec:.1f} tok/s",
                f"- Latency Improvement: {result.latency_improvement_pct:+.1f}%",
                f"- Throughput Improvement: {result.throughput_improvement_pct:+.1f}%",
                "",
            ])
        
        lines.append("")
    
    # Recommendations
    lines.extend([
        "## Recommended Configurations",
        "",
    ])
    
    for profile_name, result in results.items():
        lines.extend([
            f"### {profile_name.title()} Profile",
            "",
            "```bash",
        ])
        
        if result.best:
            lines.extend(result.best.config.to_cli_args())
        
        lines.extend([
            "```",
            "",
        ])
    
    # Methodology
    lines.extend([
        "## Methodology",
        "",
        "- **Router Profile:** Optimized for low latency with short responses",
        "  - Target p95 latency: 80ms",
        "  - High concurrency (64 concurrent requests)",
        "  - Short max tokens (96)",
        "",
        "- **Generation Profile:** Balanced latency and throughput",
        "  - Target p95 latency: 200ms",
        "  - Moderate concurrency (32 concurrent requests)",
        "  - Longer max tokens (256)",
        "",
    ])
    
    report = "\n".join(lines)
    
    # Write to file
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    
    return report


# ============================================================================
# MOCK TUNER (for testing without vLLM)
# ============================================================================

def run_mock_tune() -> Dict[str, TuneResult]:
    """Run mock tuning for testing without vLLM.
    
    Returns simulated results.
    """
    results = {}
    
    for profile_name, profile in PROFILES.items():
        result = TuneResult(profile=profile)
        
        # Simulated baseline
        base_config = VLLMConfig()
        result.baseline = BenchmarkResult(
            config=base_config,
            profile=profile,
            avg_latency_ms=60 if profile_name == "router" else 150,
            p50_latency_ms=50 if profile_name == "router" else 130,
            p95_latency_ms=100 if profile_name == "router" else 250,
            p99_latency_ms=120 if profile_name == "router" else 300,
            tokens_per_sec=120 if profile_name == "router" else 80,
            requests_per_sec=50 if profile_name == "router" else 20,
            success_rate=0.98,
        )
        result.baseline.calculate_objective()
        
        # Simulated best (20% improvement)
        best_config = VLLMConfig(
            max_model_len=2048 if profile_name == "router" else 4096,
            max_num_seqs=512 if profile_name == "router" else 256,
            enable_prefix_caching=True,
        )
        result.best = BenchmarkResult(
            config=best_config,
            profile=profile,
            avg_latency_ms=48 if profile_name == "router" else 120,
            p50_latency_ms=40 if profile_name == "router" else 100,
            p95_latency_ms=80 if profile_name == "router" else 200,
            p99_latency_ms=96 if profile_name == "router" else 240,
            tokens_per_sec=150 if profile_name == "router" else 100,
            requests_per_sec=62 if profile_name == "router" else 25,
            success_rate=0.99,
        )
        result.best.calculate_objective()
        
        result.calculate_improvement()
        results[profile_name] = result
    
    return results
