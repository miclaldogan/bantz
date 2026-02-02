"""Real-time TTFT Demo with Streaming UI (Issue #158).

Interactive demo showing:
- Real-time streaming with TTFT display
- Color-coded performance indicators
- Live dashboard overlay
- "Jarvis feel" UX experience
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bantz.llm.vllm_openai_client import VLLMOpenAIClient
from bantz.llm.ttft_monitor import TTFTMonitor
from bantz.llm.base import LLMMessage

# ANSI color codes
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    # TTFT indicators
    GREEN = "\033[92m"   # < 300ms: Excellent
    YELLOW = "\033[93m"  # 300-500ms: Good
    RED = "\033[91m"     # > 500ms: Needs improvement
    
    # UI elements
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    BLUE = "\033[94m"


def color_ttft(ttft_ms: int, phase: str = "router") -> str:
    """Color-code TTFT based on thresholds."""
    
    if phase == "router":
        threshold = 300
    else:
        threshold = 500
    
    if ttft_ms < threshold:
        return Colors.GREEN
    elif ttft_ms < threshold * 1.5:
        return Colors.YELLOW
    else:
        return Colors.RED


def print_dashboard_header():
    """Print dashboard header."""
    
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  TTFT Real-Time Monitoring Demo{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}  Issue #158: Epic LLM-4 - TTFT Monitoring & Optimization{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.RESET}\n")


def print_thinking_indicator(ttft_ms: Optional[int] = None):
    """Print thinking indicator with optional TTFT."""
    
    if ttft_ms is None:
        print(f"{Colors.DIM}[THINKING...]{Colors.RESET}", end="", flush=True)
    else:
        color = color_ttft(ttft_ms)
        print(f"\r{Colors.BOLD}[THINKING]{Colors.RESET} {color}(TTFT: {ttft_ms}ms){Colors.RESET} ", end="", flush=True)


def print_response_stream(client: VLLMOpenAIClient, prompt: str, phase: str = "router"):
    """Print streaming response with real-time TTFT."""
    
    print(f"\n{Colors.BLUE}→ You:{Colors.RESET} {prompt}")
    
    messages = [LLMMessage(role="user", content=prompt)]
    
    # Show thinking indicator
    print_thinking_indicator()
    
    response_parts = []
    ttft_ms = None
    t0 = time.perf_counter()
    
    try:
        for chunk in client.chat_stream(messages, temperature=0.7, max_tokens=256):
            # Update TTFT on first token
            if chunk.is_first_token and chunk.ttft_ms is not None:
                ttft_ms = chunk.ttft_ms
                print_thinking_indicator(ttft_ms)
                print("\n")  # New line after thinking indicator
            
            # Print token content
            print(chunk.content, end="", flush=True)
            response_parts.append(chunk.content)
        
        total_ms = int((time.perf_counter() - t0) * 1000)
        
        # Print timing summary
        print(f"\n\n{Colors.DIM}  ⏱️  TTFT: {ttft_ms}ms | Total: {total_ms}ms | Tokens: {len(response_parts)}{Colors.RESET}")
        
    except Exception as e:
        print(f"\n{Colors.RED}[ERROR]{Colors.RESET} {e}")


def interactive_mode(client: VLLMOpenAIClient, phase: str = "router"):
    """Interactive prompt mode."""
    
    print_dashboard_header()
    
    print(f"{Colors.BOLD}Interactive Mode{Colors.RESET}")
    print(f"  • Type your messages and see real-time TTFT")
    print(f"  • Color indicators: {Colors.GREEN}Green (<300ms){Colors.RESET}, {Colors.YELLOW}Yellow (300-500ms){Colors.RESET}, {Colors.RED}Red (>500ms){Colors.RESET}")
    print(f"  • Type 'quit' or 'exit' to finish")
    print(f"  • Type 'stats' to see TTFT statistics")
    
    monitor = TTFTMonitor.get_instance()
    
    while True:
        print(f"\n{Colors.MAGENTA}{'─'*80}{Colors.RESET}")
        try:
            user_input = input(f"{Colors.BOLD}Your message:{Colors.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        
        if not user_input:
            continue
        
        if user_input.lower() in ["quit", "exit", "q"]:
            break
        
        if user_input.lower() == "stats":
            monitor.print_summary()
            continue
        
        print_response_stream(client, user_input, phase)
    
    # Final statistics
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}Session Summary{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.RESET}")
    monitor.print_summary()


def demo_mode(client: VLLMOpenAIClient, phase: str = "router"):
    """Demo mode with predefined prompts."""
    
    print_dashboard_header()
    
    print(f"{Colors.BOLD}Demo Mode{Colors.RESET}")
    print(f"  • Running predefined prompts to show TTFT monitoring")
    print(f"  • Watch the real-time streaming and TTFT indicators")
    
    demo_prompts = [
        "merhaba nasılsın",
        "bugün ne işlerim var",
        "bu hafta en yoğun gün hangisi",
        "yarın saat 2 için toplantı ayarla",
        "gelecek hafta boş saatlerim hangi günlerde",
    ]
    
    for i, prompt in enumerate(demo_prompts, start=1):
        print(f"\n{Colors.MAGENTA}{'─'*80}{Colors.RESET}")
        print(f"{Colors.BOLD}Demo {i}/{len(demo_prompts)}{Colors.RESET}")
        
        print_response_stream(client, prompt, phase)
        
        # Pause between demos
        if i < len(demo_prompts):
            time.sleep(2)
    
    # Final statistics
    monitor = TTFTMonitor.get_instance()
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}Demo Summary{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*80}{Colors.RESET}")
    monitor.print_summary()


def main():
    parser = argparse.ArgumentParser(description="Real-time TTFT Monitoring Demo")
    parser.add_argument(
        "--url",
        default=os.getenv("BANTZ_VLLM_URL", "http://localhost:8001"),
        help="vLLM server URL",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("BANTZ_VLLM_MODEL", "Qwen/Qwen2.5-3B-Instruct"),
        help="Model name",
    )
    parser.add_argument(
        "--phase",
        default="router",
        choices=["router", "finalizer"],
        help="Phase name for TTFT tracking",
    )
    parser.add_argument(
        "--mode",
        default="interactive",
        choices=["interactive", "demo"],
        help="Mode: interactive prompts or demo with predefined prompts",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        help="TTFT p95 threshold in ms (default: 300 for router, 500 for finalizer)",
    )
    
    args = parser.parse_args()
    
    # Set threshold
    if args.threshold:
        threshold_ms = args.threshold
    else:
        threshold_ms = 300 if args.phase == "router" else 500
    
    # Initialize TTFT monitor
    monitor = TTFTMonitor.get_instance()
    monitor.set_threshold(args.phase, threshold_ms)
    
    # Create client
    client = VLLMOpenAIClient(
        base_url=args.url,
        model=args.model,
        track_ttft=True,
        ttft_phase=args.phase,
    )
    
    # Check availability
    if not client.is_available():
        print(f"{Colors.RED}❌ vLLM server not available: {args.url}{Colors.RESET}")
        sys.exit(1)
    
    print(f"{Colors.GREEN}✅ vLLM server available{Colors.RESET}")
    print(f"{Colors.DIM}   URL: {args.url}{Colors.RESET}")
    print(f"{Colors.DIM}   Model: {args.model}{Colors.RESET}")
    print(f"{Colors.DIM}   Phase: {args.phase}{Colors.RESET}")
    print(f"{Colors.DIM}   Threshold: {threshold_ms}ms (p95){Colors.RESET}")
    
    # Run mode
    if args.mode == "interactive":
        interactive_mode(client, args.phase)
    else:
        demo_mode(client, args.phase)


if __name__ == "__main__":
    main()
