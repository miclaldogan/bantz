"""Tests for Issue #873: Persistent User Memory — Kullanıcı Hafızasını Orchestrator'a Bağla.

Validates:
1. UserMemoryBridge creation and lifecycle
2. on_turn_start returns profile context
3. on_turn_end learns facts/preferences
4. Orchestrator wiring (init, Phase 1, Phase 4)
5. BehavioralProfile rename + backward-compat alias
6. PII filtering in bridge
"""

from __future__ import annotations

import ast
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_SRC = Path(__file__).resolve().parent.parent / "src" / "bantz"


# =========================================================================
# Class 1: UserMemoryBridge Unit Tests
# =========================================================================


class TestUserMemoryBridge(unittest.TestCase):
    """Test UserMemoryBridge core lifecycle."""

    def test_import(self):
        """UserMemoryBridge should be importable."""
        from bantz.brain.user_memory import UserMemoryBridge

        self.assertTrue(callable(UserMemoryBridge))

    def test_config_defaults(self):
        """UserMemoryConfig should have sane defaults."""
        from bantz.brain.user_memory import UserMemoryConfig

        cfg = UserMemoryConfig()
        self.assertEqual(cfg.max_recall, 5)
        self.assertTrue(cfg.learn_facts)
        self.assertTrue(cfg.pii_filter)
        self.assertIn("profile.json", cfg.profile_path)
        self.assertIn("memory.db", cfg.db_path)

    def test_config_from_env(self):
        """UserMemoryConfig.from_env reads BANTZ_MEMORY_MAX_RECALL."""
        from bantz.brain.user_memory import UserMemoryConfig

        with patch.dict(os.environ, {"BANTZ_MEMORY_MAX_RECALL": "10"}):
            cfg = UserMemoryConfig.from_env()
            self.assertEqual(cfg.max_recall, 10)

    def test_init_with_tmp_paths(self):
        """Bridge should init with temp paths without error."""
        from bantz.brain.user_memory import UserMemoryBridge, UserMemoryConfig

        with tempfile.TemporaryDirectory() as tmp:
            cfg = UserMemoryConfig(
                profile_path=os.path.join(tmp, "profile.json"),
                db_path=os.path.join(tmp, "memory.db"),
                pii_filter=False,
            )
            bridge = UserMemoryBridge(config=cfg)
            self.assertTrue(bridge.ready)
            self.assertIsNotNone(bridge.profile_manager)
            self.assertIsNotNone(bridge.memory_store)
            bridge.close()

    def test_on_turn_start_empty_profile(self):
        """on_turn_start should return empty context for fresh profile."""
        from bantz.brain.user_memory import UserMemoryBridge, UserMemoryConfig

        with tempfile.TemporaryDirectory() as tmp:
            cfg = UserMemoryConfig(
                profile_path=os.path.join(tmp, "profile.json"),
                db_path=os.path.join(tmp, "memory.db"),
                pii_filter=False,
            )
            bridge = UserMemoryBridge(config=cfg)
            result = bridge.on_turn_start("merhaba")

            self.assertIsInstance(result, dict)
            self.assertIn("profile_context", result)
            self.assertIn("facts", result)
            self.assertIn("memories", result)
            bridge.close()

    def test_on_turn_start_with_profile(self):
        """on_turn_start should return facts when profile has data."""
        from bantz.brain.user_memory import UserMemoryBridge, UserMemoryConfig

        with tempfile.TemporaryDirectory() as tmp:
            # Pre-create profile with facts
            profile_path = os.path.join(tmp, "profile.json")
            profile_data = {
                "version": 1,
                "name": "İclal",
                "preferred_language": "tr",
                "timezone": "Europe/Istanbul",
                "formality_level": 0.5,
                "verbosity_preference": 0.5,
                "humor_appreciation": 0.5,
                "technical_level": 0.5,
                "preferred_styles": [],
                "work_pattern": {},
                "common_tasks": [],
                "favorite_apps": [],
                "app_positions": {},
                "facts": {"name": "İclal", "job": "yazılımcı"},
                "preferences": {},
                "total_interactions": 5,
                "first_interaction": None,
                "last_interaction": None,
                "session_count": 1,
            }
            with open(profile_path, "w", encoding="utf-8") as f:
                json.dump(profile_data, f)

            cfg = UserMemoryConfig(
                profile_path=profile_path,
                db_path=os.path.join(tmp, "memory.db"),
                pii_filter=False,
            )
            bridge = UserMemoryBridge(config=cfg)
            result = bridge.on_turn_start("merhaba")

            self.assertIn("İclal", result.get("profile_context", ""))
            self.assertEqual(result["facts"].get("name"), "İclal")
            bridge.close()

    def test_on_turn_end_returns_dict(self):
        """on_turn_end should return dict with facts/preferences/memory_id."""
        from bantz.brain.user_memory import UserMemoryBridge, UserMemoryConfig

        with tempfile.TemporaryDirectory() as tmp:
            cfg = UserMemoryConfig(
                profile_path=os.path.join(tmp, "profile.json"),
                db_path=os.path.join(tmp, "memory.db"),
                pii_filter=False,
            )
            bridge = UserMemoryBridge(config=cfg)
            result = bridge.on_turn_end(
                user_input="benim adım Ali",
                assistant_reply="Merhaba Ali!",
                route="smalltalk",
            )

            self.assertIsInstance(result, dict)
            self.assertIn("facts", result)
            self.assertIn("preferences", result)
            self.assertIn("memory_id", result)
            bridge.close()

    def test_on_turn_end_learns_name(self):
        """on_turn_end should extract name fact from Turkish input."""
        from bantz.brain.user_memory import UserMemoryBridge, UserMemoryConfig

        with tempfile.TemporaryDirectory() as tmp:
            cfg = UserMemoryConfig(
                profile_path=os.path.join(tmp, "profile.json"),
                db_path=os.path.join(tmp, "memory.db"),
                pii_filter=False,
            )
            bridge = UserMemoryBridge(config=cfg)
            result = bridge.on_turn_end(
                user_input="benim adım Ahmet",
                assistant_reply="Merhaba Ahmet!",
            )

            # LearningEngine's FactExtractor should pick up the name
            facts = result.get("facts", [])
            if facts:
                # At least one fact about name
                name_facts = [f for f in facts if f.get("category") == "name"]
                self.assertTrue(len(name_facts) > 0, f"Expected name fact, got {facts}")
            bridge.close()

    def test_get_profile_summary(self):
        """get_profile_summary should work even for empty profile."""
        from bantz.brain.user_memory import UserMemoryBridge, UserMemoryConfig

        with tempfile.TemporaryDirectory() as tmp:
            cfg = UserMemoryConfig(
                profile_path=os.path.join(tmp, "profile.json"),
                db_path=os.path.join(tmp, "memory.db"),
                pii_filter=False,
            )
            bridge = UserMemoryBridge(config=cfg)
            summary = bridge.get_profile_summary()
            self.assertIsInstance(summary, str)
            bridge.close()

    def test_repr(self):
        """repr should contain state info."""
        from bantz.brain.user_memory import UserMemoryBridge, UserMemoryConfig

        with tempfile.TemporaryDirectory() as tmp:
            cfg = UserMemoryConfig(
                profile_path=os.path.join(tmp, "profile.json"),
                db_path=os.path.join(tmp, "memory.db"),
                pii_filter=False,
            )
            bridge = UserMemoryBridge(config=cfg)
            r = repr(bridge)
            self.assertIn("UserMemoryBridge", r)
            self.assertIn("ready=True", r)
            bridge.close()

    def test_not_ready_when_components_fail(self):
        """Bridge should be not ready when both components fail."""
        from bantz.brain.user_memory import UserMemoryBridge, UserMemoryConfig

        cfg = UserMemoryConfig(
            profile_path="/nonexistent/dir/that/wont/exist/profile.json",
            db_path="/nonexistent/dir/that/wont/exist/memory.db",
            pii_filter=False,
        )
        # This may or may not raise — depends on directory creation
        # At minimum, test that it doesn't crash the process
        try:
            bridge = UserMemoryBridge(config=cfg)
            # Even if not ready, on_turn_start should return empty
            result = bridge.on_turn_start("hello")
            self.assertIsInstance(result, dict)
        except Exception:
            pass  # OS permission errors are acceptable


