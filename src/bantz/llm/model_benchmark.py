"""3B Model Benchmark Framework.

Issue #239: Evaluate best 3B-class model for Turkish + router use case.

This module provides:
- Model evaluation framework
- Router JSON compliance testing
- Turkish smalltalk quality scoring
- Latency and throughput measurement
- Markdown report generation
"""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional

import requests


# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_REPORT_PATH = str(
    Path(__file__).resolve().parent.parent / "artifacts" / "results" / "3b_benchmark.md"
)

# vLLM default endpoint
DEFAULT_VLLM_BASE = os.getenv("BANTZ_VLLM_BASE", "http://localhost:8001")


# ============================================================================
# CANDIDATE MODELS
# ============================================================================

@dataclass
class ModelCandidate:
    """A model candidate for evaluation."""
    
    name: str
    hf_id: str
    quantization: str = "awq"
    notes: str = ""
    
    # vLLM settings
    gpu_memory_utilization: float = 0.85
    max_model_len: int = 4096
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)


# Default candidates for evaluation
DEFAULT_CANDIDATES = [
    ModelCandidate(
        name="Qwen2.5-3B-AWQ",
        hf_id="Qwen/Qwen2.5-3B-Instruct-AWQ",
        quantization="awq",
        notes="Current default, good JSON compliance",
    ),
    ModelCandidate(
        name="Qwen2.5-3B-GGUF-Q4",
        hf_id="Qwen/Qwen2.5-3B-Instruct-GGUF",
        quantization="gguf-q4",
        notes="Smaller size, may trade quality",
    ),
    ModelCandidate(
        name="Qwen2.5-3B-GPTQ",
        hf_id="Qwen/Qwen2.5-3B-Instruct-GPTQ-Int4",
        quantization="gptq-int4",
        notes="Alternative quantization",
    ),
    ModelCandidate(
        name="Phi-3.5-mini-instruct",
        hf_id="microsoft/Phi-3.5-mini-instruct",
        quantization="fp16",
        notes="Strong reasoning, may need quantization",
    ),
    ModelCandidate(
        name="Gemma-2-2B-Instruct",
        hf_id="google/gemma-2-2b-it",
        quantization="fp16",
        notes="Smaller but efficient",
    ),
]


# ============================================================================
# TEST CASES
# ============================================================================

@dataclass
class RouterTestCase:
    """Test case for router JSON compliance."""
    
    user_text: str
    expected_route: str
    expected_intent: Optional[str] = None
    expected_slots: Optional[dict] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class SmalltalkTestCase:
    """Test case for Turkish smalltalk quality."""
    
    user_text: str
    expected_keywords: List[str] = field(default_factory=list)
    min_length: int = 10
    max_length: int = 500
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)


# Router test cases
ROUTER_TEST_CASES = [
    RouterTestCase(
        user_text="saat kaç",
        expected_route="system",
        expected_intent="time",
    ),
    RouterTestCase(
        user_text="yarın toplantım var mı",
        expected_route="calendar",
        expected_intent="query",
    ),
    RouterTestCase(
        user_text="yarın saat 3'te toplantı ekle",
        expected_route="calendar",
        expected_intent="create",
        expected_slots={"time": "15:00"},
    ),
    RouterTestCase(
        user_text="son mailimi oku",
        expected_route="gmail",
        expected_intent="read",
    ),
    RouterTestCase(
        user_text="ahmet beye mail at",
        expected_route="gmail",
        expected_intent="send",
    ),
    RouterTestCase(
        user_text="merhaba nasılsın",
        expected_route="smalltalk",
    ),
    RouterTestCase(
        user_text="teşekkür ederim",
        expected_route="smalltalk",
    ),
    RouterTestCase(
        user_text="cpu kullanımı ne",
        expected_route="system",
        expected_intent="status",
    ),
    RouterTestCase(
        user_text="bugün hava nasıl",
        expected_route="weather",
    ),
    RouterTestCase(
        user_text="not defteri aç",
        expected_route="system",
        expected_intent="open_app",
    ),
]

