"""Tests for Issue #874: Personality Injection — Kişilik ve Tercihler LLM Prompt'a Enjekte.

Validates:
1. PersonalityInjector creation & config
2. Layer 1: Persona block (identity, style, honorifics)
3. Layer 2: User prefs block (facts, preferences)
4. Layer 3: Behavior rules block (confirmation, language)
5. Combined blocks (router & finalizer)
6. Token budget enforcement (~450 tokens max)
7. Preset switching (jarvis → friday → alfred)
8. PromptBuilder personality_block integration
9. FinalizationContext personality_block field
10. Fallback prompt personality awareness

Run one class at a time:
    python3 -m pytest tests/test_issue_874_personality_injection.py::TestPersonalityConfig -x -v --tb=short --no-header -p no:cacheprovider -p no:randomly
"""

from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_SRC = Path(__file__).resolve().parent.parent / "src" / "bantz"


# =========================================================================
# Class 1: PersonalityConfig Tests
# =========================================================================


class TestPersonalityConfig(unittest.TestCase):
    """Test PersonalityConfig creation and env loading."""

    def test_import(self):
        from bantz.brain.personality_injector import PersonalityConfig
        self.assertTrue(callable(PersonalityConfig))

    def test_defaults(self):
        from bantz.brain.personality_injector import PersonalityConfig
        cfg = PersonalityConfig()
        self.assertEqual(cfg.preset_name, "jarvis")
        self.assertEqual(cfg.user_name, "")
        self.assertEqual(cfg.confirmation_mode, "dangerous")
        self.assertEqual(cfg.verbosity, "short")
        self.assertEqual(cfg.response_language, "tr")

    def test_from_env(self):
        from bantz.brain.personality_injector import PersonalityConfig
        env = {
            "BANTZ_PERSONALITY": "friday",
            "BANTZ_USER_NAME": "İclal",
            "BANTZ_CONFIRMATION_MODE": "always",
            "BANTZ_VERBOSITY": "detailed",
        }
        with patch.dict(os.environ, env):
            cfg = PersonalityConfig.from_env()
            self.assertEqual(cfg.preset_name, "friday")
            self.assertEqual(cfg.user_name, "İclal")
            self.assertEqual(cfg.confirmation_mode, "always")
            self.assertEqual(cfg.verbosity, "detailed")

    def test_from_env_defaults(self):
        from bantz.brain.personality_injector import PersonalityConfig
        # Clear env vars
        env = {k: "" for k in [
            "BANTZ_PERSONALITY", "BANTZ_USER_NAME",
            "BANTZ_CONFIRMATION_MODE", "BANTZ_VERBOSITY",
        ]}
        with patch.dict(os.environ, env, clear=False):
            cfg = PersonalityConfig.from_env()
            # Should not crash
            self.assertIsNotNone(cfg.preset_name)

    def test_token_budgets(self):
        from bantz.brain.personality_injector import (
            PersonalityConfig, _PERSONA_MAX_CHARS,
            _PREFS_MAX_CHARS, _RULES_MAX_CHARS,
        )
        cfg = PersonalityConfig()
        self.assertEqual(cfg.persona_max_chars, _PERSONA_MAX_CHARS)
        self.assertEqual(cfg.prefs_max_chars, _PREFS_MAX_CHARS)
        self.assertEqual(cfg.rules_max_chars, _RULES_MAX_CHARS)


# =========================================================================
# Class 2: PersonalityInjector Unit Tests
# =========================================================================


