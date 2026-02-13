"""Privacy module — local-first, explicit cloud consent, PII redaction.

Issue #299: Privacy-first approach for Bantz.
"""

from bantz.privacy.config import PrivacyConfig, load_privacy_config, save_privacy_config
from bantz.privacy.consent import ConsentManager, ConsentResult
from bantz.privacy.redaction import redact_pii, REDACTION_PATTERNS
from bantz.privacy.indicator import MicIndicator, MicState

__all__ = [
    "PrivacyConfig",
    "load_privacy_config",
    "save_privacy_config",
    "ConsentManager",
    "ConsentResult",
    "redact_pii",
    "REDACTION_PATTERNS",
    "MicIndicator",
    "MicState",
]
