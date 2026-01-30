"""
Tests for V2-5 Log Redaction (Issue #37).
"""

import pytest

from bantz.security.redaction import (
    SensitivityLevel,
    RedactionPattern,
    LogRedactor,
    create_log_redactor,
    DEFAULT_PATTERNS,
    SENSITIVE_KEYS,
)


class TestSensitivityLevel:
    """Tests for SensitivityLevel enum."""
    
    def test_sensitivity_levels_exist(self):
        """Test all sensitivity levels exist."""
        assert SensitivityLevel.LOW is not None
        assert SensitivityLevel.MEDIUM is not None
        assert SensitivityLevel.HIGH is not None
        assert SensitivityLevel.CRITICAL is not None
    
    def test_sensitivity_values(self):
        """Test sensitivity level string values."""
        assert SensitivityLevel.LOW.value == "low"
        assert SensitivityLevel.CRITICAL.value == "critical"


class TestRedactionPattern:
    """Tests for RedactionPattern."""
    
    def test_create_pattern(self):
        """Test creating pattern from regex."""
        pattern = RedactionPattern.from_regex(
            name="test_pattern",
            regex=r"secret_\w+",
            sensitivity=SensitivityLevel.HIGH,
            replacement="[SECRET]"
        )
        
        assert pattern.name == "test_pattern"
        assert pattern.sensitivity == SensitivityLevel.HIGH
        assert pattern.replacement == "[SECRET]"
    
    def test_pattern_matching(self):
        """Test pattern matches correctly."""
        pattern = RedactionPattern.from_regex(
            name="api_key",
            regex=r"sk-[a-zA-Z0-9]{32}",
            replacement="[API_KEY]"
        )
        
        text = "My key is sk-abcdefghijklmnopqrstuvwxyz123456"
        result = pattern.pattern.sub(pattern.replacement, text)
        
        assert "[API_KEY]" in result
        assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in result


class TestLogRedactor:
    """Tests for LogRedactor."""
    
    def test_redact_email(self):
        """Test redacting email addresses."""
        redactor = LogRedactor()
        
        text = "Contact me at user@example.com for more info"
        result = redactor.redact(text)
        
        assert "user@example.com" not in result
        assert "[EMAIL]" in result
    
    def test_redact_bearer_token(self):
        """Test redacting bearer tokens."""
        redactor = LogRedactor()
        
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"
        result = redactor.redact(text)
        
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert "[BEARER_TOKEN]" in result
    
    def test_redact_password(self):
        """Test redacting passwords."""
        redactor = LogRedactor()
        
        text = "password=mysupersecretpassword123"
        result = redactor.redact(text)
        
        assert "mysupersecretpassword123" not in result
        assert "[PASSWORD]" in result
    
    def test_redact_credit_card(self):
        """Test redacting credit card numbers."""
        redactor = LogRedactor()
        
        text = "Card number: 4111-1111-1111-1111"
        result = redactor.redact(text)
        
        assert "4111-1111-1111-1111" not in result
        assert "[CREDIT_CARD]" in result
    
    def test_redact_ssn(self):
        """Test redacting SSN."""
        redactor = LogRedactor()
        
        text = "SSN is 123-45-6789"
        result = redactor.redact(text)
        
        assert "123-45-6789" not in result
        assert "[SSN]" in result
    
    def test_redact_dict(self):
        """Test redacting dictionary values."""
        redactor = LogRedactor()
        
        data = {
            "username": "john",
            "password": "secret123",
            "api_key": "sk-abc123",
            "email": "john@example.com"
        }
        
        result = redactor.redact_dict(data)
        
        assert result["username"] == "john"  # Not a sensitive key
        assert result["password"] == "[REDACTED]"  # Sensitive key
        assert result["api_key"] == "[REDACTED]"  # Sensitive key
        # email value should be redacted by pattern
        assert "john@example.com" not in str(result.get("email", ""))
    
    def test_redact_nested_dict(self):
        """Test redacting nested dictionaries."""
        redactor = LogRedactor()
        
        data = {
            "user": {
                "name": "john",
                "password": "secret123"
            }
        }
        
        result = redactor.redact_dict(data, recursive=True)
        
        assert result["user"]["name"] == "john"
        # Password key is sensitive
        assert result["user"]["password"] == "[REDACTED]"
    
    def test_redact_list_in_dict(self):
        """Test redacting lists within dictionaries."""
        redactor = LogRedactor()
        
        data = {
            "emails": ["user1@example.com", "user2@example.com"],
            "tokens": ["secret_token_1"]
        }
        
        result = redactor.redact_dict(data, recursive=True)
        
        # Emails should be redacted
        assert "[EMAIL]" in result["emails"][0]
        assert "tokens" in result
    
    def test_add_pattern(self):
        """Test adding custom pattern."""
        redactor = LogRedactor()
        
        custom_pattern = RedactionPattern.from_regex(
            name="custom",
            regex=r"CUSTOM_\d+",
            replacement="[CUSTOM]"
        )
        redactor.add_pattern(custom_pattern)
        
        text = "Value is CUSTOM_12345"
        result = redactor.redact(text)
        
        assert "[CUSTOM]" in result
    
    def test_add_sensitive_key(self):
        """Test adding sensitive key."""
        redactor = LogRedactor()
        
        redactor.add_sensitive_key("my_secret_field")
        
        data = {"my_secret_field": "hidden_value"}
        result = redactor.redact_dict(data)
        
        assert result["my_secret_field"] == "[REDACTED]"
    
    def test_remove_pattern(self):
        """Test removing a pattern."""
        redactor = LogRedactor()
        
        assert redactor.remove_pattern("email") is True
        
        text = "Contact me at user@example.com"
        result = redactor.redact(text)
        
        # Email should NOT be redacted now
        assert "user@example.com" in result
    
    def test_list_patterns(self):
        """Test listing pattern names."""
        redactor = LogRedactor()
        
        names = redactor.list_patterns()
        
        assert "email" in names
        assert "password" in names
        assert "bearer" in names
    
    def test_factory_function(self):
        """Test create_log_redactor factory."""
        redactor = create_log_redactor(min_sensitivity=SensitivityLevel.HIGH)
        
        assert isinstance(redactor, LogRedactor)
    
    def test_min_sensitivity_filtering(self):
        """Test minimum sensitivity level filtering."""
        # Only redact HIGH and CRITICAL
        redactor = LogRedactor(min_sensitivity=SensitivityLevel.HIGH)
        
        # Email is MEDIUM sensitivity
        text = "Contact me at user@example.com"
        result = redactor.redact(text)
        
        # Should NOT be redacted (MEDIUM < HIGH threshold)
        assert "user@example.com" in result


class TestDefaultPatterns:
    """Tests for default patterns."""
    
    def test_default_patterns_exist(self):
        """Test default patterns are defined."""
        assert len(DEFAULT_PATTERNS) > 0
    
    def test_sensitive_keys_exist(self):
        """Test sensitive keys are defined."""
        assert "password" in SENSITIVE_KEYS
        assert "api_key" in SENSITIVE_KEYS
        assert "token" in SENSITIVE_KEYS