class TestPersonalityInjector(unittest.TestCase):
    """Test PersonalityInjector core functionality."""

    def test_import(self):
        from bantz.brain.personality_injector import PersonalityInjector
        self.assertTrue(callable(PersonalityInjector))

    def test_init_default(self):
        from bantz.brain.personality_injector import PersonalityInjector
        inj = PersonalityInjector()
        self.assertIsNotNone(inj)
        self.assertEqual(inj.config.preset_name, "jarvis")

    def test_name_property(self):
        from bantz.brain.personality_injector import PersonalityInjector
        inj = PersonalityInjector()
        name = inj.name
        self.assertIsInstance(name, str)
        self.assertTrue(len(name) > 0)

    def test_uses_honorifics_jarvis(self):
        from bantz.brain.personality_injector import PersonalityInjector, PersonalityConfig
        cfg = PersonalityConfig(preset_name="jarvis")
        inj = PersonalityInjector(config=cfg)
        self.assertTrue(inj.uses_honorifics)

    def test_uses_honorifics_friday(self):
        from bantz.brain.personality_injector import PersonalityInjector, PersonalityConfig
        cfg = PersonalityConfig(preset_name="friday")
        inj = PersonalityInjector(config=cfg)
        self.assertFalse(inj.uses_honorifics)

    def test_personality_loaded(self):
        from bantz.brain.personality_injector import PersonalityInjector
        inj = PersonalityInjector()
        # Should have loaded the personality preset
        self.assertIsNotNone(inj.personality)

    def test_repr(self):
        from bantz.brain.personality_injector import PersonalityInjector
        inj = PersonalityInjector()
        r = repr(inj)
        self.assertIn("PersonalityInjector", r)
        self.assertIn("jarvis", r)


# =========================================================================
# Class 3: Layer Building Tests
# =========================================================================


class TestLayerBuilding(unittest.TestCase):
    """Test individual layer blocks."""

    def _make_injector(self, preset="jarvis", verbosity="short"):
        from bantz.brain.personality_injector import PersonalityInjector, PersonalityConfig
        cfg = PersonalityConfig(preset_name=preset, verbosity=verbosity)
        return PersonalityInjector(config=cfg)

    # -- Layer 1: Persona --

    def test_persona_block_not_empty(self):
        inj = self._make_injector()
        block = inj._build_persona_block("İclal")
        self.assertTrue(len(block) > 0)
        self.assertIn("İclal", block)

    def test_persona_block_contains_name(self):
        inj = self._make_injector()
        block = inj._build_persona_block("TestUser")
        self.assertIn("TestUser", block)

    def test_persona_block_jarvis_honorifics(self):
        inj = self._make_injector("jarvis")
        block = inj._build_persona_block()
        self.assertIn("Efendim", block)

    def test_persona_block_friday_no_honorifics(self):
        inj = self._make_injector("friday")
        block = inj._build_persona_block()
        self.assertIn("Samimi", block)
        self.assertNotIn("Efendim", block)

    def test_persona_block_short_verbosity(self):
        inj = self._make_injector(verbosity="short")
        block = inj._build_persona_block()
        self.assertIn("Kısa", block)

    def test_persona_block_detailed_verbosity(self):
        inj = self._make_injector(verbosity="detailed")
        block = inj._build_persona_block()
        self.assertIn("Detaylı", block)

    def test_persona_block_budget(self):
        from bantz.brain.personality_injector import _PERSONA_MAX_CHARS
        inj = self._make_injector()
        block = inj._build_persona_block()
        self.assertLessEqual(len(block), _PERSONA_MAX_CHARS)

    # -- Layer 2: Prefs --

    def test_prefs_block_empty_if_no_data(self):
        inj = self._make_injector()
        block = inj._build_prefs_block()
        self.assertEqual(block, "")

    def test_prefs_block_with_facts(self):
        inj = self._make_injector()
        facts = {"name": "İclal", "occupation": "mühendis"}
        block = inj._build_prefs_block(facts=facts)
        self.assertIn("İclal", block)
        self.assertIn("mühendis", block)
        self.assertIn("Kullanıcı hakkında", block)

    def test_prefs_block_budget(self):
        from bantz.brain.personality_injector import _PREFS_MAX_CHARS
        inj = self._make_injector()
        # Many facts
        facts = {f"fact_{i}": f"value_{i}" * 20 for i in range(20)}
        block = inj._build_prefs_block(facts=facts)
        self.assertLessEqual(len(block), _PREFS_MAX_CHARS)

    def test_prefs_block_limits_facts(self):
        inj = self._make_injector()
        # More than 8 facts should be truncated
        facts = {f"fact_{i}": f"val_{i}" for i in range(15)}
        block = inj._build_prefs_block(facts=facts)
        # Should have at most 8 fact lines
        fact_lines = [l for l in block.split("\n") if l.startswith("- fact_")]
        self.assertLessEqual(len(fact_lines), 8)

    # -- Layer 3: Rules --

    def test_rules_block_not_empty(self):
        inj = self._make_injector()
        block = inj._build_rules_block()
        self.assertTrue(len(block) > 0)
        self.assertIn("Davranış kuralları", block)

    def test_rules_block_dangerous_mode(self):
        from bantz.brain.personality_injector import PersonalityConfig, PersonalityInjector
        cfg = PersonalityConfig(confirmation_mode="dangerous")
        inj = PersonalityInjector(config=cfg)
        block = inj._build_rules_block()
        self.assertIn("Riskli", block)

    def test_rules_block_always_mode(self):
        from bantz.brain.personality_injector import PersonalityConfig, PersonalityInjector
        cfg = PersonalityConfig(confirmation_mode="always")
        inj = PersonalityInjector(config=cfg)
        block = inj._build_rules_block()
        self.assertIn("Tüm", block)

    def test_rules_block_never_mode(self):
        from bantz.brain.personality_injector import PersonalityConfig, PersonalityInjector
        cfg = PersonalityConfig(confirmation_mode="never")
        inj = PersonalityInjector(config=cfg)
        block = inj._build_rules_block()
        self.assertIn("Onay istemeden", block)

    def test_rules_language_rule(self):
        inj = self._make_injector()
        block = inj._build_rules_block()
        self.assertIn("TÜRKÇE", block)

    def test_rules_budget(self):
        from bantz.brain.personality_injector import _RULES_MAX_CHARS
        inj = self._make_injector()
        block = inj._build_rules_block()
        self.assertLessEqual(len(block), _RULES_MAX_CHARS)


