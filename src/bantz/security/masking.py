"""
Sensitive Data Masking.

Masks sensitive information in logs and outputs:
- Email addresses
- Phone numbers
- Credit card numbers
- Passwords
- API keys
- Personal identifiers
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Pattern, Tuple, Union
import re
import logging
import copy

logger = logging.getLogger(__name__)


# =============================================================================
# Masking Pattern
# =============================================================================


@dataclass
class MaskingPattern:
    """Pattern for masking sensitive data."""
    
    name: str
    pattern: str
    replacement: str
    flags: int = re.IGNORECASE
    enabled: bool = True
    
    _compiled: Optional[Pattern] = field(default=None, repr=False)
    
    def compile(self) -> Pattern:
        """Get compiled regex pattern."""
        if self._compiled is None:
            self._compiled = re.compile(self.pattern, self.flags)
        return self._compiled
    
    def mask(self, text: str) -> str:
        """Apply mask to text."""
        if not self.enabled:
            return text
        return self.compile().sub(self.replacement, text)


# =============================================================================
# Default Patterns
# =============================================================================


DEFAULT_PATTERNS = [
    # Email addresses
    MaskingPattern(
        name="email",
        pattern=r"[\w.+-]+@[\w.-]+\.\w+",
        replacement="***@***.***",
    ),
    
    # Phone numbers (various formats)
    MaskingPattern(
        name="phone",
        pattern=r"(?:\+?[\d\s-]{10,}|\(\d{3}\)\s*\d{3}[\s-]?\d{4})",
        replacement="***-***-****",
    ),
    
    # Credit card numbers
    MaskingPattern(
        name="credit_card",
        pattern=r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
        replacement="****-****-****-****",
    ),
    
    # Passwords (in key:value format)
    MaskingPattern(
        name="password",
        pattern=r"(?i)(password|şifre|parola|passwd|pwd)[:\s=]+\S+",
        replacement=r"\1: ***MASKED***",
    ),
    
    # API keys (various formats)
    MaskingPattern(
        name="api_key",
        pattern=r"(?i)(api[_-]?key|apikey|api[_-]?secret|access[_-]?token|auth[_-]?token)[:\s=]+[\w\-]+",
        replacement=r"\1: ***API_KEY***",
    ),
    
    # Bearer tokens
    MaskingPattern(
        name="bearer_token",
        pattern=r"(?i)(bearer\s+)[A-Za-z0-9\-_=]+\.?[A-Za-z0-9\-_=]*\.?[A-Za-z0-9\-_=]*",
        replacement=r"\1***TOKEN***",
    ),
    
    # Secret keys (common patterns)
    MaskingPattern(
        name="secret_key",
        pattern=r"(?i)(secret[_-]?key|private[_-]?key)[:\s=]+[\w\-]+",
        replacement=r"\1: ***SECRET***",
    ),
    
    # Turkish TC Kimlik No
    MaskingPattern(
        name="tc_kimlik",
        pattern=r"\b[1-9]\d{10}\b",
        replacement="***TC***",
    ),
    
    # SSN (US Social Security Number)
    MaskingPattern(
        name="ssn",
        pattern=r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
        replacement="***-**-****",
    ),
    
    # IP addresses
    MaskingPattern(
        name="ip_address",
        pattern=r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        replacement="***.***.***.***",
    ),
    
    # URLs with credentials
    MaskingPattern(
        name="url_credentials",
        pattern=r"(https?://)[^:@/\s]+:[^@/\s]+@",
        replacement=r"\1***:***@",
    ),
    
    # AWS Access Keys
    MaskingPattern(
        name="aws_access_key",
        pattern=r"(?i)(AKIA|ABIA|ACCA|ASIA)[A-Z0-9]{16}",
        replacement="***AWS_KEY***",
    ),
    
    # Private keys (PEM format header)
    MaskingPattern(
        name="private_key",
        pattern=r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |DSA )?PRIVATE KEY-----",
        replacement="***PRIVATE_KEY***",
    ),
]


# Sensitive field names that should always be masked
SENSITIVE_FIELD_NAMES = {
    "password", "passwd", "pwd", "secret", "token", "api_key", "apikey",
    "api_secret", "access_token", "auth_token", "private_key", "secret_key",
    "credential", "credentials", "auth", "authorization", "şifre", "parola",
    "gizli", "tc_kimlik", "tc_no", "kimlik_no", "ssn", "credit_card",
    "card_number", "cvv", "pin",
}


# =============================================================================
# Data Masker
# =============================================================================


class DataMasker:
    """
    Mask sensitive data in logs and outputs.
    
    Example:
        masker = DataMasker()
        
        # Mask text
        safe = masker.mask("User email: user@example.com")
        # "User email: ***@***.***"
        
        # Mask dictionary
        safe_dict = masker.mask_dict({
            "email": "user@example.com",
            "password": "secret123",
        })
        # {"email": "***@***.***", "password": "***MASKED***"}
    """
    
    def __init__(
        self,
        patterns: Optional[List[MaskingPattern]] = None,
        mask_sensitive_fields: bool = True,
        custom_field_names: Optional[set] = None,
    ):
        """
        Initialize data masker.
        
        Args:
            patterns: Custom masking patterns (uses defaults if None)
            mask_sensitive_fields: Also mask values of sensitive field names
            custom_field_names: Additional field names to treat as sensitive
        """
        self.patterns = patterns if patterns is not None else DEFAULT_PATTERNS.copy()
        self.mask_sensitive_fields = mask_sensitive_fields
        self.sensitive_field_names = SENSITIVE_FIELD_NAMES.copy()
        if custom_field_names:
            self.sensitive_field_names.update(custom_field_names)
    
    def mask(self, text: str) -> str:
        """
        Mask sensitive data in text.
        
        Args:
            text: Text to mask
            
        Returns:
            Masked text
        """
        if not text:
            return text
        
        result = text
        for pattern in self.patterns:
            if pattern.enabled:
                result = pattern.mask(result)
        
        return result
    
    def mask_dict(
        self,
        data: Dict[str, Any],
        _depth: int = 0,
    ) -> Dict[str, Any]:
        """
        Recursively mask sensitive data in dictionary.
        
        Args:
            data: Dictionary to mask
            
        Returns:
            Masked dictionary (deep copy)
        """
        if _depth > 20:  # Prevent infinite recursion
            return data
        
        result = {}
        
        for key, value in data.items():
            # Check if key is a sensitive field name
            if self.mask_sensitive_fields:
                key_lower = key.lower().replace("-", "_")
                if key_lower in self.sensitive_field_names:
                    result[key] = "***MASKED***"
                    continue
            
            # Process value based on type
            if isinstance(value, str):
                result[key] = self.mask(value)
            elif isinstance(value, dict):
                result[key] = self.mask_dict(value, _depth + 1)
            elif isinstance(value, list):
                result[key] = self._mask_list(value, _depth + 1)
            else:
                result[key] = value
        
        return result
    
    def _mask_list(self, data: List[Any], _depth: int = 0) -> List[Any]:
        """Mask sensitive data in list."""
        if _depth > 20:
            return data
        
        result = []
        for item in data:
            if isinstance(item, str):
                result.append(self.mask(item))
            elif isinstance(item, dict):
                result.append(self.mask_dict(item, _depth + 1))
            elif isinstance(item, list):
                result.append(self._mask_list(item, _depth + 1))
            else:
                result.append(item)
        
        return result
    
    def add_pattern(self, pattern: MaskingPattern) -> None:
        """
        Add a custom masking pattern.
        
        Args:
            pattern: Pattern to add
        """
        self.patterns.append(pattern)
    
    def remove_pattern(self, name: str) -> bool:
        """
        Remove a pattern by name.
        
        Args:
            name: Pattern name
            
        Returns:
            True if removed
        """
        before = len(self.patterns)
        self.patterns = [p for p in self.patterns if p.name != name]
        return len(self.patterns) < before
    
    def enable_pattern(self, name: str, enabled: bool = True) -> bool:
        """
        Enable or disable a pattern.
        
        Args:
            name: Pattern name
            enabled: Whether to enable
            
        Returns:
            True if pattern found
        """
        for pattern in self.patterns:
            if pattern.name == name:
                pattern.enabled = enabled
                return True
        return False
    
    def list_patterns(self) -> List[str]:
        """List all pattern names."""
        return [p.name for p in self.patterns]
    
    def add_sensitive_field(self, field_name: str) -> None:
        """Add a field name to treat as sensitive."""
        self.sensitive_field_names.add(field_name.lower())
    
    def mask_exception(self, exc: Exception) -> str:
        """
        Mask sensitive data in exception message.
        
        Args:
            exc: Exception to mask
            
        Returns:
            Masked exception string
        """
        return self.mask(str(exc))
    
    def create_safe_logger(
        self,
        base_logger: Optional[logging.Logger] = None,
    ) -> "MaskedLogger":
        """
        Create a logger that automatically masks output.
        
        Args:
            base_logger: Base logger to wrap
            
        Returns:
            MaskedLogger instance
        """
        return MaskedLogger(self, base_logger or logging.getLogger())


class MaskedLogger:
    """Logger wrapper that masks sensitive data."""
    
    def __init__(self, masker: DataMasker, logger: logging.Logger):
        self._masker = masker
        self._logger = logger
    
    def _mask_args(self, args: tuple) -> tuple:
        """Mask all string arguments."""
        return tuple(
            self._masker.mask(a) if isinstance(a, str) else a
            for a in args
        )
    
    def debug(self, msg: str, *args, **kwargs):
        self._logger.debug(self._masker.mask(msg), *self._mask_args(args), **kwargs)
    
    def info(self, msg: str, *args, **kwargs):
        self._logger.info(self._masker.mask(msg), *self._mask_args(args), **kwargs)
    
    def warning(self, msg: str, *args, **kwargs):
        self._logger.warning(self._masker.mask(msg), *self._mask_args(args), **kwargs)
    
    def error(self, msg: str, *args, **kwargs):
        self._logger.error(self._masker.mask(msg), *self._mask_args(args), **kwargs)
    
    def critical(self, msg: str, *args, **kwargs):
        self._logger.critical(self._masker.mask(msg), *self._mask_args(args), **kwargs)
    
    def exception(self, msg: str, *args, **kwargs):
        self._logger.exception(self._masker.mask(msg), *self._mask_args(args), **kwargs)


# =============================================================================
# Factory Function
# =============================================================================


_default_masker: Optional[DataMasker] = None


def get_default_masker() -> DataMasker:
    """
    Get the default global masker instance.
    
    Returns:
        Default DataMasker
    """
    global _default_masker
    if _default_masker is None:
        _default_masker = DataMasker()
    return _default_masker


def mask(text: str) -> str:
    """
    Convenience function to mask text with default masker.
    
    Args:
        text: Text to mask
        
    Returns:
        Masked text
    """
    return get_default_masker().mask(text)


def mask_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to mask dict with default masker.
    
    Args:
        data: Dictionary to mask
        
    Returns:
        Masked dictionary
    """
    return get_default_masker().mask_dict(data)
