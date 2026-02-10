"""Tests for the Declarative Skill System (Issue #833).

Tests cover:
- SKILL.md parsing (frontmatter + body)
- Skill validation
- Skill discovery from filesystem
- Skill registry operations
- Tool injection into agent ToolRegistry
- Skill executor (LLM, builtin, script handlers)
- Progressive loading
- CLI commands
- Error handling edge cases
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bantz.skills.declarative.models import (
    DeclarativeSkill,
    SkillMetadata,
    SkillPermission,
    SkillToolDef,
    SkillToolParam,
    SkillTrigger,
)
from bantz.skills.declarative.loader import SkillLoader
from bantz.skills.declarative.registry import DeclarativeSkillRegistry
from bantz.skills.declarative.executor import SkillExecutor


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

SAMPLE_SKILL_MD = textwrap.dedent("""\
    ---
    name: test-skill
    version: 1.2.3
    author: Test Author
    description: "A test skill for unit testing."
    icon: 🧪
    tags:
      - test
      - sample
    triggers:
      - pattern: "(?i)test (\\\\w+)"
        intent: test.run
        examples:
          - "test something"
          - "test this"
        priority: 80
        slots:
          query: "\\\\1"
      - pattern: "(?i)hello test"
        intent: test.greet
        examples:
          - "hello test"
    tools:
      - name: test.execute
        description: "Execute a test command"
        handler: llm
        parameters:
          - name: command
            type: string
            description: "The test command"
            required: true
          - name: verbose
            type: boolean
            description: "Enable verbose output"
        returns: "Test result string"
        risk_level: LOW
      - name: test.check
        description: "Check test status"
        handler: builtin:system.status
        parameters:
          - name: target
            type: string
            description: "What to check"
    permissions:
      - network
      - filesystem
    dependencies:
      - greeting
    config:
      timeout: 30
      retries: 3
    ---

    # Test Skill

    Sen bir test asistanısın.

    ## Görevin

    Test komutlarını çalıştır ve sonuçları raporla.

    ## Kurallar

    1. Her zaman Türkçe yanıt ver.
    2. Test sonuçlarını net göster.
""")

MINIMAL_SKILL_MD = textwrap.dedent("""\
    ---
    name: minimal
    description: "Minimal skill"
    triggers:
      - pattern: "minimal"
        intent: minimal.run
    tools:
      - name: minimal.do
        description: "Do something"
    ---

    Minimal instructions.
