from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_contacts_upsert_resolve_list_delete(monkeypatch, tmp_path: Path):
    from bantz.contacts.store import contacts_delete, contacts_list, contacts_resolve, contacts_upsert

    p = tmp_path / "contacts.json"
    monkeypatch.setenv("BANTZ_CONTACTS_PATH", str(p))

    out = contacts_upsert(name="Ali Yılmaz", email="ali@example.com", notes="friend")
    assert out["ok"] is True
    assert out["contact"]["email"] == "ali@example.com"

    r = contacts_resolve(name="  ali   yılmaz ")
    assert r["ok"] is True
    assert r["email"] == "ali@example.com"

    l = contacts_list()
    assert l["ok"] is True
    assert len(l["contacts"]) == 1
    assert l["contacts"][0]["email"] == "ali@example.com"

    d = contacts_delete(name="Ali Yılmaz")
    assert d["ok"] is True
    assert d["deleted"] is True

    r2 = contacts_resolve(name="Ali Yılmaz")
    assert r2["ok"] is False
    assert r2["error"] == "contact_not_found"


def test_contacts_file_is_valid_json(monkeypatch, tmp_path: Path):
    from bantz.contacts.store import contacts_upsert

    p = tmp_path / "contacts.json"
    monkeypatch.setenv("BANTZ_CONTACTS_PATH", str(p))

    contacts_upsert(name="Test", email="t@example.com")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert isinstance(data["contacts"], dict)