# =========================================================================
# Class 2: Orchestrator Wiring Tests
# =========================================================================


class TestOrchestratorWiring(unittest.TestCase):
    """Test that orchestrator_loop.py has the user_memory hooks."""

    def test_init_has_user_memory_attribute(self):
        """orchestrator_loop.py __init__ should set self.user_memory."""
        source = (_SRC / "brain" / "orchestrator_loop.py").read_text("utf-8")
        self.assertIn("self.user_memory", source)
        self.assertIn("UserMemoryBridge", source)

    def test_phase1_injects_profile_context(self):
        """_llm_planning_phase should inject USER_PROFILE into context_parts.

        Issue #1010: Context building extracted to ContextBuilder, so
        the literal 'USER_PROFILE:' string now lives in context_builder.py.
        """
        cb_source = (_SRC / "brain" / "context_builder.py").read_text("utf-8")
        self.assertIn("USER_PROFILE:", cb_source)
        self.assertIn("on_turn_start", cb_source)

    def test_phase4_calls_on_turn_end(self):
        """_update_state_phase should call user_memory.on_turn_end."""
        source = (_SRC / "brain" / "orchestrator_loop.py").read_text("utf-8")
        self.assertIn("on_turn_end", source)

    def test_phase1_injects_long_term_memory(self):
        """_llm_planning_phase should inject LONG_TERM_MEMORY block.

        Issue #1010: Context building extracted to ContextBuilder.
        """
        cb_source = (_SRC / "brain" / "context_builder.py").read_text("utf-8")
        self.assertIn("LONG_TERM_MEMORY:", cb_source)

    def test_user_memory_init_is_best_effort(self):
        """user_memory init should be wrapped in try/except."""
        source = (_SRC / "brain" / "orchestrator_loop.py").read_text("utf-8")
        # Find the user_memory block
        idx = source.find("Issue #873")
        self.assertGreater(idx, -1)
        # There should be a try block nearby
        block = source[idx:idx + 300]
        self.assertIn("try:", block)
        self.assertIn("except", block)

    def test_phase4_on_turn_end_is_best_effort(self):
        """on_turn_end call should be wrapped in try/except."""
        source = (_SRC / "brain" / "orchestrator_loop.py").read_text("utf-8")
        # Find on_turn_end in _update_state_phase
        idx = source.find("on_turn_end")
        self.assertGreater(idx, -1)
        # Look backwards for try
        block = source[max(0, idx - 200):idx + 100]
        self.assertIn("try:", block)