# =========================================================================
# Class 4: Combined Blocks & Token Budget Tests
# =========================================================================


class TestCombinedBlocks(unittest.TestCase):
    """Test router_block, finalizer_block, identity_lines, and token budget."""

    def _make_injector(self, preset="jarvis"):
        from bantz.brain.personality_injector import PersonalityInjector, PersonalityConfig
        cfg = PersonalityConfig(preset_name=preset, user_name="İclal")
        return PersonalityInjector(config=cfg)

    def test_router_block_has_persona(self):
        inj = self._make_injector()
        block = inj.build_router_block(user_name="İclal")
        self.assertIn("İclal", block)
        self.assertTrue(len(block) > 10)

    def test_router_block_has_facts(self):
        inj = self._make_injector()
        facts = {"hobby": "coding"}
        block = inj.build_router_block(facts=facts)
        self.assertIn("coding", block)

    def test_router_block_no_rules(self):
        """Router block should NOT include Layer 3 (rules)."""
        inj = self._make_injector()
        block = inj.build_router_block()
        self.assertNotIn("Davranış kuralları", block)

    def test_finalizer_block_has_rules(self):
        """Finalizer block SHOULD include Layer 3 (rules)."""
        inj = self._make_injector()
        block = inj.build_finalizer_block()
        self.assertIn("Davranış kuralları", block)

    def test_finalizer_block_all_layers(self):
        inj = self._make_injector()
        facts = {"name": "İclal"}
        block = inj.build_finalizer_block(user_name="İclal", facts=facts)
        # Layer 1: persona
        self.assertIn("İclal", block)
        # Layer 2: facts
        self.assertIn("Kullanıcı hakkında", block)
        # Layer 3: rules
        self.assertIn("Davranış kuralları", block)

    def test_total_budget(self):
        from bantz.brain.personality_injector import _TOTAL_MAX_CHARS
        inj = self._make_injector()
        # Big facts to push budget
        facts = {f"f{i}": f"val_{i}" * 10 for i in range(15)}
        prefs = {f"p{i}": {"value": f"x_{i}", "confidence": 0.9} for i in range(10)}
        block = inj.build_finalizer_block(facts=facts, preferences=prefs)
        self.assertLessEqual(len(block), _TOTAL_MAX_CHARS)

    def test_identity_lines_jarvis(self):
        inj = self._make_injector("jarvis")
        lines = inj.build_identity_lines("İclal")
        self.assertIn("Jarvis", lines)
        self.assertIn("İclal", lines)
        self.assertIn("Efendim", lines)

    def test_identity_lines_friday(self):
        inj = self._make_injector("friday")
        lines = inj.build_identity_lines("İclal")
        self.assertIn("Friday", lines)
        self.assertIn("Samimi", lines)
        self.assertNotIn("Efendim", lines)

    def test_switch_preset(self):
        inj = self._make_injector("jarvis")
        self.assertEqual(inj.name.lower(), "jarvis")
        inj.switch_preset("friday")
        self.assertEqual(inj.name.lower(), "friday")
        self.assertFalse(inj.uses_honorifics)

    def test_update_user_name(self):
        inj = self._make_injector("jarvis")
        inj.update_user_name("TestUser")
        self.assertEqual(inj.config.user_name, "TestUser")
        block = inj.build_router_block()
        self.assertIn("TestUser", block)


