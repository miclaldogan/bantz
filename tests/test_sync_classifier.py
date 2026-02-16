"""
Tests for bantz.data.sync.classifier — SenderClassifier, ClassificationRule.

Tests cover:
- Default rule matching (github, tubitak, linkedin, etc.)
- Confidence scoring
- Custom rule addition
- YAML config loading
- Edge cases (empty strings, no match)
"""

from __future__ import annotations

import pytest

from bantz.data.sync.classifier import (
    ClassificationRule,
    SenderClassifier,
    classify_sender,
)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def classifier():
    return SenderClassifier()


# ── Default rules ─────────────────────────────────────────────────

class TestDefaultRules:
    def test_github_by_domain(self, classifier: SenderClassifier):
        result = classifier.classify(sender="noreply@github.com")
        assert result == "github"

    def test_github_by_sender_name(self, classifier: SenderClassifier):
        result = classifier.classify(sender_name="GitHub")
        assert result == "github"

    def test_github_by_subject(self, classifier: SenderClassifier):
        result = classifier.classify(subject="[bantz] PR #42 merged")
        assert result == "github"

    def test_tubitak_by_domain(self, classifier: SenderClassifier):
        result = classifier.classify(sender="info@tubitak.gov.tr")
        assert result == "tubitak"

    def test_tubitak_by_name(self, classifier: SenderClassifier):
        result = classifier.classify(sender_name="TÜBİTAK BİDEB")
        assert result == "tubitak"

    def test_tubitak_by_subject(self, classifier: SenderClassifier):
        result = classifier.classify(subject="TÜBİTAK ARDEB Başvuru Sonuçları")
        assert result == "tubitak"

    def test_linkedin(self, classifier: SenderClassifier):
        result = classifier.classify(sender="messages-noreply@linkedin.com")
        assert result == "linkedin"

    def test_google(self, classifier: SenderClassifier):
        result = classifier.classify(sender="noreply@google.com")
        assert result == "google"

    def test_amazon(self, classifier: SenderClassifier):
        result = classifier.classify(sender="orders@amazon.com.tr")
        assert result == "amazon"

    def test_bank_garanti(self, classifier: SenderClassifier):
        result = classifier.classify(sender="bilgi@garanti.com.tr")
        assert result == "bank"

    def test_bank_paypal(self, classifier: SenderClassifier):
        result = classifier.classify(sender_name="PayPal")
        assert result == "bank"

    def test_newsletter(self, classifier: SenderClassifier):
        result = classifier.classify(sender="newsletter@example.com")
        assert result == "newsletter"

    def test_social_twitter(self, classifier: SenderClassifier):
        result = classifier.classify(sender="notify@x.com")
        assert result == "social"

    def test_social_instagram(self, classifier: SenderClassifier):
        result = classifier.classify(sender="noreply@instagram.com")
        assert result == "social"

    def test_education(self, classifier: SenderClassifier):
        result = classifier.classify(sender="registrar@university.edu.tr")
        assert result == "education"

    def test_shopping_trendyol(self, classifier: SenderClassifier):
        result = classifier.classify(sender="info@trendyol.com")
        assert result == "shopping"

    def test_travel_booking(self, classifier: SenderClassifier):
        result = classifier.classify(sender="confirm@booking.com")
        assert result == "travel"

    def test_uncategorized_fallback(self, classifier: SenderClassifier):
        result = classifier.classify(sender="random@unknowndomain.xyz")
        assert result == "uncategorized"


# ── Confidence scoring ────────────────────────────────────────────

class TestConfidence:
    def test_domain_match_high_confidence(self, classifier: SenderClassifier):
        cat, conf = classifier.classify_with_confidence(
            sender="noreply@github.com",
        )
        assert cat == "github"
        assert conf >= 0.9

    def test_sender_regex_confidence(self, classifier: SenderClassifier):
        cat, conf = classifier.classify_with_confidence(
            sender="alerts@tubitak.gov.tr",
        )
        assert cat == "tubitak"
        assert conf >= 0.8

    def test_name_match_confidence(self, classifier: SenderClassifier):
        cat, conf = classifier.classify_with_confidence(
            sender_name="GitHub Actions",
        )
        assert cat == "github"
        assert conf >= 0.7

    def test_subject_match_lower_confidence(self, classifier: SenderClassifier):
        cat, conf = classifier.classify_with_confidence(
            subject="TÜBİTAK Burs Sonuçları",
        )
        assert cat == "tubitak"
        assert conf >= 0.5
        assert conf < 0.9

    def test_no_match_zero_confidence(self, classifier: SenderClassifier):
        cat, conf = classifier.classify_with_confidence(
            sender="user@nowhere.xyz",
            sender_name="Nobody",
            subject="Random stuff",
        )
        assert cat == "uncategorized"
        assert conf == 0.0


# ── Custom rules ──────────────────────────────────────────────────

class TestCustomRules:
    def test_add_custom_rule(self, classifier: SenderClassifier):
        rule = ClassificationRule(
            category="my_company",
            domain_patterns=["mycompany.com"],
            priority=100,
        )
        classifier.add_rule(rule)
        result = classifier.classify(sender="boss@mycompany.com")
        assert result == "my_company"

    def test_custom_rule_priority(self):
        """Higher priority custom rule should override default."""
        custom = ClassificationRule(
            category="vip_github",
            domain_patterns=["github.com"],
            priority=200,
        )
        classifier = SenderClassifier(extra_rules=[custom])
        result = classifier.classify(sender="noreply@github.com")
        assert result == "vip_github"

    def test_categories_property(self, classifier: SenderClassifier):
        cats = classifier.categories
        assert "github" in cats
        assert "tubitak" in cats
        assert "uncategorized" in cats

    def test_rule_count(self, classifier: SenderClassifier):
        initial = classifier.rule_count
        classifier.add_rule(ClassificationRule(category="test", priority=0))
        assert classifier.rule_count == initial + 1


# ── Edge cases ────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_strings(self, classifier: SenderClassifier):
        result = classifier.classify(sender="", sender_name="", subject="")
        assert result == "uncategorized"

    def test_case_insensitive(self, classifier: SenderClassifier):
        result = classifier.classify(sender="NOREPLY@GITHUB.COM")
        assert result == "github"

    def test_mixed_case_name(self, classifier: SenderClassifier):
        result = classifier.classify(sender_name="tübitak")
        assert result == "tubitak"


# ── Module-level convenience ──────────────────────────────────────

class TestModuleFunction:
    def test_classify_sender_convenience(self):
        result = classify_sender(sender="noreply@github.com")
        assert result == "github"

    def test_classify_sender_uncategorized(self):
        result = classify_sender(sender="someone@random.org")
        assert result == "uncategorized"
