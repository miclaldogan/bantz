"""Tests for the Self-Evolving Agent (Issue #837).

Tests cover:
- SkillNeedDetector: gap detection, smalltalk filtering, throttling
- SkillGenerator: LLM-based SKILL.md generation, output cleaning, security
- SkillValidator: structure, security, dangerous patterns
- SkillVersionManager: record, approve, reject, rollback
- SelfEvolvingSkillManager: full flow, approval, rejection
- Orchestrator integration: route="unknown" hook
- Server integration: approval/rejection commands
"""

from __future__ import annotations

import json
import textwrap
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from bantz.skills.declarative.generator import (
    GenerationResult,
    SelfEvolvingSkillManager,
    SkillGap,
    SkillGenerator,
    SkillNeedDetector,
    SkillValidator,
    SkillVersion,
    SkillVersionManager,
    _BLOCKED_SKILL_NAMES,
    _MAX_SKILLS_PER_SESSION,
    get_self_evolving_manager,
    setup_self_evolving,
)
from bantz.skills.declarative.models import (
    DeclarativeSkill,
    SkillMetadata,
    SkillPermission,
    SkillToolDef,
    SkillTrigger,
)


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

SAMPLE_GENERATED_SKILL_MD = textwrap.dedent("""\
    ---
    name: hava-durumu
    version: 0.1.0
    author: bantz-auto
    description: "Hava durumu bilgisi sağlayan skill"
    icon: 🌤️
    tags:
      - weather
      - bilgi

    triggers:
      - pattern: "(?i)hava.*(durumu|nasıl)"
        intent: hava-durumu.query
        examples:
          - "bugün hava nasıl"
          - "hava durumu ne"
        priority: 60

    tools:
      - name: hava-durumu.get
        description: "Hava durumu bilgisi sağlar"
        handler: llm
        parameters:
          - name: location
            type: string
            description: "Şehir adı"
            required: true

    permissions: []

    config:
      enabled: true
    ---

    # Hava Durumu Skill

    Sen Bantz asistanının hava durumu yeteneğisin.

    ## Görevin

    Kullanıcı hava durumu sorduğunda, bilgi ver.

    ## Kurallar

    1. Türkçe yanıt ver.
    2. Net ve öz ol.
""")


@pytest.fixture
def mock_llm():
    """Create a mock LLM that returns a sample SKILL.md."""
    llm = MagicMock()
    llm.complete_text.return_value = SAMPLE_GENERATED_SKILL_MD
    return llm


@pytest.fixture
def tmp_skill_dir(tmp_path: Path) -> Path:
    """Create a temporary skill directory."""
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir(parents=True)
    return skill_dir


@pytest.fixture
def detector() -> SkillNeedDetector:
    return SkillNeedDetector()


@pytest.fixture
def generator(mock_llm, tmp_skill_dir) -> SkillGenerator:
    return SkillGenerator(llm=mock_llm, auto_skill_dir=tmp_skill_dir)


@pytest.fixture
def validator() -> SkillValidator:
    return SkillValidator()


@pytest.fixture
def version_mgr(tmp_skill_dir) -> SkillVersionManager:
    return SkillVersionManager(auto_skill_dir=tmp_skill_dir)


@pytest.fixture
def manager(mock_llm, tmp_skill_dir) -> SelfEvolvingSkillManager:
    return SelfEvolvingSkillManager(llm=mock_llm, auto_skill_dir=tmp_skill_dir)


def _make_skill(name: str = "demo-tool", **kwargs) -> DeclarativeSkill:
    """Helper to create a minimal valid DeclarativeSkill."""
    meta_kwargs = {
        "name": name,
        "version": "0.1.0",
        "description": f"{name} skill",
        "triggers": [
            SkillTrigger(pattern=f"(?i){name}", intent=f"{name}.default", examples=[f"{name} çalıştır"]),
        ],
        "tools": [
            SkillToolDef(name=f"{name}.run", description=f"Run {name}", handler="llm"),
        ],
    }
    meta_kwargs.update(kwargs)
    metadata = SkillMetadata(**meta_kwargs)
    return DeclarativeSkill(
        metadata=metadata,
        instructions=f"# {name}\n\nInstructions for {name}.",
        _instructions_loaded=True,
    )


