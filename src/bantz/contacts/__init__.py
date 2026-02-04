"""Local contacts (name → email) helpers.

This module stores user-specific contacts outside the repo by default, under
~/.config/bantz/contacts.json (or XDG_CONFIG_HOME).

No contact data is shipped with the repository.
"""

from __future__ import annotations

from .store import (
    contacts_delete,
    contacts_list,
    contacts_resolve,
    contacts_upsert,
    get_contacts_path,
)

__all__ = [
    "get_contacts_path",
    "contacts_upsert",
    "contacts_resolve",
    "contacts_list",
    "contacts_delete",
]
