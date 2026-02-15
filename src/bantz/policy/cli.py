"""CLI subcommand for Policy Engine v2 — info & preset management (Issue #1291).

Usage::

    bantz policy info                       # Show current preset, risk map stats
    bantz policy preset                     # Show current preset
    bantz policy preset balanced            # Switch to balanced preset
    bantz policy preset autopilot           # Switch to autopilot preset
    bantz policy risk <tool_name>           # Show risk tier for a tool
    bantz policy audit [--last N]           # Show recent policy audit entries
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


def _get_engine():
    """Create a PolicyEngineV2 instance for CLI inspection."""
    from bantz.policy.engine_v2 import PolicyEngineV2

    return PolicyEngineV2()


def _cmd_info(args: argparse.Namespace) -> int:
    """Show policy engine info."""
    engine = _get_engine()
    info = engine.to_dict()
    print("Policy Engine v2")
    print(f"  Preset         : {info['preset']}")
    print(f"  Risk map       : {info['risk_map_size']} tools")
    print(f"  Redact fields  : {info['redact_fields_count']} tools")
    print(f"  Editable fields: {info['editable_fields_count']} tools")
    return 0


def _cmd_preset(args: argparse.Namespace) -> int:
    """Show or set current preset."""
    from bantz.policy.engine_v2 import PolicyPreset

    engine = _get_engine()

    if not args.preset_name:
        print(f"Current preset: {engine.preset.value}")
        print("\nAvailable presets:")
        for p in PolicyPreset:
            marker = " ← active" if p == engine.preset else ""
            desc = {
                "paranoid": "confirm everything (LOW included)",
                "balanced": "LOW auto, MED confirm, HIGH confirm+edit",
                "autopilot": "never confirm (test/demo mode)",
            }.get(p.value, "")
            print(f"  {p.value:12s}  {desc}{marker}")
        print(
            "\nTo change: set BANTZ_POLICY_PRESET env var or run:\n"
            "  bantz policy preset <name>"
        )
        return 0

    name = args.preset_name.lower().strip()
    valid = {p.value for p in PolicyPreset}
    if name not in valid:
        print(f"Error: unknown preset '{name}'. Valid: {', '.join(sorted(valid))}")
        return 1

    # Show what this preset does
    preset = PolicyPreset(name)
    print(f"Preset: {preset.value}")
    print(
        "\nTo apply at runtime, set the environment variable:\n"
        f"  export BANTZ_POLICY_PRESET={preset.value}\n"
        "\nor restart bantz with the preset active."
    )
    return 0


def _cmd_risk(args: argparse.Namespace) -> int:
    """Show risk tier for a tool."""
    engine = _get_engine()
    tool_name = args.tool_name
    tier = engine.get_risk_tier(tool_name)

    desc = {
        "LOW": "auto-execute (read-only)",
        "MED": "confirm once per session (write/modify)",
        "HIGH": "confirm every time + param edit (destructive/send)",
    }

    print(f"Tool : {tool_name}")
    print(f"Tier : {tier.value} — {desc.get(tier.value, '')}")

    # Show redact fields
    redact = engine.get_redact_fields(tool_name)
    tool_redact = redact - set()  # copy
    if tool_redact:
        print(f"Redact: {', '.join(sorted(tool_redact))}")

    # Show editable fields
    editable = engine._editable_fields.get(tool_name, [])
    if editable:
        print(f"Edit  : {', '.join(editable)}")

    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    """Show recent policy audit entries."""
    try:
        from bantz.brain.safety_guard import SafetyGuard

        guard = SafetyGuard()
        entries = guard.query_audit(
            last_days=args.last,
            limit=args.limit,
        )
        if not entries:
            print("No audit entries found.")
            return 0

        for entry in entries:
            ts = entry.get("timestamp", "?")
            action = entry.get("action", "?")
            resource = entry.get("resource", "?")
            outcome = entry.get("outcome", "?")
            print(f"  {ts}  {action:30s}  {resource:30s}  {outcome}")

        print(f"\n{len(entries)} entries (last {args.last} days)")
        return 0
    except Exception as exc:
        print(f"Audit query failed: {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``bantz policy`` subcommand."""
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="bantz policy",
        description="Policy Engine v2 — inspect and manage risk tiers & presets",
    )
    sub = parser.add_subparsers(dest="action")

    # info
    sub.add_parser("info", help="Show policy engine info")

    # preset
    preset_p = sub.add_parser("preset", help="Show or set current preset")
    preset_p.add_argument("preset_name", nargs="?", default="", help="Preset name")

    # risk
    risk_p = sub.add_parser("risk", help="Show risk tier for a tool")
    risk_p.add_argument("tool_name", help="Fully qualified tool name")

    # audit
    audit_p = sub.add_parser("audit", help="Show recent policy audit entries")
    audit_p.add_argument("--last", type=int, default=7, help="Last N days (default: 7)")
    audit_p.add_argument("--limit", type=int, default=50, help="Max entries (default: 50)")

    args = parser.parse_args(argv)

    if not args.action:
        # Default to info
        return _cmd_info(args)

    dispatch = {
        "info": _cmd_info,
        "preset": _cmd_preset,
        "risk": _cmd_risk,
        "audit": _cmd_audit,
    }
    handler = dispatch.get(args.action)
    if handler:
        return handler(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
