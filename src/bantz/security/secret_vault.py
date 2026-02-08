"""Unified Secrets Vault v0 (Issue #454).

Single API for secret management with multiple backends:

1. **Environment variables** — ``BANTZ_SECRET_*`` prefix (always available)
2. **Encrypted file** — ``~/.bantz/secrets.enc`` (Fernet, machine-key)
3. **Plain JSON file** — ``~/.bantz/secrets.json`` + ``chmod 600`` (fallback)

Features:

- ``get / set / delete / list_keys / exists``
- Env-var fallback: ``vault.get("GOOGLE_API_KEY")`` checks
  ``BANTZ_SECRET_GOOGLE_API_KEY`` then encrypted store then plain file.
- Leak detection via :func:`scan_for_leaks`
- Secret rotation with backup of old value
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

__all__ = [
    "SecretVault",
    "scan_for_leaks",
]


# ── Fernet-like encryption (stdlib only) ──────────────────────────────
# We use a simple XOR + HMAC scheme when `cryptography` is not installed.
# When `cryptography` IS available, real Fernet is used.

def _derive_key(passphrase: str) -> bytes:
    """Derive a 32-byte key from a passphrase via SHA-256."""
    return hashlib.sha256(passphrase.encode()).digest()


def _machine_key() -> str:
    """Best-effort machine-unique passphrase."""
    parts: list[str] = []
    # machine-id (Linux)
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            parts.append(Path(p).read_text().strip())
            break
        except OSError:
            pass
    parts.append(os.getenv("USER", "bantz"))
    parts.append("bantz-vault-v0")
    return ":".join(parts)


def _encrypt(data: bytes, key: bytes) -> bytes:
    """Simple XOR-based encryption (for fallback when no crypto lib)."""
    try:
        from cryptography.fernet import Fernet  # type: ignore[import-untyped]
        f = Fernet(urlsafe_b64encode(key))
        return b"FERNET:" + f.encrypt(data)
    except ImportError:
        pass
    # Fallback: repeating-key XOR (NOT production-grade!)
    extended = (key * ((len(data) // len(key)) + 1))[:len(data)]
    xored = bytes(a ^ b for a, b in zip(data, extended))
    return b"XOR:" + urlsafe_b64encode(xored)


def _decrypt(blob: bytes, key: bytes) -> bytes:
    if blob.startswith(b"FERNET:"):
        from cryptography.fernet import Fernet  # type: ignore[import-untyped]
        f = Fernet(urlsafe_b64encode(key))
        return f.decrypt(blob[7:])
    if blob.startswith(b"XOR:"):
        xored = urlsafe_b64decode(blob[4:])
        extended = (key * ((len(xored) // len(key)) + 1))[:len(xored)]
        return bytes(a ^ b for a, b in zip(xored, extended))
    raise ValueError("Unknown encryption prefix")


# ── Leak detection ────────────────────────────────────────────────────

def scan_for_leaks(text: str, secrets: Set[str]) -> List[str]:
    """Return any secret values found in *text*.

    Parameters
    ----------
    text:
        The string to scan (e.g. a log line).
    secrets:
        Set of known secret values.

    Returns
    -------
    list[str]
        Secret values that were found in *text*.
    """
    found: List[str] = []
    for s in secrets:
        if s and len(s) >= 4 and s in text:
            found.append(s)
    return found


def redact_secrets(text: str, secrets: Set[str]) -> str:
    """Replace any secret values in *text* with ``[REDACTED]``."""
    for s in secrets:
        if s and len(s) >= 4:
            text = text.replace(s, "[REDACTED]")
    return text


# ── Vault ─────────────────────────────────────────────────────────────

class SecretVault:
    """Unified secret storage with backend fallback chain.

    Parameters
    ----------
    base_dir:
        Directory for file-based backends.  Defaults to ``~/.bantz``.
    passphrase:
        Encryption passphrase.  Defaults to a machine-derived key.
    env_prefix:
        Prefix for environment variable lookup.
    """

    ENV_PREFIX = "BANTZ_SECRET_"

    def __init__(
        self,
        base_dir: Optional[str] = None,
        passphrase: Optional[str] = None,
        env_prefix: str = "BANTZ_SECRET_",
    ) -> None:
        self._base = Path(base_dir) if base_dir else Path.home() / ".bantz"
        self._base.mkdir(parents=True, exist_ok=True)
        self._enc_path = self._base / "secrets.enc"
        self._plain_path = self._base / "secrets.json"
        self._key = _derive_key(passphrase or _machine_key())
        self._env_prefix = env_prefix
        self._lock = threading.Lock()
        self._cache: Dict[str, str] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ── public API ────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[str]:
        """Get a secret value.

        Lookup order: in-memory cache → env var → encrypted file → plain file.
        """
        # 1. Cache (includes file-loaded secrets)
        if key in self._cache:
            return self._cache[key]

        # 2. Env var
        env_key = self._env_prefix + key
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return env_val

        return None

    def set(self, key: str, value: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Store a secret."""
        with self._lock:
            self._cache[key] = value
            if metadata:
                self._metadata[key] = metadata
            else:
                self._metadata.setdefault(key, {})
            self._metadata[key]["updated_at"] = datetime.utcnow().isoformat()
            self._save()

    def delete(self, key: str) -> bool:
        """Remove a secret.  Returns *True* if it existed."""
        with self._lock:
            existed = key in self._cache
            self._cache.pop(key, None)
            self._metadata.pop(key, None)
            if existed:
                self._save()
            return existed

    def list_keys(self) -> List[str]:
        """List stored secret names (no values exposed)."""
        keys = set(self._cache.keys())
        # Include env-based keys
        for env_key in os.environ:
            if env_key.startswith(self._env_prefix):
                keys.add(env_key[len(self._env_prefix):])
        return sorted(keys)

    def exists(self, key: str) -> bool:
        """Check whether a secret exists (in any backend)."""
        return self.get(key) is not None

    def rotate(self, key: str, new_value: str) -> Optional[str]:
        """Rotate a secret: backup old value, store new.

        Returns the old value (for caller to revoke upstream if needed).
        """
        old = self.get(key)
        meta = self._metadata.get(key, {})
        if old is not None:
            meta["previous_value_hash"] = hashlib.sha256(old.encode()).hexdigest()[:16]
            meta["rotated_at"] = datetime.utcnow().isoformat()
        self.set(key, new_value, metadata=meta)
        return old

    def import_env(self, keys: Optional[List[str]] = None) -> int:
        """Import secrets from environment variables into the vault.

        Parameters
        ----------
        keys:
            Specific env var names to import (without prefix).
            If *None*, imports all ``BANTZ_SECRET_*`` vars.

        Returns
        -------
        int
            Number of secrets imported.
        """
        count = 0
        if keys:
            for k in keys:
                val = os.environ.get(self._env_prefix + k)
                if val is not None:
                    self.set(k, val)
                    count += 1
        else:
            for env_key, val in os.environ.items():
                if env_key.startswith(self._env_prefix):
                    name = env_key[len(self._env_prefix):]
                    self.set(name, val)
                    count += 1
        return count

    def get_all_values(self) -> Set[str]:
        """Return set of all secret values (for leak scanning)."""
        vals = set(self._cache.values())
        for env_key in os.environ:
            if env_key.startswith(self._env_prefix):
                vals.add(os.environ[env_key])
        return vals

    # ── persistence ───────────────────────────────────────────────────

    def _load(self) -> None:
        """Load secrets from the encrypted file, falling back to plain."""
        # Try encrypted first
        if self._enc_path.exists():
            try:
                blob = self._enc_path.read_bytes()
                raw = _decrypt(blob, self._key)
                data = json.loads(raw)
                self._cache = data.get("secrets", {})
                self._metadata = data.get("metadata", {})
                return
            except Exception as exc:
                logger.warning("Failed to load encrypted vault: %s", exc)

        # Fall back to plain JSON
        if self._plain_path.exists():
            try:
                data = json.loads(self._plain_path.read_text(encoding="utf-8"))
                self._cache = data.get("secrets", {})
                self._metadata = data.get("metadata", {})
                return
            except Exception as exc:
                logger.warning("Failed to load plain vault: %s", exc)

    def _save(self) -> None:
        """Persist secrets (must hold lock).  Tries encrypted, falls back to plain."""
        data = json.dumps(
            {"secrets": self._cache, "metadata": self._metadata},
            ensure_ascii=False,
        ).encode("utf-8")

        try:
            blob = _encrypt(data, self._key)
            self._enc_path.write_bytes(blob)
            os.chmod(str(self._enc_path), 0o600)
            # Remove plain file if encrypted write succeeded
            if self._plain_path.exists():
                self._plain_path.unlink()
        except Exception:
            # Fallback: write plain JSON
            self._plain_path.write_text(
                json.dumps(
                    {"secrets": self._cache, "metadata": self._metadata},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            try:
                os.chmod(str(self._plain_path), 0o600)
            except OSError:
                pass
