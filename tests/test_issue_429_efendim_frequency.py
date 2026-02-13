"""
Tests for Issue #429 — Efendim frequency control.

Covers:
- limit_efendim: removes excess efendim, keeps preferred position
- count_efendim: accurate count
- Edge cases: empty, no efendim, single, Turkish casing
- EfendimPosition: START vs END preference
- Integration with VoiceStyle.acknowledge
"""

from __future__ import annotations

import pytest

from bantz.voice_style import (
    EfendimConfig,
    EfendimPosition,
    VoiceStyle,
    count_efendim,
    limit_efendim,
)


# ─────────────────────────────────────────────────────────────────
# count_efendim
# ─────────────────────────────────────────────────────────────────


class TestCountEfendim:
    """Test efendim counter."""

    def test_none(self):
        assert count_efendim("Merhaba nasılsınız?") == 0

    def test_one(self):
        assert count_efendim("Merhaba efendim, nasılsınız?") == 1

    def test_multiple(self):
        assert count_efendim("Efendim, merhaba efendim. Nasılsınız efendim?") == 3

    def test_empty(self):
        assert count_efendim("") == 0

    def test_case_insensitive(self):
        assert count_efendim("EFENDIM nasılsınız Efendim?") == 2


# ─────────────────────────────────────────────────────────────────
# limit_efendim — keep START (default)
# ─────────────────────────────────────────────────────────────────


class TestLimitEfendimStart:
    """Test limiting efendim with START preference (default)."""

    def test_already_one(self):
        text = "Merhaba efendim, nasılsınız?"
        assert limit_efendim(text) == text

    def test_no_efendim(self):
        text = "Merhaba, nasılsınız?"
        assert limit_efendim(text) == text

    def test_two_keeps_first(self):
        result = limit_efendim("Merhaba efendim, nasılsınız efendim?")
        assert count_efendim(result) == 1
        # First efendim kept
        assert "Merhaba efendim" in result

    def test_three_keeps_first(self):
        result = limit_efendim(
            "Efendim, etkinlik oluşturuldu efendim. Başka bir şey var mı efendim?"
        )
        assert count_efendim(result) == 1
        assert result.startswith("Efendim")

    def test_every_sentence(self):
        """The problem case from the issue: efendim in every sentence."""
        text = "Merhaba efendim, nasılsınız efendim? Size nasıl yardımcı olabilirim efendim?"
        result = limit_efendim(text)
        assert count_efendim(result) == 1

    def test_empty_string(self):
        assert limit_efendim("") == ""

    def test_max_count_two(self):
        text = "Efendim bir efendim iki efendim üç efendim"
        result = limit_efendim(text, max_count=2)
        assert count_efendim(result) == 2


# ─────────────────────────────────────────────────────────────────
# limit_efendim — keep END
# ─────────────────────────────────────────────────────────────────


class TestLimitEfendimEnd:
    """Test limiting efendim with END preference."""

    def test_two_keeps_last(self):
        result = limit_efendim(
            "Efendim, etkinlik oluşturuldu efendim.",
            preferred_position=EfendimPosition.END,
        )
        assert count_efendim(result) == 1
        assert result.rstrip(".").endswith("efendim")

    def test_three_keeps_last(self):
        result = limit_efendim(
            "Efendim merhaba efendim güle güle efendim.",
            preferred_position=EfendimPosition.END,
        )
        assert count_efendim(result) == 1


# ─────────────────────────────────────────────────────────────────
# Tool success summary
# ─────────────────────────────────────────────────────────────────


class TestToolSuccessSummary:
    """Verify tool-generated responses get deduplicated too."""

    def test_tool_result(self):
        text = "Etkinlik oluşturuldu efendim. Takvime eklendi efendim."
        result = limit_efendim(text)
        assert count_efendim(result) == 1

    def test_pure_efendim(self):
        """Edge case: response is just 'Efendim.'."""
        text = "Efendim."
        result = limit_efendim(text)
        assert result == "Efendim."


# ─────────────────────────────────────────────────────────────────
# EfendimConfig
# ─────────────────────────────────────────────────────────────────


class TestEfendimConfig:
    """Test config dataclass."""

    def test_defaults(self):
        cfg = EfendimConfig()
        assert cfg.max_per_turn == 1
        assert cfg.preferred_position == EfendimPosition.START

    def test_custom(self):
        cfg = EfendimConfig(max_per_turn=2, preferred_position=EfendimPosition.END)
        assert cfg.max_per_turn == 2


# ─────────────────────────────────────────────────────────────────
# Case sensitivity
# ─────────────────────────────────────────────────────────────────


class TestCaseSensitivity:
    """Ensure mixed-case 'Efendim' / 'efendim' / 'EFENDIM' all handled."""

    def test_uppercase(self):
        result = limit_efendim("EFENDIM merhaba EFENDIM")
        assert count_efendim(result) == 1

    def test_mixed(self):
        result = limit_efendim("Efendim merhaba efendim nasılsın EFENDIM")
        assert count_efendim(result) == 1


# ─────────────────────────────────────────────────────────────────
# VoiceStyle integration
# ─────────────────────────────────────────────────────────────────


class TestVoiceStyleIntegration:
    """Verify VoiceStyle.acknowledge + limit_efendim pipeline."""

    def test_acknowledge_then_limit(self):
        """acknowledge adds Efendim prefix; if LLM also had one, limit cleans it."""
        raw = "Efendim, toplantı eklendi."
        ack = VoiceStyle.acknowledge(raw)
        # acknowledge detects existing efendim, so should not double
        assert count_efendim(ack) <= 2
        final = limit_efendim(ack)
        assert count_efendim(final) == 1

    def test_no_efendim_response(self):
        raw = "Toplantı eklendi."
        ack = VoiceStyle.acknowledge(raw)
        final = limit_efendim(ack)
        assert count_efendim(final) == 1  # acknowledge adds one


# ─────────────────────────────────────────────────────────────────
# 10 varied responses (from issue description)
# ─────────────────────────────────────────────────────────────────


class TestTenVariedResponses:
    """Issue spec: 10 different responses, each max 1 efendim."""

    RESPONSES = [
        "Efendim, bugün 3 toplantınız var efendim.",
        "Merhaba efendim, takvimize baktım efendim. Yoğun bir gün efendim.",
        "Efendim anlaşıldı efendim, etkinlik silindi efendim.",
        "Mail gönderildi efendim. Başka bir şey efendim?",
        "Efendim, saat 14'te toplantı var efendim. Sonrasında boşsunuz efendim.",
        "Takvim güncellendi efendim.",  # already 1
        "Efendim, hava 22 derece efendim.",
        "Anlaşıldı efendim, not alındı efendim.",
        "Efendim, Ahmet Bey'e mail attım efendim. Onay bekliyorum efendim.",
        "Peki efendim, iptal edildi efendim.",
    ]

    @pytest.mark.parametrize("text", RESPONSES)
    def test_max_one_efendim(self, text):
        result = limit_efendim(text)
        assert count_efendim(result) <= 1, f"Too many efendim in: {result}"
        # Text should still be meaningful (not empty)
        assert len(result) > 5
