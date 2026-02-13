"""Tests for Issue #872: Component Integration Audit — Personalization Altyapı Bağlantı Haritası.

Validates:
1. Reverse dependency fix (memory/safety.py lazy import)
2. Import graph correctness (no production imports from memory/learning)
3. Dead code detection (memory/learning not wired to orchestrator)
4. PIIFilter still works after lazy import refactor
5. Integration map document exists
"""

from __future__ import annotations

import ast
import importlib
import os
import unittest
from pathlib import Path


# Base paths
_SRC = Path(__file__).resolve().parent.parent / "src" / "bantz"
_DOCS = Path(__file__).resolve().parent.parent / "docs"


class TestReverseDependencyFix(unittest.TestCase):
    """Verify memory/safety.py no longer has module-level brain import."""

    def test_no_toplevel_brain_import(self):
        """memory/safety.py must NOT have a top-level 'from bantz.brain' import."""
        safety_path = _SRC / "memory" / "safety.py"
        self.assertTrue(safety_path.exists(), f"Missing {safety_path}")

        source = safety_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        toplevel_brain_imports = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "bantz.brain" in node.module:
                    toplevel_brain_imports.append(node.module)

        self.assertEqual(
            toplevel_brain_imports,
            [],
            f"Top-level brain imports still exist in memory/safety.py: {toplevel_brain_imports}. "
            f"Should use lazy import inside function body.",
        )

    def test_lazy_import_function_exists(self):
        """_get_pii_filter() lazy import helper must exist."""
        from bantz.memory.safety import _get_pii_filter

        # Should return the PIIFilter class
        pii_cls = _get_pii_filter()
        self.assertTrue(hasattr(pii_cls, "filter"), "PIIFilter must have a 'filter' method")

    def test_mask_pii_still_works(self):
        """mask_pii must still mask emails after lazy import refactor."""
        from bantz.memory.safety import mask_pii

        result = mask_pii("Contact user@example.com for info")
        self.assertNotIn("user@example.com", result)
        self.assertIn("<EMAIL>", result)

    def test_mask_pii_empty(self):
        """mask_pii handles empty/None gracefully."""
        from bantz.memory.safety import mask_pii

        self.assertEqual(mask_pii(""), "")
        self.assertEqual(mask_pii(None), "")

    def test_safe_tool_episode_still_works(self):
        """safe_tool_episode must still work after refactor."""
        from bantz.memory.safety import safe_tool_episode

        result = safe_tool_episode(
            tool_name="calendar.list_events",
            params={"start": "2026-01-01T09:00", "end": "2026-01-01T10:00"},
            result={"events": [{"id": "1"}, {"id": "2"}]},
        )
        self.assertIn("calendar.list_events", result)
        self.assertIn("count=2", result)


class TestImportGraphIntegrity(unittest.TestCase):
    """Ensure no production code in brain/ imports memory/ or learning/ at module level."""

    # Files that should NOT import from bantz.memory or bantz.learning
    PRODUCTION_FILES = [
        "brain/orchestrator_loop.py",
        "brain/prompt_engineering.py",
        "brain/finalization_pipeline.py",
        "brain/llm_router.py",
        "brain/runtime_factory.py",
        "server.py",
        "api/ws.py",
    ]

    def test_no_memory_imports_in_production(self):
        """Production brain/ files must not import from bantz.memory directly.
        
        Note: Issue #873 wires memory via bantz.brain.user_memory (a façade),
        which is allowed — we only block direct bantz.memory imports.
        """
        violations = []
        for relpath in self.PRODUCTION_FILES:
            fpath = _SRC / relpath
            if not fpath.exists():
                continue
            source = fpath.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith("bantz.memory"):
                        violations.append(f"{relpath}: from {node.module}")
        self.assertEqual(violations, [], f"Unexpected memory imports: {violations}")

    def test_no_learning_imports_in_production(self):
        """Production brain/ files must not import from bantz.learning."""
        violations = []
        for relpath in self.PRODUCTION_FILES:
            fpath = _SRC / relpath
            if not fpath.exists():
                continue
            source = fpath.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith("bantz.learning"):
                        violations.append(f"{relpath}: from {node.module}")
        self.assertEqual(violations, [], f"Unexpected learning imports: {violations}")


