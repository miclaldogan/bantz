"""Contacts runtime tool handlers (Issue #845).

Wraps bantz.contacts.store for OrchestratorLoop.
Tools: contacts.search, contacts.get, contacts.list, contacts.add
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def contacts_search_tool(*, query: str = "", **_: Any) -> Dict[str, Any]:
    """Search contacts by name or email fragment."""
    if not query:
        return {"ok": False, "error": "query_required"}
    try:
        from bantz.contacts.store import contacts_list as _list
    except ImportError:
        return {"ok": False, "error": "contacts_module_not_available"}
    try:
        all_contacts = _list()
        q = query.lower()
        matches = [
            c for c in all_contacts
            if q in c.get("name", "").lower() or q in c.get("email", "").lower()
        ]
        return {"ok": True, "results": matches, "count": len(matches)}
    except Exception as e:
        logger.error(f"[Contacts] search error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def contacts_get_tool(*, name: str = "", **_: Any) -> Dict[str, Any]:
    """Resolve a contact name to email address."""
    if not name:
        return {"ok": False, "error": "name_required"}
    try:
        from bantz.contacts.store import contacts_resolve
    except ImportError:
        return {"ok": False, "error": "contacts_module_not_available"}
    try:
        result = contacts_resolve(name)
        if result is None:
            return {"ok": False, "error": f"Kişi bulunamadı: {name}"}
        return {"ok": True, "name": name, "email": result}
    except Exception as e:
        logger.error(f"[Contacts] get error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def contacts_list_tool(*, limit: int = 50, **_: Any) -> Dict[str, Any]:
    """List all contacts."""
    try:
        from bantz.contacts.store import contacts_list as _list
    except ImportError:
        return {"ok": False, "error": "contacts_module_not_available"}
    try:
        all_contacts = _list()
        return {"ok": True, "contacts": all_contacts[:limit], "total": len(all_contacts)}
    except Exception as e:
        logger.error(f"[Contacts] list error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def contacts_add_tool(*, name: str = "", email: str = "", **_: Any) -> Dict[str, Any]:
    """Add or update a contact."""
    if not name or not email:
        return {"ok": False, "error": "name_and_email_required"}
    try:
        from bantz.contacts.store import contacts_upsert
    except ImportError:
        return {"ok": False, "error": "contacts_module_not_available"}
    try:
        contacts_upsert(name=name, email=email)
        return {"ok": True, "name": name, "email": email, "action": "upserted"}
    except Exception as e:
        logger.error(f"[Contacts] add error: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}
