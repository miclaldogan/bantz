#!/usr/bin/env python3
"""Bantz Demo — automated demo flow (Issue #665).

Runs various scenarios sequentially when the system is ready
and prints formatted results to the terminal.

Usage:
    python scripts/demo.py
    python scripts/demo.py --no-color
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Optional


# ── Terminal colors ──────────────────────────────────────────
class _Colors:
    CYAN = "\033[0;36m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    RED = "\033[0;31m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    NC = "\033[0m"


_NO_COLOR = _Colors()
for attr in vars(_NO_COLOR):
    if not attr.startswith("_"):
        setattr(_NO_COLOR, attr, "")


def _box(title: str, c: _Colors) -> None:
    w = max(len(title) + 4, 44)
    print(f"\n{c.CYAN}╔{'═' * w}╗{c.NC}")
    print(f"{c.CYAN}║  {title}{' ' * (w - len(title) - 2)}║{c.NC}")
    print(f"{c.CYAN}╚{'═' * w}╝{c.NC}\n")


def _step(n: int, label: str, c: _Colors) -> None:
    print(f"  {c.BOLD}[{n}]{c.NC} {label}")


def _result(text: str, latency_ms: float, c: _Colors) -> None:
    print(f"      {c.GREEN}→{c.NC} {text}")
    print(f"      {c.DIM}⏱  {latency_ms:.0f} ms{c.NC}\n")


def _error(text: str, c: _Colors) -> None:
    print(f"      {c.RED}✗ {text}{c.NC}\n")


# ── Demo scenarios ───────────────────────────────────────────
def _run_query(query: str) -> tuple[Optional[str], float]:
    """Run a single query through the orchestrator and return (reply, latency_ms)."""
    try:
        from bantz.brain.orchestrator_loop import OrchestratorLoop, OrchestratorConfig
        from bantz.llm import create_llm_from_env
    except ImportError as e:
        return f"[Import error: {e}]", 0.0

    try:
        llm = create_llm_from_env()
        cfg = OrchestratorConfig()
        orch = OrchestratorLoop(llm=llm, config=cfg)

        t0 = time.perf_counter()
        output = orch.run(query)
        elapsed = (time.perf_counter() - t0) * 1000

        reply = getattr(output, "assistant_reply", None) or str(output)
        return reply, elapsed
    except Exception as e:
        return f"[Error: {e}]", 0.0


DEMO_SCENARIOS = [
    ("Merhaba!", "Selamlama testi"),
    ("Saat kaç?", "Sistem tool testi (time.now)"),
    ("Bugün takvimde ne var?", "Takvim sorgusu"),
    ("Okunmamış kaç mail var?", "Gmail sorgusu"),
    ("Teşekkürler!", "Teşekkür testi"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Bantz Demo")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    args = parser.parse_args()

    c = _NO_COLOR if args.no_color else _Colors()

    _box("🚀 BANTZ Demo", c)

    # Ön kontrol: vLLM erişimi
    print(f"  {c.DIM}System initializing...{c.NC}")
    try:
        from bantz.llm import create_llm_from_env
        llm = create_llm_from_env()
        print(f"  {c.GREEN}✓{c.NC} LLM connection ready\n")
    except Exception as e:
        print(f"  {c.RED}✗{c.NC} LLM connection error: {e}")
        print(f"\n  {c.YELLOW}💡 Start vLLM first:{c.NC}")
        print(f"     docker compose up -d")
        print(f"     # or: vllm serve Qwen/Qwen2.5-3B-Instruct-AWQ --port 8001\n")
        return 1

    latencies: list[float] = []

    for i, (query, desc) in enumerate(DEMO_SCENARIOS, 1):
        _step(i, f"{desc}: {c.YELLOW}\"{query}\"{c.NC}", c)
        reply, ms = _run_query(query)
        if reply and not reply.startswith("[Error"):
            _result(reply[:200], ms, c)
            latencies.append(ms)
        else:
            _error(str(reply), c)

    # Results report
    _box("📊 Latency Report", c)
    if latencies:
        avg = sum(latencies) / len(latencies)
        p50 = sorted(latencies)[len(latencies) // 2]
        mx = max(latencies)
        print(f"  Successful: {len(latencies)}/{len(DEMO_SCENARIOS)}")
        print(f"  Average:    {avg:.0f} ms")
        print(f"  Median:     {p50:.0f} ms")
        print(f"  Maximum:    {mx:.0f} ms")
    else:
        print(f"  {c.RED}No scenario succeeded.{c.NC}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