# Smalltalk test cases
SMALLTALK_TEST_CASES = [
    SmalltalkTestCase(
        user_text="merhaba",
        expected_keywords=["merhaba", "selam", "hoş geldin", "günaydın", "iyi"],
    ),
    SmalltalkTestCase(
        user_text="nasılsın",
        expected_keywords=["iyi", "teşekkür", "siz", "nasıl", "yardım"],
    ),
    SmalltalkTestCase(
        user_text="iyi geceler",
        expected_keywords=["iyi", "gece", "görüşürüz", "dinlen", "uyku"],
    ),
    SmalltalkTestCase(
        user_text="teşekkür ederim çok yardımcı oldun",
        expected_keywords=["rica", "teşekkür", "yardım", "memnun", "seve"],
    ),
    SmalltalkTestCase(
        user_text="bugün çok yorgunum",
        expected_keywords=["dinlen", "anlıyorum", "geçmiş", "yardım", "olsun"],
    ),
]


# ============================================================================
# ROUTER PROMPT
# ============================================================================

ROUTER_SYSTEM_PROMPT = """Sen Jarvis, akıllı bir asistansın. Kullanıcının isteğini analiz et ve JSON formatında yanıt ver.

Çıktı formatı:
{
  "route": "calendar | gmail | system | smalltalk | weather | unknown",
  "intent": "amaç (query, create, send, read, status, open_app, greeting, etc)",
  "slots": {"slot_key": "value"},
  "confidence": 0.0-1.0,
  "assistant_reply": "smalltalk için doğrudan cevap"
}

Kurallar:
1. JSON formatında yanıt ver, başka metin ekleme
2. route mutlaka belirt
3. smalltalk için assistant_reply dolu olmalı
4. Slot değerlerini metinden çıkar (saat, tarih, isim vb)"""


# ============================================================================
# BENCHMARK RESULTS
# ============================================================================

@dataclass
class RouterResult:
    """Result of a single router test."""
    
    test_case: RouterTestCase
    raw_output: str
    parsed_output: Optional[dict] = None
    parse_success: bool = False
    route_correct: bool = False
    intent_correct: bool = False
    slots_correct: bool = False
    latency_ms: float = 0.0
    tokens_generated: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "user_text": self.test_case.user_text,
            "expected_route": self.test_case.expected_route,
            "parsed_output": self.parsed_output,
            "parse_success": self.parse_success,
            "route_correct": self.route_correct,
            "latency_ms": self.latency_ms,
        }


@dataclass
class SmalltalkResult:
    """Result of a single smalltalk test."""
    
    test_case: SmalltalkTestCase
    response: str
    keyword_hits: int = 0
    length_ok: bool = False
    quality_score: float = 0.0  # 0-1
    latency_ms: float = 0.0
    tokens_generated: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "user_text": self.test_case.user_text,
            "response": self.response[:100] + "..." if len(self.response) > 100 else self.response,
            "quality_score": self.quality_score,
            "latency_ms": self.latency_ms,
        }


@dataclass
class ModelBenchmarkResult:
    """Complete benchmark result for a model."""
    
    model: ModelCandidate
    
    # Router metrics
    router_results: List[RouterResult] = field(default_factory=list)
    json_compliance_rate: float = 0.0
    route_accuracy: float = 0.0
    intent_accuracy: float = 0.0
    
    # Smalltalk metrics
    smalltalk_results: List[SmalltalkResult] = field(default_factory=list)
    smalltalk_quality: float = 0.0
    
    # Latency metrics
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    avg_tokens_per_sec: float = 0.0
    
    # Overall
    overall_score: float = 0.0
    notes: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "model": self.model.to_dict(),
            "json_compliance_rate": self.json_compliance_rate,
            "route_accuracy": self.route_accuracy,
            "intent_accuracy": self.intent_accuracy,
            "smalltalk_quality": self.smalltalk_quality,
            "avg_latency_ms": self.avg_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "avg_tokens_per_sec": self.avg_tokens_per_sec,
            "overall_score": self.overall_score,
        }


