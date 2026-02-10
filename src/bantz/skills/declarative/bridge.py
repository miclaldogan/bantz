"""Brain pipeline bridge for declarative skills (Issue #833).

Integrates the declarative skill system into the existing Bantz brain
pipeline. This module is loaded by ``runtime_factory.py`` to:

1. Discover skills from ``~/.config/bantz/skills/``
2. Inject skill tools into the runtime :class:`ToolRegistry`
3. Register skill triggers with the NLU/routing layer
4. Provide skill instruction context to the finalizer

Usage::

    from bantz.skills.declarative.bridge import setup_declarative_skills

    # In runtime_factory.py or startup code:
    skill_registry = setup_declarative_skills(tool_registry)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Module-level singleton for the skill registry
_global_skill_registry: Optional[Any] = None


def setup_declarative_skills(
    tool_registry: Any,
    *,
    skill_dirs: Optional[list[Path]] = None,
    lazy: bool = True,
) -> Any:
    """Initialize the declarative skill system and inject into pipeline.

    This is the main entry point called during Bantz startup. It:

    1. Creates a :class:`SkillLoader` and discovers all SKILL.md files
    2. Creates a :class:`DeclarativeSkillRegistry` and registers them
    3. Injects skill tools into the runtime :class:`ToolRegistry`
    4. Stores the registry globally for later access

    Parameters
    ----------
    tool_registry : bantz.agent.tools.ToolRegistry
        The runtime tool registry to inject skill tools into.
    skill_dirs : list[Path] | None
        Override skill directories (for testing).
    lazy : bool
        Whether to use progressive loading (default True).

    Returns
    -------
    DeclarativeSkillRegistry
        The initialized skill registry.
    """
    global _global_skill_registry

    from bantz.skills.declarative.loader import SkillLoader
    from bantz.skills.declarative.registry import DeclarativeSkillRegistry

    loader = SkillLoader(skill_dirs=skill_dirs, lazy=lazy)
    registry = DeclarativeSkillRegistry()

    # Discover and register skills
    skills = loader.discover()
    for skill in skills:
        try:
            registry.register(skill)
        except ValueError:
            logger.warning("Skipping duplicate skill: %s", skill.name)

    # Inject tools into runtime registry
    injected = registry.inject_into_tool_registry(tool_registry)

    _global_skill_registry = registry

    logger.info(
        "Declarative skill system initialized: %d skills, %d tools injected",
        len(skills),
        injected,
    )

    return registry


def get_skill_registry() -> Optional[Any]:
    """Return the global declarative skill registry (if initialized)."""
    return _global_skill_registry


def get_skill_context_for_tool(tool_name: str) -> Optional[str]:
    """Get the skill instructions for a tool (for LLM context injection).

    Called by the orchestrator loop when executing an ``llm``-handler tool.
    Returns the skill's Markdown instructions to inject into the finalizer
    prompt.

    Parameters
    ----------
    tool_name : str
        The tool name being executed.

    Returns
    -------
    str | None
        The skill's Markdown instructions, or None if not a skill tool.
    """
    if _global_skill_registry is None:
        return None

    skill = _global_skill_registry.get_by_tool(tool_name)
    if skill is None:
        return None

    # Trigger progressive loading
    return skill.load_instructions()


def get_skill_triggers() -> list[dict[str, Any]]:
    """Return all skill trigger patterns for NLU integration.

    Returns
    -------
    list[dict]
        List of trigger dicts with ``pattern``, ``intent``, ``priority``,
        ``examples``, ``skill_name``.
    """
    if _global_skill_registry is None:
        return []
    return _global_skill_registry.get_all_intents()
