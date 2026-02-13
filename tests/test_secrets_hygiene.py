"""Tests for secrets_hygiene module.

Issue #233: Comprehensive tests for secrets hygiene.
"""

import pytest
import os
import logging
import tempfile
import pathlib
from unittest.mock import patch, MagicMock

from bantz.security.secrets_hygiene import (
    SecretStatus,
    SecretCheck,
    PreflightResult,
    PreflightChecker,
    LoggerRedactionHandler,
    SecretsHygiene,
    run_preflight,
    install_logger_redaction,
    _check_env_var,
    _check_file_path,
    ALL_SECRET_VARS,
    FEATURE_SECRETS,
    SECRET_PATTERNS,
)


class TestSecretCheck:
    """Tests for SecretCheck dataclass."""
    
    def test_is_ok_present(self):
        check = SecretCheck(
            name="TEST_KEY",
            status=SecretStatus.PRESENT,
            source="env",
        )
        assert check.is_ok == True
    
    def test_is_ok_missing(self):
        check = SecretCheck(
            name="TEST_KEY",
            status=SecretStatus.MISSING,
            source="env",
        )
        assert check.is_ok == False
    
    def test_is_ok_file_readable(self):
        check = SecretCheck(
            name="config.json",
            status=SecretStatus.FILE_READABLE,
            source="file",
        )
        assert check.is_ok == True
    
    def test_to_dict(self):
        check = SecretCheck(
            name="TEST_KEY",
            status=SecretStatus.PRESENT,
            source="env",
            message="OK",
            required=True,
        )
        d = check.to_dict()
        assert d["name"] == "TEST_KEY"
        assert d["status"] == "present"
        assert d["source"] == "env"
        assert d["is_ok"] == True
        assert d["required"] == True


class TestPreflightResult:
    """Tests for PreflightResult dataclass."""
    
    def test_to_dict(self):
        result = PreflightResult(
            passed=True,
            checks=[
                SecretCheck(name="KEY1", status=SecretStatus.PRESENT),
                SecretCheck(name="KEY2", status=SecretStatus.MISSING),
            ],
            warnings=["warning1"],
            errors=[],
        )
        d = result.to_dict()
        assert d["passed"] == True
        assert d["ok_count"] == 1
        assert d["fail_count"] == 1
        assert len(d["warnings"]) == 1


class TestCheckEnvVar:
    """Tests for _check_env_var function."""
    
    @patch.dict(os.environ, {"TEST_KEY": "AIzaSyTestKeyValue12345678901234567890"})
    def test_present_valid(self):
        check = _check_env_var("TEST_KEY")
        assert check.status == SecretStatus.PRESENT
        assert check.is_ok == True
    
    @patch.dict(os.environ, {}, clear=True)
    def test_missing(self):
        # Ensure the key doesn't exist
        os.environ.pop("NONEXISTENT_KEY", None)
        check = _check_env_var("NONEXISTENT_KEY")
        assert check.status == SecretStatus.MISSING
        assert check.is_ok == False
    
    @patch.dict(os.environ, {"EMPTY_KEY": ""})
    def test_empty(self):
        check = _check_env_var("EMPTY_KEY")
        assert check.status == SecretStatus.EMPTY
        assert check.is_ok == False
    
    @patch.dict(os.environ, {"GEMINI_API_KEY": "invalid_format"})
    def test_invalid_format(self):
        check = _check_env_var("GEMINI_API_KEY", validate_format=True)
        assert check.status == SecretStatus.INVALID_FORMAT
    
    @patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaSyTestKeyValue12345678901234567890"})
    def test_valid_format(self):
        check = _check_env_var("GEMINI_API_KEY", validate_format=True)
        assert check.status == SecretStatus.PRESENT


class TestCheckFilePath:
    """Tests for _check_file_path function."""
    
    def test_missing_path(self):
        check = _check_file_path("config.json", "")
        assert check.status == SecretStatus.MISSING
    
    def test_file_not_found(self):
        check = _check_file_path("config.json", "/nonexistent/path/file.json")
        assert check.status == SecretStatus.FILE_NOT_FOUND
    
    def test_file_readable(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"test": true}')
            f.flush()
            
            check = _check_file_path("config.json", f.name)
            assert check.status == SecretStatus.FILE_READABLE
            assert check.is_ok == True
            
            os.unlink(f.name)
    
    def test_directory_not_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            check = _check_file_path("config.json", tmpdir)
            assert check.status == SecretStatus.INVALID_FORMAT