# ============================================================================
# BENCHMARK ENGINE
# ============================================================================

class ModelBenchmark:
    """Benchmark engine for 3B models."""
    
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
    
    def _call_vllm(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 512,
        temperature: float = 0.1,
    ) -> tuple[str, float, int]:
        """Call vLLM API.
        
        Returns:
            (response_text, latency_ms, tokens_generated)
        """
        url = f"{self.vllm_base}/v1/chat/completions"
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        start = time.perf_counter()
        resp = requests.post(url, json=payload, timeout=self.timeout)
        latency_ms = (time.perf_counter() - start) * 1000
        
        resp.raise_for_status()
        data = resp.json()
        
        text = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("completion_tokens", len(text.split()))
        
        return text, latency_ms, tokens
    
    def _parse_json(self, text: str) -> Optional[dict]:
        """Try to parse JSON from response."""
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # Try to extract JSON block
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        
        # Try nested JSON
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        
        return None
    
    def run_router_tests(
        self,
        test_cases: List[RouterTestCase] = None,
    ) -> List[RouterResult]:
        """Run router compliance tests.
        
        Args:
            test_cases: Test cases (default: ROUTER_TEST_CASES)
            
        Returns:
            List of RouterResult
        """
        test_cases = test_cases or ROUTER_TEST_CASES
        results = []
        
        for tc in test_cases:
            try:
                text, latency, tokens = self._call_vllm(
                    prompt=tc.user_text,
                    system_prompt=ROUTER_SYSTEM_PROMPT,
                    max_tokens=256,
                    temperature=0.1,
                )
                
                parsed = self._parse_json(text)
                
                result = RouterResult(
                    test_case=tc,
                    raw_output=text,
                    parsed_output=parsed,
                    parse_success=parsed is not None,
                    latency_ms=latency,
                    tokens_generated=tokens,
                )
                
                if parsed:
                    result.route_correct = parsed.get("route") == tc.expected_route
                    if tc.expected_intent:
                        result.intent_correct = parsed.get("intent") == tc.expected_intent
                    else:
                        result.intent_correct = True  # No expectation
                    
                    # Slots check (partial)
                    if tc.expected_slots:
                        slots = parsed.get("slots", {})
                        result.slots_correct = all(
                            k in slots for k in tc.expected_slots
                        )
                    else:
                        result.slots_correct = True
                
                results.append(result)
                
            except Exception as e:
                results.append(RouterResult(
                    test_case=tc,
                    raw_output=str(e),
                    parse_success=False,
                ))
        
        return results
    
    def run_smalltalk_tests(
        self,
        test_cases: List[SmalltalkTestCase] = None,
    ) -> List[SmalltalkResult]:
        """Run Turkish smalltalk quality tests.
        
        Args:
            test_cases: Test cases (default: SMALLTALK_TEST_CASES)
            
        Returns:
            List of SmalltalkResult
        """
        test_cases = test_cases or SMALLTALK_TEST_CASES
        results = []
        
        for tc in test_cases:
            try:
                text, latency, tokens = self._call_vllm(
                    prompt=tc.user_text,
                    system_prompt="Sen Jarvis, nazik ve yardımsever bir asistansın. Türkçe cevap ver.",
                    max_tokens=200,
                    temperature=0.7,
                )
                
                # Score quality
                response_lower = text.lower()
                keyword_hits = sum(
                    1 for kw in tc.expected_keywords 
                    if kw.lower() in response_lower
                )
                
                length_ok = tc.min_length <= len(text) <= tc.max_length
                
                # Quality score: keyword match + length + fluency heuristic
                keyword_score = keyword_hits / len(tc.expected_keywords) if tc.expected_keywords else 0.5
                length_score = 1.0 if length_ok else 0.5
                
                # Basic fluency: has Turkish chars, proper punctuation
                has_turkish = any(c in text for c in "çğıöşüÇĞİÖŞÜ")
                has_punctuation = any(c in text for c in ".,!?")
                fluency_score = 0.5 + (0.25 if has_turkish else 0) + (0.25 if has_punctuation else 0)
                
                quality_score = (keyword_score + length_score + fluency_score) / 3
                
                results.append(SmalltalkResult(
                    test_case=tc,
                    response=text,
                    keyword_hits=keyword_hits,
                    length_ok=length_ok,
                    quality_score=quality_score,
                    latency_ms=latency,
                    tokens_generated=tokens,
                ))
                
            except Exception as e:
                results.append(SmalltalkResult(
                    test_case=tc,
                    response=str(e),
                    quality_score=0.0,
                ))
        
        return results
    
    def run_benchmark(
        self,
        model: ModelCandidate,
    ) -> ModelBenchmarkResult:
        """Run full benchmark for a model.
        
        Note: This assumes the model is already loaded in vLLM.
        
        Args:
            model: Model candidate info
            
        Returns:
            ModelBenchmarkResult
        """
        result = ModelBenchmarkResult(model=model)
        
        # Run router tests
        result.router_results = self.run_router_tests()
        
        if result.router_results:
            parse_ok = [r for r in result.router_results if r.parse_success]
            route_ok = [r for r in result.router_results if r.route_correct]
            intent_ok = [r for r in result.router_results if r.intent_correct]
            
            result.json_compliance_rate = len(parse_ok) / len(result.router_results)
            result.route_accuracy = len(route_ok) / len(result.router_results)
            result.intent_accuracy = len(intent_ok) / len(result.router_results)
        
        # Run smalltalk tests
        result.smalltalk_results = self.run_smalltalk_tests()
        
        if result.smalltalk_results:
            result.smalltalk_quality = statistics.mean(
                r.quality_score for r in result.smalltalk_results
            )
        
        # Calculate latency metrics
        all_latencies = [
            r.latency_ms for r in result.router_results + result.smalltalk_results
            if r.latency_ms > 0
        ]
        all_tokens = [
            r.tokens_generated for r in result.router_results + result.smalltalk_results
            if r.tokens_generated > 0
        ]
        
        if all_latencies:
            result.avg_latency_ms = statistics.mean(all_latencies)
            sorted_lat = sorted(all_latencies)
            idx = int(len(sorted_lat) * 0.95)
            result.p95_latency_ms = sorted_lat[min(idx, len(sorted_lat) - 1)]
        
        if all_tokens and all_latencies:
            total_tokens = sum(all_tokens)
            total_time_s = sum(all_latencies) / 1000
            if total_time_s > 0:
                result.avg_tokens_per_sec = total_tokens / total_time_s
        
        # Overall score (weighted)
        # 40% JSON compliance, 30% route accuracy, 20% smalltalk, 10% speed
        speed_score = min(1.0, 50 / result.avg_latency_ms) if result.avg_latency_ms > 0 else 0
        result.overall_score = (
            0.40 * result.json_compliance_rate +
            0.30 * result.route_accuracy +
            0.20 * result.smalltalk_quality +
            0.10 * speed_score
        )
        
        return result