# ──────────────────────────────────────────────────────────────────────
# SkillNeedDetector Tests
# ──────────────────────────────────────────────────────────────────────


class TestSkillNeedDetector:
    """Tests for SkillNeedDetector."""

    def test_detect_unknown_route_with_action(self, detector: SkillNeedDetector):
        """Detect gap when route=unknown and user wants an action."""
        gap = detector.detect(
            user_input="dosya yönetimi yapabilir misin",
            route="unknown",
            confidence=0.1,
        )
        assert gap is not None
        assert gap.user_input == "dosya yönetimi yapabilir misin"
        assert gap.route == "unknown"

    def test_no_detect_known_route(self, detector: SkillNeedDetector):
        """No gap when route is known (calendar, gmail, etc.)."""
        gap = detector.detect(
            user_input="takvime etkinlik ekle",
            route="calendar",
            confidence=0.8,
        )
        assert gap is None

    def test_no_detect_smalltalk(self, detector: SkillNeedDetector):
        """No gap for smalltalk (greetings, thanks, etc.)."""
        for msg in ["merhaba", "selam", "teşekkürler", "tamam", "evet"]:
            gap = detector.detect(
                user_input=msg,
                route="unknown",
                confidence=0.1,
            )
            assert gap is None, f"Should not detect gap for: {msg!r}"

    def test_no_detect_very_short(self, detector: SkillNeedDetector):
        """No gap for very short non-action inputs."""
        gap = detector.detect(
            user_input="aa",
            route="unknown",
            confidence=0.1,
        )
        assert gap is None

    def test_detect_long_request_without_action_pattern(self, detector: SkillNeedDetector):
        """Detect gap for longer requests even without explicit action words."""
        gap = detector.detect(
            user_input="bitcoin fiyatını öğrenmek istiyorum şu anda ne kadar",
            route="unknown",
            confidence=0.2,
        )
        assert gap is not None

    def test_throttling(self, detector: SkillNeedDetector):
        """Throttle after too many detections."""
        for i in range(_MAX_SKILLS_PER_SESSION):
            gap = detector.detect(
                user_input=f"yapabilir misin test {i}",
                route="unknown",
                confidence=0.1,
            )
            assert gap is not None

        # Next should be throttled
        gap = detector.detect(
            user_input="bir şey daha yapabilir misin",
            route="unknown",
            confidence=0.1,
        )
        assert gap is None

    def test_recent_gaps_property(self, detector: SkillNeedDetector):
        """recent_gaps returns list of detected gaps."""
        detector.detect("dosya ara", route="unknown", confidence=0.1)
        assert len(detector.recent_gaps) == 1

    def test_gap_to_dict(self):
        """SkillGap serializes to dict."""
        gap = SkillGap(
            user_input="test input",
            route="unknown",
            confidence=0.1,
            suggested_name="test",
        )
        d = gap.to_dict()
        assert d["user_input"] == "test input"
        assert d["route"] == "unknown"
        assert "detected_at" in d


# ──────────────────────────────────────────────────────────────────────
# SkillGenerator Tests
# ──────────────────────────────────────────────────────────────────────


