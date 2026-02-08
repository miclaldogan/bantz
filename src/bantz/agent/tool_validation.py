"""
Tool Registry Validation — Issue #432.

Startup-time validation for the tool registry:
- Mandatory tool presence check
- Health check stubs (calendar, gmail, time, system)
- Route→tool dependency graph + startup warnings
- ValidationReport with to_dict() export

Usage::

    from bantz.agent.tool_validation import (
        validate_registry,
        RegistryValidator,
        ROUTE_TOOL_DEPENDENCIES,
    )
    report = validate_registry(registry)
    if not report.ok:
        for w in report.warnings:
            logger.warning(w)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Mandatory tools — must exist in registry at startup
# ─────────────────────────────────────────────────────────────────

MANDATORY_TOOLS: List[str] = [
    "time.now",
    "system.status",
    "calendar.list_events",
    "calendar.create_event",
    "gmail.list_messages",
    "gmail.send",
]

# ─────────────────────────────────────────────────────────────────
# Route → Tool dependency graph
# ─────────────────────────────────────────────────────────────────

# Each route maps to the tools it may invoke at runtime.
ROUTE_TOOL_DEPENDENCIES: Dict[str, List[str]] = {
    "calendar": [
        "calendar.list_events",
        "calendar.create_event",
        "calendar.update_event",
        "calendar.delete_event",
        "calendar.find_free_slots",
    ],
    "gmail": [
        "gmail.list_messages",
        "gmail.get_message",
        "gmail.send",
        "gmail.smart_search",
        "gmail.archive",
        "gmail.generate_reply",
    ],
    "system": [
        "time.now",
        "system.status",
        "system.open_app",
        "system.shutdown",
    ],
    "browser": [
        "browser.open",
        "browser.search",
    ],
}

# Reverse map: tool → routes that depend on it
TOOL_ROUTE_MAP: Dict[str, List[str]] = {}
for _route, _tools in ROUTE_TOOL_DEPENDENCIES.items():
    for _tool in _tools:
        TOOL_ROUTE_MAP.setdefault(_tool, []).append(_route)


# ─────────────────────────────────────────────────────────────────
# Validation Report
# ─────────────────────────────────────────────────────────────────


@dataclass
class ValidationReport:
    """Result of a startup tool registry validation."""

    registered_tools: List[str] = field(default_factory=list)
    missing_mandatory: List[str] = field(default_factory=list)
    missing_route_deps: Dict[str, List[str]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    health_results: Dict[str, bool] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True if no mandatory tools are missing and no errors."""
        return len(self.missing_mandatory) == 0 and len(self.errors) == 0

    @property
    def healthy(self) -> bool:
        """True if all health checks passed."""
        return all(self.health_results.values()) if self.health_results else True

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "ok": self.ok,
            "registered_tools": self.registered_tools,
            "missing_mandatory": self.missing_mandatory,
        }
        if self.missing_route_deps:
            d["missing_route_deps"] = self.missing_route_deps
        if self.warnings:
            d["warnings"] = self.warnings
        if self.errors:
            d["errors"] = self.errors
        if self.health_results:
            d["health_results"] = self.health_results
        return d


# ─────────────────────────────────────────────────────────────────
# Validator
# ─────────────────────────────────────────────────────────────────


class RegistryValidator:
    """
    Validates a ToolRegistry at startup.

    Checks:
    1. All mandatory tools are registered.
    2. Route→tool dependencies are satisfied (warning if not).
    3. Health check stubs for core tools.
    """

    def __init__(
        self,
        mandatory_tools: Optional[List[str]] = None,
        route_deps: Optional[Dict[str, List[str]]] = None,
    ):
        self._mandatory = mandatory_tools or MANDATORY_TOOLS
        self._route_deps = route_deps or ROUTE_TOOL_DEPENDENCIES

    def validate(self, registry: Any) -> ValidationReport:
        """
        Run all validation checks on a registry.

        Args:
            registry: Object with .names() → List[str] and .get(name) → Optional[Tool]

        Returns:
            ValidationReport with findings.
        """
        report = ValidationReport()

        # Gather registered tool names
        registered: Set[str] = set()
        try:
            registered = set(registry.names())
        except Exception as exc:
            report.errors.append(f"Registry.names() failed: {exc}")
            return report

        report.registered_tools = sorted(registered)

        # 1. Mandatory tool check
        for tool_name in self._mandatory:
            if tool_name not in registered:
                report.missing_mandatory.append(tool_name)
                report.errors.append(
                    f"Mandatory tool '{tool_name}' is not registered"
                )
                logger.error(
                    "[TOOL_VALIDATION] Mandatory tool MISSING: %s", tool_name
                )

        # 2. Route dependency check
        for route, deps in self._route_deps.items():
            missing_deps = [t for t in deps if t not in registered]
            if missing_deps:
                report.missing_route_deps[route] = missing_deps
                for dep in missing_deps:
                    msg = (
                        f"Route '{route}' depends on tool '{dep}' "
                        f"which is not registered"
                    )
                    report.warnings.append(msg)
                    logger.warning("[TOOL_VALIDATION] %s", msg)

        # 3. Health check — basic verify .get() returns non-None for core tools
        core_tools = ["time.now", "system.status", "calendar.list_events", "gmail.list_messages"]
        for tool_name in core_tools:
            if tool_name not in registered:
                report.health_results[tool_name] = False
                continue
            try:
                tool = registry.get(tool_name)
                report.health_results[tool_name] = tool is not None
            except Exception:
                report.health_results[tool_name] = False

        return report


def validate_registry(registry: Any) -> ValidationReport:
    """Convenience: validate a ToolRegistry with default settings."""
    validator = RegistryValidator()
    report = validator.validate(registry)

    if report.ok:
        logger.info(
            "[TOOL_VALIDATION] Registry OK — %d tools registered",
            len(report.registered_tools),
        )
    else:
        logger.error(
            "[TOOL_VALIDATION] Registry FAILED — missing: %s",
            ", ".join(report.missing_mandatory),
        )

    return report