# ============================================================================
# REPORT GENERATION
# ============================================================================

def generate_report(
    results: List[ModelBenchmarkResult],
    output_path: str = DEFAULT_REPORT_PATH,
) -> str:
    """Generate markdown benchmark report.
    
    Args:
        results: List of benchmark results
        output_path: Path to write report
        
    Returns:
        Markdown report string
    """
    lines = [
        "# 3B Model Benchmark Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Summary",
        "",
        "| Model | JSON Compliance | Route Accuracy | Smalltalk | Latency (ms) | tok/s | Overall |",
        "|-------|-----------------|----------------|-----------|--------------|-------|---------|",
    ]
    
    # Sort by overall score
    sorted_results = sorted(results, key=lambda r: r.overall_score, reverse=True)
    
    for r in sorted_results:
        lines.append(
            f"| {r.model.name} | {r.json_compliance_rate*100:.0f}% | "
            f"{r.route_accuracy*100:.0f}% | {r.smalltalk_quality*100:.0f}% | "
            f"{r.avg_latency_ms:.0f} | {r.avg_tokens_per_sec:.0f} | "
            f"**{r.overall_score*100:.0f}%** |"
        )
    
    lines.extend([
        "",
        "## Recommendation",
        "",
    ])
    
    if sorted_results:
        best = sorted_results[0]
        lines.append(f"**Recommended Model:** {best.model.name}")
        lines.append(f"- HuggingFace ID: `{best.model.hf_id}`")
        lines.append(f"- Quantization: {best.model.quantization}")
        lines.append(f"- Notes: {best.model.notes}")
        lines.append("")
        lines.append("**Recommended vLLM Flags:**")
        lines.append("```bash")
        lines.append(f"--model {best.model.hf_id} \\")
        lines.append(f"--quantization {best.model.quantization} \\")
        lines.append(f"--gpu-memory-utilization {best.model.gpu_memory_utilization} \\")
        lines.append(f"--max-model-len {best.model.max_model_len}")
        lines.append("```")
    
    # Detailed results
    lines.extend([
        "",
        "## Detailed Results",
        "",
    ])
    
    for r in sorted_results:
        lines.extend([
            f"### {r.model.name}",
            "",
            f"**JSON Compliance:** {r.json_compliance_rate*100:.1f}%",
            f"**Route Accuracy:** {r.route_accuracy*100:.1f}%",
            f"**Intent Accuracy:** {r.intent_accuracy*100:.1f}%",
            f"**Smalltalk Quality:** {r.smalltalk_quality*100:.1f}%",
            "",
            f"**Latency:** avg={r.avg_latency_ms:.0f}ms, p95={r.p95_latency_ms:.0f}ms",
            f"**Throughput:** {r.avg_tokens_per_sec:.0f} tok/s",
            "",
        ])
        
        # Router test details
        if r.router_results:
            lines.append("**Router Tests:**")
            for rr in r.router_results:
                status = "✅" if rr.route_correct else "❌"
                lines.append(f"- {status} `{rr.test_case.user_text}` → {rr.parsed_output.get('route', 'N/A') if rr.parsed_output else 'PARSE_FAIL'}")
            lines.append("")
    
    report = "\n".join(lines)
    
    # Write to file
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    
    return report


