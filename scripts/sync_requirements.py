"""Sync requirements*.txt files from pyproject.toml.

Usage:
  /home/iclaldogan/Desktop/Bantz/.venv/bin/python scripts/sync_requirements.py

Generates:
  - requirements.txt              (recommended: base + llm + browser)
  - requirements-all.txt          (base + all extras)
  - requirements-<extra>.txt      (one per extra)

Notes:
  - This repo is pyproject-first; requirements files are convenience outputs.
  - Keep pyproject.toml as the source of truth.
"""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib  # py3.11+
except Exception:  # pragma: no cover
    tomllib = None

try:
    import tomli  # py3.10 fallback
except Exception:  # pragma: no cover
    tomli = None


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

RECOMMENDED_EXTRAS = ("llm", "browser")


def _load_pyproject() -> dict:
    raw = PYPROJECT.read_text(encoding="utf-8")
    if tomllib is not None:
        return tomllib.loads(raw)
    if tomli is not None:
        return tomli.loads(raw)
    raise RuntimeError("Neither tomllib nor tomli is available; install tomli or use Python 3.11+")


def _normalize(req: str) -> str:
    return str(req).strip()


def _unique_sorted(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        it = _normalize(it)
        if not it or it.startswith("#"):
            continue
        if it not in seen:
            seen.add(it)
            out.append(it)
    return sorted(out, key=lambda s: s.lower())


def _write_requirements(path: Path, reqs: list[str]) -> None:
    content = "\n".join(reqs) + ("\n" if reqs else "")
    path.write_text(content, encoding="utf-8")


def main() -> None:
    data = _load_pyproject()
    project = data.get("project", {})

    base_deps = list(project.get("dependencies") or [])
    opt = dict(project.get("optional-dependencies") or {})

    # Per-extra files
    for extra_name in sorted(opt.keys(), key=lambda s: s.lower()):
        reqs = _unique_sorted(list(base_deps) + list(opt.get(extra_name) or []))
        _write_requirements(ROOT / f"requirements-{extra_name}.txt", reqs)

    # Recommended requirements.txt
    recommended = list(base_deps)
    for extra in RECOMMENDED_EXTRAS:
        recommended.extend(opt.get(extra) or [])
    _write_requirements(ROOT / "requirements.txt", _unique_sorted(recommended))

    # All
    all_reqs = list(base_deps)
    for reqs in opt.values():
        all_reqs.extend(reqs or [])
    _write_requirements(ROOT / "requirements-all.txt", _unique_sorted(all_reqs))


if __name__ == "__main__":
    main()
