"""Tests for Issue #449 — Memory write policy (save-worthy filter).

Covers:
- Sensitivity classifier: email, phone, TC kimlik, credit card, passwords
- Write decision engine: ALWAYS / ASK / NEVER categories
- Dedup (same content → skip)
- Smalltalk → never
- User preferences → always
- Task results → always
- Personal info → ask
- Sensitive data → never
"""

from __future__ import annotations

import pytest

from bantz.memory.sensitivity import (
    SensitivityLevel,
    SensitivityResult,
    classify_sensitivity,
)
from bantz.memory.write_decision import (
    MemoryWriteDecision,
    WriteDecisionEngine,
)


# ===================================================================
# 1. Sensitivity classifier
# ===================================================================

class TestSensitivityClassifier:
    def test_no_sensitive_content(self):
        r = classify_sensitivity("Bugün hava güzel.")
        assert r.level == SensitivityLevel.NONE
        assert r.matched_patterns == []

    def test_email_detection(self):
        r = classify_sensitivity("Mail adresim test@example.com")
        assert r.level == SensitivityLevel.MEDIUM
        assert any(p[0] == "email" for p in r.matched_patterns)

    def test_phone_tr_detection(self):
        r = classify_sensitivity("Numaram +90 532 123 45 67")
        assert r.level == SensitivityLevel.MEDIUM
        assert any(p[0] == "phone_tr" for p in r.matched_patterns)

    def test_password_keyword(self):
        r = classify_sensitivity("Şifrem: gizli1234")
        assert r.level == SensitivityLevel.HIGH
        assert any(p[0] == "password_keyword" for p in r.matched_patterns)

    def test_api_key_keyword(self):
        r = classify_sensitivity("api_key=sk_12345abcdef")
        assert r.level == SensitivityLevel.HIGH

    def test_tc_kimlik(self):
        r = classify_sensitivity("TC Kimlik: 12345678901")
        assert r.level == SensitivityLevel.HIGH
        assert any(p[0] == "tc_kimlik" for p in r.matched_patterns)

    def test_address_keyword(self):
        r = classify_sensitivity("Adresim Kadıköy Moda mahalle")
        assert r.level == SensitivityLevel.LOW
        assert any(p[0] == "address_keyword" for p in r.matched_patterns)

    def test_multiple_patterns(self):
        r = classify_sensitivity("Email: a@b.com, şifre: 1234")
        assert r.level == SensitivityLevel.HIGH  # worst-case
        assert len(r.matched_patterns) >= 2

    def test_clean_turkish_text(self):
        r = classify_sensitivity("Yarın toplantım var saat 3'te")
        assert r.level == SensitivityLevel.NONE


# ===================================================================
# 2. Write decision — NEVER cases
# ===================================================================

class TestWriteNever:
    def test_password_never(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate("Şifrem: 1234abcd")
        assert d.should_write is False
        assert d.category == "never"
        assert d.sensitivity == "high"

    def test_smalltalk_merhaba(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate("Merhaba!")
        assert d.should_write is False
        assert d.category == "never"
        assert "smalltalk" in d.reason.lower() or "sohbet" in d.reason.lower()

    def test_smalltalk_tamam(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate("Tamam")
        assert d.should_write is False
        assert d.category == "never"

    def test_short_content_never(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate("ok")
        assert d.should_write is False

    def test_token_never(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate("auth_token=eyJhbGciOiJIUzI1NiJ9")
        assert d.should_write is False
        assert d.category == "never"


# ===================================================================
# 3. Write decision — ALWAYS cases
# ===================================================================

class TestWriteAlways:
    def test_user_preference_birthday(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate("Doğum günüm 15 Mart")
        assert d.should_write is True
        assert d.category == "always"

    def test_user_preference_tercih(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate("Koyu tema tercih ediyorum artık")
        assert d.should_write is True
        assert d.category == "always"

    def test_hatirla_keyword(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate("Bunu hatırla: toplantı her Pazartesi")
        assert d.should_write is True
        assert d.category == "always"

    def test_task_result_route(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate(
            "Etkinlik oluşturuldu: Toplantı yarın 15:00",
            turn_context={"route": "calendar.create_event"},
        )
        assert d.should_write is True
        assert d.category == "always"

    def test_is_task_result_flag(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate(
            "Gmail gönderildi: konu: merhaba",
            turn_context={"is_task_result": True},
        )
        assert d.should_write is True
        assert d.category == "always"

    def test_substantial_general_content(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate("Yarın Ankara'ya gidiyorum, toplantı için hazırlık yapmalıyım")
        assert d.should_write is True


# ===================================================================
# 4. Write decision — ASK cases
# ===================================================================

class TestWriteAsk:
    def test_address_ask(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate("Adresim Kadıköy Moda Caddesi No:5 çok güzel bir yer")
        assert d.category == "ask"

    def test_phone_ask(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate("Bana +90 532 123 45 67 numarasından ulaşabilirsin")
        assert d.category == "ask"
        assert d.sensitivity == "medium"

    def test_financial_ask(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate("Maaşım 30 bin TL civarında, bütçe hesaplayalım")
        assert d.category == "ask"

    def test_health_ask(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate("Doktor randevusu almalıyım, sağlık kontrolü var")
        assert d.category == "ask"


# ===================================================================
# 5. Dedup
# ===================================================================

class TestDedup:
    def test_same_content_skipped(self):
        engine = WriteDecisionEngine()
        d1 = engine.evaluate("Yarın toplantı ayarla saat 15:00'e kesinlikle")
        assert d1.should_write is True
        d2 = engine.evaluate("Yarın toplantı ayarla saat 15:00'e kesinlikle")
        assert d2.should_write is False
        assert "dedup" in d2.reason.lower()

    def test_different_content_not_deduped(self):
        engine = WriteDecisionEngine()
        d1 = engine.evaluate("Yarın toplantı var sabah erkenden kalkmalıyım")
        d2 = engine.evaluate("Bugün market alışverişi yapmalıyım sonra")
        assert d1.should_write is True
        assert d2.should_write is True

    def test_reset_seen_clears_dedup(self):
        engine = WriteDecisionEngine()
        engine.evaluate("Tekrar eden bilgi uzun metin buraya yazılır")
        engine.reset_seen()
        d = engine.evaluate("Tekrar eden bilgi uzun metin buraya yazılır")
        assert d.should_write is True


# ===================================================================
# 6. Content hash
# ===================================================================

class TestContentHash:
    def test_hash_present(self):
        engine = WriteDecisionEngine()
        d = engine.evaluate("test content")
        assert len(d.content_hash) == 64  # SHA-256 hex

    def test_same_content_same_hash(self):
        engine = WriteDecisionEngine()
        d1 = engine.evaluate("hello world 12345678901234567890")
        engine.reset_seen()
        d2 = engine.evaluate("hello world 12345678901234567890")
        assert d1.content_hash == d2.content_hash

    def test_case_insensitive_hash(self):
        engine = WriteDecisionEngine()
        d1 = engine.evaluate("Hello World this is a long test message")
        engine.reset_seen()
        d2 = engine.evaluate("hello world this is a long test message")
        assert d1.content_hash == d2.content_hash