# ============================================================================
# MOCK BENCHMARK (for testing without vLLM)
# ============================================================================

def run_mock_benchmark() -> List[ModelBenchmarkResult]:
    """Run mock benchmark for testing.
    
    Returns simulated results without actually calling vLLM.
    """
    results = []
    
    # Simulate results for candidates
    mock_scores = [
        (DEFAULT_CANDIDATES[0], 0.95, 0.90, 0.85, 45, 120),  # Qwen - best
        (DEFAULT_CANDIDATES[1] if len(DEFAULT_CANDIDATES) > 1 else DEFAULT_CANDIDATES[0], 
         0.88, 0.82, 0.80, 50, 100),
        (DEFAULT_CANDIDATES[2] if len(DEFAULT_CANDIDATES) > 2 else DEFAULT_CANDIDATES[0],
         0.90, 0.85, 0.75, 48, 110),
    ]
    
    for model, json_rate, route_acc, smalltalk, latency, toks in mock_scores:
        result = ModelBenchmarkResult(
            model=model,
            json_compliance_rate=json_rate,
            route_accuracy=route_acc,
            intent_accuracy=route_acc * 0.9,
            smalltalk_quality=smalltalk,
            avg_latency_ms=latency,
            p95_latency_ms=latency * 1.5,
            avg_tokens_per_sec=toks,
        )
        
        # Calculate overall score
        speed_score = min(1.0, 50 / latency) if latency > 0 else 0
        result.overall_score = (
            0.40 * json_rate +
            0.30 * route_acc +
            0.20 * smalltalk +
            0.10 * speed_score
        )
        
        results.append(result)
    
    return results
