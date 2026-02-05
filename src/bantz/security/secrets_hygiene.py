"""Secrets hygiene module.

Issue #233: Comprehensive secrets management including preflight checks,
logger redaction, and environment validation.

This module provides:
- SecretsHygiene: Main class for secrets validation
- PreflightChecker: Startup checks for secrets presence
- LoggerRedactionHandler: Enhanced logging handler with redaction
- Environment validation utilities
"""

from __future__ import annotations

import os
import re
import logging
import pathlib
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class SecretStatus(Enum):
    """Status of a secret check."""
    PRESENT = "present"
    MISSING = "missing"
    EMPTY = "empty"
    INVALID_FORMAT = "invalid_format"
    FILE_NOT_FOUND = "file_not_found"
    FILE_READABLE = "file_readable"


@dataclass
class SecretCheck:
    """Result of a single secret check."""
    name: str
    status: SecretStatus
    source: str = ""  # "env", "file", etc.
    message: str = ""
    required: bool = False
    
    @property
    def is_ok(self) -> bool:
        return self.status in (SecretStatus.PRESENT, SecretStatus.FILE_READABLE)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "source": self.source,
            "message": self.message,
            "required": self.required,
            "is_ok": self.is_ok,
        }


@dataclass
class PreflightResult:
    """Result of preflight secrets check."""
    passed: bool
    checks: List[SecretCheck] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [c.to_dict() for c in self.checks],
            "warnings": self.warnings,
            "errors": self.errors,
            "ok_count": sum(1 for c in self.checks if c.is_ok),
            "fail_count": sum(1 for c in self.checks if not c.is_ok),
        }


# Secret patterns for validation
SECRET_PATTERNS = {
    "GEMINI_API_KEY": re.compile(r"^AIza[0-9A-Za-z\-_]{30,}$"),
    "GOOGLE_API_KEY": re.compile(r"^AIza[0-9A-Za-z\-_]{30,}$"),
    "BANTZ_GEMINI_API_KEY": re.compile(r"^AIza[0-9A-Za-z\-_]{30,}$"),
    "OPENAI_API_KEY": re.compile(r"^sk-[a-zA-Z0-9]{32,}$"),
    "ANTHROPIC_API_KEY": re.compile(r"^sk-ant-[a-zA-Z0-9]{40,}$"),
}

# Required secrets for different features
FEATURE_SECRETS = {
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY", "BANTZ_GEMINI_API_KEY"],
    "google_oauth": ["BANTZ_GOOGLE_CLIENT_ID", "BANTZ_GOOGLE_CLIENT_SECRET"],
    "gmail": ["BANTZ_GMAIL_CLIENT_ID", "BANTZ_GMAIL_CLIENT_SECRET"],
    "vision": ["GOOGLE_APPLICATION_CREDENTIALS"],
}

# All known secret environment variable names
ALL_SECRET_VARS = {
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "BANTZ_GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "BANTZ_GOOGLE_CLIENT_ID",
    "BANTZ_GOOGLE_CLIENT_SECRET",
    "BANTZ_GMAIL_CLIENT_ID",
    "BANTZ_GMAIL_CLIENT_SECRET",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "BANTZ_GOOGLE_SERVICE_ACCOUNT",
}


def _check_env_var(
    name: str,
    required: bool = False,
    validate_format: bool = True,
) -> SecretCheck:
    """Check if an environment variable is set and valid."""
    value = os.environ.get(name, "")
    
    if not value:
        if name in os.environ:
            return SecretCheck(
                name=name,
                status=SecretStatus.EMPTY,
                source="env",
                message="Environment variable is set but empty",
                required=required,
            )
        return SecretCheck(
            name=name,
            status=SecretStatus.MISSING,
            source="env",
            message="Environment variable not set",
            required=required,
        )
    
    # Validate format if pattern exists
    if validate_format and name in SECRET_PATTERNS:
        pattern = SECRET_PATTERNS[name]
        if not pattern.match(value):
            return SecretCheck(
                name=name,
                status=SecretStatus.INVALID_FORMAT,
                source="env",
                message="Value does not match expected format",
                required=required,
            )
    
    return SecretCheck(
        name=name,
        status=SecretStatus.PRESENT,
        source="env",
        message="OK",
        required=required,
    )