# =========================================================================
# Class 5: PromptBuilder Integration Tests
# =========================================================================


class TestPromptBuilderIntegration(unittest.TestCase):
    """Test PromptBuilder personality_block parameter threading."""

    def test_build_finalizer_prompt_accepts_personality(self):
        """build_finalizer_prompt should accept personality_block kwarg."""
        from bantz.brain.prompt_engineering import PromptBuilder

        builder = PromptBuilder(token_budget=4000)
        result = builder.build_finalizer_prompt(
            route="chat",
            user_input="merhaba",
            planner_decision={"route": "chat"},
            personality_block="- Sen Jarvis'sin, İclal'ın asistanısın.",
        )
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.prompt)

    def test_personality_block_in_prompt(self):
        """Personality block content should appear in generated prompt."""
        from bantz.brain.prompt_engineering import PromptBuilder

        marker = "UNIQUE_PERSONALITY_MARKER_XYZ"
        builder = PromptBuilder(token_budget=5000)
        result = builder.build_finalizer_prompt(
            route="chat",
            user_input="merhaba",
            planner_decision={"route": "chat"},
            personality_block=f"- {marker}",
        )
        self.assertIn(marker, result.prompt)

    def test_system_prompt_uses_personality(self):
        """When personality_block given, system prompt should use it."""
        from bantz.brain.prompt_engineering import PromptBuilder

        builder = PromptBuilder(token_budget=5000)
        result = builder.build_finalizer_prompt(
            route="calendar",
            user_input="bugün takvimde ne var",
            planner_decision={"route": "calendar"},
            personality_block="- Sen Alfred'sin.",
        )
        # System prompt should include personality block
        self.assertIn("Alfred", result.prompt)

    def test_no_personality_falls_back(self):
        """Without personality_block, should use default BANTZ identity."""
        from bantz.brain.prompt_engineering import PromptBuilder

        builder = PromptBuilder(token_budget=5000)
        result = builder.build_finalizer_prompt(
            route="chat",
            user_input="merhaba",
            planner_decision={"route": "chat"},
        )
        self.assertIn("BANTZ", result.prompt)

    def test_personality_block_none_falls_back(self):
        """personality_block=None should use default BANTZ identity."""
        from bantz.brain.prompt_engineering import PromptBuilder

        builder = PromptBuilder(token_budget=5000)
        result = builder.build_finalizer_prompt(
            route="chat",
            user_input="merhaba",
            planner_decision={"route": "chat"},
            personality_block=None,
        )
        self.assertIn("BANTZ", result.prompt)

    def test_language_rule_always_present(self):
        """TÜRKÇE language rule must be present regardless of personality."""
        from bantz.brain.prompt_engineering import PromptBuilder

        builder = PromptBuilder(token_budget=5000)

        # With personality
        r1 = builder.build_finalizer_prompt(
            route="chat",
            user_input="hi",
            planner_decision={"route": "chat"},
            personality_block="- Sen Friday'sin.",
        )
        self.assertIn("TÜRKÇE", r1.prompt)

        # Without personality
        r2 = builder.build_finalizer_prompt(
            route="chat",
            user_input="hi",
            planner_decision={"route": "chat"},
        )
        self.assertIn("TÜRKÇE", r2.prompt)


