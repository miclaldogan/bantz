"""
Tests for WritePolicy (Issue #36 - V2-4).

Tests:
- Policy decisions (ALLOW/DENY/REDACT)
- Sensitive pattern detection
- Redaction of sensitive content
- Policy configuration
"""

import pytest


class TestWriteDecision:
    """Tests for WriteDecision enum."""
    
    def test_decisions_exist(self):
        """Test all decisions are defined."""
        from bantz.memory.write_policy import WriteDecision
        
        assert WriteDecision.ALLOW.value == "allow"
        assert WriteDecision.DENY.value == "deny"
        assert WriteDecision.REDACT.value == "redact"
        assert WriteDecision.ENCRYPT.value == "encrypt"


class TestPolicyResult:
    """Tests for PolicyResult dataclass."""
    
    def test_result_creation(self):
        """Test PolicyResult creation."""
        from bantz.memory.write_policy import PolicyResult, WriteDecision
        
        result = PolicyResult(
            decision=WriteDecision.ALLOW,
            reason="Test reason"
        )
        
        assert result.decision == WriteDecision.ALLOW
        assert result.reason == "Test reason"
    
    def test_result_is_allowed(self):
        """Test is_allowed property."""
        from bantz.memory.write_policy import PolicyResult, WriteDecision
        
        allow = PolicyResult(decision=WriteDecision.ALLOW)
        redact = PolicyResult(decision=WriteDecision.REDACT)
        deny = PolicyResult(decision=WriteDecision.DENY)
        
        assert allow.is_allowed == True
        assert redact.is_allowed == True
        assert deny.is_allowed == False


class TestWritePolicy:
    """Tests for WritePolicy class."""
    
    @pytest.fixture
    def policy(self):
        """Create WritePolicy for testing."""
        from bantz.memory.write_policy import WritePolicy
        return WritePolicy()
    
    def test_policy_allows_normal_content(self, policy):
        """Test normal content is allowed."""
        from bantz.memory.write_policy import WriteDecision
        
        result = policy.check("Normal text without sensitive data")
        
        assert result.decision == WriteDecision.ALLOW
    
    def test_policy_denies_password(self, policy):
        """Test password content is denied."""
        from bantz.memory.write_policy import WriteDecision
        
        result = policy.check("My password: secret123")
        
        assert result.decision == WriteDecision.DENY
        assert "password" in result.matched_patterns
    
    def test_policy_denies_sifre(self, policy):
        """Test Turkish password (şifre) is denied."""
        from bantz.memory.write_policy import WriteDecision
        
        result = policy.check("Şifre: gizli123")
        
        assert result.decision == WriteDecision.DENY
    
    def test_policy_redacts_email(self, policy):
        """Test email is redacted."""
        from bantz.memory.write_policy import WriteDecision
        
        result = policy.check("Contact me at user@example.com please")
        
        assert result.decision == WriteDecision.REDACT
        assert "email" in result.matched_patterns
        assert "[EMAIL]" in result.redacted_content
    
    def test_policy_redacts_credit_card(self, policy):
        """Test credit card is redacted."""
        from bantz.memory.write_policy import WriteDecision
        
        result = policy.check("Card: 4111-1111-1111-1111")
        
        assert result.decision == WriteDecision.REDACT
        assert "credit_card" in result.matched_patterns
        assert "[CREDIT_CARD]" in result.redacted_content
    
    def test_policy_redacts_tc_kimlik(self, policy):
        """Test TC Kimlik is redacted."""
        from bantz.memory.write_policy import WriteDecision
        
        result = policy.check("TC: 12345678901")
        
        assert result.decision == WriteDecision.REDACT
        assert "tc_kimlik" in result.matched_patterns
        assert "[TC_KIMLIK]" in result.redacted_content
    
    def test_policy_redacts_iban(self, policy):
        """Test IBAN is redacted."""
        from bantz.memory.write_policy import WriteDecision
        
        result = policy.check("IBAN: TR12 0001 0002 0003 0004 0005 00")
        
        assert result.decision == WriteDecision.REDACT
        assert "iban" in result.matched_patterns
    
    def test_policy_denies_api_key(self, policy):
        """Test API key is denied."""
        from bantz.memory.write_policy import WriteDecision
        
        result = policy.check("api_key=sk-1234567890abcdefghij")
        
        assert result.decision == WriteDecision.DENY
        assert "api_key" in result.matched_patterns
    
    def test_policy_profile_stricter(self, policy):
        """Test profile type triggers redaction."""
        from bantz.memory.write_policy import WriteDecision
        from bantz.memory.snippet import SnippetType
        
        result = policy.check("Email: test@test.com", SnippetType.PROFILE)
        
        assert result.decision == WriteDecision.REDACT
    
    def test_policy_empty_content(self, policy):
        """Test empty content is allowed."""
        from bantz.memory.write_policy import WriteDecision
        
        result = policy.check("")
        
        assert result.decision == WriteDecision.ALLOW
    
    def test_redact_sensitive(self, policy):
        """Test redact_sensitive method."""
        content = "Email: user@test.com, Card: 1234567890123456"
        
        redacted = policy.redact_sensitive(content)
        
        assert "[EMAIL]" in redacted
        assert "[CREDIT_CARD]" in redacted
        assert "user@test.com" not in redacted


class TestSensitivePattern:
    """Tests for SensitivePattern class."""
    
    def test_pattern_matches(self):
        """Test pattern matching."""
        from bantz.memory.write_policy import SensitivePattern
        
        pattern = SensitivePattern(
            name="test",
            pattern=r"\btest\b"
        )
        
        matches = pattern.matches("This is a test string")
        
        assert len(matches) >= 1
    
    def test_pattern_redact(self):
        """Test pattern redaction."""
        from bantz.memory.write_policy import SensitivePattern
        
        pattern = SensitivePattern(
            name="secret",
            pattern=r"secret\d+",
            replacement="[SECRET]"
        )
        
        result = pattern.redact("My secret123 is here")
        
        assert result == "My [SECRET] is here"


class TestWritePolicyFactory:
    """Tests for create_write_policy factory."""
    
    def test_factory_creates_policy(self):
        """Test factory creates policy."""
        from bantz.memory.write_policy import create_write_policy, WritePolicy
        
        policy = create_write_policy()
        
        assert isinstance(policy, WritePolicy)
    
    def test_factory_strict_mode(self):
        """Test factory with strict mode."""
        from bantz.memory.write_policy import create_write_policy, WriteDecision
        
        policy = create_write_policy(strict_mode=True)
        
        # Any sensitive content should be denied in strict mode
        result = policy.check("Email: test@test.com")
        
        assert result.decision == WriteDecision.DENY
    
    def test_factory_custom_patterns(self):
        """Test factory with custom patterns."""
        from bantz.memory.write_policy import (
            create_write_policy,
            SensitivePattern,
            WriteDecision
        )
        
        custom = SensitivePattern(
            name="custom",
            pattern=r"CUSTOM-\d+",
            decision=WriteDecision.REDACT,
            replacement="[CUSTOM]"
        )
        
        policy = create_write_policy(custom_patterns=[custom])
        
        result = policy.check("Code: CUSTOM-12345")
        
        assert "custom" in result.matched_patterns
