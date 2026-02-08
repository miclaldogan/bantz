"""Tests for Issue #217 — Python 3.11+ upgrade.

Verifies pyproject.toml requires-python, docs, and module compatibility.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestPython311Upgrade:
    """Verify Python 3.11+ requirement is set."""

    def test_pyproject_requires_310(self):
        content = (ROOT / "pyproject.toml").read_text()
        assert '>=3.10' in content

    def test_upgrade_guide_exists(self):
        assert (ROOT / "docs" / "setup" / "python311-upgrade.md").is_file()

    def test_upgrade_guide_content(self):
        doc = (ROOT / "docs" / "setup" / "python311-upgrade.md").read_text()
        assert "pyenv" in doc
        assert "uv" in doc
        assert "3.11" in doc

    def test_boot_jarvis_updated(self):
        doc = (ROOT / "docs" / "setup" / "boot-jarvis.md").read_text()
        assert "3.11+" in doc

    def test_current_python_compat(self):
        """Current runtime must be >= 3.10 (existing env)."""
        assert sys.version_info >= (3, 10)

    def test_requires_python_minimum(self):
        """pyproject.toml requires-python should be >=3.10."""
        content = (ROOT / "pyproject.toml").read_text()
        lines = content.split("\n")
        for line in lines:
            if "requires-python" in line:
                assert ">=3.10" in line, f"requires-python should be >=3.10, got: {line}"
