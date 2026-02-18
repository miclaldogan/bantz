"""Backward-compatibility shim — Google connectors moved to bantz.google.

All classes are now in bantz.google.*
This module re-exports them so existing imports keep working.
"""
from bantz.google.auth_manager import GoogleAuthManager
from bantz.google.connector_base import GoogleConnector

__all__ = ["GoogleAuthManager", "GoogleConnector"]