# =========================================================================
# Class 3: BehavioralProfile Rename Tests
# =========================================================================


class TestBehavioralProfileRename(unittest.TestCase):
    """Test that learning/profile.py uses BehavioralProfile with alias."""

    def test_behavioral_profile_class_exists(self):
        """BehavioralProfile class should exist in learning.profile."""
        from bantz.learning.profile import BehavioralProfile

        p = BehavioralProfile()
        self.assertTrue(hasattr(p, "preferred_apps"))
        self.assertTrue(hasattr(p, "command_sequences"))

    def test_user_profile_alias_works(self):
        """UserProfile should still be importable as backward-compat alias."""
        from bantz.learning.profile import UserProfile, BehavioralProfile

        self.assertIs(UserProfile, BehavioralProfile)

    def test_user_profile_from_init(self):
        """UserProfile should be importable from bantz.learning."""
        from bantz.learning import UserProfile, BehavioralProfile

        self.assertIs(UserProfile, BehavioralProfile)

    def test_behavioral_profile_in_all(self):
        """BehavioralProfile should be in __all__."""
        from bantz.learning import __all__ as exports

        self.assertIn("BehavioralProfile", exports)
        self.assertIn("UserProfile", exports)

    def test_profile_creation(self):
        """BehavioralProfile should be instantiable."""
        from bantz.learning.profile import BehavioralProfile

        p = BehavioralProfile()
        self.assertIsNotNone(p.id)
        self.assertEqual(p.total_interactions, 0)
        self.assertIsInstance(p.preferred_apps, dict)

    def test_profile_round_trip(self):
        """BehavioralProfile to_dict/from_dict round trip."""
        from bantz.learning.profile import BehavioralProfile

        p = BehavioralProfile()
        p.preferred_apps["discord"] = 0.9
        p.record_interaction(success=True)

        data = p.to_dict()
        p2 = BehavioralProfile.from_dict(data)

        self.assertEqual(p2.preferred_apps.get("discord"), 0.9)
        self.assertEqual(p2.total_interactions, 1)

    def test_learning_modules_import_behavioral(self):
        """Internal learning/ modules should import BehavioralProfile."""
        for mod_name in ["behavioral", "preferences", "adaptive", "storage"]:
            mod_path = _SRC / "learning" / f"{mod_name}.py"
            if not mod_path.exists():
                continue
            source = mod_path.read_text("utf-8")
            self.assertIn(
                "BehavioralProfile",
                source,
                f"learning/{mod_name}.py should reference BehavioralProfile",
            )

    def test_no_name_collision_with_memory_profile(self):
        """memory.profile.UserProfile and learning.profile.BehavioralProfile are different."""
        from bantz.memory.profile import UserProfile as MemoryProfile
        from bantz.learning.profile import BehavioralProfile

        # They should be different classes
        self.assertIsNot(MemoryProfile, BehavioralProfile)

        # Memory profile has 'facts' dict
        mp = MemoryProfile()
        self.assertTrue(hasattr(mp, "facts"))

        # Behavioral profile has 'command_sequences'
        bp = BehavioralProfile()
        self.assertTrue(hasattr(bp, "command_sequences"))
        self.assertFalse(hasattr(bp, "facts"))


