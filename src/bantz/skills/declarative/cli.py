"""CLI commands for declarative skill management (Issue #833).

Provides ``bantz skill`` subcommands:
- ``bantz skill list``    — list discovered skills
- ``bantz skill info <n>``— show details of a skill
- ``bantz skill create <n>`` — scaffold a new skill
- ``bantz skill validate <path>`` — validate a SKILL.md file
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


def add_skill_subparser(subparsers: argparse._SubParsersAction) -> None:
    """Add the 'skill' subcommand group to the main CLI parser."""
    skill_parser = subparsers.add_parser(
        "skill",
        help="Declarative skill management",
        description="Manage SKILL.md-based declarative skills.",
    )
    skill_sub = skill_parser.add_subparsers(dest="skill_action")
    skill_sub.required = True

    # bantz skill list
    list_p = skill_sub.add_parser("list", help="List discovered skills")
    list_p.add_argument(
        "--json", action="store_true", dest="as_json", help="Output as JSON"
    )
    list_p.add_argument(
        "--dir", type=str, default=None, help="Extra skill directory to scan"
    )

    # bantz skill info <name>
    info_p = skill_sub.add_parser("info", help="Show skill details")
    info_p.add_argument("name", help="Skill name")
    info_p.add_argument(
        "--dir", type=str, default=None, help="Extra skill directory to scan"
    )

    # bantz skill create <name>
    create_p = skill_sub.add_parser("create", help="Create a new skill scaffold")
    create_p.add_argument("name", help="Skill name")
    create_p.add_argument(
        "--dir", type=str, default=None, help="Target directory"
    )
    create_p.add_argument(
        "--description", "-d", type=str, default="", help="Skill description"
    )
    create_p.add_argument(
        "--author", "-a", type=str, default="", help="Author name"
    )

    # bantz skill validate <path>
    validate_p = skill_sub.add_parser("validate", help="Validate a SKILL.md file")
    validate_p.add_argument("path", help="Path to SKILL.md file")


def handle_skill_command(args: argparse.Namespace) -> int:
    """Handle a 'bantz skill' subcommand. Returns exit code."""
    action = args.skill_action

    if action == "list":
        return _cmd_list(args)
    elif action == "info":
        return _cmd_info(args)
    elif action == "create":
        return _cmd_create(args)
    elif action == "validate":
        return _cmd_validate(args)
    else:
        print(f"Unknown skill action: {action}", file=sys.stderr)
        return 1


def _get_loader(extra_dir: Optional[str] = None):
    """Create a SkillLoader with optional extra directory."""
    from bantz.skills.declarative.loader import SkillLoader

    dirs = None
    if extra_dir:
        from bantz.skills.declarative.loader import _get_default_skill_dirs

        dirs = _get_default_skill_dirs()
        dirs.insert(0, Path(extra_dir))

    return SkillLoader(skill_dirs=dirs)


def _cmd_list(args: argparse.Namespace) -> int:
    """List all discovered skills."""
    loader = _get_loader(getattr(args, "dir", None))
    skills = loader.discover()

    if getattr(args, "as_json", False):
        from bantz.skills.declarative.registry import DeclarativeSkillRegistry

        reg = DeclarativeSkillRegistry()
        for s in skills:
            reg.register(s)
        print(json.dumps(reg.get_status(), indent=2, ensure_ascii=False))
        return 0

    if not skills:
        print("📭 No loaded skills found.")
        print()
        print("Skill directories:")
        for d in loader.skill_dirs:
            exists = "✅" if d.is_dir() else "❌"
            print(f"  {exists} {d}")
        print()
        print("To create a new skill:")
        print("  bantz skill create <name>")
        return 0

    print(f"📦 {len(skills)} skill bulundu:\n")
    for skill in skills:
        m = skill.metadata
        triggers = ", ".join(t.intent for t in m.triggers)
        tools = ", ".join(t.name for t in m.tools)
        print(f"  {m.icon} {m.name} v{m.version}")
        print(f"    {m.description}")
        print(f"    Triggers: {triggers}")
        print(f"    Tools: {tools}")
        if skill.source_path:
            print(f"    Path: {skill.source_path}")
        print()

    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    """Show detailed info for a skill."""
    loader = _get_loader(getattr(args, "dir", None))
    skills = loader.discover()

    skill = None
    for s in skills:
        if s.name == args.name:
            skill = s
            break

    if skill is None:
        print(f"❌ Skill not found: {args.name}", file=sys.stderr)
        return 1

    m = skill.metadata
    print(f"{m.icon} {m.name} v{m.version}")
    print(f"  Author: {m.author}")
    print(f"  Description: {m.description}")
    print(f"  Tags: {', '.join(m.tags) or '-'}")
    print(f"  Permissions: {', '.join(p.name for p in m.permissions) or 'none'}")
    print(f"  Dependencies: {', '.join(m.dependencies) or 'none'}")
    print(f"  Source: {skill.source_path}")
    print()
    print("  Triggers:")
    for t in m.triggers:
        print(f"    • {t.intent} — /{t.pattern}/")
        if t.examples:
            print(f"      Examples: {', '.join(t.examples)}")
    print()
    print("  Tools:")
    for t in m.tools:
        print(f"    • {t.name} ({t.handler})")
        print(f"      {t.description}")
        if t.parameters:
            for p in t.parameters:
                req = " [required]" if p.required else ""
                print(f"      - {p.name}: {p.type}{req} — {p.description}")
    print()

    # Load and show instructions
    instructions = skill.load_instructions()
    if instructions:
        print("  Instructions (SKILL.md body):")
        print("  " + "─" * 50)
        for line in instructions.split("\n")[:20]:
            print(f"  {line}")
        if instructions.count("\n") > 20:
            print(f"  ... ({instructions.count(chr(10)) - 20} more lines)")
    return 0


def _cmd_create(args: argparse.Namespace) -> int:
    """Create a new skill scaffold."""
    from bantz.skills.declarative.loader import SkillLoader

    target = Path(args.dir) if args.dir else None

    try:
        path = SkillLoader.create_skill_scaffold(
            name=args.name,
            target_dir=target,
            description=args.description,
            author=args.author,
        )
        print(f"✅ Skill created: {path}")
        print()
        print("Next steps:")
        print(f"  1. Edit SKILL.md: {path}")
        print(f"  2. Define triggers and tools")
        print(f"  3. Write the instructions section")
        print(f"  4. Test it: bantz skill validate {path}")
        return 0
    except FileExistsError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"❌ Failed to create skill: {exc}", file=sys.stderr)
        return 1


def _cmd_validate(args: argparse.Namespace) -> int:
    """Validate a SKILL.md file."""
    from bantz.skills.declarative.loader import SkillLoader

    path = Path(args.path)
    if not path.exists():
        print(f"❌ File not found: {path}", file=sys.stderr)
        return 1

    try:
        skill = SkillLoader.parse_skill_file(path)
        errors = skill.validate()

        if errors:
            print(f"❌ {len(errors)} validation errors:")
            for err in errors:
                print(f"  • {err}")
            return 1

        m = skill.metadata
        print(f"✅ Valid SKILL.md: {m.icon} {m.name} v{m.version}")
        print(f"  {len(m.triggers)} trigger, {len(m.tools)} tool")
        print(f"  Instructions: {len(skill.instructions)} characters")
        return 0

    except ValueError as exc:
        print(f"❌ Parse error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"❌ Unexpected error: {exc}", file=sys.stderr)
        return 1
