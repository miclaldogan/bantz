"""Google services — Calendar, Gmail, Classroom, Contacts, OAuth, Tasks, Keep.

All Google connectors (previously in bantz.connectors.google) are now
consolidated here.  bantz.connectors.google is kept as a backward-compat shim.
"""
from bantz.google.auth import get_credentials
from bantz.google.calendar import list_events
from bantz.google.gmail_auth import authenticate_gmail
# Unified OAuth manager (was bantz.connectors.google.auth_manager)
from bantz.google.auth_manager import GoogleAuthManager, get_auth_manager

__all__ = [
    "get_credentials",
    "list_events",
    "authenticate_gmail",
    "GoogleAuthManager",
    "get_auth_manager",
]