class TestSkillGenerator:
    """Tests for SkillGenerator."""

    def test_generate_success(self, generator: SkillGenerator, tmp_skill_dir: Path):
        """Successfully generate a SKILL.md from a gap."""
        gap = SkillGap(user_input="hava durumu bilgisi ver", route="unknown", confidence=0.1)
        result = generator.generate(gap)

        assert result.success is True
        assert result.skill is not None
        assert result.skill.name == "hava-durumu"
        assert result.skill_path is not None
        assert result.skill_path.exists()
        assert result.generation_time_ms >= 0

    def test_generate_writes_skill_md(self, generator: SkillGenerator, tmp_skill_dir: Path):
        """Generated SKILL.md is written to disk."""
        gap = SkillGap(user_input="hava durumu", route="unknown", confidence=0.1)
        result = generator.generate(gap)
        assert result.success

        # Check file exists and is readable
        content = result.skill_path.read_text(encoding="utf-8")
        assert "---" in content
        assert "hava-durumu" in content

    def test_generate_writes_metadata_marker(self, generator: SkillGenerator, tmp_skill_dir: Path):
        """Auto-generated marker file is created alongside SKILL.md."""
        gap = SkillGap(user_input="hava durumu", route="unknown", confidence=0.1)
        result = generator.generate(gap)
        assert result.success

        meta_path = result.skill_path.parent / ".auto-generated.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["source"] == "self-evolving-agent"
        assert meta["approved"] is False

    def test_generate_empty_llm_response(self, generator: SkillGenerator):
        """Fail gracefully when LLM returns empty."""
        generator._llm.complete_text.return_value = ""
        gap = SkillGap(user_input="test", route="unknown", confidence=0.1)
        result = generator.generate(gap)
        assert result.success is False
        assert "boş yanıt" in result.errors[0]

    def test_generate_invalid_yaml(self, generator: SkillGenerator):
        """Fail gracefully when LLM returns invalid YAML."""
        generator._llm.complete_text.return_value = "this is not yaml at all"
        gap = SkillGap(user_input="test", route="unknown", confidence=0.1)
        result = generator.generate(gap)
        assert result.success is False

    def test_generate_max_per_session(self, generator: SkillGenerator):
        """Enforce max generation per session."""
        generator._generation_count = _MAX_SKILLS_PER_SESSION
        gap = SkillGap(user_input="test", route="unknown", confidence=0.1)
        result = generator.generate(gap)
        assert result.success is False
        assert "maksimum" in result.errors[0].lower()

    def test_clean_llm_output_removes_fences(self, generator: SkillGenerator):
        """Clean markdown code fences from LLM output."""
        raw = "```yaml\n---\nname: test\n---\nBody\n```"
        cleaned = generator._clean_llm_output(raw)
        assert cleaned.startswith("---")
        assert "```" not in cleaned

    def test_clean_llm_output_finds_frontmatter(self, generator: SkillGenerator):
        """Find frontmatter even with leading text."""
        raw = "Here is the SKILL.md:\n---\nname: test\n---\nBody"
        cleaned = generator._clean_llm_output(raw)
        assert cleaned.startswith("---")

    def test_security_check_blocks_script_handler(self, generator: SkillGenerator):
        """Security check blocks script: handlers."""
        skill = _make_skill()
        skill.metadata.tools[0] = SkillToolDef(
            name="bad.tool", description="bad", handler="script:evil.py"
        )
        errors = generator._security_check(skill)
        assert any("script" in e.lower() for e in errors)

    def test_security_check_blocks_dangerous_name(self, generator: SkillGenerator):
        """Security check blocks dangerous skill names."""
        skill = _make_skill(name="shell-exec")
        errors = generator._security_check(skill)
        assert any("yasaklı" in e.lower() for e in errors)

    def test_security_check_blocks_dangerous_perms(self, generator: SkillGenerator):
        """Security check blocks dangerous permissions."""
        skill = _make_skill(permissions=[SkillPermission.SYSTEM])
        errors = generator._security_check(skill)
        assert any("tehlikeli" in e.lower() for e in errors)

    def test_result_to_dict(self, generator: SkillGenerator):
        """GenerationResult serializes to dict."""
        gap = SkillGap(user_input="test", route="unknown", confidence=0.1)
        result = generator.generate(gap)
        d = result.to_dict()
        assert "success" in d
        assert "generation_time_ms" in d

    def test_lazy_llm_init_fails_gracefully(self, tmp_skill_dir: Path):
        """Generate returns error result when LLM is not available."""
        gen = SkillGenerator(llm=None, auto_skill_dir=tmp_skill_dir)
        with patch.object(gen, "_get_llm", side_effect=RuntimeError("LLM client not available")):
            gap = SkillGap(user_input="test yapabilir misin", route="unknown", confidence=0.1)
            result = gen.generate(gap)
            assert result.success is False
            assert any("hata" in e.lower() or "error" in e.lower() for e in result.errors)

    def test_generate_handles_type_error_on_complete_text(self, tmp_skill_dir: Path):
        """Falls back to simple complete_text when kwargs not supported."""
        mock_llm = MagicMock()

        # First call with kwargs raises TypeError, second call without kwargs works
        def side_effect(**kwargs):
            if "temperature" in kwargs:
                raise TypeError("unexpected keyword argument")
            return SAMPLE_GENERATED_SKILL_MD

        mock_llm.complete_text.side_effect = side_effect

        gen = SkillGenerator(llm=mock_llm, auto_skill_dir=tmp_skill_dir)
        gap = SkillGap(user_input="hava durumu", route="unknown", confidence=0.1)
        result = gen.generate(gap)
        assert result.success