# =========================================================================
# Class 6: FinalizationContext & Pipeline Integration Tests
# =========================================================================


class TestFinalizationContextIntegration(unittest.TestCase):
    """Test FinalizationContext personality_block field and threading."""

    def test_finalization_context_has_personality_field(self):
        """FinalizationContext should accept personality_block."""
        from bantz.brain.finalization_pipeline import FinalizationContext
        from bantz.brain.orchestrator_state import OrchestratorState

        oo = MagicMock()
        oo.route = "chat"

        ctx = FinalizationContext(
            user_input="merhaba",
            orchestrator_output=oo,
            tool_results=[],
            state=MagicMock(spec=OrchestratorState),
            planner_decision={"route": "chat"},
            personality_block="- Sen Jarvis'sin.",
        )
        self.assertEqual(ctx.personality_block, "- Sen Jarvis'sin.")

    def test_finalization_context_personality_default_none(self):
        """personality_block should default to None."""
        from bantz.brain.finalization_pipeline import FinalizationContext

        ctx = FinalizationContext(
            user_input="test",
            orchestrator_output=MagicMock(),
            tool_results=[],
            state=MagicMock(),
            planner_decision={},
        )
        self.assertIsNone(ctx.personality_block)

    def test_build_finalization_context_accepts_personality(self):
        """build_finalization_context should accept personality_block."""
        from bantz.brain.finalization_pipeline import build_finalization_context
        from bantz.brain.orchestrator_state import OrchestratorState

        oo = MagicMock()
        oo.route = "chat"
        oo.calendar_intent = None
        oo.slots = {}
        oo.tool_plan = []
        oo.requires_confirmation = False
        oo.confirmation_prompt = ""
        oo.ask_user = False
        oo.question = ""

        state = MagicMock(spec=OrchestratorState)
        state.get_context_for_llm.return_value = {}
        state.session_context = None

        memory = MagicMock()
        memory.to_prompt_block.return_value = ""

        ctx = build_finalization_context(
            user_input="test",
            orchestrator_output=oo,
            tool_results=[],
            state=state,
            memory=memory,
            finalizer_llm=None,
            personality_block="- Sen Alfred'sin.",
        )
        self.assertEqual(ctx.personality_block, "- Sen Alfred'sin.")

    def test_build_finalization_context_personality_default(self):
        """Without personality_block arg, should default to None."""
        from bantz.brain.finalization_pipeline import build_finalization_context
        from bantz.brain.orchestrator_state import OrchestratorState

        oo = MagicMock()
        oo.route = "chat"
        oo.calendar_intent = None
        oo.slots = {}
        oo.tool_plan = []
        oo.requires_confirmation = False
        oo.confirmation_prompt = ""
        oo.ask_user = False
        oo.question = ""

        state = MagicMock(spec=OrchestratorState)
        state.get_context_for_llm.return_value = {}
        state.session_context = None

        memory = MagicMock()
        memory.to_prompt_block.return_value = ""

        ctx = build_finalization_context(
            user_input="test",
            orchestrator_output=oo,
            tool_results=[],
            state=state,
            memory=memory,
            finalizer_llm=None,
        )
        self.assertIsNone(ctx.personality_block)


# =========================================================================
# Class 7: Fallback Prompt Personality Tests
# =========================================================================


