"""Skill Executor — runs declarative skill tools (Issue #833).

Handles execution of tools defined in SKILL.md files. Three handler modes:

1. **``llm``** (default): Loads the skill's Markdown instructions into the
   LLM context and lets the LLM generate a response. This is the core
   declarative pattern — no Python code needed.

2. **``builtin:<tool_name>``**: Delegates to an existing runtime tool.
   E.g., ``builtin:calendar.list_events`` would call the calendar tool.

3. **``script:<filename>``**: Runs a Python script from the skill's
   ``scripts/`` directory. The script receives parameters as a JSON dict
   on stdin and writes results to stdout.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from bantz.skills.declarative.registry import DeclarativeSkillRegistry

logger = logging.getLogger(__name__)


class SkillExecutionError(Exception):
    """Raised when a skill tool execution fails."""
    pass


class SkillExecutor:
    """Executes declarative skill tools.

    Parameters
    ----------
    registry : DeclarativeSkillRegistry
        The skill registry to look up skills and their instructions.
    runtime_tools : ToolRegistry | None
        The runtime tool registry for ``builtin:`` handler delegation.
    """

    def __init__(
        self,
        registry: "DeclarativeSkillRegistry",
        runtime_tools: Any = None,
    ) -> None:
        self._registry = registry
        self._runtime_tools = runtime_tools

    def execute(
        self,
        tool_name: str,
        params: dict[str, Any],
        *,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute a declarative skill tool.

        Parameters
        ----------
        tool_name : str
            The tool name (e.g. ``weather.get_current``).
        params : dict
            Tool parameters from the LLM plan.
        context : dict | None
            Additional execution context (user_input, session, etc.).

        Returns
        -------
        dict
            Execution result with keys: ``success``, ``result``, ``skill``,
            ``tool``, ``handler``.
        """
        # Find the skill that owns this tool
        skill = self._registry.get_by_tool(tool_name)
        if skill is None:
            return {
                "success": False,
                "result": f"No skill found for tool: {tool_name}",
                "tool": tool_name,
                "handler": "none",
            }

        # Find the tool definition
        tool_def = None
        for t in skill.metadata.tools:
            if t.name == tool_name:
                tool_def = t
                break

        if tool_def is None:
            return {
                "success": False,
                "result": f"Tool definition not found: {tool_name}",
                "tool": tool_name,
                "handler": "none",
            }

        handler = tool_def.handler.strip()

        try:
            if handler == "llm":
                return self._execute_llm(skill, tool_def, params, context)
            elif handler.startswith("builtin:"):
                builtin_name = handler[len("builtin:"):]
                return self._execute_builtin(
                    builtin_name, params, skill.name, tool_name
                )
            elif handler.startswith("script:"):
                script_name = handler[len("script:"):]
                return self._execute_script(
                    skill, script_name, params, tool_name
                )
            else:
                return {
                    "success": False,
                    "result": f"Unknown handler type: {handler!r}",
                    "skill": skill.name,
                    "tool": tool_name,
                    "handler": handler,
                }
        except Exception as exc:
            logger.exception(
                "Error executing skill tool %s (handler=%s)", tool_name, handler
            )
            return {
                "success": False,
                "result": f"Execution error: {exc}",
                "skill": skill.name,
                "tool": tool_name,
                "handler": handler,
            }

    def _execute_llm(
        self,
        skill: Any,
        tool_def: Any,
        params: dict[str, Any],
        context: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute via LLM — inject skill instructions into context.

        For LLM-driven tools, the executor loads the skill's Markdown
        instructions and returns them along with the parameters. The
        orchestrator loop will use these instructions as additional
        system context for the LLM finalizer.
        """
        # Progressive loading: load instructions on first use
        instructions = skill.load_instructions()

        return {
            "success": True,
            "result": instructions,
            "skill": skill.name,
            "tool": tool_def.name,
            "handler": "llm",
            "instructions": instructions,
            "parameters": params,
            "context": context or {},
            "skill_metadata": {
                "name": skill.name,
                "description": skill.metadata.description,
                "icon": skill.metadata.icon,
            },
        }

    def _execute_builtin(
        self,
        builtin_name: str,
        params: dict[str, Any],
        skill_name: str,
        tool_name: str,
    ) -> dict[str, Any]:
        """Delegate to an existing runtime tool."""
        if self._runtime_tools is None:
            return {
                "success": False,
                "result": "No runtime tool registry available for builtin delegation",
                "skill": skill_name,
                "tool": tool_name,
                "handler": f"builtin:{builtin_name}",
            }

        tool = self._runtime_tools.get(builtin_name)
        if tool is None:
            return {
                "success": False,
                "result": f"Builtin tool not found: {builtin_name}",
                "skill": skill_name,
                "tool": tool_name,
                "handler": f"builtin:{builtin_name}",
            }

        if tool.function is None:
            return {
                "success": False,
                "result": f"Builtin tool {builtin_name} has no handler function",
                "skill": skill_name,
                "tool": tool_name,
                "handler": f"builtin:{builtin_name}",
            }

        result = tool.function(**params)
        return {
            "success": True,
            "result": result,
            "skill": skill_name,
            "tool": tool_name,
            "handler": f"builtin:{builtin_name}",
        }

    def _execute_script(
        self,
        skill: Any,
        script_name: str,
        params: dict[str, Any],
        tool_name: str,
    ) -> dict[str, Any]:
        """Run a Python script from the skill's scripts/ directory."""
        if skill.source_path is None:
            return {
                "success": False,
                "result": "Skill has no source path for script execution",
                "skill": skill.name,
                "tool": tool_name,
                "handler": f"script:{script_name}",
            }

        scripts_dir = skill.source_path.parent / "scripts"
        script_path = scripts_dir / script_name

        if not script_path.is_file():
            return {
                "success": False,
                "result": f"Script not found: {script_path}",
                "skill": skill.name,
                "tool": tool_name,
                "handler": f"script:{script_name}",
            }

        # Security: only allow .py files within the skill's own directory
        try:
            script_path.resolve().relative_to(skill.source_path.parent.resolve())
        except ValueError:
            return {
                "success": False,
                "result": f"Script path traversal detected: {script_path}",
                "skill": skill.name,
                "tool": tool_name,
                "handler": f"script:{script_name}",
            }

        try:
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                input=json.dumps(params),
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(skill.source_path.parent),
            )

            if proc.returncode != 0:
                return {
                    "success": False,
                    "result": f"Script failed (exit {proc.returncode}): {proc.stderr.strip()}",
                    "skill": skill.name,
                    "tool": tool_name,
                    "handler": f"script:{script_name}",
                }

            # Try to parse JSON output
            output = proc.stdout.strip()
            try:
                result = json.loads(output)
            except json.JSONDecodeError:
                result = output

            return {
                "success": True,
                "result": result,
                "skill": skill.name,
                "tool": tool_name,
                "handler": f"script:{script_name}",
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "result": f"Script timed out after 30s: {script_name}",
                "skill": skill.name,
                "tool": tool_name,
                "handler": f"script:{script_name}",
            }