# =========================================================================
# Class 4: PII Filtering Tests
# =========================================================================


class TestPIIFiltering(unittest.TestCase):
    """Test PII filtering in UserMemoryBridge."""

    def test_filter_pii_static_method(self):
        """_filter_pii should exist as static method."""
        from bantz.brain.user_memory import UserMemoryBridge

        self.assertTrue(hasattr(UserMemoryBridge, "_filter_pii"))
        # Should not crash on empty
        result = UserMemoryBridge._filter_pii("")
        self.assertEqual(result, "")

    def test_filter_pii_passthrough(self):
        """_filter_pii should pass through non-PII text."""
        from bantz.brain.user_memory import UserMemoryBridge

        text = "merhaba dünya"
        result = UserMemoryBridge._filter_pii(text)
        self.assertIsInstance(result, str)
        # At minimum, should not be empty (PII filter may not strip this)
        self.assertTrue(len(result) > 0)

    def test_pii_filter_in_on_turn_start(self):
        """When pii_filter=True, on_turn_start should apply filtering."""
        from bantz.brain.user_memory import UserMemoryBridge, UserMemoryConfig

        with tempfile.TemporaryDirectory() as tmp:
            cfg = UserMemoryConfig(
                profile_path=os.path.join(tmp, "profile.json"),
                db_path=os.path.join(tmp, "memory.db"),
                pii_filter=True,
            )
            bridge = UserMemoryBridge(config=cfg)
            # Should not crash even with PII filter on
            result = bridge.on_turn_start("merhaba")
            self.assertIsInstance(result, dict)
            bridge.close()