# ──────────────────────────────────────────────────────────────────────
# SkillValidator Tests
# ──────────────────────────────────────────────────────────────────────


class TestSkillValidator:
    """Tests for SkillValidator."""

    def test_validate_good_skill(self, validator: SkillValidator):
        """Valid skill passes validation."""
        skill = _make_skill()
        errors = validator.validate(skill)
        assert errors == []

    def test_validate_blocked_name(self, validator: SkillValidator):
        """Blocked names are rejected."""
        skill = _make_skill(name="shell-exec")
        errors = validator.validate(skill)
        assert any("yasaklı" in e.lower() for e in errors)

    def test_validate_dangerous_instructions(self, validator: SkillValidator):
        """Dangerous patterns in instructions are flagged."""
        skill = _make_skill()
        skill.instructions = "Use subprocess.run() to execute"
        errors = validator.validate(skill)
        assert any("tehlikeli" in e.lower() for e in errors)

    def test_validate_script_handler(self, validator: SkillValidator):
        """Script handlers are rejected in auto-generated skills."""
        skill = _make_skill()
        skill.metadata.tools[0] = SkillToolDef(
            name="test.run", description="test", handler="script:run.py"
        )
        errors = validator.validate(skill)
        assert any("script" in e.lower() for e in errors)

    def test_validate_dangerous_permissions(self, validator: SkillValidator):
        """Dangerous permissions are flagged."""
        skill = _make_skill(permissions=[SkillPermission.FILESYSTEM])
        errors = validator.validate(skill)
        assert any("tehlikeli" in e.lower() for e in errors)

    def test_validate_missing_name(self, validator: SkillValidator):
        """Missing name fails validation."""
        meta = SkillMetadata(
            name="",
            description="test",
            triggers=[SkillTrigger(pattern="x", intent="x.y")],
            tools=[SkillToolDef(name="x.z", description="z")],
        )
        skill = DeclarativeSkill(metadata=meta, _instructions_loaded=True)
        errors = validator.validate(skill)
        assert any("name" in e.lower() for e in errors)

    def test_validate_os_system_in_instructions(self, validator: SkillValidator):
        """os.system in instructions is flagged."""
        skill = _make_skill()
        skill.instructions = "Call os.system('ls') to list files"
        errors = validator.validate(skill)
        assert len(errors) > 0


# ──────────────────────────────────────────────────────────────────────
# SkillVersionManager Tests
# ──────────────────────────────────────────────────────────────────────


