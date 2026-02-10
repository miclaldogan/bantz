"""Tests for Issue #648: score_writing_need() read-only arama isteklerini QUALITY'e escalate ediyor.

Bug:
  read_only_verbs listesinde "ara", "bul", "getir", "tara", "sorgula" fiilleri
  eksikti. Ayrıca "linkedin" kelimesi write_keywords listesindeydi, bu yüzden
  "linkedin dan gelen mailleri ara" gibi basit arama istekleri writing=4 alıp
  gereksiz yere QUALITY tier'e gidiyordu.

Fix:
  1. "linkedin" → write_keywords'den çıkarılıp read_keywords'e taşındı.
  2. read_only_verbs listesine "ara", "bul", "getir", "tara", "sorgula" eklendi.
  3. Write-intent'li istekler (ör. "linkedin'a post yaz") hâlâ yüksek skor alıyor
     çünkü "yaz" write_keywords'te.
"""

from __future__ import annotations

import pytest

from bantz.llm.tiered import score_writing_need


# ─────────────────────────────────────────────────────────────────────────────
# Core fix: read-only search verbs should keep writing score low
# ─────────────────────────────────────────────────────────────────────────────

class TestReadOnlyVerbsFix:
    """Issue #648 fix: read-only verbs in read_keywords context → score ≤ 1."""

    def test_linkedin_mail_ara_is_fast(self):
        """Exact scenario from the issue: was 4, now should be 1."""
        assert score_writing_need("linkedin dan gelen mailleri ara") == 1

    def test_mail_ara_is_fast(self):
        assert score_writing_need("mail ara") == 1

    def test_mailleri_bul_is_fast(self):
        assert score_writing_need("mailleri bul") == 1

    def test_eposta_sorgula_is_fast(self):
        assert score_writing_need("e-posta sorgula") == 1

    def test_mailleri_sorgula_is_fast(self):
        assert score_writing_need("mailleri sorgula") == 1

    def test_maillerimi_listele_is_fast(self):
        """Pre-existing correct behaviour — should stay at 1."""
        assert score_writing_need("maillerimi listele") == 1

    def test_linkedin_mesajlarini_oku_is_fast(self):
        assert score_writing_need("linkedin mesajlarını oku") == 1

    def test_linkedin_bak_is_fast(self):
        assert score_writing_need("linkedin'a bak") == 1

    def test_haber_ara_is_fast(self):
        assert score_writing_need("haber ara") == 1

    def test_email_bul_is_fast(self):
        assert score_writing_need("email bul") == 1

    def test_pdf_getir_is_fast(self):
        """'getir' was missing from read_only_verbs."""
        assert score_writing_need("pdf getir") == 1


# ─────────────────────────────────────────────────────────────────────────────
# No-match edge cases: no read_keywords hit → score stays 0
# ─────────────────────────────────────────────────────────────────────────────

class TestNoMatchEdgeCases:
    """When neither write nor read keywords match, score should be 0."""

    def test_mesajlari_getir_zero(self):
        """'mesajlar' is NOT in read_keywords → 0."""
        assert score_writing_need("mesajları getir") == 0

    def test_inbox_tara_zero(self):
        assert score_writing_need("inbox u tara") == 0

    def test_empty_string(self):
        assert score_writing_need("") == 0

    def test_none_input(self):
        assert score_writing_need(None) == 0

    def test_whitespace_only(self):
        assert score_writing_need("   ") == 0


# ─────────────────────────────────────────────────────────────────────────────
# Regression: write-intent keywords must STILL score high
# ─────────────────────────────────────────────────────────────────────────────

class TestWriteIntentRegression:
    """Ensure write-intent requests still escalate to QUALITY."""

    def test_linkedin_post_yaz_is_quality(self):
        """'yaz' is a write keyword → 4, even though 'linkedin' moved."""
        assert score_writing_need("linkedin a post yaz") == 4

    def test_hocaya_mail_yaz_is_quality(self):
        assert score_writing_need("hocaya mail yaz") == 4

    def test_taslak_olustur_is_quality(self):
        assert score_writing_need("taslak oluştur") == 4

    def test_dilekce_yaz_is_quality(self):
        assert score_writing_need("dilekçe yaz") == 4

    def test_cv_duzenle_is_quality(self):
        assert score_writing_need("cv düzenle") == 4

    def test_blog_yazisi_yaz_is_quality(self):
        assert score_writing_need("blog yazısı yaz") == 4

    def test_resmi_metin_is_quality(self):
        assert score_writing_need("resmi metin yaz") == 4

    def test_cover_letter_is_quality(self):
        assert score_writing_need("cover letter yaz") == 4


# ─────────────────────────────────────────────────────────────────────────────
# Ambiguous: read_keywords WITHOUT read_only_verbs → moderate (3)
# ─────────────────────────────────────────────────────────────────────────────

class TestAmbiguousContext:
    """read_keywords present but no read_only_verb → moderate score (3)."""

    def test_linkedin_profil_guncelle_is_moderate(self):
        """'linkedin' in read_keywords, no read_only_verb, no write keyword → 3."""
        assert score_writing_need("linkedin profil güncelle") == 3

    def test_mail_hakkinda_bir_sey_yap(self):
        assert score_writing_need("mail hakkında bir şey yap") == 3


# ─────────────────────────────────────────────────────────────────────────────
# Short-ack dampener should still work
# ─────────────────────────────────────────────────────────────────────────────

class TestShortAckDampener:
    """'kısaca', 'tl;dr' etc. should reduce score by 2."""

    def test_kisaca_dampens_write(self):
        """write_keywords match (4) - 2 dampener = 2."""
        assert score_writing_need("taslak yaz kısaca") == 2

    def test_tldr_dampens_read(self):
        """read_keywords + no read_only_verb (3) - 2 dampener = 1."""
        assert score_writing_need("mail tl;dr") == 1

    def test_kisaca_dampens_to_zero(self):
        """read_keywords + read_only_verb (1) - 2 dampener = 0 (clamped)."""
        assert score_writing_need("mail listele kısaca") == 0


# ─────────────────────────────────────────────────────────────────────────────
# Parametrized: every new read_only_verb with every read_keyword
# ─────────────────────────────────────────────────────────────────────────────

NEW_VERBS = ["ara", "bul", "getir", "tara", "sorgula"]
READ_KEYWORDS = ["mail", "e-posta", "email", "haber", "linkedin", "pdf", "classroom"]


@pytest.mark.parametrize("verb", NEW_VERBS)
@pytest.mark.parametrize("keyword", READ_KEYWORDS)
def test_new_verb_with_read_keyword_is_fast(keyword: str, verb: str):
    """Every new verb + every read keyword should produce score ≤ 1."""
    text = f"{keyword} {verb}"
    score = score_writing_need(text)
    assert score <= 1, f"score_writing_need('{text}') = {score}, expected ≤ 1"
