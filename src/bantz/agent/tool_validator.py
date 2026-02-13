"""Startup Tool Validator (Issue #459).

Validates every registered tool at boot time:

- Required secrets present (via vault or env)
- Required packages importable
- Optional health-check callback passes
- Dependency graph: tool A depends on tool B

Disabled tools get ``enabled=False`` and a clear report is logged.

See Also
--------
- ``src/bantz/agent/tools.py`` — ToolRegistry / ToolSpec
- ``src/bantz/agent/circuit_breaker.py`` — circuit breaker
- ``src/bantz/security/secret_vault.py`` — secrets (Issue #454)
"""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

__all__ = [
    "ValidatedTool",
    "ValidationResult",
    "ToolValidationReport",
    "ToolValidator",
]


# ── Validated tool spec ───────────────────────────────────────────────

@dataclass
class ValidatedTool:
    """Extended tool spec with validation metadata."""

    name: str
    description: str = ""
    handler: Optional[Callable[..., Any]] = None
    health_check: Optional[Callable[[], bool]] = None
    required_secrets: List[str] = field(default_factory=list)
    required_packages: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)  # tool names
    enabled: bool = True
    disable_reason: Optional[str] = None


# ── Validation result per tool ────────────────────────────────────────

class ValidationResult(Enum):
    OK = "ok"
    MISSING_SECRET = "missing_secret"
    MISSING_PACKAGE = "missing_package"
    HEALTH_CHECK_FAILED = "health_check_failed"
    DEPENDENCY_DISABLED = "dependency_disabled"


@dataclass
class ToolValidationReport:
    """Aggregate report of tool validation."""

    total: int = 0
    enabled_count: int = 0
    disabled: List[tuple[str, str]] = field(default_factory=list)  # (name, reason)

    @property
    def summary(self) -> str:
        lines = [f"[TOOLS] {self.enabled_count}/{self.total} tools ready"]
        for name, reason in self.disabled:
            lines.append(f"[TOOLS] DISABLED: {name} ({reason})")
        return "\n".join(lines)


# ── Validator ─────────────────────────────────────────────────────────

class ToolValidator:
    """Validates tools at startup and produces a report.

    Parameters
    ----------
    secret_checker:
        ``(secret_name) → bool`` — returns True if secret is available.
        If ``None``, secret checks are skipped.
    package_checker:
        ``(module_name) → bool`` — returns True if package is importable.
        If ``None``, uses :func:`importlib.util.find_spec`.
    """

    def __init__(
        self,
        *,
        secret_checker: Optional[Callable[[str], bool]] = None,
        package_checker: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self._check_secret = secret_checker
        self._check_package = package_checker or self._default_package_check
        self._tools: Dict[str, ValidatedTool] = {}

    # ── register ──────────────────────────────────────────────────────

    def register(self, tool: ValidatedTool) -> None:
        """Register a tool for validation."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ValidatedTool]:
        """Retrieve a registered tool."""
        return self._tools.get(name)

    def list_tools(self) -> List[ValidatedTool]:
        """Return all tools sorted by name."""
        return [self._tools[n] for n in sorted(self._tools)]

    # ── validate ──────────────────────────────────────────────────────

    def validate_all(self) -> ToolValidationReport:
        """Validate every registered tool.

        Returns
        -------
        ToolValidationReport
        """
        report = ToolValidationReport(total=len(self._tools))

        # Phase 1: check secrets, packages, health
        for tool in self._tools.values():
            self._validate_tool(tool)

        # Phase 2: dependency graph (disabled deps propagate)
        self._propagate_dependencies()

        # Build report
        for tool in self._tools.values():
            if tool.enabled:
                report.enabled_count += 1
            else:
                report.disabled.append((tool.name, tool.disable_reason or "unknown"))

        logger.info(report.summary)
        return report

    def _validate_tool(self, tool: ValidatedTool) -> None:
        """Check a single tool's secrets, packages, health."""
        # Secrets
        if self._check_secret is not None:
            for secret in tool.required_secrets:
                if not self._check_secret(secret):
                    tool.enabled = False
                    tool.disable_reason = f"missing secret: {secret}"
                    return

        # Packages
        for pkg in tool.required_packages:
            if not self._check_package(pkg):
                tool.enabled = False
                tool.disable_reason = f"missing package: {pkg}"
                return

        # Health check
        if tool.health_check is not None:
            try:
                result = tool.health_check()
                if not result:
                    tool.enabled = False
                    tool.disable_reason = "health check returned False"
                    return
            except Exception as exc:
                tool.enabled = False
                tool.disable_reason = f"health check error: {exc}"
                return

    def _propagate_dependencies(self) -> None:
        """Disable tools whose dependencies are disabled."""
        changed = True
        iterations = 0
        max_iter = len(self._tools) + 1  # prevent infinite loop

        while changed and iterations < max_iter:
            changed = False
            iterations += 1
            for tool in self._tools.values():
                if not tool.enabled:
                    continue
                for dep_name in tool.depends_on:
                    dep = self._tools.get(dep_name)
                    if dep is None or not dep.enabled:
                        tool.enabled = False
                        tool.disable_reason = f"dependency disabled: {dep_name}"
                        changed = True
                        break

    # ── reload ────────────────────────────────────────────────────────

    def reload(self) -> ToolValidationReport:
        """Re-validate all tools (hot-reload)."""
        for tool in self._tools.values():
            tool.enabled = True
            tool.disable_reason = None
        return self.validate_all()

    # ── call disabled tool helper ─────────────────────────────────────

    def check_enabled(self, name: str) -> tuple[bool, str]:
        """Check if tool is enabled. Returns ``(enabled, message)``."""
        tool = self._tools.get(name)
        if tool is None:
            return False, f"Tool '{name}' not found"
        if not tool.enabled:
            return False, f"Tool '{name}' is disabled: {tool.disable_reason}"
        return True, "ok"

    # ── default package checker ───────────────────────────────────────

    @staticmethod
    def _default_package_check(module_name: str) -> bool:
        """Check if a module is importable."""
        try:
            spec = importlib.util.find_spec(module_name)
            return spec is not None
        except (ModuleNotFoundError, ValueError):
            return False
