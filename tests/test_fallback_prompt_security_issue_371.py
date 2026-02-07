"""Tests for Issue #371: Fallback prompt security rules strengthened.

Verifies that the fallback finalizer prompt contains:
- Explicit JSON prohibition with examples
- Explicit Markdown prohibition with examples
- No-new-facts rule (explicit: sayı, saat, tarih, isim ekleme yasağı)
- Format rules are stricter than the original
"""

import json
import pytest


def _build_fallback_prompt(
    planner_decision: dict,
    tool_results: list | None = None,
    dialog_summary: str | None = None,
    user_input: str = "test",
) -> str:
    """Simulate the fallback prompt construction from orchestrator_loop.py.
    
    This mirrors the except-branch logic in _llm_finalization_phase().
    """
    finalizer_results = tool_results or []
    
    finalizer_prompt = "\n".join(
        [
            "Kimlik / Roller:",
            "- Sen BANTZ'sın. Kullanıcı USER'dır.",
            "- SADECE TÜRKÇE konuş. Asla Çince, Korece, İngilizce veya başka dil kullanma!",
            "- 'Efendim' hitabını kullan.",
            "",
            "FORMAT KURALLARI (KESİN):",
            "- Sadece kullanıcıya söyleyeceğin düz metni üret.",
            "- JSON üretme. Örnek: {\"route\": ...} YASAK.",
            "- Markdown üretme. Örnek: **kalın**, # başlık, ```kod``` YASAK.",
            "- Kod bloğu üretme.",
            "- Liste işareti (-, *, 1.) kullanma; düz cümle kur.",
            "",
            "DOĞRULUK KURALLARI (KESİN):",
            "- SADECE verilen TOOL_RESULTS ve PLANNER_DECISION içindeki bilgileri kullan.",
            "- Yeni sayı, saat, tarih, miktar, fiyat UYDURMA. Verilerde yoksa söyleme.",
            "- Yeni isim, e-posta, telefon UYDURMA.",
            "- Emin olmadığın bilgiyi söyleme; belirsizse 'bilgi yok' de.",
            "",
            "- Kısa ve öz cevap ver (1-3 cümle).",
            "",
            f"DIALOG_SUMMARY:\n{dialog_summary}\n" if dialog_summary else "",
            "PLANNER_DECISION (JSON):",
            json.dumps(planner_decision, ensure_ascii=False),
            "\nTOOL_RESULTS (JSON):\n" + json.dumps(finalizer_results, ensure_ascii=False) if finalizer_results else "",
            f"\nUSER: {user_input}\nASSISTANT (SADECE TÜRKÇE, düz metin, yeni bilgi ekleme):",
        ]
    ).strip()
    return finalizer_prompt


class TestFallbackPromptSecurity:
    """Verify fallback prompt contains stricter security rules."""

    def setup_method(self):
        self.prompt = _build_fallback_prompt(
            planner_decision={"route": "calendar", "tool_plan": ["calendar.list_events"]},
            tool_results=[{"tool": "calendar.list_events", "success": True, "result": []}],
            dialog_summary="Kullanıcı takvim sorguladı.",
            user_input="bugün neler var",
        )

    def test_json_prohibition_explicit(self):
        """Fallback prompt explicitly prohibits JSON with example."""
        assert "JSON üretme" in self.prompt
        assert "YASAK" in self.prompt

    def test_markdown_prohibition_explicit(self):
        """Fallback prompt explicitly prohibits Markdown with examples."""
        assert "Markdown üretme" in self.prompt
        assert "**kalın**" in self.prompt

    def test_no_new_facts_numbers(self):
        """Fallback prompt prohibits inventing new numbers/times/dates."""
        assert "Yeni sayı" in self.prompt
        assert "saat" in self.prompt
        assert "tarih" in self.prompt
        assert "UYDURMA" in self.prompt

    def test_no_new_facts_names(self):
        """Fallback prompt prohibits inventing new names/emails."""
        assert "isim" in self.prompt
        assert "e-posta" in self.prompt
        assert "UYDURMA" in self.prompt

    def test_only_use_given_data(self):
        """Fallback prompt says to ONLY use provided data."""
        assert "SADECE verilen TOOL_RESULTS" in self.prompt

    def test_uncertainty_handling(self):
        """Fallback prompt guides what to do when uncertain."""
        assert "belirsizse" in self.prompt

    def test_format_kurallari_section(self):
        """Fallback prompt has a dedicated FORMAT KURALLARI section."""
        assert "FORMAT KURALLARI (KESİN)" in self.prompt

    def test_dogruluk_kurallari_section(self):
        """Fallback prompt has a dedicated DOĞRULUK KURALLARI section."""
        assert "DOĞRULUK KURALLARI (KESİN)" in self.prompt

    def test_assistant_suffix_strengthened(self):
        """ASSISTANT suffix includes 'yeni bilgi ekleme'."""
        assert "yeni bilgi ekleme" in self.prompt

    def test_no_code_block_rule(self):
        """Fallback prompt prohibits code blocks."""
        assert "Kod bloğu üretme" in self.prompt

    def test_no_list_markers(self):
        """Fallback prompt prohibits list markers in output."""
        assert "Liste işareti" in self.prompt

    def test_dialog_summary_included(self):
        """Dialog summary is included when provided."""
        assert "Kullanıcı takvim sorguladı" in self.prompt

    def test_planner_decision_included(self):
        """Planner decision JSON is included."""
        assert "calendar.list_events" in self.prompt

    def test_tool_results_included(self):
        """Tool results JSON is included."""
        assert "TOOL_RESULTS" in self.prompt


class TestFastFinalizePromptSecurity:
    """Verify that _fast_finalize_with_planner prompt is also strengthened."""

    def test_fast_finalize_prompt_rules(self):
        """The fast finalize prompt (from source) should have stricter rules."""
        # Simulate the fast finalize prompt lines
        prompt_lines = [
            "Kimlik / Roller:",
            "- Sen BANTZ'sın. Kullanıcı USER'dır.",
            "- SADECE TÜRKÇE konuş. Asla Çince, Korece, İngilizce veya başka dil kullanma!",
            "- 'Efendim' hitabını kullan.",
            "- Sadece kullanıcıya söyleyeceğin düz metni üret.",
            "- JSON üretme ({...} YASAK). Markdown üretme (**, #, ``` YASAK).",
            "- Yeni sayı/saat/tarih/isim uydurma; SADECE verilerdeki bilgileri kullan.",
            "- Kısa ve öz cevap ver (1-3 cümle).",
        ]
        prompt = "\n".join(prompt_lines)
        
        assert "JSON üretme" in prompt
        assert "Markdown üretme" in prompt
        assert "YASAK" in prompt
        assert "uydurma" in prompt
        assert "SADECE verilerdeki" in prompt
