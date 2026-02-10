"""Data models for declarative skills (Issue #833).

Defines the in-memory representation of a SKILL.md file after parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Optional


class SkillPermission(Enum):
    """Permissions a declarative skill can request."""

    NETWORK = auto()
    FILESYSTEM = auto()
    SYSTEM = auto()
    BROWSER = auto()
    NOTIFICATIONS = auto()
    AUDIO = auto()
    CLIPBOARD = auto()
    KEYBOARD = auto()
    MOUSE = auto()
    SCREEN = auto()
    CALENDAR = auto()
    EMAIL = auto()
    CONTACTS = auto()
    LOCATION = auto()

    @classmethod
    def from_string(cls, value: str) -> "SkillPermission":
        """Parse a permission from string (case-insensitive)."""
        try:
            return cls[value.upper().strip()]
        except KeyError:
            raise ValueError(f"Unknown permission: {value!r}")


@dataclass(frozen=True)
class SkillTrigger:
    """A trigger pattern that activates the skill.

    Attributes:
        pattern: Regex pattern for matching user input.
        intent: Intent name this trigger maps to (e.g. ``weather.current``).
        examples: Example user inputs for this trigger (for docs/testing).
        priority: Higher priority triggers are checked first (default 50).
        slots: Slot extraction patterns — mapping of slot name → regex group.
    """

    pattern: str
    intent: str
    examples: list[str] = field(default_factory=list)
    priority: int = 50
    slots: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate regex at construction time
        try:
            re.compile(self.pattern)
        except re.error as exc:
            raise ValueError(
                f"Invalid regex in trigger for intent {self.intent!r}: {exc}"
            ) from exc

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillTrigger":
        """Create from YAML dict."""
        return cls(
            pattern=data["pattern"],
            intent=data["intent"],
            examples=data.get("examples", []),
            priority=data.get("priority", 50),
            slots=data.get("slots", {}),
        )


@dataclass(frozen=True)
class SkillToolParam:
    """Parameter definition for a skill tool."""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    default: Any = None
    enum: Optional[list[Any]] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillToolParam":
        return cls(
            name=data["name"],
            type=data.get("type", "string"),
            description=data.get("description", ""),
            required=data.get("required", False),
            default=data.get("default"),
            enum=data.get("enum"),
        )

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema property dict."""
        schema: dict[str, Any] = {
            "type": self.type,
            "description": self.description,
        }
        if self.enum:
            schema["enum"] = self.enum
        if self.default is not None:
            schema["default"] = self.default
        return schema


