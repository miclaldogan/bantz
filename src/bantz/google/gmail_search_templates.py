from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


DEFAULT_TEMPLATES_PATH = "~/.config/bantz/gmail_search_templates.json"


def _resolve_path(value: str) -> Path:
    return Path(os.path.expanduser(value)).resolve()


def get_templates_path(*, path: Optional[str] = None) -> Path:
    p = path or os.getenv("BANTZ_GMAIL_TEMPLATES_PATH") or DEFAULT_TEMPLATES_PATH
    resolved = _resolve_path(p)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _normalize_key(name: str) -> str:
    return " ".join(str(name or "").strip().casefold().split())


def _read_templates(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(obj, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in obj.items():
        if not isinstance(k, str) or not isinstance(v, dict):
            continue
        out[str(k)] = v
    return out


def _atomic_write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def templates_upsert(*, name: str, query: str, path: Optional[str] = None) -> dict[str, Any]:
    if not str(name or "").strip():
        raise ValueError("name must be non-empty")
    if not str(query or "").strip():
        raise ValueError("query must be non-empty")

    p = get_templates_path(path=path)
    key = _normalize_key(name)
    db = _read_templates(p)
    db[key] = {"name": str(name).strip(), "query": str(query).strip()}
    _atomic_write_json(p, db)
    return {"ok": True, "template": db[key], "key": key, "path": str(p)}


def templates_get(*, name: str, path: Optional[str] = None) -> dict[str, Any]:
    p = get_templates_path(path=path)
    key = _normalize_key(name)
    db = _read_templates(p)
    tpl = db.get(key)
    if not tpl:
        return {"ok": False, "error": "template_not_found", "key": key, "path": str(p)}
    return {"ok": True, "template": tpl, "key": key, "path": str(p)}


def templates_list(*, prefix: Optional[str] = None, limit: int = 50, path: Optional[str] = None) -> dict[str, Any]:
    p = get_templates_path(path=path)
    db = _read_templates(p)

    pref = _normalize_key(prefix) if prefix else None
    out: list[dict[str, Any]] = []
    for key in sorted(db.keys()):
        if pref and not key.startswith(pref):
            continue
        tpl = db.get(key)
        if isinstance(tpl, dict):
            out.append({"key": key, "name": tpl.get("name"), "query": tpl.get("query")})
        if len(out) >= limit:
            break

    return {"ok": True, "templates": out, "path": str(p)}


def templates_delete(*, name: str, path: Optional[str] = None) -> dict[str, Any]:
    p = get_templates_path(path=path)
    key = _normalize_key(name)
    db = _read_templates(p)
    existed = key in db
    if existed:
        db.pop(key, None)
        _atomic_write_json(p, db)
    return {"ok": True, "deleted": bool(existed), "key": key, "path": str(p)}