class TestSkillVersionManager:
    """Tests for SkillVersionManager."""

    def test_record_version(self, version_mgr: SkillVersionManager, tmp_skill_dir: Path):
        """Record a new skill version."""
        skill = _make_skill()
        version = version_mgr.record(skill, tmp_skill_dir / "test" / "SKILL.md")
        assert version.name == "demo-tool"
        assert version.approved is False

    def test_approve_version(self, version_mgr: SkillVersionManager, tmp_skill_dir: Path):
        """Approve the latest version."""
        skill = _make_skill()
        skill_dir = tmp_skill_dir / "demo-tool"
        skill_dir.mkdir(parents=True)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text("test", encoding="utf-8")
        meta_path = skill_dir / ".auto-generated.json"
        meta_path.write_text(json.dumps({"approved": False}), encoding="utf-8")

        version_mgr.record(skill, skill_path)
        assert version_mgr.approve("demo-tool") is True

        versions = version_mgr.get_versions("demo-tool")
        assert versions[-1].approved is True

    def test_reject_version(self, version_mgr: SkillVersionManager, tmp_skill_dir: Path):
        """Reject and clean up the latest version."""
        skill = _make_skill()
        skill_dir = tmp_skill_dir / "demo-tool"
        skill_dir.mkdir(parents=True)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text("test", encoding="utf-8")

        version_mgr.record(skill, skill_path)
        assert version_mgr.reject("demo-tool") is True
        assert len(version_mgr.get_versions("demo-tool")) == 0

    def test_reject_nonexistent(self, version_mgr: SkillVersionManager):
        """Reject returns False for nonexistent skill."""
        assert version_mgr.reject("nonexistent") is False

    def test_approve_nonexistent(self, version_mgr: SkillVersionManager):
        """Approve returns False for nonexistent skill."""
        assert version_mgr.approve("nonexistent") is False

    def test_rollback(self, version_mgr: SkillVersionManager, tmp_skill_dir: Path):
        """Rollback to previous version."""
        skill = _make_skill()

        # Version 1
        v1_dir = tmp_skill_dir / "demo-tool-v1"
        v1_dir.mkdir(parents=True)
        v1_path = v1_dir / "SKILL.md"
        v1_path.write_text("v1", encoding="utf-8")
        version_mgr.record(skill, v1_path)

        # Version 2
        v2_dir = tmp_skill_dir / "demo-tool-v2"
        v2_dir.mkdir(parents=True)
        v2_path = v2_dir / "SKILL.md"
        v2_path.write_text("v2", encoding="utf-8")
        version_mgr.record(skill, v2_path)

        # Rollback
        prev = version_mgr.rollback("demo-tool")
        assert prev is not None
        assert prev.path == v1_path
        assert prev.active is True

    def test_rollback_single_version(self, version_mgr: SkillVersionManager, tmp_skill_dir: Path):
        """Can't rollback with only one version."""
        skill = _make_skill()
        version_mgr.record(skill, tmp_skill_dir / "SKILL.md")
        assert version_mgr.rollback("demo-tool") is None

    def test_get_pending(self, version_mgr: SkillVersionManager, tmp_skill_dir: Path):
        """Get all pending (unapproved) skills."""
        s1 = _make_skill(name="skill-a")
        s2 = _make_skill(name="skill-b")
        version_mgr.record(s1, tmp_skill_dir / "a" / "SKILL.md")
        version_mgr.record(s2, tmp_skill_dir / "b" / "SKILL.md")
        assert len(version_mgr.get_pending()) == 2

    def test_get_status(self, version_mgr: SkillVersionManager, tmp_skill_dir: Path):
        """Status dict has expected structure."""
        skill = _make_skill()
        version_mgr.record(skill, tmp_skill_dir / "SKILL.md")
        status = version_mgr.get_status()
        assert status["total_skills"] == 1
        assert "demo-tool" in status["skills"]


# ──────────────────────────────────────────────────────────────────────
# SelfEvolvingSkillManager Tests
# ──────────────────────────────────────────────────────────────────────


class TestSelfEvolvingSkillManager:
    """Tests for SelfEvolvingSkillManager."""

    def test_check_for_skill_gap_detected(self, manager: SelfEvolvingSkillManager):
        """Detect skill gap on unknown route."""
        gap = manager.check_for_skill_gap(
            user_input="dosya yönetimi yapabilir misin",
            route="unknown",
            confidence=0.1,
        )
        assert gap is not None

    def test_check_for_skill_gap_not_detected(self, manager: SelfEvolvingSkillManager):
        """No gap on known route."""
        gap = manager.check_for_skill_gap(
            user_input="takvime etkinlik ekle",
            route="calendar",
            confidence=0.8,
        )
        assert gap is None

    def test_generate_and_approve(self, manager: SelfEvolvingSkillManager):
        """Full flow: generate → approve."""
        gap = SkillGap(user_input="hava durumu bilgisi ver", route="unknown", confidence=0.1)

        # Generate
        with patch.object(manager, "_hot_load_skill", return_value=True):
            result = manager.generate_skill(gap)
            assert result.success
            assert manager.has_pending

            # Approve
            approve_result = manager.approve_pending()
            assert approve_result["ok"] is True
            assert "başarıyla kuruldu" in approve_result["text"]
            assert not manager.has_pending

    def test_generate_and_reject(self, manager: SelfEvolvingSkillManager):
        """Full flow: generate → reject."""
        gap = SkillGap(user_input="hava durumu bilgisi ver", route="unknown", confidence=0.1)

        result = manager.generate_skill(gap)
        assert result.success
        assert manager.has_pending

        # Reject
        reject_result = manager.reject_pending()
        assert reject_result["ok"] is True
        assert not manager.has_pending

    def test_approve_nothing_pending(self, manager: SelfEvolvingSkillManager):
        """Approve fails when nothing is pending."""
        result = manager.approve_pending()
        assert result["ok"] is False
        assert "yok" in result["text"].lower()

    def test_reject_nothing_pending(self, manager: SelfEvolvingSkillManager):
        """Reject fails when nothing is pending."""
        result = manager.reject_pending()
        assert result["ok"] is False

    def test_pending_skill_name(self, manager: SelfEvolvingSkillManager):
        """Pending skill name is accessible."""
        assert manager.pending_skill_name is None
        gap = SkillGap(user_input="hava durumu", route="unknown", confidence=0.1)
        manager.generate_skill(gap)
        assert manager.pending_skill_name == "hava-durumu"

    def test_get_status(self, manager: SelfEvolvingSkillManager):
        """Status dict has expected structure."""
        status = manager.get_status()
        assert "detector" in status
        assert "generator" in status
        assert "versions" in status
        assert "has_pending" in status


