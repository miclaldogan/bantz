"""Tests for Git-based SkillRegistry (Issue #852).

Covers:
- install_from_git (clone, version pin, manifest)
- update (pull, tag checkout)
- uninstall (rmtree + index cleanup)
- check_updates (fetch + rev-list)
- list_versions (tags)
- search / get from local index
- index persistence (load/save JSON)
- _repo_name_from_url edge cases
- MockSkillRegistry helper
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bantz.plugins.registry import (
    MockSkillRegistry,
    RegistryEntry,
    RegistrySearchResult,
    RegistrySource,
    SkillRegistry,
    SKILL_MANIFEST,
)


# ── fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def tmp_install(tmp_path):
    """Temporary install directory."""
    return tmp_path / "plugins"


@pytest.fixture
def registry(tmp_install, tmp_path):
    """SkillRegistry with temp dirs."""
    return SkillRegistry(install_dir=tmp_install, cache_dir=tmp_path / "cache")


def _ok(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr=stderr)


def _fail(stderr: str = "error") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 1, stdout="", stderr=stderr)


# ─────────────────────────────────────────────────────────────────
# _repo_name_from_url
# ─────────────────────────────────────────────────────────────────

class TestRepoNameFromUrl:

    def test_https_url(self):
        assert SkillRegistry._repo_name_from_url("https://github.com/org/plugin-x") == "plugin-x"

    def test_dot_git_suffix(self):
        assert SkillRegistry._repo_name_from_url("git@github.com:org/foo.git") == "foo"

    def test_trailing_slash(self):
        assert SkillRegistry._repo_name_from_url("https://host/bar/") == "bar"


# ─────────────────────────────────────────────────────────────────
# install_from_git
# ─────────────────────────────────────────────────────────────────

class TestInstallFromGit:

    @patch.object(SkillRegistry, "_run_git", return_value=_ok())
    def test_success(self, mock_git, registry, tmp_install):
        assert registry.install_from_git("https://github.com/org/my-skill") is True
        assert "my-skill" in registry._index
        assert registry._index["my-skill"]["url"] == "https://github.com/org/my-skill"
        assert (tmp_install / "installed.json").exists()

    @patch.object(SkillRegistry, "_run_git", return_value=_ok())
    def test_custom_name(self, mock_git, registry):
        registry.install_from_git("https://github.com/org/repo", name="custom")
        assert "custom" in registry._index

    @patch.object(SkillRegistry, "_run_git")
    def test_with_version(self, mock_git, registry):
        mock_git.return_value = _ok()
        registry.install_from_git("https://github.com/org/r", version="v2.0.0")
        assert registry._index["r"]["version"] == "v2.0.0"

    @patch.object(SkillRegistry, "_run_git", return_value=_fail("clone error"))
    def test_clone_failure(self, mock_git, registry):
        assert registry.install_from_git("https://bad/repo") is False
        assert registry._index == {}

    @patch.object(SkillRegistry, "_run_git", return_value=_ok())
    def test_already_installed(self, mock_git, registry, tmp_install):
        (tmp_install / "dup").mkdir(parents=True)
        assert registry.install_from_git("https://g.c/o/dup") is False

    @patch.object(SkillRegistry, "_run_git", return_value=_ok())
    def test_reads_manifest(self, mock_git, registry, tmp_install):
        # Simulate git clone creating dir
        pdir = tmp_install / "myplugin"
        pdir.mkdir(parents=True)
        manifest = pdir / SKILL_MANIFEST
        manifest.write_text("name: myplugin\nauthor: test\ntags: [a, b]\n")

        # Because the dir already exists, install_from_git will see "already installed"
        # So we test _read_manifest directly
        meta = SkillRegistry._read_manifest(pdir)
        if meta is not None:  # yaml may not be installed
            assert meta["name"] == "myplugin"


# ─────────────────────────────────────────────────────────────────
# install (by name via index)
# ─────────────────────────────────────────────────────────────────

class TestInstallByName:

    @patch.object(SkillRegistry, "install_from_git", return_value=True)
    def test_with_entry(self, mock_ifg, registry):
        registry._index["myp"] = {
            "url": "https://github.com/org/myp",
            "version": "1.0",
            "source": "GIT",
            "metadata": None,
        }
        assert registry.install("myp") is True

    def test_unknown_name(self, registry):
        assert registry.install("nonexistent") is False


# ─────────────────────────────────────────────────────────────────
# uninstall
# ─────────────────────────────────────────────────────────────────

class TestUninstall:

    def test_success(self, registry, tmp_install):
        pdir = tmp_install / "rm-me"
        pdir.mkdir(parents=True)
        (pdir / "plugin.py").write_text("")
        registry._index["rm-me"] = {"url": "", "version": "1.0"}
        registry._save_index()

        assert registry.uninstall("rm-me") is True
        assert not pdir.exists()
        assert "rm-me" not in registry._index

    def test_not_installed(self, registry):
        assert registry.uninstall("ghost") is False


# ─────────────────────────────────────────────────────────────────
# update
# ─────────────────────────────────────────────────────────────────

class TestUpdate:

    @patch.object(SkillRegistry, "_run_git", return_value=_ok())
    def test_pull_latest(self, mock_git, registry, tmp_install):
        pdir = tmp_install / "upd"
        pdir.mkdir(parents=True)
        registry._index["upd"] = {"url": "u", "version": "1.0", "metadata": None}

        assert registry.update("upd") is True

    @patch.object(SkillRegistry, "_run_git", return_value=_ok())
    def test_pin_version(self, mock_git, registry, tmp_install):
        pdir = tmp_install / "upd2"
        pdir.mkdir(parents=True)
        registry._index["upd2"] = {"url": "u", "version": "1.0", "metadata": None}

        assert registry.update("upd2", version="v3.0") is True
        assert registry._index["upd2"]["version"] == "v3.0"

    def test_not_installed(self, registry):
        assert registry.update("nope") is False

    @patch.object(SkillRegistry, "_run_git", return_value=_fail())
    def test_pull_fail(self, mock_git, registry, tmp_install):
        (tmp_install / "failpull").mkdir(parents=True)
        registry._index["failpull"] = {"url": "u", "version": "1.0", "metadata": None}
        assert registry.update("failpull") is False


# ─────────────────────────────────────────────────────────────────
# check_updates
# ─────────────────────────────────────────────────────────────────

class TestCheckUpdates:

    @patch.object(SkillRegistry, "_run_git")
    def test_outdated(self, mock_git, registry, tmp_install):
        pdir = tmp_install / "outdated"
        pdir.mkdir(parents=True)
        registry._index["outdated"] = {"url": "u", "version": "1.0"}
        registry._save_index()

        mock_git.side_effect = [_ok(), _ok(stdout="3\n")]
        result = registry.check_updates()
        assert "outdated" in result

    @patch.object(SkillRegistry, "_run_git")
    def test_up_to_date(self, mock_git, registry, tmp_install):
        pdir = tmp_install / "fresh"
        pdir.mkdir(parents=True)
        registry._index["fresh"] = {"url": "u", "version": "1.0"}
        registry._save_index()

        mock_git.side_effect = [_ok(), _ok(stdout="0\n")]
        result = registry.check_updates()
        assert result == []


# ─────────────────────────────────────────────────────────────────
# list_versions
# ─────────────────────────────────────────────────────────────────

class TestListVersions:

    @patch.object(SkillRegistry, "_run_git")
    def test_returns_tags(self, mock_git, registry, tmp_install):
        pdir = tmp_install / "tagged"
        pdir.mkdir(parents=True)
        mock_git.side_effect = [_ok(), _ok(stdout="v2.0.0\nv1.0.0\n")]
        tags = registry.list_versions("tagged")
        assert tags == ["v2.0.0", "v1.0.0"]

    def test_not_installed(self, registry):
        assert registry.list_versions("nope") == []


# ─────────────────────────────────────────────────────────────────
# get_installed / is_installed
# ─────────────────────────────────────────────────────────────────

class TestGetInstalled:

    def test_with_plugin_py(self, registry, tmp_install):
        pdir = tmp_install / "real"
        pdir.mkdir(parents=True)
        (pdir / "plugin.py").write_text("")
        assert "real" in registry.get_installed()
        assert registry.is_installed("real")

    def test_without_plugin_py(self, registry, tmp_install):
        (tmp_install / "empty").mkdir(parents=True)
        assert "empty" not in registry.get_installed()
        assert not registry.is_installed("empty")

    def test_no_dir(self, registry):
        assert registry.get_installed() == []


# ─────────────────────────────────────────────────────────────────
# get_installed_version
# ─────────────────────────────────────────────────────────────────

class TestGetInstalledVersion:

    def test_known(self, registry):
        registry._index["x"] = {"version": "v1.2.3"}
        assert registry.get_installed_version("x") == "v1.2.3"

    def test_unknown(self, registry):
        assert registry.get_installed_version("y") is None


# ─────────────────────────────────────────────────────────────────
# index persistence
# ─────────────────────────────────────────────────────────────────

class TestIndexPersistence:

    def test_save_and_load(self, tmp_install, tmp_path):
        r1 = SkillRegistry(install_dir=tmp_install, cache_dir=tmp_path / "c")
        r1._index["a"] = {"url": "https://x", "version": "1"}
        r1._save_index()

        r2 = SkillRegistry(install_dir=tmp_install, cache_dir=tmp_path / "c")
        assert "a" in r2._index

    def test_corrupt_json(self, tmp_install, tmp_path):
        tmp_install.mkdir(parents=True)
        (tmp_install / "installed.json").write_text("{bad json")
        r = SkillRegistry(install_dir=tmp_install, cache_dir=tmp_path / "c")
        assert r._index == {}


# ─────────────────────────────────────────────────────────────────
# search / get
# ─────────────────────────────────────────────────────────────────

class TestSearchAndGet:

    def _seeded(self, registry):
        registry._index["alpha"] = {
            "url": "https://g.c/alpha",
            "version": "1.0",
            "metadata": {"author": "A", "description": "Alpha plugin", "tags": ["ai"]},
        }
        registry._index["beta"] = {
            "url": "https://g.c/beta",
            "version": "2.0",
            "metadata": {"author": "B", "description": "Beta thing", "tags": ["web"]},
        }
        return registry

    def test_search_all(self, registry):
        r = self._seeded(registry)
        result = r.search()
        assert result.total == 2

    def test_search_query(self, registry):
        r = self._seeded(registry)
        result = r.search(query="alpha")
        assert result.total == 1
        assert result.entries[0].name == "alpha"

    def test_search_by_tag(self, registry):
        r = self._seeded(registry)
        result = r.search(tags=["web"])
        assert result.total == 1

    def test_get_existing(self, registry):
        r = self._seeded(registry)
        e = r.get("alpha")
        assert e is not None
        assert e.name == "alpha"

    def test_get_missing(self, registry):
        assert registry.get("nope") is None


# ─────────────────────────────────────────────────────────────────
# RegistryEntry (kept from original)
# ─────────────────────────────────────────────────────────────────

class TestRegistryEntry:

    def test_to_dict(self):
        e = RegistryEntry(name="x", version="1", author="A", description="D")
        d = e.to_dict()
        assert d["name"] == "x"
        assert d["source"] == "COMMUNITY"

    def test_from_dict_roundtrip(self):
        orig = RegistryEntry(name="y", version="2", author="B", description="E", tags=["t"])
        d = orig.to_dict()
        restored = RegistryEntry.from_dict(d)
        assert restored.name == "y"
        assert restored.tags == ["t"]


# ─────────────────────────────────────────────────────────────────
# MockSkillRegistry
# ─────────────────────────────────────────────────────────────────

class TestMockSkillRegistry:

    def test_with_entries(self):
        entries = [
            RegistryEntry(name="a", version="1", author="X", description="A", repository="https://r"),
        ]
        m = MockSkillRegistry(entries=entries)
        assert "a" in m._index

    def test_add_entry(self):
        m = MockSkillRegistry()
        m.add_entry(RegistryEntry(name="b", version="1", author="Y", description="B"))
        assert "b" in m._index

    def test_clear(self):
        m = MockSkillRegistry(entries=[
            RegistryEntry(name="c", version="1", author="Z", description="C"),
        ])
        m.clear()
        assert m._index == {}
