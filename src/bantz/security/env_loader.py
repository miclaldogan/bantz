from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

# Project root: three levels up from this file (src/bantz/security/ → project root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Keys that must never be set from .env — they allow code injection.
_BLOCKED_KEYS = frozenset({
    "PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT",
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
    "NODE_OPTIONS", "HOME", "USER", "SHELL",
})

# Only keys starting with these prefixes are accepted.
_ALLOWED_PREFIXES = ("BANTZ_", "LLM_", "GOOGLE_", "VLLM_")


def _strip_quotes(value: str) -> str:
    v = value.strip()
    is_quoted = len(v) >= 2 and (
        (v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")
    )
    if is_quoted:
        v = v[1:-1]
        # Only allow \n replacement inside quoted values
        v = v.replace("\\n", "\n")
    # Never allow embedded newlines — they could inject extra KEY=VALUE pairs
    if "\n" in v:
        logger.warning(
            "Stripping newlines from env value to prevent injection"
        )
        v = v.replace("\n", " ")
    return v


def load_env_file(path: str | os.PathLike[str], *, override: bool = False) -> list[str]:
    """Load environment variables from a simple .env file.

    - Supports lines like: KEY=VALUE or export KEY=VALUE
    - Ignores blank lines and comments (#...)
    - Does not print/log any values
    - By default, does not override existing os.environ entries

    Returns a list of keys loaded.
    """

    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        return []

    loaded: list[str] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = _strip_quotes(value)
        if key in _BLOCKED_KEYS or not key.startswith(_ALLOWED_PREFIXES):
            logger.warning("Skipping blocked/disallowed env key: %s", key)
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        loaded.append(key)

    return loaded


def load_env(
    *,
    env_var: str = "BANTZ_ENV_FILE",
    default_files: Iterable[str] = (".env",),
    override: bool = False,
) -> list[str]:
    """Load a .env file into os.environ.

    Prefers the file specified via `BANTZ_ENV_FILE`; otherwise tries `default_files`
    in the current working directory.

    Returns a list of loaded keys (possibly empty).
    """

    explicit = (os.getenv(env_var) or "").strip()
    if explicit:
        env_path = Path(explicit).resolve()
        if not str(env_path).startswith(str(_PROJECT_ROOT)):
            logger.warning(
                "Ignoring %s=%s — path is outside project root %s",
                env_var, explicit, _PROJECT_ROOT,
            )
            return []
        return load_env_file(explicit, override=override)

    for name in default_files:
        keys = load_env_file(name, override=override)
        if keys:
            return keys
    return []