@dataclass(frozen=True)
class SkillToolDef:
    """A tool definition within a declarative skill.

    These are tools that the skill declares for the LLM planner.
    The tool's ``handler`` is ``"llm"`` (LLM-driven via instructions),
    ``"builtin"`` (delegate to an existing runtime tool), or
    ``"script"`` (run a script in the skill directory).

    Attributes:
        name: Tool name (e.g. ``weather.get_current``).
        description: Human-readable description.
        handler: How to execute: ``"llm"``, ``"builtin:<tool_name>"``, or
                 ``"script:<filename>"``.
        parameters: List of parameters.
        returns: Description of return value.
        requires_confirmation: Whether to show confirmation firewall.
        risk_level: LOW / MED / HIGH.
    """

    name: str
    description: str
    handler: str = "llm"
    parameters: list[SkillToolParam] = field(default_factory=list)
    returns: str = ""
    requires_confirmation: bool = False
    risk_level: str = "LOW"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillToolDef":
        params = [
            SkillToolParam.from_dict(p) for p in data.get("parameters", [])
        ]
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            handler=data.get("handler", "llm"),
            parameters=params,
            returns=data.get("returns", ""),
            requires_confirmation=data.get("requires_confirmation", False),
            risk_level=data.get("risk_level", "LOW"),
        )

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to agent Tool-compatible JSON Schema."""
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param in self.parameters:
            properties[param.name] = param.to_json_schema()
            if param.required:
                required.append(param.name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }


@dataclass
class SkillMetadata:
    """Parsed YAML frontmatter from SKILL.md.

    Attributes:
        name: Unique skill identifier (e.g. ``weather``).
        version: Semantic version string.
        author: Author name.
        description: Short description (1-2 sentences).
        icon: Emoji icon for display.
        tags: Categorization tags.
        triggers: Input patterns that activate the skill.
        tools: Tools this skill provides.
        permissions: Required permissions.
        dependencies: Other skills this depends on.
        config: Default configuration values.
        min_bantz_version: Minimum Bantz version required.
    """

    name: str
    version: str = "0.1.0"
    author: str = ""
    description: str = ""
    icon: str = "🔧"
    tags: list[str] = field(default_factory=list)
    triggers: list[SkillTrigger] = field(default_factory=list)
    tools: list[SkillToolDef] = field(default_factory=list)
    permissions: list[SkillPermission] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)
    min_bantz_version: str = "0.1.0"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillMetadata":
        """Create from parsed YAML frontmatter dict."""
        triggers = [
            SkillTrigger.from_dict(t) for t in data.get("triggers", [])
        ]
        tools = [
            SkillToolDef.from_dict(t) for t in data.get("tools", [])
        ]
        permissions = []
        for p in data.get("permissions", []):
            try:
                permissions.append(SkillPermission.from_string(p))
            except ValueError:
                pass  # Skip unknown permissions gracefully

        return cls(
            name=data["name"],
            version=data.get("version", "0.1.0"),
            author=data.get("author", ""),
            description=data.get("description", ""),
            icon=data.get("icon", "🔧"),
            tags=data.get("tags", []),
            triggers=triggers,
            tools=tools,
            permissions=permissions,
            dependencies=data.get("dependencies", []),
            config=data.get("config", {}),
            min_bantz_version=data.get("min_bantz_version", "0.1.0"),
        )


@dataclass
class DeclarativeSkill:
    """A fully parsed declarative skill.

    Combines the YAML frontmatter (:class:`SkillMetadata`) with the
    Markdown body (instructions for the LLM).

    Attributes:
        metadata: Parsed YAML frontmatter.
        instructions: Markdown body — LLM context injected at activation.
        source_path: Path to the SKILL.md file on disk.
        _instructions_loaded: Whether the instructions body has been loaded
            (supports progressive loading).
    """

    metadata: SkillMetadata
    instructions: str = ""
    source_path: Optional[Path] = None
    _instructions_loaded: bool = False

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def is_loaded(self) -> bool:
        """Whether the full instructions body has been loaded."""
        return self._instructions_loaded

    def load_instructions(self) -> str:
        """Load the instructions body from disk (progressive loading).

        On first call, reads the Markdown body from the SKILL.md file.
        Subsequent calls return the cached value.
        """
        if self._instructions_loaded:
            return self.instructions

        if self.source_path and self.source_path.exists():
            from bantz.skills.declarative.loader import SkillLoader

            full_skill = SkillLoader.parse_skill_file(self.source_path)
            self.instructions = full_skill.instructions
            self._instructions_loaded = True

        return self.instructions

    def validate(self) -> list[str]:
        """Validate skill definition, return list of errors."""
        errors: list[str] = []

        if not self.metadata.name:
            errors.append("Skill name is required")
        if not self.metadata.name.replace("-", "").replace("_", "").isalnum():
            errors.append(
                f"Skill name must be alphanumeric (with - or _): {self.metadata.name!r}"
            )
        if not self.metadata.description:
            errors.append("Skill description is required")
        if not self.metadata.triggers:
            errors.append("At least one trigger is required")
        if not self.metadata.tools:
            errors.append("At least one tool is required")

        # Check tool name uniqueness
        tool_names = [t.name for t in self.metadata.tools]
        if len(tool_names) != len(set(tool_names)):
            errors.append("Duplicate tool names found")

        # Check trigger intent uniqueness
        intent_names = [t.intent for t in self.metadata.triggers]
        if len(intent_names) != len(set(intent_names)):
            errors.append("Duplicate trigger intent names found")

        return errors