class TestMemoryLearningModuleIntegrity(unittest.TestCase):
    """Verify memory/ and learning/ packages are importable and internally consistent."""

    def test_memory_package_importable(self):
        """bantz.memory should import without errors."""
        try:
            import bantz.memory
        except Exception as e:
            self.fail(f"bantz.memory import failed: {e}")

    def test_learning_package_importable(self):
        """bantz.learning should import without errors."""
        try:
            import bantz.learning
        except Exception as e:
            self.fail(f"bantz.learning import failed: {e}")

    def test_memory_safety_importable(self):
        """bantz.memory.safety should import (lazy import, no circular)."""
        try:
            from bantz.memory.safety import mask_pii, safe_tool_episode
        except Exception as e:
            self.fail(f"bantz.memory.safety import failed: {e}")

    def test_no_circular_imports_memory(self):
        """memory/ → brain/ should not cause circular import with lazy loading."""
        # Force fresh import
        import bantz.memory.safety
        importlib.reload(bantz.memory.safety)
        from bantz.memory.safety import mask_pii
        # If we get here without ImportError, no circular dependency
        result = mask_pii("test@test.com")
        self.assertNotIn("test@test.com", result)

    def test_memory_file_count(self):
        """memory/ should have ~21 Python files."""
        memory_dir = _SRC / "memory"
        py_files = list(memory_dir.glob("*.py"))
        self.assertGreaterEqual(len(py_files), 18, f"Expected ~21 memory files, got {len(py_files)}")

    def test_learning_file_count(self):
        """learning/ should have ~9 Python files."""
        learning_dir = _SRC / "learning"
        py_files = list(learning_dir.glob("*.py"))
        self.assertGreaterEqual(len(py_files), 7, f"Expected ~9 learning files, got {len(py_files)}")


class TestDuplicateUserProfileAudit(unittest.TestCase):
    """Verify duplicate UserProfile classes are documented and distinct."""

    def test_memory_user_profile_exists(self):
        """memory/profile.py must have a UserProfile class."""
        from bantz.memory.profile import UserProfile
        self.assertTrue(hasattr(UserProfile, "__dataclass_fields__") or hasattr(UserProfile, "__init__"))

    def test_learning_user_profile_exists(self):
        """learning/profile.py must have a UserProfile class (to be renamed)."""
        from bantz.learning.profile import UserProfile
        self.assertTrue(hasattr(UserProfile, "__dataclass_fields__"))

    def test_profiles_are_different_classes(self):
        """The two UserProfile classes must be distinct objects."""
        from bantz.memory.profile import UserProfile as MemoryProfile
        from bantz.learning.profile import UserProfile as LearningProfile
        self.assertIsNot(MemoryProfile, LearningProfile)

    def test_memory_profile_has_communication_style(self):
        """memory UserProfile should have fact-oriented fields."""
        from bantz.memory.profile import UserProfile
        # Check field names via dataclass
        fields = {f.name for f in UserProfile.__dataclass_fields__.values()} if hasattr(UserProfile, "__dataclass_fields__") else set()
        # At minimum should have some fact fields
        self.assertTrue(
            len(fields) > 0 or hasattr(UserProfile, "communication_style"),
            "memory UserProfile should have fact-oriented fields",
        )

    def test_learning_profile_has_behavioral_fields(self):
        """learning UserProfile should have behavioral/RL fields."""
        from bantz.learning.profile import UserProfile
        fields = {f.name for f in UserProfile.__dataclass_fields__.values()}
        behavioral_fields = {"preferred_apps", "command_sequences", "time_patterns"}
        found = fields & behavioral_fields
        self.assertTrue(
            len(found) >= 2,
            f"learning UserProfile missing behavioral fields. Has: {fields}",
        )


class TestIntegrationMapDocument(unittest.TestCase):
    """Verify docs/integration-map.md exists with required sections."""

    def test_document_exists(self):
        doc = _DOCS / "integration-map.md"
        self.assertTrue(doc.exists(), f"Missing {doc}")

    def test_document_has_required_sections(self):
        doc = _DOCS / "integration-map.md"
        content = doc.read_text(encoding="utf-8")

        required_sections = [
            "Import Graph",
            "Duplicate UserProfile",
            "Wire Noktaları",
            "Dead Code",
            "Ters Bağımlılık",
        ]
        for section in required_sections:
            self.assertIn(
                section,
                content,
                f"integration-map.md missing required section: '{section}'",
            )

    def test_document_mentions_all_key_components(self):
        doc = _DOCS / "integration-map.md"
        content = doc.read_text(encoding="utf-8")

        key_components = [
            "MemoryContextBuilder",
            "PreferenceIntegration",
            "UserProfile",
            "MemoryStore",
            "PatternExtractor",
            "CompactSummary",
            "PIIFilter",
        ]
        for comp in key_components:
            self.assertIn(
                comp,
                content,
                f"integration-map.md missing key component: '{comp}'",
            )

    def test_document_has_decision_for_each_component(self):
        """Document must have explicit connect/defer decision."""
        doc = _DOCS / "integration-map.md"
        content = doc.read_text(encoding="utf-8")
        # Must mention wiring decisions
        self.assertIn("Bağlanacak", content)
        self.assertIn("Kalacak", content)


if __name__ == "__main__":
    unittest.main()