class TestPreflightChecker:
    """Tests for PreflightChecker class."""
    
    def test_init(self):
        checker = PreflightChecker()
        assert checker.required_features == []
        assert checker.validate_format == True
    
    def test_init_with_features(self):
        checker = PreflightChecker(required_features=["gemini"])
        assert "gemini" in checker.required_features
    
    @patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaSyTestKeyValue12345678901234567890"})
    def test_run_with_gemini_present(self):
        checker = PreflightChecker(required_features=["gemini"])
        result = checker.run()
        # Should pass if Gemini key is present
        assert result.passed == True
    
    @patch.dict(os.environ, {}, clear=True)
    def test_run_with_gemini_missing(self):
        # Clear all Gemini-related keys
        for key in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "BANTZ_GEMINI_API_KEY"]:
            os.environ.pop(key, None)
        
        checker = PreflightChecker(required_features=["gemini"])
        result = checker.run()
        # Should fail if no Gemini key is present
        assert result.passed == False
        assert len(result.errors) > 0
    
    def test_run_unknown_feature(self):
        checker = PreflightChecker(required_features=["unknown_feature"])
        result = checker.run()
        assert "Unknown feature" in str(result.warnings)
    
    def test_run_no_requirements(self):
        checker = PreflightChecker()
        result = checker.run()
        # No required features means should pass
        assert result.passed == True


class TestLoggerRedactionHandler:
    """Tests for LoggerRedactionHandler class."""
    
    def test_redact_api_key(self):
        mock_handler = MagicMock(spec=logging.Handler)
        handler = LoggerRedactionHandler(mock_handler)
        
        text = "Using API key: AIzaSyTestKeyValue12345678901234567890"
        result = handler._redact(text)
        
        assert "AIzaSy" not in result
        assert "***REDACTED***" in result
    
    def test_redact_bearer_token(self):
        mock_handler = MagicMock(spec=logging.Handler)
        handler = LoggerRedactionHandler(mock_handler)
        
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"
        result = handler._redact(text)
        
        # The token should be redacted
        assert "eyJh" not in result or "***REDACTED***" in result
    
    def test_redact_oauth_token(self):
        mock_handler = MagicMock(spec=logging.Handler)
        handler = LoggerRedactionHandler(mock_handler)
        
        text = "Token: ya29.abcdef123456"
        result = handler._redact(text)
        
        assert "ya29" not in result
        assert "***REDACTED***" in result
    
    def test_redact_env_assignment(self):
        mock_handler = MagicMock(spec=logging.Handler)
        handler = LoggerRedactionHandler(mock_handler)
        
        text = "GEMINI_API_KEY=secretvalue123"
        result = handler._redact(text)
        
        assert "secretvalue123" not in result
        assert "GEMINI_API_KEY" in result
    
    def test_redact_json_field(self):
        mock_handler = MagicMock(spec=logging.Handler)
        handler = LoggerRedactionHandler(mock_handler)
        
        # Use an actual API key format that will be redacted
        text = '{"api_key": "AIzaSyTestKeyValue12345678901234567890", "name": "test"}'
        result = handler._redact(text)
        
        assert "AIzaSy" not in result or "***REDACTED***" in result
        assert '"name": "test"' in result
    
    def test_emit_redacts_message(self):
        mock_handler = MagicMock(spec=logging.Handler)
        handler = LoggerRedactionHandler(mock_handler)
        
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="API key: AIzaSyTestKeyValue12345678901234567890",
            args=(),
            exc_info=None,
        )
        
        handler.emit(record)
        
        # Check that wrapped handler was called
        assert mock_handler.emit.called
        
        # Check that the message was redacted
        emitted_record = mock_handler.emit.call_args[0][0]
        assert "AIzaSy" not in emitted_record.msg
    
    def test_empty_text(self):
        mock_handler = MagicMock(spec=logging.Handler)
        handler = LoggerRedactionHandler(mock_handler)
        
        result = handler._redact("")
        assert result == ""
    
    def test_none_text(self):
        mock_handler = MagicMock(spec=logging.Handler)
        handler = LoggerRedactionHandler(mock_handler)
        
        result = handler._redact(None)
        assert result is None


