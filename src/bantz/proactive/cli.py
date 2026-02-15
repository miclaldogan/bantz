"""CLI subcommands for the Proactive Intelligence Engine.

Provides ``bantz proactive {status,list,run,history,policy,dnd}`` commands
for managing and monitoring the proactive engine from the command line.

Usage::

    bantz proactive status           # Engine status
    bantz proactive list             # List all checks
    bantz proactive run <name>       # Manually trigger a check
    bantz proactive run --all        # Run all checks
    bantz proactive history [name]   # Recent check results
    bantz proactive policy           # Show notification policy
    bantz proactive dnd on/off       # Toggle Do Not Disturb
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional


def add_proactive_subparser(subparsers: Any) -> None:
    """Add 'proactive' subcommand to CLI parser."""
    p = subparsers.add_parser(
        "proactive",
        help="Proactive engine management",
        description="List, run proactive checks and manage notification policy.",
    )
    sub = p.add_subparsers(dest="proactive_action")
    sub.required = True

    # status
    status_p = sub.add_parser("status", help="Show engine status")
    status_p.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    # list
    list_p = sub.add_parser("list", help="List all proactive checks")
    list_p.add_argument("--json", action="store_true", dest="as_json", help="JSON output")

    # run
    run_p = sub.add_parser("run", help="Run a check")
    run_p.add_argument("name", nargs="?", default=None, help="Check name")
    run_p.add_argument("--all", action="store_true", help="Run all checks")

    # history
    hist_p = sub.add_parser("history", help="Show recent check results")
    hist_p.add_argument("name", nargs="?", default=None, help="Check name (optional)")
    hist_p.add_argument("-n", "--limit", type=int, default=10, help="Maximum number of results")

    # policy
    policy_p = sub.add_parser("policy", help="Show/set notification policy")
    policy_p.add_argument("--json", action="store_true", dest="as_json", help="JSON output")
    policy_p.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="Change policy setting")

    # dnd
    dnd_p = sub.add_parser("dnd", help="Toggle Do Not Disturb mode")
    dnd_p.add_argument("mode", choices=["on", "off"], help="on or off")

    # notifications
    notif_p = sub.add_parser("notifications", help="Show notifications")
    notif_p.add_argument("--unread", action="store_true", help="Unread only")
    notif_p.add_argument("--clear", action="store_true", help="Clear all")
    notif_p.add_argument("--json", action="store_true", dest="as_json", help="JSON output")


def handle_proactive_command(args: argparse.Namespace) -> int:
    """Handle 'bantz proactive <action>' commands."""
    action = getattr(args, "proactive_action", None)

    handlers = {
        "status": _cmd_status,
        "list": _cmd_list,
        "run": _cmd_run,
        "history": _cmd_history,
        "policy": _cmd_policy,
        "dnd": _cmd_dnd,
        "notifications": _cmd_notifications,
    }

    handler = handlers.get(action)
    if handler is None:
        print(f"Unknown command: {action}", file=sys.stderr)
        return 1

    return handler(args)


# ── Command Handlers ────────────────────────────────────────────


def _get_engine() -> Any:
    """Get or create a ProactiveEngine for CLI commands."""
    from bantz.proactive.engine import get_proactive_engine, ProactiveEngine

    engine = get_proactive_engine()
    if engine is not None:
        return engine

    # Create a standalone engine for CLI inspection (no auto-start)
    return ProactiveEngine()


def _cmd_status(args: argparse.Namespace) -> int:
    """Show engine status."""
    engine = _get_engine()
    status = engine.get_status()

    if getattr(args, "as_json", False):
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return 0

    running = "✅ Running" if status["running"] else "⏸️ Stopped"
    print(f"\n🧠 Proactive Engine — {running}")
    print(f"   Checks: {status['enabled_checks']}/{status['total_checks']} active")
    print(f"   Notification queue: {status['notification_queue_size']} notifications")
    print(f"   Unread: {status['unread_notifications']}")
    print(f"   DND: {'On' if status['dnd'] else 'Off'}")

    if status["checks"]:
        print(f"\n   {'Check':<25} {'Status':<10} {'Last Run':<20} {'Next':<20}")
        print(f"   {'─' * 75}")
        for c in status["checks"]:
            state = "✅" if c["enabled"] else "⏸️"
            last = c["last_run"][:16] if c["last_run"] else "-"
            nxt = c["next_run"][:16] if c["next_run"] else "-"
            print(f"   {c['name']:<25} {state:<10} {last:<20} {nxt:<20}")

    print()
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    """List all proactive checks."""
    engine = _get_engine()
    checks = engine.get_all_checks()

    if getattr(args, "as_json", False):
        print(json.dumps([c.to_dict() for c in checks], indent=2, ensure_ascii=False))
        return 0

    if not checks:
        print("\n📭 No registered proactive checks.\n")
        return 0

    print(f"\n🧠 Proactive Checks ({len(checks)} total):\n")
    for check in checks:
        state = "✅" if check.enabled else "⏸️"
        schedule_info = check.schedule.to_dict()
        stype = schedule_info.get("type", "?")

        schedule_desc = stype
        if tod := schedule_info.get("time_of_day"):
            schedule_desc = f"Daily at {tod}"
        elif interval := schedule_info.get("interval_seconds"):
            if interval >= 3600:
                schedule_desc = f"Every {interval // 3600} hours"
            else:
                schedule_desc = f"Every {interval // 60} minutes"
        elif event := schedule_info.get("event_type"):
            schedule_desc = f"Event: {event}"

        print(f"  {state} {check.name}")
        print(f"     {check.description}")
        print(f"     Schedule: {schedule_desc}")
        if check.required_tools:
            print(f"     Tools: {', '.join(check.required_tools)}")
        if check.tags:
            print(f"     Tags: {', '.join(check.tags)}")
        print()

    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    """Manually run a check."""
    engine = _get_engine()

    if getattr(args, "all", False):
        print("🔄 Tüm kontroller çalıştırılıyor...\n")
        results = engine.run_all_checks()
        for result in results:
            _print_result(result)
        print(f"\n✅ {len(results)} kontrol tamamlandı.\n")
        return 0

    name = getattr(args, "name", None)
    if not name:
        print("❌ Kontrol adı belirtin veya --all kullanın.", file=sys.stderr)
        return 1

    check = engine.get_check(name)
    if not check:
        print(f"❌ Kontrol bulunamadı: {name}", file=sys.stderr)
        available = [c.name for c in engine.get_all_checks()]
        if available:
            print(f"   Mevcut kontroller: {', '.join(available)}")
        return 1

    print(f"🔄 '{name}' çalıştırılıyor...\n")
    result = engine.run_check(name)
    if result:
        _print_result(result)
    return 0 if result and result.ok else 1


def _cmd_history(args: argparse.Namespace) -> int:
    """Show check history."""
    engine = _get_engine()
    name = getattr(args, "name", None)
    limit = getattr(args, "limit", 10)

    results = engine.get_history(check_name=name, limit=limit)

    if not results:
        print("\n📭 Henüz kontrol geçmişi yok.\n")
        return 0

    print(f"\n📋 Son Kontrol Sonuçları ({len(results)} adet):\n")
    for result in results:
        _print_result(result)

    return 0


def _cmd_policy(args: argparse.Namespace) -> int:
    """Show or modify notification policy."""
    engine = _get_engine()

    if getattr(args, "set", None):
        key, value = args.set
        policy = engine.policy

        # Map string keys to policy fields
        field_map = {
            "min_severity": lambda v: setattr(policy, "min_severity", _parse_severity(v)),
            "quiet_start": lambda v: setattr(policy, "quiet_start", _parse_time(v)),
            "quiet_end": lambda v: setattr(policy, "quiet_end", _parse_time(v)),
            "max_per_hour": lambda v: setattr(policy, "max_notifications_per_hour", int(v)),
            "max_per_day": lambda v: setattr(policy, "max_notifications_per_day", int(v)),
            "cooldown": lambda v: setattr(policy, "cooldown_seconds", int(v)),
            "desktop": lambda v: setattr(policy, "desktop_notifications", v.lower() in ("true", "1", "on")),
        }

        if key not in field_map:
            print(f"❌ Bilinmeyen politika anahtarı: {key}", file=sys.stderr)
            print(f"   Geçerli anahtarlar: {', '.join(field_map.keys())}")
            return 1

        try:
            field_map[key](value)
            engine.update_policy(policy)
            print(f"✅ Politika güncellendi: {key} = {value}")
        except Exception as e:
            print(f"❌ Güncelleme başarısız: {e}", file=sys.stderr)
            return 1
        return 0

    # Show policy
    policy_dict = engine.policy.to_dict()

    if getattr(args, "as_json", False):
        print(json.dumps(policy_dict, indent=2, ensure_ascii=False))
        return 0

    print("\n📋 Bildirim Politikası:\n")
    for key, value in policy_dict.items():
        label = key.replace("_", " ").title()
        print(f"   {label}: {value}")
    print()
    return 0


def _cmd_dnd(args: argparse.Namespace) -> int:
    """Toggle Do Not Disturb."""
    engine = _get_engine()
    mode = getattr(args, "mode", "off")
    enabled = mode == "on"
    engine.set_dnd(enabled)
    status = "açıldı 🔕" if enabled else "kapatıldı 🔔"
    print(f"✅ Rahatsız Etme modu {status}")
    return 0


def _cmd_notifications(args: argparse.Namespace) -> int:
    """Show or manage notifications."""
    engine = _get_engine()

    if getattr(args, "clear", False):
        count = engine.notifications.clear()
        print(f"✅ {count} bildirim temizlendi.")
        return 0

    unread_only = getattr(args, "unread", False)
    notifications = engine.notifications.get_all(unread_only=unread_only)

    if getattr(args, "as_json", False):
        print(json.dumps([n.to_dict() for n in notifications], indent=2, ensure_ascii=False))
        return 0

    if not notifications:
        label = "okunmamış " if unread_only else ""
        print(f"\n📭 {label}Bildirim yok.\n")
        return 0

    label = "Okunmamış Bildirimler" if unread_only else "Bildirimler"
    print(f"\n🔔 {label} ({len(notifications)} adet):\n")
    for n in notifications:
        status = "●" if not n.read else "○"
        ts = n.timestamp.strftime("%H:%M") if n.timestamp else ""
        print(f"  [{n.id}] {status} {ts} {n.icon} {n.body[:80]}")
        for s in n.suggestions[:2]:
            print(f"       💡 {s.text}")
    print()
    return 0


# ── Helpers ─────────────────────────────────────────────────────


def _print_result(result: "CheckResult") -> None:
    """Pretty-print a check result."""
    from bantz.proactive.models import CheckResult

    status = "✅" if result.ok else "❌"
    ts = result.timestamp.strftime("%H:%M:%S") if result.timestamp else ""
    print(f"  {status} [{ts}] {result.check_name} ({result.duration_ms:.0f}ms)")

    if result.error:
        print(f"     ❌ Hata: {result.error}")

    if result.summary:
        for line in result.summary.split("\n"):
            print(f"     {line}")

    if result.analysis and result.analysis.suggestions:
        for s in result.analysis.suggestions[:3]:
            print(f"     💡 {s.text}")

    print()


def _parse_severity(value: str) -> Any:
    """Parse severity string to enum."""
    from bantz.proactive.models import InsightSeverity
    return InsightSeverity(value.lower())


def _parse_time(value: str) -> Any:
    """Parse time string like '23:00'."""
    from datetime import time
    parts = value.split(":")
    return time(int(parts[0]), int(parts[1]))