def _check_file_path(
    name: str,
    path: str,
    required: bool = False,
) -> SecretCheck:
    """Check if a file path exists and is readable."""
    if not path:
        return SecretCheck(
            name=name,
            status=SecretStatus.MISSING,
            source="file",
            message="Path not specified",
            required=required,
        )
    
    # Expand user home
    expanded = os.path.expanduser(path)
    p = pathlib.Path(expanded)
    
    if not p.exists():
        return SecretCheck(
            name=name,
            status=SecretStatus.FILE_NOT_FOUND,
            source="file",
            message=f"File not found: .../{p.name}",
            required=required,
        )
    
    if not p.is_file():
        return SecretCheck(
            name=name,
            status=SecretStatus.INVALID_FORMAT,
            source="file",
            message=f"Not a file: .../{p.name}",
            required=required,
        )
    
    try:
        with open(p, "r") as f:
            f.read(1)  # Just check readability
    except Exception as e:
        return SecretCheck(
            name=name,
            status=SecretStatus.INVALID_FORMAT,
            source="file",
            message=f"Cannot read file: {type(e).__name__}",
            required=required,
        )
    
    return SecretCheck(
        name=name,
        status=SecretStatus.FILE_READABLE,
        source="file",
        message="OK",
        required=required,
    )


class PreflightChecker:
    """Startup preflight checks for secrets presence and validity.
    
    Usage:
        checker = PreflightChecker()
        result = checker.run()
        if not result.passed:
            print("Missing required secrets:", result.errors)
    """
    
    def __init__(
        self,
        required_features: Optional[List[str]] = None,
        validate_format: bool = True,
    ):
        """Initialize preflight checker.
        
        Args:
            required_features: List of features requiring secrets (gemini, google_oauth, etc.)
            validate_format: Whether to validate secret formats
        """
        self.required_features = required_features or []
        self.validate_format = validate_format
    
    def run(self) -> PreflightResult:
        """Run all preflight checks.
        
        Returns:
            PreflightResult with pass/fail and details
        """
        checks: List[SecretCheck] = []
        warnings: List[str] = []
        errors: List[str] = []
        
        # Check required feature secrets
        for feature in self.required_features:
            if feature not in FEATURE_SECRETS:
                warnings.append(f"Unknown feature: {feature}")
                continue
            
            secret_names = FEATURE_SECRETS[feature]
            # At least one of the secrets must be present
            feature_ok = False
            for name in secret_names:
                check = _check_env_var(name, required=True, validate_format=self.validate_format)
                checks.append(check)
                if check.is_ok:
                    feature_ok = True
            
            if not feature_ok:
                errors.append(f"Feature '{feature}' requires one of: {', '.join(secret_names)}")
        
        # Check credential files
        client_secret_path = os.environ.get("BANTZ_CLIENT_SECRET_PATH", "")
        if client_secret_path:
            check = _check_file_path("client_secret.json", client_secret_path)
            checks.append(check)
            if not check.is_ok:
                warnings.append(f"Client secret file issue: {check.message}")
        
        svc_account_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        if svc_account_path:
            check = _check_file_path("service_account.json", svc_account_path)
            checks.append(check)
            if not check.is_ok:
                warnings.append(f"Service account file issue: {check.message}")
        
        # Check for secrets in potentially unsafe locations
        self._check_env_file_safety(warnings)
        
        passed = len(errors) == 0
        
        return PreflightResult(
            passed=passed,
            checks=checks,
            warnings=warnings,
            errors=errors,
        )
    
    def _check_env_file_safety(self, warnings: List[str]) -> None:
        """Check for .env file safety issues."""
        # Check if .env exists and is in .gitignore
        cwd = pathlib.Path.cwd()
        env_file = cwd / ".env"
        gitignore = cwd / ".gitignore"
        
        if env_file.exists():
            if gitignore.exists():
                try:
                    content = gitignore.read_text()
                    if ".env" not in content:
                        warnings.append(
                            ".env file exists but is not in .gitignore - risk of committing secrets"
                        )
                except Exception:
                    pass
            else:
                warnings.append(
                    ".env file exists but no .gitignore found - risk of committing secrets"
                )


