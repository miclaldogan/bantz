# SPDX-License-Identifier: MIT
"""Issue #1226: Regression Test Suite.

Top 5 recurring bug scenarios that must never regress.
These tests cover the most common failure modes observed in production.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bantz.brain.orchestrator_state import OrchestratorState


pytestmark = pytest.mark.regression


# ============================================================================
# Regression #1: Turkish anaphora tokens detected on EN-translated text
# (Issue #1254 — was the most critical LanguageBridge interaction bug)
# ============================================================================
class TestRegressionAnaphoricBridge:
    """Anaphoric check must use original TR text, not bridge-translated EN."""

    def test_tr_tokens_in_anaphora_set(self) -> None:
        """Turkish follow-up tokens are in the _ANAPHORA_TOKENS set."""
        from bantz.brain.llm_router import JarvisLLMOrchestrator
        anaphora = JarvisLLMOrchestrator._ANAPHORA_TOKENS
        tr_tokens = {"başka", "içeriğinde", "içeriği", "daha", "neler", "bana", "söyle"}
        assert tr_tokens.issubset(anaphora)

    def test_state_preserves_original_input(self) -> None:
        """state.current_user_input should hold original TR text."""
        state = OrchestratorState()
        state.current_user_input = "yarın sabah toplantı koy"
        assert state.current_user_input == "yarın sabah toplantı koy"


# ============================================================================
# Regression #2: Finalizer context overflow on 4096-token models
# (Issue #1253 — QualityFinalizer used budget=5000 with 4096 context)
# ============================================================================
class TestRegressionContextOverflow:
    """Finalizer must cap prompt budget below context window."""

    def test_get_context_window_default(self) -> None:
        from bantz.brain.finalization_pipeline import _get_context_window
        assert _get_context_window(None) == 4096

    def test_get_context_window_from_attr(self) -> None:
        from bantz.brain.finalization_pipeline import _get_context_window
        mock_llm = MagicMock()
        mock_llm.get_model_context_length = MagicMock(side_effect=AttributeError)
        mock_llm.context_window = 8192
        assert _get_context_window(mock_llm) == 8192


# ============================================================================
# Regression #3: NLU period-of-day words ignored
# (Issue #1255 — "yarın sabah" returned tomorrow with base hour, not 09:00)
# ============================================================================
class TestRegressionPeriodOfDay:
    """extract_time must handle period-of-day words."""

    def test_yarin_sabah(self) -> None:
        from datetime import datetime
        from bantz.nlu.slots import extract_time
        base = datetime(2025, 1, 15, 10, 0, 0)
        result = extract_time("yarın sabah", base_time=base)
        assert result is not None
        assert result.value.hour == 9

    def test_yarin_aksam(self) -> None:
        from datetime import datetime
        from bantz.nlu.slots import extract_time
        base = datetime(2025, 1, 15, 10, 0, 0)
        result = extract_time("yarın akşam", base_time=base)
        assert result is not None
        assert result.value.hour == 18


# ============================================================================
# Regression #4: Fuzzy mail match fails on Turkish İ lowering
# (Issue #1256 — Python .lower() maps İ to i+U+0307, breaking tokenization)
# ============================================================================
class TestRegressionTurkishLower:
    """Turkish İ lowering must strip combining dot."""

    def test_turkish_lower_tubitak(self) -> None:
        from bantz.brain.orchestrator_loop import _turkish_lower
        assert _turkish_lower("TÜBİTAK") == "tübitak"

    def test_fuzzy_match_with_typo(self) -> None:
        from bantz.brain.orchestrator_loop import _match_mail_by_keyword
        messages = [
            {"id": "m1", "subject": "TÜBİTAK Proje Onayı", "from": "tubitak@gov.tr"},
        ]
        # Typo: tübirak instead of tübitak
        result = _match_mail_by_keyword("tübirak maili", messages)
        assert result == "m1"


# ============================================================================
# Regression #5: Calendar #N refs not resolved across turns
# (Issue #1224 — "#2 sil" had no way to resolve to actual event_id)
# ============================================================================
class TestRegressionCalendarRefs:
    """Calendar #N references must resolve to stored event_ids."""

    def test_hash_ref_parsing(self) -> None:
        from bantz.brain.calendar_intent import parse_hash_ref_index
        assert parse_hash_ref_index("#1 sil") == 1
        assert parse_hash_ref_index("#3'ü güncelle") == 3
        assert parse_hash_ref_index("toplantıyı sil") is None

    def test_context_persistence(self) -> None:
        from bantz.brain.orchestrator_loop import OrchestratorLoop
        state = OrchestratorState()
        events = [
            {"id": "e1", "summary": "A", "start": "T09:00", "end": "T10:00"},
            {"id": "e2", "summary": "B", "start": "T11:00", "end": "T12:00"},
        ]
        OrchestratorLoop._save_calendar_context(
            [{"tool": "calendar.list_events", "success": True, "raw_result": {"ok": True, "events": events}}],
            state,
        )
        assert state.calendar_listed_events[0]["id"] == "e1"
        assert state.calendar_listed_events[1]["id"] == "e2"
