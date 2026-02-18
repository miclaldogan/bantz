"""Google Suite Super-Connector — Unified OAuth + service connectors.

Issue #1292: Single OAuth2 token manager with incremental scope expansion,
base connector interface, and service-specific connectors for
Contacts, Tasks, Keep, and Classroom.
"""

from bantz.connectors.google.auth_manager import GoogleAuthManager
from bantz.connectors.google.base import GoogleConnector

__all__ = [
    "GoogleAuthManager",
    "GoogleConnector",
]
