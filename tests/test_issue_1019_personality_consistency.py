"""Tests for Issue #1019: Personality block consistency — Broadcaster persona."""

from __future__ import annotations

import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "bantz"


class TestPersonalityBlockConsistency(unittest.TestCase):
    """Ensure Broadcaster identity appears regardless of personality_block."""

    def _build(self, personality_block=None):
        from bantz.brain.prompt_engineering import PromptBuilder
        pb = PromptBuilder()
        return pb._build_system_prompt(
            variant="A", writing=2, personality_block=personality_block
        )

    def test_default_has_broadcaster_identity(self):
        """Default system prompt (no personality_block) includes Broadcaster identity."""
        prompt = self._build()
        self.assertIn("Broadcaster", prompt)

    def test_personality_block_used(self):
        """If personality_block is provided, it appears in the prompt."""
        prompt = self._build(personality_block="- You are Bantz, The Broadcaster.")
        self.assertIn("Broadcaster", prompt)

    def test_always_has_tone(self):
        """Tone rule should always be present."""
        for pb in [None, "- Custom personality."]:
            prompt = self._build(personality_block=pb)
            self.assertIn("Tone:", prompt)

    def test_always_has_output_format_rule(self):
        """Output format rule should always be present."""
        for pb in [None, "- Custom personality."]:
            prompt = self._build(personality_block=pb)
            self.assertIn("No JSON/Markdown", prompt)

    def test_source_no_comment_about_already_contains(self):
        """The old comment 'already contains identity, style, honorifics' should be gone."""
        source = (_SRC / "brain" / "prompt_engineering.py").read_text("utf-8")
        self.assertNotIn(
            "already contains identity, style, honorifics",
            source,
        )


if __name__ == "__main__":
    unittest.main()
