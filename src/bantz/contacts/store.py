from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import json
import os
import re
import tempfile


_CONTACTS_VERSION = 1


def _default_contacts_path() -> Path:
    config_home = Path(os.path.expanduser(os.getenv("XDG_CONFIG_HOME", "~/.config"))).resolve()
    return (config_home / "bantz" / "contacts.json").resolve()


def get_contacts_path(path: Optional[str] = None) -> Path:
    raw = (path or "").strip() or (os.getenv("BANTZ_CONTACTS_PATH") or "").strip()
    if raw:
        return Path(os.path.expanduser(raw)).resolve()
    return _default_contacts_path()


def _normalize_key(name: str) -> str:
    s = str(name or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _read_contacts(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": _CONTACTS_VERSION, "contacts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": _CONTACTS_VERSION, "contacts": {}}
        contacts = data.get("contacts")
        if not isinstance(contacts, dict):
            contacts = {}
        return {"version": int(data.get("version") or _CONTACTS_VERSION), "contacts": contacts}
    except Exception:
        return {"version": _CONTACTS_VERSION, "contacts": {}}


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(prefix="contacts_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        Path(tmp_name).replace(path)
    finally:
        try:
            if Path(tmp_name).exists() and Path(tmp_name) != path:
                Path(tmp_name).unlink(missing_ok=True)
        except Exception:
            pass


@dataclass(frozen=True)
class Contact:
    key: str
    name: str
    email: str
    notes: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "email": self.email}
        if self.notes:
            out["notes"] = self.notes
        return out


def contacts_upsert(
    *,
    name: str,
    email: str,
    notes: Optional[str] = None,
    path: Optional[str] = None,
) -> dict[str, Any]:
    """Create or update a contact.

    Stored outside the repo by default. SAFE.
    """

    key = _normalize_key(name)
    if not key:
        raise ValueError("name must be non-empty")

    addr = str(email or "").strip()
    if not addr or "@" not in addr:
        raise ValueError("email must look like an email address")

    p = get_contacts_path(path)
    data = _read_contacts(p)
    contacts = data.get("contacts")
    if not isinstance(contacts, dict):
        contacts = {}
        data["contacts"] = contacts

    contact = Contact(key=key, name=str(name).strip(), email=addr, notes=(str(notes).strip() if notes else None))
    contacts[key] = contact.to_dict()
    data["version"] = _CONTACTS_VERSION

    _atomic_write_json(p, data)

    return {"ok": True, "contact": {"key": key, **contact.to_dict()}, "path": str(p)}


def contacts_resolve(*, name: str, path: Optional[str] = None) -> dict[str, Any]:
    """Resolve a contact name to an email address. SAFE."""

    key = _normalize_key(name)
    if not key:
        raise ValueError("name must be non-empty")

    p = get_contacts_path(path)
    data = _read_contacts(p)
    contacts = data.get("contacts")
    if not isinstance(contacts, dict):
        contacts = {}

    raw = contacts.get(key)
    if not isinstance(raw, dict):
        return {"ok": False, "error": "contact_not_found", "name": name, "key": key, "path": str(p)}

    email = str(raw.get("email") or "").strip()
    if not email:
        return {"ok": False, "error": "contact_missing_email", "name": name, "key": key, "path": str(p)}

    return {
        "ok": True,
        "name": str(raw.get("name") or name),
        "key": key,
        "email": email,
        "notes": raw.get("notes"),
        "path": str(p),
    }


def contacts_list(
    *,
    prefix: Optional[str] = None,
    limit: int = 50,
    path: Optional[str] = None,
) -> dict[str, Any]:
    """List contacts. SAFE."""

    if not isinstance(limit, int) or limit <= 0:
        raise ValueError("limit must be a positive integer")

    p = get_contacts_path(path)
    data = _read_contacts(p)
    contacts = data.get("contacts")
    if not isinstance(contacts, dict):
        contacts = {}

    pref = _normalize_key(prefix) if prefix else ""

    out: list[dict[str, Any]] = []
    for k in sorted(contacts.keys()):
        if pref and not str(k).startswith(pref):
            continue
        raw = contacts.get(k)
        if not isinstance(raw, dict):
            continue
        out.append(
            {
                "key": str(k),
                "name": str(raw.get("name") or ""),
                "email": str(raw.get("email") or ""),
                "notes": raw.get("notes"),
            }
        )
        if len(out) >= limit:
            break

    return {"ok": True, "contacts": out, "path": str(p)}


def contacts_delete(*, name: str, path: Optional[str] = None) -> dict[str, Any]:
    """Delete a contact by name. SAFE."""

    key = _normalize_key(name)
    if not key:
        raise ValueError("name must be non-empty")

    p = get_contacts_path(path)
    data = _read_contacts(p)
    contacts = data.get("contacts")
    if not isinstance(contacts, dict):
        contacts = {}
        data["contacts"] = contacts

    existed = key in contacts
    if existed:
        contacts.pop(key, None)
        data["version"] = _CONTACTS_VERSION
        _atomic_write_json(p, data)

    return {"ok": True, "deleted": bool(existed), "key": key, "path": str(p)}