""")

INVALID_NO_FRONTMATTER = "This is not a valid SKILL.md file."

INVALID_YAML = textwrap.dedent("""\
    ---
    name: broken
    description: [invalid yaml
    ---

    Body.
""")


@pytest.fixture
def skill_dir(tmp_path: Path) -> Path:
    """Create a temporary skill directory with sample skills."""
    # test-skill
    test_dir = tmp_path / "test-skill"
    test_dir.mkdir()
    (test_dir / "SKILL.md").write_text(SAMPLE_SKILL_MD, encoding="utf-8")

    # minimal
    min_dir = tmp_path / "minimal"
    min_dir.mkdir()
    (min_dir / "SKILL.md").write_text(MINIMAL_SKILL_MD, encoding="utf-8")

    return tmp_path


@pytest.fixture
def loader(skill_dir: Path) -> SkillLoader:
    """Create a SkillLoader pointing to the test skill directory."""
    return SkillLoader(skill_dirs=[skill_dir], lazy=False)


@pytest.fixture
def lazy_loader(skill_dir: Path) -> SkillLoader:
    """Create a lazy SkillLoader."""
    return SkillLoader(skill_dirs=[skill_dir], lazy=True)


@pytest.fixture
def registry() -> DeclarativeSkillRegistry:
    return DeclarativeSkillRegistry()


@pytest.fixture
def sample_skill(skill_dir: Path) -> DeclarativeSkill:
    """Parse the sample SKILL.md file."""
    return SkillLoader.parse_skill_file(skill_dir / "test-skill" / "SKILL.md")


# ──────────────────────────────────────────────────────────────────────
# Model Tests
# ──────────────────────────────────────────────────────────────────────

class TestSkillPermission:
    def test_from_string(self):
        assert SkillPermission.from_string("network") == SkillPermission.NETWORK
        assert SkillPermission.from_string("FILESYSTEM") == SkillPermission.FILESYSTEM
        assert SkillPermission.from_string("  browser  ") == SkillPermission.BROWSER

    def test_from_string_invalid(self):
        with pytest.raises(ValueError, match="Unknown permission"):
            SkillPermission.from_string("nonexistent")


class TestSkillTrigger:
    def test_from_dict(self):
        data = {
            "pattern": "(?i)hello",
            "intent": "greet.hello",
            "examples": ["hello", "hi"],
            "priority": 90,
        }
        trigger = SkillTrigger.from_dict(data)
        assert trigger.pattern == "(?i)hello"
        assert trigger.intent == "greet.hello"
        assert trigger.examples == ["hello", "hi"]
        assert trigger.priority == 90

    def test_from_dict_defaults(self):
        data = {"pattern": "test", "intent": "test.run"}
        trigger = SkillTrigger.from_dict(data)
        assert trigger.priority == 50
        assert trigger.examples == []
        assert trigger.slots == {}

    def test_invalid_regex(self):
        with pytest.raises(ValueError, match="Invalid regex"):
            SkillTrigger(pattern="[invalid", intent="test")


class TestSkillToolParam:
    def test_to_json_schema(self):
        param = SkillToolParam(
            name="query",
            type="string",
            description="Search query",
            enum=["a", "b"],
            default="a",
        )
        schema = param.to_json_schema()
        assert schema["type"] == "string"
        assert schema["description"] == "Search query"
        assert schema["enum"] == ["a", "b"]
        assert schema["default"] == "a"


class TestSkillToolDef:
    def test_from_dict(self):
        data = {
            "name": "test.run",
            "description": "Run a test",
            "handler": "llm",
            "parameters": [
                {"name": "cmd", "type": "string", "required": True},
            ],
            "risk_level": "MED",
            "requires_confirmation": True,
        }
        tool = SkillToolDef.from_dict(data)
        assert tool.name == "test.run"
        assert tool.handler == "llm"
        assert tool.risk_level == "MED"
        assert tool.requires_confirmation is True
        assert len(tool.parameters) == 1
        assert tool.parameters[0].name == "cmd"

    def test_to_json_schema(self):
        tool = SkillToolDef(
            name="test",
            description="Test",
            parameters=[
                SkillToolParam(name="a", type="string", required=True),
                SkillToolParam(name="b", type="integer"),
            ],
        )
        schema = tool.to_json_schema()
        assert schema["type"] == "object"
        assert "a" in schema["properties"]
        assert "b" in schema["properties"]
        assert schema["required"] == ["a"]


class TestSkillMetadata:
    def test_from_dict_full(self):
        data = {
            "name": "test",
            "version": "2.0.0",
            "author": "Me",
            "description": "Test skill",
            "icon": "🧪",
            "tags": ["test"],
            "triggers": [{"pattern": "test", "intent": "test.run"}],
            "tools": [{"name": "test.do", "description": "Do"}],
            "permissions": ["network", "filesystem"],
            "dependencies": ["other"],
            "config": {"key": "value"},
        }
        meta = SkillMetadata.from_dict(data)
        assert meta.name == "test"
        assert meta.version == "2.0.0"
        assert len(meta.triggers) == 1
        assert len(meta.tools) == 1
        assert SkillPermission.NETWORK in meta.permissions
        assert meta.dependencies == ["other"]
        assert meta.config == {"key": "value"}

    def test_from_dict_minimal(self):
        data = {"name": "min"}
        meta = SkillMetadata.from_dict(data)
        assert meta.name == "min"
        assert meta.version == "0.1.0"
        assert meta.triggers == []
        assert meta.tools == []
        assert meta.permissions == []

    def test_unknown_permission_skipped(self):
        data = {
            "name": "test",
            "permissions": ["network", "unknown_perm", "filesystem"],
        }
        meta = SkillMetadata.from_dict(data)
        assert len(meta.permissions) == 2


class TestDeclarativeSkill:
    def test_validate_valid(self, sample_skill: DeclarativeSkill):
        errors = sample_skill.validate()
        assert errors == []

    def test_validate_missing_name(self):
        meta = SkillMetadata(name="", description="Test")
        skill = DeclarativeSkill(metadata=meta)
        errors = skill.validate()
        assert any("name is required" in e for e in errors)

    def test_validate_missing_description(self):
        meta = SkillMetadata(name="test", description="")
        skill = DeclarativeSkill(metadata=meta)
        errors = skill.validate()
        assert any("description is required" in e for e in errors)

    def test_validate_missing_triggers(self):
        meta = SkillMetadata(
            name="test", description="Test",
            tools=[SkillToolDef(name="t", description="d")],
        )
        skill = DeclarativeSkill(metadata=meta)
        errors = skill.validate()
        assert any("trigger" in e.lower() for e in errors)

    def test_validate_missing_tools(self):
        meta = SkillMetadata(
            name="test", description="Test",
            triggers=[SkillTrigger(pattern="t", intent="t.r")],
        )
        skill = DeclarativeSkill(metadata=meta)
        errors = skill.validate()
        assert any("tool" in e.lower() for e in errors)

    def test_validate_duplicate_tools(self):
        meta = SkillMetadata(
            name="test", description="Test",
            triggers=[SkillTrigger(pattern="t", intent="t.r")],
            tools=[
                SkillToolDef(name="same", description="a"),
                SkillToolDef(name="same", description="b"),
            ],
        )
        skill = DeclarativeSkill(metadata=meta)
        errors = skill.validate()
        assert any("duplicate tool" in e.lower() for e in errors)

    def test_validate_invalid_name(self):
        meta = SkillMetadata(
            name="bad name!", description="Test",
            triggers=[SkillTrigger(pattern="t", intent="t.r")],
            tools=[SkillToolDef(name="t", description="d")],
        )
        skill = DeclarativeSkill(metadata=meta)
        errors = skill.validate()
        assert any("alphanumeric" in e for e in errors)


# ──────────────────────────────────────────────────────────────────────
# Loader Tests
# ──────────────────────────────────────────────────────────────────────

class TestSkillLoader:
    def test_parse_skill_file(self, skill_dir: Path):
        skill = SkillLoader.parse_skill_file(
            skill_dir / "test-skill" / "SKILL.md"
        )
        assert skill.name == "test-skill"
        assert skill.metadata.version == "1.2.3"
        assert skill.metadata.author == "Test Author"
        assert skill.metadata.icon == "🧪"
        assert len(skill.metadata.triggers) == 2
        assert len(skill.metadata.tools) == 2
        assert SkillPermission.NETWORK in skill.metadata.permissions
        assert SkillPermission.FILESYSTEM in skill.metadata.permissions
        assert "test asistanısın" in skill.instructions
        assert skill.is_loaded is True

    def test_parse_frontmatter_only(self, skill_dir: Path):
        skill = SkillLoader.parse_frontmatter_only(
            skill_dir / "test-skill" / "SKILL.md"
        )
        assert skill.name == "test-skill"
        assert skill.instructions == ""
        assert skill.is_loaded is False

    def test_parse_invalid_no_frontmatter(self, tmp_path: Path):
        f = tmp_path / "bad.md"
        f.write_text(INVALID_NO_FRONTMATTER, encoding="utf-8")
        with pytest.raises(ValueError, match="No valid YAML frontmatter"):
            SkillLoader.parse_skill_file(f)

    def test_parse_invalid_yaml(self, tmp_path: Path):
        f = tmp_path / "bad.md"
        f.write_text(INVALID_YAML, encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid YAML"):
            SkillLoader.parse_skill_file(f)

    def test_discover(self, loader: SkillLoader):
        skills = loader.discover()
        names = {s.name for s in skills}
        assert "test-skill" in names
        assert "minimal" in names
        assert len(skills) == 2

    def test_discover_lazy(self, lazy_loader: SkillLoader):
        skills = lazy_loader.discover()
        assert len(skills) == 2
        # Instructions should NOT be loaded in lazy mode
        for s in skills:
            assert s.is_loaded is False

    def test_discover_empty_dir(self, tmp_path: Path):
        loader = SkillLoader(skill_dirs=[tmp_path / "nonexistent"])
        skills = loader.discover()
        assert skills == []

    def test_discover_skips_invalid(self, skill_dir: Path):
        # Add an invalid skill
        bad_dir = skill_dir / "bad-skill"
        bad_dir.mkdir()
        (bad_dir / "SKILL.md").write_text("not valid", encoding="utf-8")

        loader = SkillLoader(skill_dirs=[skill_dir], lazy=False)
        skills = loader.discover()
        # Should still load the valid ones
        assert len(skills) == 2

    def test_discover_skips_duplicate(self, tmp_path: Path):
        # Two directories with same skill name
        dir1 = tmp_path / "dir1" / "minimal"
        dir1.mkdir(parents=True)
        (dir1 / "SKILL.md").write_text(MINIMAL_SKILL_MD, encoding="utf-8")

        dir2 = tmp_path / "dir2" / "minimal"
        dir2.mkdir(parents=True)
        (dir2 / "SKILL.md").write_text(MINIMAL_SKILL_MD, encoding="utf-8")

        loader = SkillLoader(
            skill_dirs=[tmp_path / "dir1", tmp_path / "dir2"], lazy=False
        )
        skills = loader.discover()
        assert len(skills) == 1

    def test_create_skill_scaffold(self, tmp_path: Path):
        path = SkillLoader.create_skill_scaffold(
            name="my-skill",
            target_dir=tmp_path,
            description="My awesome skill",
            author="Test",
        )
        assert path.exists()
        assert path.name == "SKILL.md"

        # Should be parseable
        skill = SkillLoader.parse_skill_file(path)
        assert skill.name == "my-skill"
        assert "My awesome skill" in skill.metadata.description

    def test_create_skill_scaffold_exists(self, tmp_path: Path):
        SkillLoader.create_skill_scaffold(name="dup", target_dir=tmp_path)
        with pytest.raises(FileExistsError):
            SkillLoader.create_skill_scaffold(name="dup", target_dir=tmp_path)

    def test_progressive_loading(self, lazy_loader: SkillLoader, skill_dir: Path):
        skills = lazy_loader.discover()
        test_skill = next(s for s in skills if s.name == "test-skill")

        assert test_skill.is_loaded is False
        assert test_skill.instructions == ""

        # Load instructions
        instructions = test_skill.load_instructions()
        assert test_skill.is_loaded is True
        assert "test asistanısın" in instructions

        # Second call returns cached
        instructions2 = test_skill.load_instructions()
        assert instructions2 == instructions


# ──────────────────────────────────────────────────────────────────────
# Registry Tests
# ──────────────────────────────────────────────────────────────────────

class TestDeclarativeSkillRegistry:
    def test_register(self, registry: DeclarativeSkillRegistry, sample_skill):
        registry.register(sample_skill)
        assert sample_skill.name in registry.skill_names
        assert registry.get(sample_skill.name) is sample_skill

    def test_register_duplicate(self, registry, sample_skill):
        registry.register(sample_skill)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(sample_skill)

    def test_unregister(self, registry, sample_skill):
        registry.register(sample_skill)
        assert registry.unregister(sample_skill.name) is True
        assert registry.get(sample_skill.name) is None

    def test_unregister_missing(self, registry):
        assert registry.unregister("nope") is False

    def test_get_by_intent(self, registry, sample_skill):
        registry.register(sample_skill)
        found = registry.get_by_intent("test.run")
        assert found is sample_skill
        assert registry.get_by_intent("nonexistent") is None

    def test_get_by_tool(self, registry, sample_skill):
        registry.register(sample_skill)
        found = registry.get_by_tool("test.execute")
        assert found is sample_skill
        assert registry.get_by_tool("nonexistent") is None

    def test_get_all_intents(self, registry, sample_skill):
        registry.register(sample_skill)
        intents = registry.get_all_intents()
        assert len(intents) == 2
        intent_names = {i["intent"] for i in intents}
        assert "test.run" in intent_names
        assert "test.greet" in intent_names
        assert all(i["skill_name"] == "test-skill" for i in intents)

    def test_get_all_tool_defs(self, registry, sample_skill):
        registry.register(sample_skill)
        tools = registry.get_all_tool_defs()
        assert len(tools) == 2
        tool_names = {t.name for t in tools}
        assert "test.execute" in tool_names
        assert "test.check" in tool_names

    def test_inject_into_tool_registry(self, registry, sample_skill):
        from bantz.agent.tools import ToolRegistry

        registry.register(sample_skill)
        tool_reg = ToolRegistry()
        count = registry.inject_into_tool_registry(tool_reg)

        assert count == 2
        assert tool_reg.get("test.execute") is not None
        assert tool_reg.get("test.check") is not None

        # Verify tool schema
        tool = tool_reg.get("test.execute")
        assert tool.description == "Execute a test command"
        assert "command" in tool.parameters["properties"]
        assert tool.function is not None

    def test_inject_skips_existing(self, registry, sample_skill):
        from bantz.agent.tools import Tool, ToolRegistry

        registry.register(sample_skill)
        tool_reg = ToolRegistry()

        # Pre-register one tool
        tool_reg.register(Tool(
            name="test.execute",
            description="Existing",
            parameters={},
            function=lambda: None,
        ))

        count = registry.inject_into_tool_registry(tool_reg)
        assert count == 1  # Only test.check injected

        # Original tool should not be overridden
        assert tool_reg.get("test.execute").description == "Existing"

    def test_get_status(self, registry, sample_skill):
        registry.register(sample_skill)
        status = registry.get_status()
        assert status["total_skills"] == 1
        assert status["total_triggers"] == 2
        assert status["total_tools"] == 2
        assert "test-skill" in status["skills"]


# ──────────────────────────────────────────────────────────────────────
# Executor Tests
# ──────────────────────────────────────────────────────────────────────

class TestSkillExecutor:
    def test_execute_llm_handler(self, registry, sample_skill):
        registry.register(sample_skill)
        executor = SkillExecutor(registry)

        result = executor.execute("test.execute", {"command": "run_test"})
        assert result["success"] is True
        assert result["handler"] == "llm"
        assert result["skill"] == "test-skill"
        assert "instructions" in result
        assert result["parameters"] == {"command": "run_test"}

    def test_execute_builtin_handler(self, registry, sample_skill):
        from bantz.agent.tools import Tool, ToolRegistry

        registry.register(sample_skill)

        # Create a mock runtime registry
        runtime = ToolRegistry()
        runtime.register(Tool(
            name="system.status",
            description="System status",
            parameters={},
            function=lambda **kw: {"cpu": "50%", "ram": "8GB"},
        ))

        executor = SkillExecutor(registry, runtime_tools=runtime)
        result = executor.execute("test.check", {"target": "cpu"})
        assert result["success"] is True
        assert result["handler"] == "builtin:system.status"
        assert result["result"] == {"cpu": "50%", "ram": "8GB"}

    def test_execute_builtin_no_registry(self, registry, sample_skill):
        registry.register(sample_skill)
        executor = SkillExecutor(registry)  # No runtime tools
        result = executor.execute("test.check", {})
        assert result["success"] is False
        assert "No runtime tool registry" in result["result"]

    def test_execute_builtin_tool_not_found(self, registry, sample_skill):
        from bantz.agent.tools import ToolRegistry

        registry.register(sample_skill)
        executor = SkillExecutor(registry, runtime_tools=ToolRegistry())
        result = executor.execute("test.check", {})
        assert result["success"] is False
        assert "not found" in result["result"]

    def test_execute_unknown_tool(self, registry):
        executor = SkillExecutor(registry)
        result = executor.execute("nonexistent.tool", {})
        assert result["success"] is False
        assert "No skill found" in result["result"]

    def test_execute_script_handler(self, tmp_path):
        """Test script execution handler."""
        # Create a skill with a script handler
        skill_dir = tmp_path / "script-skill"
        skill_dir.mkdir()
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()

        # Create a simple script
        script = scripts_dir / "hello.py"
        script.write_text(
            'import json, sys\n'
            'params = json.loads(sys.stdin.read())\n'
            'print(json.dumps({"greeting": f"Hello {params.get(\'name\', \'World\')}!"}))\n',
            encoding="utf-8",
        )

        skill_md = textwrap.dedent("""\
            ---
            name: script-test
            description: "Script test"
            triggers:
              - pattern: "script"
                intent: script.run
            tools:
              - name: script.hello
                description: "Say hello via script"
                handler: "script:hello.py"
                parameters:
                  - name: name
                    type: string
            ---

            Script test instructions.
        """)
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

        loader = SkillLoader(skill_dirs=[tmp_path], lazy=False)
        skills = loader.discover()
        assert len(skills) == 1

        reg = DeclarativeSkillRegistry()
        reg.register(skills[0])

        executor = SkillExecutor(reg)
        result = executor.execute("script.hello", {"name": "Bantz"})
        assert result["success"] is True
        assert result["result"]["greeting"] == "Hello Bantz!"
        assert result["handler"] == "script:hello.py"

    def test_execute_script_not_found(self, tmp_path):
        skill_dir = tmp_path / "bad-script"
        skill_dir.mkdir()

        skill_md = textwrap.dedent("""\
            ---
            name: bad-script
            description: "Missing script"
            triggers:
              - pattern: "bad"
                intent: bad.run
            tools:
              - name: bad.run
                description: "Will fail"
                handler: "script:nonexistent.py"
            ---

            Instructions.
        """)
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

        loader = SkillLoader(skill_dirs=[tmp_path], lazy=False)
        skills = loader.discover()
        reg = DeclarativeSkillRegistry()
        reg.register(skills[0])

        executor = SkillExecutor(reg)
        result = executor.execute("bad.run", {})
        assert result["success"] is False
        assert "not found" in result["result"]

    def test_execute_script_path_traversal(self, tmp_path):
        """Script handler should reject path traversal attempts."""
        skill_dir = tmp_path / "traversal"
        skill_dir.mkdir()
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()

        skill_md = textwrap.dedent("""\
            ---
            name: traversal
            description: "Traversal test"
            triggers:
              - pattern: "hack"
                intent: traversal.run
            tools:
              - name: traversal.run
                description: "Try path traversal"
                handler: "script:../../etc/passwd"
            ---

            Instructions.
        """)
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

        loader = SkillLoader(skill_dirs=[tmp_path], lazy=False)
        skills = loader.discover()
        reg = DeclarativeSkillRegistry()
        reg.register(skills[0])

        executor = SkillExecutor(reg)
        result = executor.execute("traversal.run", {})
        assert result["success"] is False
        # Should fail for either "not found" or "traversal detected"


# ──────────────────────────────────────────────────────────────────────
# Bridge Tests
# ──────────────────────────────────────────────────────────────────────

class TestBridge:
    def test_setup_declarative_skills(self, skill_dir):
        from bantz.agent.tools import ToolRegistry
        from bantz.skills.declarative.bridge import (
            setup_declarative_skills,
            get_skill_registry,
            get_skill_context_for_tool,
            get_skill_triggers,
        )

        tool_reg = ToolRegistry()
        skill_reg = setup_declarative_skills(tool_reg, skill_dirs=[skill_dir])

        assert skill_reg is not None
        assert len(skill_reg.skill_names) == 2
        assert get_skill_registry() is skill_reg

        # Tools should be injected
        assert tool_reg.get("test.execute") is not None
        assert tool_reg.get("minimal.do") is not None

        # Triggers should be available
        triggers = get_skill_triggers()
        assert len(triggers) >= 2

        # Context for LLM tool
        ctx = get_skill_context_for_tool("test.execute")
        assert ctx is not None
        assert "test asistanısın" in ctx

        # No context for unknown tool
        assert get_skill_context_for_tool("unknown") is None

    def test_setup_empty_dir(self, tmp_path):
        from bantz.agent.tools import ToolRegistry
        from bantz.skills.declarative.bridge import setup_declarative_skills

        tool_reg = ToolRegistry()
        skill_reg = setup_declarative_skills(
            tool_reg, skill_dirs=[tmp_path / "empty"]
        )
        assert len(skill_reg.skill_names) == 0


# ──────────────────────────────────────────────────────────────────────
# CLI Tests
# ──────────────────────────────────────────────────────────────────────

class TestCLI:
    def test_cmd_list_empty(self, tmp_path, capsys):
        from bantz.skills.declarative.cli import handle_skill_command

        args = MagicMock()
        args.skill_action = "list"
        args.as_json = False
        args.dir = str(tmp_path)

        result = handle_skill_command(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "bulunamadı" in captured.out

    def test_cmd_list_with_skills(self, skill_dir, capsys):
        from bantz.skills.declarative.cli import handle_skill_command

        args = MagicMock()
        args.skill_action = "list"
        args.as_json = False
        args.dir = str(skill_dir)

        result = handle_skill_command(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "test-skill" in captured.out
        assert "minimal" in captured.out

    def test_cmd_list_json(self, skill_dir, capsys):
        from bantz.skills.declarative.cli import handle_skill_command

        args = MagicMock()
        args.skill_action = "list"
        args.as_json = True
        args.dir = str(skill_dir)

        result = handle_skill_command(args)
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["total_skills"] == 2

    def test_cmd_info(self, skill_dir, capsys):
        from bantz.skills.declarative.cli import handle_skill_command

        args = MagicMock()
        args.skill_action = "info"
        args.name = "test-skill"
        args.dir = str(skill_dir)

        result = handle_skill_command(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "test-skill" in captured.out
        assert "Test Author" in captured.out

    def test_cmd_info_not_found(self, skill_dir, capsys):
        from bantz.skills.declarative.cli import handle_skill_command

        args = MagicMock()
        args.skill_action = "info"
        args.name = "nonexistent"
        args.dir = str(skill_dir)

        result = handle_skill_command(args)
        assert result == 1

    def test_cmd_create(self, tmp_path, capsys):
        from bantz.skills.declarative.cli import handle_skill_command

        args = MagicMock()
        args.skill_action = "create"
        args.name = "new-skill"
        args.dir = str(tmp_path)
        args.description = "A brand new skill"
        args.author = "Test"

        result = handle_skill_command(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "oluşturuldu" in captured.out

        # Verify the file was created and is valid
        skill_file = tmp_path / "new-skill" / "SKILL.md"
        assert skill_file.exists()
        skill = SkillLoader.parse_skill_file(skill_file)
        assert skill.name == "new-skill"

    def test_cmd_validate_valid(self, skill_dir, capsys):
        from bantz.skills.declarative.cli import handle_skill_command

        args = MagicMock()
        args.skill_action = "validate"
        args.path = str(skill_dir / "test-skill" / "SKILL.md")

        result = handle_skill_command(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "Geçerli" in captured.out

    def test_cmd_validate_invalid(self, tmp_path, capsys):
        from bantz.skills.declarative.cli import handle_skill_command

        f = tmp_path / "bad.md"
        f.write_text(INVALID_NO_FRONTMATTER, encoding="utf-8")

        args = MagicMock()
        args.skill_action = "validate"
        args.path = str(f)

        result = handle_skill_command(args)
        assert result == 1

    def test_cmd_validate_not_found(self, capsys):
        from bantz.skills.declarative.cli import handle_skill_command

        args = MagicMock()
        args.skill_action = "validate"
        args.path = "/nonexistent/SKILL.md"

        result = handle_skill_command(args)
        assert result == 1


# ──────────────────────────────────────────────────────────────────────
# Integration / Edge-case Tests
# ──────────────────────────────────────────────────────────────────────

class TestIntegration:
    def test_full_pipeline_discover_register_inject_execute(self, skill_dir):
        """Full end-to-end: discover → register → inject → execute."""
        from bantz.agent.tools import ToolRegistry

        loader = SkillLoader(skill_dirs=[skill_dir], lazy=True)
        registry = DeclarativeSkillRegistry()
        tool_reg = ToolRegistry()

        # Discover
        skills = loader.discover()
        assert len(skills) == 2

        # Register
        for s in skills:
            registry.register(s)

        # Inject
        count = registry.inject_into_tool_registry(tool_reg)
        assert count >= 2

        # Execute via tool registry function
        tool = tool_reg.get("test.execute")
        assert tool is not None
        assert tool.function is not None

        result = tool.function(command="hello")
        assert result["success"] is True
        assert result["handler"] == "llm"
        # Progressive loading should have loaded instructions
        test_skill = registry.get("test-skill")
        assert test_skill.is_loaded is True

    def test_builtin_skills_from_skills_dir(self):
        """Test loading the built-in example skills from skills/ directory."""
        # Try multiple possible locations
        test_file = Path(__file__).resolve()
        project_root = test_file.parent.parent
        project_skills = project_root / "skills"
        if not project_skills.is_dir():
            # Try from CWD
            project_skills = Path.cwd() / "skills"
        if not project_skills.is_dir():
            pytest.skip("Built-in skills directory not found")

        loader = SkillLoader(skill_dirs=[project_skills], lazy=False)
        skills = loader.discover()

        # We should find the example skills we created
        names = {s.name for s in skills}
        # At least greeting and weather should be there
        assert len(skills) >= 2, f"Expected ≥2 skills, got: {names}"

        # All should be valid
        for skill in skills:
            errors = skill.validate()
            assert errors == [], f"Skill {skill.name} has errors: {errors}"

    def test_env_var_skill_dir(self, skill_dir, monkeypatch):
        """Test BANTZ_SKILLS_DIR env var."""
        monkeypatch.setenv("BANTZ_SKILLS_DIR", str(skill_dir))
        loader = SkillLoader()  # Should use default dirs including env
        skills = loader.discover()
        names = {s.name for s in skills}
        assert "test-skill" in names