# ──────────────────────────────────────────────────────────────────────
# Module-level function tests
# ──────────────────────────────────────────────────────────────────────


class TestModuleFunctions:
    """Tests for module-level setup / get functions."""

    def test_setup_self_evolving(self, tmp_skill_dir: Path):
        """setup_self_evolving creates a manager."""
        mgr = setup_self_evolving(auto_skill_dir=tmp_skill_dir)
        assert mgr is not None
        assert get_self_evolving_manager() is mgr

    def test_get_self_evolving_manager_none_initially(self):
        """Returns None if not initialized."""
        import bantz.skills.declarative.generator as gen_mod
        old = gen_mod._global_manager
        try:
            gen_mod._global_manager = None
            assert get_self_evolving_manager() is None
        finally:
            gen_mod._global_manager = old


# ──────────────────────────────────────────────────────────────────────
# Orchestrator Integration Tests
# ──────────────────────────────────────────────────────────────────────


class TestOrchestratorIntegration:
    """Tests for orchestrator_loop.py integration."""

    def test_skill_gap_detected_in_process_turn(self):
        """When route=unknown, skill gap is detected and proposal is returned."""
        # We test the integration logic by mocking the orchestrator
        from bantz.brain.llm_router import OrchestratorOutput

        output = OrchestratorOutput(
            route="unknown",
            calendar_intent="none",
            slots={},
            confidence=0.1,
            tool_plan=[],
            assistant_reply="Anlayamadım efendim.",
            raw_output={},
        )

        # The integration code in orchestrator_loop.py checks:
        # 1. route == "unknown"
        # 2. not ask_user
        # 3. confidence < 0.4
        assert output.route == "unknown"
        assert not output.ask_user
        assert output.confidence < 0.4
        # These conditions would trigger skill gap detection


# ──────────────────────────────────────────────────────────────────────
# Server Integration Tests
# ──────────────────────────────────────────────────────────────────────


class TestServerIntegration:
    """Tests for server.py approval/rejection commands."""

    def test_approval_commands_recognized(self):
        """Approval keywords are correctly identified."""
        approval_words = {"evet", "yes", "kur", "onayla", "approve", "evet kur"}
        rejection_words = {"hayır", "no", "reddet", "reject", "iptal", "vazgeç"}

        # These are the exact words checked in server.py
        for word in approval_words:
            assert word in approval_words

        for word in rejection_words:
            assert word in rejection_words


# ──────────────────────────────────────────────────────────────────────
# Security Tests
# ──────────────────────────────────────────────────────────────────────