class TestFallbackPromptPersonality(unittest.TestCase):
    """Test fallback prompt uses personality when available."""

    def _make_ctx(self, personality_block=None):
        from bantz.brain.finalization_pipeline import FinalizationContext

        oo = MagicMock()
        oo.route = "chat"

        return FinalizationContext(
            user_input="merhaba",
            orchestrator_output=oo,
            tool_results=[],
            state=MagicMock(),
            planner_decision={"route": "chat"},
            personality_block=personality_block,
        )

    def test_fallback_with_personality(self):
        """Fallback prompt should use personality block when present."""
        from bantz.brain.finalization_pipeline import QualityFinalizer

        ctx = self._make_ctx(personality_block="- Sen Alfred'sin, İclal'ın sadık asistanısın.")
        prompt = QualityFinalizer._build_fallback_prompt(ctx, [])
        self.assertIn("Alfred", prompt)
        self.assertIn("İclal", prompt)

    def test_fallback_without_personality(self):
        """Fallback prompt should use default BANTZ when no personality."""
        from bantz.brain.finalization_pipeline import QualityFinalizer

        ctx = self._make_ctx(personality_block=None)
        prompt = QualityFinalizer._build_fallback_prompt(ctx, [])
        self.assertIn("BANTZ", prompt)
        self.assertIn("Efendim", prompt)

    def test_fallback_format_rules_always_present(self):
        """FORMAT KURALLARI should always be present in fallback."""
        from bantz.brain.finalization_pipeline import QualityFinalizer

        ctx = self._make_ctx(personality_block="- Sen Friday'sin.")
        prompt = QualityFinalizer._build_fallback_prompt(ctx, [])
        self.assertIn("FORMAT KURALLARI", prompt)

    def test_fallback_dogruluk_rules_always_present(self):
        """DOĞRULUK KURALLARI should always be present in fallback."""
        from bantz.brain.finalization_pipeline import QualityFinalizer

        ctx = self._make_ctx(personality_block="- Sen Friday'sin.")
        prompt = QualityFinalizer._build_fallback_prompt(ctx, [])
        self.assertIn("DOĞRULUK KURALLARI", prompt)


# =========================================================================
# Class 8: Orchestrator Wiring (AST-based, no heavy imports)
# =========================================================================


class TestOrchestratorWiring(unittest.TestCase):
    """Verify orchestrator has personality_injector wired in (AST analysis)."""

    @classmethod
    def setUpClass(cls):
        path = _SRC / "brain" / "orchestrator_loop.py"
        cls._source = path.read_text(encoding="utf-8")
        cls._tree = ast.parse(cls._source)

    def test_personality_injector_in_init(self):
        """__init__ should create self.personality_injector."""
        self.assertIn("personality_injector", self._source)
        self.assertIn("PersonalityInjector", self._source)

    def test_personality_block_in_phase1(self):
        """Phase 1 should inject PERSONALITY block."""
        self.assertIn("PERSONALITY:", self._source)
        self.assertIn("build_router_block", self._source)

    def test_personality_block_in_phase3(self):
        """Phase 3 should pass personality_block to build_finalization_context."""
        self.assertIn("build_finalizer_block", self._source)
        self.assertIn("personality_block=_personality_block", self._source)

    def test_personality_injector_import(self):
        """PersonalityInjector should be imported in orchestrator."""
        self.assertIn("from bantz.brain.personality_injector", self._source)

    def test_finalization_pipeline_personality_field(self):
        """finalization_pipeline should have personality_block field."""
        fp_path = _SRC / "brain" / "finalization_pipeline.py"
        source = fp_path.read_text(encoding="utf-8")
        self.assertIn("personality_block", source)

    def test_prompt_engineering_personality_param(self):
        """PromptBuilder should accept personality_block."""
        pe_path = _SRC / "brain" / "prompt_engineering.py"
        source = pe_path.read_text(encoding="utf-8")
        self.assertIn("personality_block", source)


if __name__ == "__main__":
    unittest.main()