class LoggerRedactionHandler(logging.Handler):
    """Enhanced logging handler with automatic secrets redaction.
    
    This handler wraps another handler and redacts secrets before emitting.
    """
    
    REDACTED = "***REDACTED***"
    
    # Compiled patterns for efficiency
    _patterns: List[re.Pattern] = []
    
    def __init__(self, wrapped_handler: logging.Handler):
        """Initialize with a wrapped handler.
        
        Args:
            wrapped_handler: The handler to wrap
        """
        super().__init__()
        self.wrapped = wrapped_handler
        self._compile_patterns()
    
    def _compile_patterns(self) -> None:
        """Compile redaction patterns."""
        self._patterns = [
            # API keys
            re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b"),
            re.compile(r"\bsk-[a-zA-Z0-9]{32,}\b"),
            re.compile(r"\bsk-ant-[a-zA-Z0-9]{40,}\b"),
            
            # OAuth tokens
            re.compile(r"\bya29\.[0-9A-Za-z\-_]+\b"),
            re.compile(r"\bBearer\s+[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE),
            
            # JWT tokens
            re.compile(r"\beyJ[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]{10,}\b"),
            
            # Private keys
            re.compile(
                r"-----BEGIN PRIVATE KEY-----[\s\S]*?-----END PRIVATE KEY-----",
                re.MULTILINE,
            ),
            
            # Env assignments
            re.compile(
                r"\b(GEMINI_API_KEY|GOOGLE_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|"
                r"CLIENT_SECRET|ACCESS_TOKEN|REFRESH_TOKEN)\s*[:=]\s*([^\s'\"\n]+)",
                re.IGNORECASE,
            ),
        ]
    
    def _redact(self, text: str) -> str:
        """Redact secrets from text."""
        if not text:
            return text
        
        result = text
        for pattern in self._patterns:
            if "BEGIN PRIVATE KEY" in pattern.pattern:
                result = pattern.sub(self.REDACTED, result)
            elif "GEMINI_API_KEY" in pattern.pattern or "OPENAI_API_KEY" in pattern.pattern:
                # Env assignment with groups - keep the key name
                def replace_env(m):
                    try:
                        return f"{m.group(1)}={self.REDACTED}"
                    except (IndexError, AttributeError):
                        return self.REDACTED
                result = pattern.sub(replace_env, result)
            else:
                result = pattern.sub(self.REDACTED, result)
        
        return result
    
    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record with secrets redacted."""
        try:
            # Redact the formatted message
            msg = record.getMessage()
            redacted_msg = self._redact(msg)
            
            # Create a new record with redacted message
            new_record = logging.LogRecord(
                name=record.name,
                level=record.levelno,
                pathname=record.pathname,
                lineno=record.lineno,
                msg=redacted_msg,
                args=(),  # Clear args since message is already formatted
                exc_info=record.exc_info,
            )
            
            # Forward to wrapped handler
            self.wrapped.emit(new_record)
        except Exception:
            self.handleError(record)
    
    def setFormatter(self, fmt: logging.Formatter) -> None:
        """Set formatter on wrapped handler."""
        self.wrapped.setFormatter(fmt)
    
    def setLevel(self, level: int) -> None:
        """Set level on both handlers."""
        super().setLevel(level)
        self.wrapped.setLevel(level)


class SecretsHygiene:
    """Main class for secrets management and hygiene.
    
    Usage:
        hygiene = SecretsHygiene()
        
        # Run preflight checks
        result = hygiene.preflight_check(required_features=["gemini"])
        if not result.passed:
            sys.exit(1)
        
        # Install logger redaction
        hygiene.install_redaction()
    """
    
    def __init__(self):
        """Initialize secrets hygiene manager."""
        self._redaction_installed = False
    
    def preflight_check(
        self,
        required_features: Optional[List[str]] = None,
        validate_format: bool = True,
    ) -> PreflightResult:
        """Run preflight secrets check.
        
        Args:
            required_features: Features requiring secrets
            validate_format: Whether to validate secret formats
        
        Returns:
            PreflightResult with pass/fail and details
        """
        checker = PreflightChecker(
            required_features=required_features,
            validate_format=validate_format,
        )
        return checker.run()
    
    def install_redaction(
        self,
        logger_name: Optional[str] = None,
        wrap_existing: bool = True,
    ) -> None:
        """Install secrets redaction on logger.
        
        Args:
            logger_name: Logger name (None for root logger)
            wrap_existing: Whether to wrap existing handlers
        """
        if self._redaction_installed:
            return
        
        log = logging.getLogger(logger_name)
        
        if wrap_existing:
            # Wrap existing handlers
            new_handlers = []
            for handler in list(log.handlers):
                log.removeHandler(handler)
                wrapped = LoggerRedactionHandler(handler)
                new_handlers.append(wrapped)
            
            for handler in new_handlers:
                log.addHandler(handler)
        
        # Also install filter from existing secrets module
        try:
            from bantz.security.secrets import install_secrets_redaction_filter
            install_secrets_redaction_filter(log)
        except ImportError:
            pass
        
        self._redaction_installed = True
    
    def check_env_security(self) -> List[str]:
        """Check for common environment security issues.
        
        Returns:
            List of warning messages
        """
        warnings: List[str] = []
        
        # Check for secrets in command line (visible in ps)
        # This is a static check - actual detection would need /proc access
        
        # Check .env file permissions
        cwd = pathlib.Path.cwd()
        env_file = cwd / ".env"
        
        if env_file.exists():
            try:
                mode = env_file.stat().st_mode
                if mode & 0o077:  # Group or others have any permission
                    warnings.append(
                        f".env file has loose permissions: {oct(mode)[-3:]} - recommend 600"
                    )
            except Exception:
                pass
        
        # Check for common mistakes
        for var in ALL_SECRET_VARS:
            value = os.environ.get(var, "")
            if value:
                # Check for placeholder values
                if value.lower() in ("xxx", "your_key_here", "changeme", "placeholder"):
                    warnings.append(f"{var} appears to be a placeholder value")
                
                # Check for accidentally quoted values
                if value.startswith('"') or value.startswith("'"):
                    warnings.append(f"{var} value starts with quote - may be incorrectly set")
        
        return warnings
    
    def get_secrets_status(self) -> Dict[str, Any]:
        """Get status of all known secrets.
        
        Returns:
            Dict with secret statuses (never includes actual values)
        """
        status: Dict[str, Any] = {}
        
        for var in sorted(ALL_SECRET_VARS):
            value = os.environ.get(var, "")
            if value:
                status[var] = {
                    "present": True,
                    "length": len(value),
                    "prefix": value[:4] + "..." if len(value) > 4 else "****",
                }
            else:
                status[var] = {
                    "present": False,
                }
        
        return status


# Convenience functions
def run_preflight(required_features: Optional[List[str]] = None) -> PreflightResult:
    """Run preflight secrets check.
    
    Args:
        required_features: Features requiring secrets
    
    Returns:
        PreflightResult
    """
    hygiene = SecretsHygiene()
    return hygiene.preflight_check(required_features=required_features)


def install_logger_redaction(logger_name: Optional[str] = None) -> None:
    """Install secrets redaction on logger.
    
    Args:
        logger_name: Logger name (None for root)
    """
    hygiene = SecretsHygiene()
    hygiene.install_redaction(logger_name=logger_name)