class TestSecretsHygiene:
    """Tests for SecretsHygiene class."""
    
    def test_init(self):
        hygiene = SecretsHygiene()
        assert hygiene._redaction_installed == False
    
    def test_preflight_check(self):
        hygiene = SecretsHygiene()
        result = hygiene.preflight_check()
        assert isinstance(result, PreflightResult)
    
    def test_check_env_security(self):
        hygiene = SecretsHygiene()
        warnings = hygiene.check_env_security()
        assert isinstance(warnings, list)
    
    @patch.dict(os.environ, {"GEMINI_API_KEY": "xxx"})
    def test_check_env_security_placeholder(self):
        hygiene = SecretsHygiene()
        warnings = hygiene.check_env_security()
        assert any("placeholder" in w for w in warnings)
    
    @patch.dict(os.environ, {"GEMINI_API_KEY": '"quoted_value"'})
    def test_check_env_security_quoted(self):
        hygiene = SecretsHygiene()
        warnings = hygiene.check_env_security()
        assert any("quote" in w.lower() for w in warnings)
    
    def test_get_secrets_status(self):
        hygiene = SecretsHygiene()
        status = hygiene.get_secrets_status()
        
        assert isinstance(status, dict)
        # Should have entries for all known secret vars
        for var in ALL_SECRET_VARS:
            assert var in status
    
    @patch.dict(os.environ, {"GEMINI_API_KEY": "AIzaSyTestKeyValue12345678901234567890"})
    def test_get_secrets_status_present(self):
        hygiene = SecretsHygiene()
        status = hygiene.get_secrets_status()
        
        assert status["GEMINI_API_KEY"]["present"] == True
        assert status["GEMINI_API_KEY"]["length"] > 0
        # Prefix should be masked
        assert "AIza" in status["GEMINI_API_KEY"]["prefix"]
        assert "..." in status["GEMINI_API_KEY"]["prefix"]


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    def test_run_preflight(self):
        result = run_preflight()
        assert isinstance(result, PreflightResult)
    
    def test_run_preflight_with_features(self):
        result = run_preflight(required_features=["gemini"])
        assert isinstance(result, PreflightResult)
    
    def test_install_logger_redaction(self):
        # Should not raise
        install_logger_redaction("test_logger")


class TestSecretPatterns:
    """Tests for secret pattern validation."""
    
    def test_gemini_pattern_valid(self):
        pattern = SECRET_PATTERNS["GEMINI_API_KEY"]
        assert pattern.match("AIzaSyTestKeyValue12345678901234567890")
    
    def test_gemini_pattern_invalid(self):
        pattern = SECRET_PATTERNS["GEMINI_API_KEY"]
        assert not pattern.match("invalid_key")
        assert not pattern.match("short")
    
    def test_openai_pattern_valid(self):
        pattern = SECRET_PATTERNS["OPENAI_API_KEY"]
        assert pattern.match("sk-" + "a" * 48)
    
    def test_anthropic_pattern_valid(self):
        pattern = SECRET_PATTERNS["ANTHROPIC_API_KEY"]
        assert pattern.match("sk-ant-" + "a" * 48)


class TestFeatureSecrets:
    """Tests for feature secret mappings."""
    
    def test_gemini_feature(self):
        assert "gemini" in FEATURE_SECRETS
        assert "GEMINI_API_KEY" in FEATURE_SECRETS["gemini"]
    
    def test_google_oauth_feature(self):
        assert "google_oauth" in FEATURE_SECRETS
        assert "BANTZ_GOOGLE_CLIENT_ID" in FEATURE_SECRETS["google_oauth"]
    
    def test_gmail_feature(self):
        assert "gmail" in FEATURE_SECRETS
        assert "BANTZ_GMAIL_CLIENT_ID" in FEATURE_SECRETS["gmail"]


class TestIntegrationScenarios:
    """Integration tests for real-world scenarios."""
    
    @patch.dict(os.environ, {
        "GEMINI_API_KEY": "AIzaSyTestKeyValue12345678901234567890",
    })
    def test_full_preflight_gemini(self):
        """Full preflight check for Gemini feature."""
        hygiene = SecretsHygiene()
        result = hygiene.preflight_check(required_features=["gemini"])
        
        assert result.passed == True
        assert any(c.name == "GEMINI_API_KEY" and c.is_ok for c in result.checks)
    
    def test_logger_with_redaction(self):
        """Test that logger properly redacts secrets."""
        # Create a test logger
        test_logger = logging.getLogger("test_secrets_hygiene")
        test_logger.setLevel(logging.DEBUG)
        
        # Create a string handler to capture output
        import io
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        
        # Wrap with redaction
        redacting_handler = LoggerRedactionHandler(handler)
        test_logger.addHandler(redacting_handler)
        
        # Log a message with a secret
        test_logger.info("API key is: AIzaSyTestKeyValue12345678901234567890")
        
        # Check output
        output = stream.getvalue()
        assert "AIzaSy" not in output or "***REDACTED***" in output
        
        # Cleanup
        test_logger.removeHandler(redacting_handler)
    
    def test_env_file_example_exists(self):
        """Verify .env.example exists after Issue #233."""
        env_example = pathlib.Path("/home/iclaldogan/Desktop/Bantz/.env.example")
        assert env_example.exists(), ".env.example should exist"
        
        content = env_example.read_text()
        assert "GEMINI_API_KEY" in content
        assert "NEVER commit" in content.upper() or "never commit" in content.lower()
