"""Declarative Skill Registry — manages loaded skills and bridges to agent (Issue #833).

This registry holds all discovered :class:`DeclarativeSkill` instances and
provides aggregation methods compatible with the existing Bantz tool/intent
infrastructure.

Key integration points:

- **Tool Registry**: :meth:`inject_into_tool_registry` adds skill tools to an
  existing :class:`~bantz.agent.tools.ToolRegistry` so they appear in the
  planner catalog and runtime execution.

- **Intent Patterns**: :meth:`get_all_intents` returns
  :class:`~bantz.plugins.base.IntentPattern` instances compatible with the
  plugin system's NLU integration.

- **Progressive Loading**: Instructions are only loaded when a skill is
  activated (triggered), not at discovery time.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from bantz.skills.declarative.models import DeclarativeSkill, SkillToolDef

logger = logging.getLogger(__name__)


class DeclarativeSkillRegistry:
    """Registry of loaded declarative skills.

    Thread-safe skill management with tool/intent aggregation.
    """

    def __init__(self) -> None:
        self._skills: dict[str, DeclarativeSkill] = {}

    def register(self, skill: DeclarativeSkill) -> None:
        """Register a discovered skill.

        Parameters
        ----------
        skill : DeclarativeSkill
            The skill to register.

        Raises
        ------
        ValueError
            If a skill with the same name is already registered.
        """
        if skill.name in self._skills:
            raise ValueError(
                f"Skill {skill.name!r} is already registered. "
                f"Unregister it first or use a different name."
            )
        self._skills[skill.name] = skill
        logger.info(
            "Registered declarative skill: %s %s v%s",
            skill.metadata.icon,
            skill.name,
            skill.metadata.version,
        )

    def unregister(self, name: str) -> bool:
        """Unregister a skill by name.

        Returns True if the skill was found and removed.
        """
        if name in self._skills:
            del self._skills[name]
            logger.info("Unregistered declarative skill: %s", name)
            return True
        return False

    def get(self, name: str) -> Optional[DeclarativeSkill]:
        """Get a skill by name."""
        return self._skills.get(name)

    def get_by_intent(self, intent: str) -> Optional[DeclarativeSkill]:
        """Find the skill that handles a given intent.

        Parameters
        ----------
        intent : str
            Intent name (e.g. ``weather.current``).

        Returns
        -------
        DeclarativeSkill | None
            The skill that handles this intent, or None.
        """
        for skill in self._skills.values():
            for trigger in skill.metadata.triggers:
                if trigger.intent == intent:
                    return skill
        return None

    def get_by_tool(self, tool_name: str) -> Optional[DeclarativeSkill]:
        """Find the skill that provides a given tool.

        Parameters
        ----------
        tool_name : str
            Tool name (e.g. ``weather.get_current``).
        """
        for skill in self._skills.values():
            for tool in skill.metadata.tools:
                if tool.name == tool_name:
                    return skill
        return None

    @property
    def skill_names(self) -> list[str]:
        """Return sorted list of registered skill names."""
        return sorted(self._skills.keys())

    @property
    def skills(self) -> list[DeclarativeSkill]:
        """Return all registered skills."""
        return list(self._skills.values())

    def get_all_intents(self) -> list[dict[str, Any]]:
        """Return all intent patterns from all skills.

        Returns a list of dicts compatible with the plugin IntentPattern format:
        ``{"pattern": ..., "intent": ..., "priority": ..., "examples": ...}``
        """
        intents: list[dict[str, Any]] = []
        for skill in self._skills.values():
            for trigger in skill.metadata.triggers:
                intents.append({
                    "pattern": trigger.pattern,
                    "intent": trigger.intent,
                    "priority": trigger.priority,
                    "examples": trigger.examples,
                    "slots": trigger.slots,
                    "skill_name": skill.name,
                })
        return intents

    def get_all_tool_defs(self) -> list[SkillToolDef]:
        """Return all tool definitions from all skills."""
        tools: list[SkillToolDef] = []
        for skill in self._skills.values():
            tools.extend(skill.metadata.tools)
        return tools

    def inject_into_tool_registry(self, registry: Any) -> int:
        """Inject all skill tools into an agent ToolRegistry.

        Creates :class:`~bantz.agent.tools.Tool` instances for each
        :class:`SkillToolDef` and registers them. The tool's ``function``
        is a closure that delegates to :class:`SkillExecutor`.

        Parameters
        ----------
        registry : bantz.agent.tools.ToolRegistry
            The runtime tool registry to inject into.

        Returns
        -------
        int
            Number of tools injected.
        """
        from bantz.agent.tools import Tool
        from bantz.skills.declarative.executor import SkillExecutor

        executor = SkillExecutor(self)
        count = 0

        for skill in self._skills.values():
            for tool_def in skill.metadata.tools:
                # Check if already registered (don't override runtime tools)
                if registry.get(tool_def.name) is not None:
                    logger.debug(
                        "Tool %s already in registry — skipping (skill: %s)",
                        tool_def.name,
                        skill.name,
                    )
                    continue

                # Create a closure that captures the tool name
                def _make_handler(tn: str):
                    def handler(**kwargs):
                        return executor.execute(tn, kwargs)
                    return handler

                tool = Tool(
                    name=tool_def.name,
                    description=tool_def.description,
                    parameters=tool_def.to_json_schema(),
                    risk_level=tool_def.risk_level,
                    requires_confirmation=tool_def.requires_confirmation,
                    function=_make_handler(tool_def.name),
                )
                registry.register(tool)
                count += 1
                logger.debug(
                    "Injected skill tool: %s (from skill %s)",
                    tool_def.name,
                    skill.name,
                )

        logger.info(
            "Injected %d declarative skill tools into registry", count
        )
        return count

    def get_status(self) -> dict[str, Any]:
        """Return status summary for all skills."""
        return {
            "total_skills": len(self._skills),
            "total_triggers": sum(
                len(s.metadata.triggers) for s in self._skills.values()
            ),
            "total_tools": sum(
                len(s.metadata.tools) for s in self._skills.values()
            ),
            "skills": {
                name: {
                    "version": skill.metadata.version,
                    "icon": skill.metadata.icon,
                    "description": skill.metadata.description,
                    "triggers": len(skill.metadata.triggers),
                    "tools": len(skill.metadata.tools),
                    "instructions_loaded": skill.is_loaded,
                    "source": str(skill.source_path) if skill.source_path else None,
                }
                for name, skill in sorted(self._skills.items())
            },
        }
