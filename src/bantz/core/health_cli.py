"""CLI for ``bantz health`` subcommand (Issue #1298).

Runs live health checks against all monitored services and
displays a formatted report. Optionally outputs JSON or
checks a single service.

Usage:
    bantz health                   # Full health report
    bantz health --json            # JSON output
    bantz health --service ollama  # Single service check
    bantz health --cb              # Include circuit breaker states
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import List

from bantz.core.health_monitor import (
    HealthMonitor,
    ServiceStatus,
    get_health_monitor,
    reset_health_monitor,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bantz health",
        description="Live service health checks with circuit breaker & fallback status",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output health report as JSON",
    )
    parser.add_argument(
        "--service",
        default=None,
        metavar="NAME",
        help="Check a single service (e.g. ollama, sqlite, google)",
    )
    parser.add_argument(
        "--cb",
        action="store_true",
        help="Include circuit breaker states in the report",
    )
    parser.add_argument(
        "--fallback",
        action="store_true",
        help="Include fallback registry configurations",
    )
    return parser


def _run_checks(monitor: HealthMonitor, service: str | None = None):
    """Run health checks synchronously."""
    loop = asyncio.new_event_loop()
    try:
        if service:
            result = loop.run_until_complete(monitor.check_service(service))
            # Wrap single service in a report-like structure
            from bantz.core.health_monitor import HealthReport
            report = HealthReport(
                checks={service: result},
                overall=result.status,
            )
            return report
        else:
            return loop.run_until_complete(monitor.check_all())
    finally:
        loop.close()


def _format_cb_section() -> str:
    """Format circuit breaker states for display."""
    try:
        from bantz.agent.circuit_breaker import get_circuit_breaker
        cb = get_circuit_breaker()
        states = cb.to_dict()
        if not states:
            return "\n⚡ Circuit Breaker: No tracked domains"
        lines = ["\n⚡ Circuit Breaker States:"]
        for domain, info in sorted(states.items()):
            state = info["state"]
            icon = {"closed": "🟢", "open": "🔴", "half_open": "🟡"}.get(state, "⚪")
            detail = f"failures={info['failures']}"
            if info.get("opened_at"):
                detail += f", opened_at={info['opened_at']}"
            lines.append(f"  {icon} {domain:<16} {state:<10} {detail}")
        return "\n".join(lines)
    except Exception as exc:
        return f"\n⚡ Circuit Breaker: unavailable ({exc})"


def _format_fallback_section() -> str:
    """Format fallback registry configurations for display."""
    try:
        from bantz.core.fallback_registry import get_fallback_registry
        registry = get_fallback_registry()
        configs = registry.to_dict()
        if not configs:
            return "\n🔄 Fallback Registry: No configurations"
        lines = ["\n🔄 Fallback Registry:"]
        for service, config in sorted(configs.items()):
            strategy = config["strategy"]
            message = config["message"]
            lines.append(f"  • {service:<16} → {strategy}")
            lines.append(f"    {message}")
        return "\n".join(lines)
    except Exception as exc:
        return f"\n🔄 Fallback Registry: unavailable ({exc})"


def main(argv: List[str] | None = None) -> int:
    """Entry point for ``bantz health``."""
    parser = _build_parser()
    args = parser.parse_args(argv or [])

    # Ensure a fresh monitor with default checks
    reset_health_monitor()
    monitor = get_health_monitor()

    try:
        report = _run_checks(monitor, service=args.service)
    except Exception as exc:
        print(f"❌ Health check failed: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        data = report.to_dict()
        if args.cb:
            try:
                from bantz.agent.circuit_breaker import get_circuit_breaker
                data["circuit_breaker"] = get_circuit_breaker().to_dict()
            except Exception:
                pass
        if args.fallback:
            try:
                from bantz.core.fallback_registry import get_fallback_registry
                data["fallback"] = get_fallback_registry().to_dict()
            except Exception:
                pass
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(monitor.format_report(report))
        if args.cb:
            print(_format_cb_section())
        if args.fallback:
            print(_format_fallback_section())

    return 0 if report.overall == ServiceStatus.HEALTHY else 1