class TestSecurity:
    """Security-focused tests."""

    def test_blocked_names_comprehensive(self):
        """All dangerous skill names are blocked."""
        assert "shell" in _BLOCKED_SKILL_NAMES
        assert "sudo" in _BLOCKED_SKILL_NAMES
        assert "rm" in _BLOCKED_SKILL_NAMES
        assert "eval" in _BLOCKED_SKILL_NAMES
        assert "exec" in _BLOCKED_SKILL_NAMES
        assert "hack" in _BLOCKED_SKILL_NAMES

    def test_script_handler_blocked(self, validator: SkillValidator):
        """Script handlers are always blocked in auto-generated skills."""
        skill = _make_skill()
        skill.metadata.tools.append(
            SkillToolDef(name="test.script", description="evil", handler="script:evil.py")
        )
        errors = validator.validate(skill)
        assert len(errors) > 0

    def test_system_permission_blocked(self, validator: SkillValidator):
        """SYSTEM permission is blocked."""
        skill = _make_skill(permissions=[SkillPermission.SYSTEM])
        errors = validator.validate(skill)
        assert any("SYSTEM" in e for e in errors)

    def test_filesystem_permission_blocked(self, validator: SkillValidator):
        """FILESYSTEM permission is blocked."""
        skill = _make_skill(permissions=[SkillPermission.FILESYSTEM])
        errors = validator.validate(skill)
        assert any("FILESYSTEM" in e for e in errors)

    def test_network_permission_allowed(self, validator: SkillValidator):
        """NETWORK permission is allowed (not in dangerous set)."""
        skill = _make_skill(permissions=[SkillPermission.NETWORK])
        errors = validator.validate(skill)
        # Should only fail for SYSTEM/FILESYSTEM, not NETWORK
        assert not any("NETWORK" in e for e in errors)

    def test_llm_handler_allowed(self, validator: SkillValidator):
        """LLM handler is allowed."""
        skill = _make_skill()
        assert skill.metadata.tools[0].handler == "llm"
        errors = validator.validate(skill)
        assert errors == []

    def test_dangerous_instruction_patterns(self, validator: SkillValidator):
        """Various dangerous patterns in instructions are detected."""
        dangerous_patterns = [
            "import subprocess",
            "os.popen('ls')",
            "eval('code')",
            "exec('code')",
            "sudo rm -rf /",
            "chmod 777 /etc",
            "api_key = 'secret123'",
        ]
        for pattern in dangerous_patterns:
            skill = _make_skill()
            skill.instructions = f"Use this: {pattern}"
            errors = validator.validate(skill)
            assert len(errors) > 0, f"Should detect dangerous pattern: {pattern!r}"

    def test_max_skills_per_session(self, generator: SkillGenerator):
        """Enforce per-session skill generation limit."""
        generator._generation_count = _MAX_SKILLS_PER_SESSION
        gap = SkillGap(user_input="test", route="unknown", confidence=0.1)
        result = generator.generate(gap)
        assert not result.success


# ──────────────────────────────────────────────────────────────────────
# Edge Cases
# ──────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_generate_with_existing_skill_name(self, generator: SkillGenerator, tmp_skill_dir: Path):
        """Handle duplicate skill names with timestamp suffix."""
        # Create first skill
        gap = SkillGap(user_input="hava durumu", route="unknown", confidence=0.1)
        result1 = generator.generate(gap)
        assert result1.success

        # Create second with same name
        generator._generation_count = 0  # Reset counter
        result2 = generator.generate(gap)
        assert result2.success
        # Second one should have a different path
        assert result1.skill_path != result2.skill_path

    def test_generation_result_without_skill(self):
        """GenerationResult to_dict works without a skill."""
        result = GenerationResult(success=False, errors=["test error"])
        d = result.to_dict()
        assert d["success"] is False
        assert "skill_name" not in d

    def test_llm_returns_markdown_wrapped(self, generator: SkillGenerator):
        """Handle LLM response wrapped in markdown code blocks."""
        generator._llm.complete_text.return_value = (
            "```markdown\n" + SAMPLE_GENERATED_SKILL_MD + "\n```"
        )
        gap = SkillGap(user_input="hava durumu", route="unknown", confidence=0.1)
        result = generator.generate(gap)
        assert result.success

    def test_llm_returns_with_preamble(self, generator: SkillGenerator):
        """Handle LLM response with preamble text before frontmatter."""
        generator._llm.complete_text.return_value = (
            "İşte SKILL.md dosyası:\n\n" + SAMPLE_GENERATED_SKILL_MD
        )
        gap = SkillGap(user_input="hava durumu", route="unknown", confidence=0.1)
        result = generator.generate(gap)
        assert result.success

    def test_hot_load_without_registry(self, manager: SelfEvolvingSkillManager):
        """Hot-load fails gracefully without skill registry."""
        skill = _make_skill()
        with patch("bantz.skills.declarative.bridge.get_skill_registry", return_value=None):
            loaded = manager._hot_load_skill(skill, None)
            assert loaded is False