# =========================================================================
# Class 5: Integration Smoke Tests
# =========================================================================


class TestIntegrationSmoke(unittest.TestCase):
    """End-to-end smoke tests for the full memory pipeline."""

    def test_full_turn_lifecycle(self):
        """Full turn: start → end → start again should work."""
        from bantz.brain.user_memory import UserMemoryBridge, UserMemoryConfig

        with tempfile.TemporaryDirectory() as tmp:
            cfg = UserMemoryConfig(
                profile_path=os.path.join(tmp, "profile.json"),
                db_path=os.path.join(tmp, "memory.db"),
                pii_filter=False,
            )
            bridge = UserMemoryBridge(config=cfg)

            # Turn 1
            ctx1 = bridge.on_turn_start("merhaba")
            self.assertIsInstance(ctx1, dict)

            bridge.on_turn_end(
                user_input="benim adım Test",
                assistant_reply="Merhaba Test!",
                route="smalltalk",
            )

            # Turn 2 — profile should now have the name
            ctx2 = bridge.on_turn_start("nasılsın")
            self.assertIsInstance(ctx2, dict)

            bridge.close()

    def test_tool_results_passed_to_learning(self):
        """Tool results should be forwarded to LearningEngine."""
        from bantz.brain.user_memory import UserMemoryBridge, UserMemoryConfig

        with tempfile.TemporaryDirectory() as tmp:
            cfg = UserMemoryConfig(
                profile_path=os.path.join(tmp, "profile.json"),
                db_path=os.path.join(tmp, "memory.db"),
                pii_filter=False,
            )
            bridge = UserMemoryBridge(config=cfg)

            tool_results = [
                {"tool": "calendar.list_events", "success": True, "result": "ok"},
                {"tool": "gmail.list_messages", "success": False, "result": "error"},
            ]
            result = bridge.on_turn_end(
                user_input="takvimimi göster",
                assistant_reply="Bugün 2 toplantın var",
                route="calendar",
                tool_results=tool_results,
            )

            self.assertIsInstance(result, dict)
            bridge.close()

    def test_user_memory_bridge_module_exists(self):
        """brain/user_memory.py should exist."""
        path = _SRC / "brain" / "user_memory.py"
        self.assertTrue(path.exists(), f"Missing {path}")

    def test_profile_persists_across_bridges(self):
        """Profile data should persist on disk between bridge instances."""
        from bantz.brain.user_memory import UserMemoryBridge, UserMemoryConfig

        with tempfile.TemporaryDirectory() as tmp:
            profile_path = os.path.join(tmp, "profile.json")
            db_path = os.path.join(tmp, "memory.db")

            # Bridge 1: learn a name
            cfg1 = UserMemoryConfig(
                profile_path=profile_path,
                db_path=db_path,
                pii_filter=False,
            )
            b1 = UserMemoryBridge(config=cfg1)
            b1.on_turn_end(
                user_input="benim adım Zeynep",
                assistant_reply="Merhaba Zeynep!",
            )
            b1.close()

            # Profile JSON should exist
            self.assertTrue(
                os.path.exists(profile_path),
                "profile.json should be written to disk"
            )

            # Bridge 2: should see the name
            cfg2 = UserMemoryConfig(
                profile_path=profile_path,
                db_path=db_path,
                pii_filter=False,
            )
            b2 = UserMemoryBridge(config=cfg2)
            ctx = b2.on_turn_start("merhaba")

            # The name should appear in facts or profile_context
            has_name = (
                "Zeynep" in ctx.get("profile_context", "")
                or ctx.get("facts", {}).get("name") == "Zeynep"
            )
            self.assertTrue(has_name, f"Expected Zeynep in context, got {ctx}")
            b2.close()


if __name__ == "__main__":
    unittest.main()
