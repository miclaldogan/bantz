"""Tests for Issue #1019: Personality block 'Efendim' consistency."""

from __future__ import annotations

import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "bantz"


class TestPersonalityBlockConsistency(unittest.TestCase):
    """Ensure 'Efendim' honorific appears regardless of personality_block."""

    def _build(self, personality_block=None):
        from bantz.brain.prompt_engineering import PromptBuilder
        pb = PromptBuilder()
        return pb._build_system_prompt(
            variant="A", writing=2, personality_block=personality_block
        )

    def test_default_has_efendim(self):
        """Default system prompt (no personality_block) includes 'Efendim'."""
        prompt = self._build()
        self.assertIn("Efendim", prompt)

    def test_personality_without_efendim_adds_it(self):
        """If personality_block doesn't mention 'Efendim', it's added."""
        prompt = self._build(personality_block="- Sen Jarvis'sin.")
        self.assertIn("Efendim", prompt)
        self.assertIn("Jarvis", prompt)

    def test_personality_with_efendim_no_duplicate(self):
        """If personality_block already has 'Efendim', don't duplicate."""
        block = "- Sen Jarvis'sin. 'Efendim' hitabıyla konuş."
        prompt = self._build(personality_block=block)
        # Should appear from the block itself, not duplicated
        count = prompt.lower().count("efendim")
        self.assertEqual(count, 1, f"Expected 1 'efendim', found {count}")

    def test_always_has_turkish_rule(self):
        """Turkish-only rule should always be present."""
        for pb in [None, "- Custom personality."]:
            prompt = self._build(personality_block=pb)
            self.assertIn("SADECE TÜRKÇE", prompt)

    def test_always_has_output_format_rule(self):
        """Output format rule should always be present."""
        for pb in [None, "- Custom personality."]:
            prompt = self._build(personality_block=pb)
            self.assertIn("JSON/Markdown yok", prompt)

    def test_source_no_comment_about_already_contains(self):
        """The old comment 'already contains identity, style, honorifics' should be gone."""
        source = (_SRC / "brain" / "prompt_engineering.py").read_text("utf-8")
        self.assertNotIn(
            "already contains identity, style, honorifics",
            source,
        )


if __name__ == "__main__":
    unittest.main()
