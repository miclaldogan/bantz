"""Declarative Skill System — SKILL.md based skill definitions (Issue #833).

Allows adding new skills to Bantz by writing a SKILL.md file with
YAML frontmatter (metadata, triggers, tools, permissions) + Markdown
instructions — **no Python code required**.

Usage::

    from bantz.skills.declarative import SkillLoader, SkillRegistry

    loader = SkillLoader()
    registry = SkillRegistry()

    for skill in loader.discover():
        registry.register(skill)

    # Router integration
    tools = registry.get_all_tools()      # → agent.ToolRegistry compatible
    intents = registry.get_all_intents()   # → IntentPattern list
"""

from bantz.skills.declarative.models import (
    DeclarativeSkill,
    SkillMetadata,
    SkillTrigger,
    SkillToolDef,
    SkillPermission,
)
from bantz.skills.declarative.loader import SkillLoader
from bantz.skills.declarative.registry import DeclarativeSkillRegistry
from bantz.skills.declarative.executor import SkillExecutor
from bantz.skills.declarative.generator import (
    SelfEvolvingSkillManager,
    SkillGenerator,
    SkillNeedDetector,
    SkillValidator,
    SkillVersionManager,
    SkillGap,
    GenerationResult,
    get_self_evolving_manager,
    setup_self_evolving,
)

__all__ = [
    "DeclarativeSkill",
    "SkillMetadata",
    "SkillTrigger",
    "SkillToolDef",
    "SkillPermission",
    "SkillLoader",
    "DeclarativeSkillRegistry",
    "SkillExecutor",
    "SelfEvolvingSkillManager",
    "SkillGenerator",
    "SkillNeedDetector",
    "SkillValidator",
    "SkillVersionManager",
    "SkillGap",
    "GenerationResult",
    "get_self_evolving_manager",
    "setup_self_evolving",
]
