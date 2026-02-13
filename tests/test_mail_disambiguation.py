# SPDX-License-Identifier: MIT
"""Issue #1230: Mail disambiguation-first tests.

Ensures that when user asks for mail content without specifying which mail,
the system either resolves via #N ref / keyword match, or asks the user to
disambiguate instead of hallucinating content.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bantz.brain.orchestrator_state import OrchestratorState


# ── Sample listed messages ──────────────────────────────────────────────────

SAMPLE_MESSAGES = [
    {"id": "m1", "from": "github-actions@github.com", "subject": "Build passed"},
    {"id": "m2", "from": "ali@company.com", "subject": "Sprint notları"},
    {"id": "m3", "from": "tubitak@gov.tr", "subject": "TÜBİTAK Proje Onayı"},
]


# ── #N reference resolution ─────────────────────────────────────────────────

class TestGmailHashRefResolution:
    """#N references (e.g. '#2 maili anlat') must resolve to the correct id."""

    def test_hash_ref_resolves(self) -> None:
        from bantz.brain.calendar_intent import parse_hash_ref_index
        assert parse_hash_ref_index("#1 maili anlat") == 1
        assert parse_hash_ref_index("#3 nedir") == 3

    def test_hash_ref_out_of_range(self) -> None:
        from bantz.brain.calendar_intent import parse_hash_ref_index
        # #N beyond listed messages should return the index (validation happens later)
        idx = parse_hash_ref_index("#99 maili göster")
        assert idx == 99


# ── Keyword match ───────────────────────────────────────────────────────────

class TestMailKeywordMatch:
    """Keyword-based mail resolution should work for detail/read intent."""

    def test_github_keyword_match(self) -> None:
        from bantz.brain.orchestrator_loop import _match_mail_by_keyword
        result = _match_mail_by_keyword("github maili", SAMPLE_MESSAGES)
        assert result == "m1"

    def test_tubitak_keyword_match(self) -> None:
        from bantz.brain.orchestrator_loop import _match_mail_by_keyword
        result = _match_mail_by_keyword("tübitak maili", SAMPLE_MESSAGES)
        assert result == "m3"

    def test_no_match_returns_none(self) -> None:
        from bantz.brain.orchestrator_loop import _match_mail_by_keyword
        result = _match_mail_by_keyword("içeriğini anlat", SAMPLE_MESSAGES)
        assert result is None


# ── Disambiguation prompt ───────────────────────────────────────────────────

class TestMailDisambiguation:
    """When no match found, system must ask user to pick a mail."""

    def _run_disambiguation(
        self,
        user_input: str,
        gmail_intent: str = "detail",
        messages: list[dict[str, str]] | None = None,
    ) -> Any:
        """Simulate the orchestrator loop post-processing for disambiguation."""
        from bantz.brain.orchestrator_loop import _match_mail_by_keyword
        from bantz.brain.llm_router import OrchestratorOutput

        msgs = messages if messages is not None else SAMPLE_MESSAGES
        state = OrchestratorState()
        state.gmail_listed_messages = msgs

        output = OrchestratorOutput(
            route="gmail",
            calendar_intent="none",
            gmail_intent=gmail_intent,
            slots={},
            confidence=0.9,
            tool_plan=["gmail.get_message"],
            assistant_reply="",
        )

        # Simulate the #1230 disambiguation block
        if (
            state.gmail_listed_messages
            and output.route == "gmail"
            and output.gmail_intent in ("read", "detail")
            and not (output.slots or {}).get("message_id")
        ):
            _mail_resolved = False

            # 1) #N ref
            try:
                from bantz.brain.calendar_intent import parse_hash_ref_index
                _ref = parse_hash_ref_index(user_input)
                if _ref is not None and 1 <= _ref <= len(state.gmail_listed_messages):
                    _msg = state.gmail_listed_messages[_ref - 1]
                    output = replace(
                        output,
                        tool_plan=["gmail.get_message"],
                        slots={**output.slots, "message_id": _msg["id"]},
                    )
                    _mail_resolved = True
            except Exception:
                pass

            # 2) Keyword match
            if not _mail_resolved:
                _kw_id = _match_mail_by_keyword(user_input, state.gmail_listed_messages)
                if _kw_id:
                    output = replace(
                        output,
                        tool_plan=["gmail.get_message"],
                        slots={**output.slots, "message_id": _kw_id},
                    )
                    _mail_resolved = True

            # 3) Disambiguation
            if not _mail_resolved:
                lines = ["Hangi maili istiyorsunuz efendim?"]
                for i, m in enumerate(state.gmail_listed_messages[:10], start=1):
                    _subj = m.get("subject") or "(konu yok)"
                    _sender = m.get("from") or ""
                    lines.append(f"  #{i}  {_sender} — {_subj}")
                output = replace(
                    output,
                    ask_user=True,
                    question="\n".join(lines),
                    tool_plan=[],
                )

        return output

    def test_ambiguous_request_asks_user(self) -> None:
        """'içeriğini anlat' without keyword → disambiguation prompt."""
        result = self._run_disambiguation("içeriğini anlat")
        assert result.ask_user is True
        assert "Hangi maili" in result.question
        assert result.tool_plan == []

    def test_disambiguation_lists_all_messages(self) -> None:
        """Disambiguation prompt must list all stored messages."""
        result = self._run_disambiguation("özetle bakalım")
        assert "#1" in result.question
        assert "#2" in result.question
        assert "#3" in result.question
        assert "github" in result.question.lower()

    def test_hash_ref_resolves_directly(self) -> None:
        """'#2 maili anlat' → resolves to m2 without disambiguation."""
        result = self._run_disambiguation("#2 maili anlat")
        assert result.ask_user is False
        assert result.slots.get("message_id") == "m2"
        assert result.tool_plan == ["gmail.get_message"]

    def test_keyword_resolves_directly(self) -> None:
        """'github maili' → resolves to m1 without disambiguation."""
        result = self._run_disambiguation("github maili hakkında bilgi ver")
        assert result.ask_user is False
        assert result.slots.get("message_id") == "m1"

    def test_list_intent_skips_disambiguation(self) -> None:
        """'list' intent should NOT trigger disambiguation."""
        result = self._run_disambiguation("son mailleri göster", gmail_intent="list")
        assert result.ask_user is False  # no disambiguation for list intent

    def test_no_listed_messages_skips(self) -> None:
        """If no previous messages stored, disambiguation shouldn't fire."""
        result = self._run_disambiguation("içeriğini anlat", messages=[])
        assert result.ask_user is False

    def test_no_factual_claim_in_disambiguation(self) -> None:
        """Disambiguation response must NOT contain any mail body/content."""
        result = self._run_disambiguation("bu maili anlat")
        if result.ask_user:
            # Should only contain subjects/senders, not mail bodies
            assert "body" not in result.question.lower()
            assert "content" not in result.question.lower()
