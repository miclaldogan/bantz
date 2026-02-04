from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def _strip_quotes(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
        v = v[1:-1]
    # Allow writing multiline values using literal \n in .env.
    return v.replace("\\n", "\n")


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
        return load_env_file(explicit, override=override)

    for name in default_files:
        keys = load_env_file(name, override=override)
        if keys:
            return keys
    return []
