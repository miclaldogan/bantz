"""FileManager deep tests (Issue #854).

Covers:
- Read/write with line ranges
- Backup creation and cleanup
- Edit with occurrence selection
- Undo/redo chain
- Directory operations
- Content search
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from bantz.coding.files import FileEdit, FileInfo, FileManager
from bantz.coding.security import ConfirmationRequired, SecurityError, SecurityPolicy


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def fm(workspace):
    policy = SecurityPolicy(workspace_root=workspace)
    return FileManager(workspace_root=workspace, security=policy)


# ─────────────────────────────────────────────────────────────────
# Read operations
# ─────────────────────────────────────────────────────────────────

class TestFileRead:

    def test_read_full(self, workspace, fm):
        f = workspace / "test.txt"
        f.write_text("Hello\nWorld")
        assert fm.read_file(str(f)) == "Hello\nWorld"

    def test_read_line_range(self, workspace, fm):
        f = workspace / "test.txt"
        f.write_text("L1\nL2\nL3\nL4\nL5")
        content = fm.read_file(str(f), start_line=2, end_line=4)
        assert "L2" in content
        assert "L4" in content
        assert "L1" not in content
        assert "L5" not in content

    def test_read_single_line(self, workspace, fm):
        f = workspace / "test.txt"
        f.write_text("A\nB\nC")
        content = fm.read_file(str(f), start_line=2, end_line=2)
        assert content.strip() == "B"

    def test_read_nonexistent_raises(self, workspace, fm):
        with pytest.raises(FileNotFoundError):
            fm.read_file(str(workspace / "nope.txt"))

    def test_read_directory_raises(self, workspace, fm):
        d = workspace / "adir"
        d.mkdir()
        with pytest.raises(ValueError, match="Not a file"):
            fm.read_file(str(d))

    def test_read_relative_path(self, workspace, fm):
        f = workspace / "sub" / "file.py"
        f.parent.mkdir(parents=True)
        f.write_text("content")
        assert fm.read_file("sub/file.py") == "content"

    def test_read_lines(self, workspace, fm):
        f = workspace / "test.txt"
        f.write_text("A\nB\nC\nD")
        lines = fm.read_lines(str(f))
        assert len(lines) == 4
        assert lines[2] == "C"


# ─────────────────────────────────────────────────────────────────
# Write operations
# ─────────────────────────────────────────────────────────────────

class TestFileWrite:

    def test_write_creates_file(self, workspace, fm):
        f = workspace / "new.txt"
        fm.write_file(str(f), "hello")
        assert f.read_text() == "hello"

    def test_write_creates_backup(self, workspace, fm):
        f = workspace / "test.txt"
        f.write_text("original")
        fm.write_file(str(f), "updated")
        backups = list((workspace / ".bantz_backups").rglob("*.bak"))
        assert len(backups) >= 1

    def test_write_no_backup_option(self, workspace):
        policy = SecurityPolicy(workspace_root=workspace)
        fm = FileManager(workspace_root=workspace, security=policy, backup_enabled=False)
        f = workspace / "test.txt"
        f.write_text("original")
        fm.write_file(str(f), "updated", create_backup=False)
        backup_dir = workspace / ".bantz_backups"
        assert not backup_dir.exists() or not list(backup_dir.rglob("*.bak"))

    def test_write_creates_parent_dirs(self, workspace, fm):
        f = workspace / "deep" / "nested" / "file.py"
        fm.write_file(str(f), "# code")
        assert f.exists()

    def test_write_records_history(self, workspace, fm):
        f = workspace / "test.txt"
        f.write_text("v1")
        fm.write_file(str(f), "v2")
        fm.write_file(str(f), "v3")
        history = fm.get_edit_history()
        assert len(history) == 2


# ─────────────────────────────────────────────────────────────────
# Edit operations (string replacement)
# ─────────────────────────────────────────────────────────────────

class TestFileEdit:

    def test_edit_replace_first(self, workspace, fm):
        f = workspace / "test.py"
        f.write_text("aaa bbb aaa")
        fm.edit_file(str(f), "aaa", "xxx", occurrence=1)
        assert f.read_text() == "xxx bbb aaa"

    def test_edit_replace_all(self, workspace, fm):
        f = workspace / "test.py"
        f.write_text("aaa bbb aaa")
        fm.edit_file(str(f), "aaa", "xxx", occurrence=0)
        assert f.read_text() == "xxx bbb xxx"

    def test_edit_replace_second(self, workspace, fm):
        f = workspace / "test.py"
        f.write_text("aaa bbb aaa ccc aaa")
        fm.edit_file(str(f), "aaa", "xxx", occurrence=2)
        content = f.read_text()
        assert content == "aaa bbb xxx ccc aaa"

    def test_edit_not_found_raises(self, workspace, fm):
        f = workspace / "test.py"
        f.write_text("hello world")
        with pytest.raises(ValueError, match="String not found"):
            fm.edit_file(str(f), "nothere", "x")

    def test_edit_occurrence_too_high_raises(self, workspace, fm):
        f = workspace / "test.py"
        f.write_text("aaa bbb")
        with pytest.raises(ValueError, match="Only 1 occurrences"):
            fm.edit_file(str(f), "aaa", "xxx", occurrence=5)

    def test_edit_nonexistent_raises(self, workspace, fm):
        with pytest.raises(FileNotFoundError):
            fm.edit_file(str(workspace / "nope.py"), "x", "y")


# ─────────────────────────────────────────────────────────────────
# Create / Delete
# ─────────────────────────────────────────────────────────────────

class TestCreateDelete:

    def test_create_new_file(self, workspace, fm):
        f = workspace / "brand_new.py"
        fm.create_file(str(f), "# new")
        assert f.read_text() == "# new"

    def test_create_existing_raises(self, workspace, fm):
        f = workspace / "exists.py"
        f.write_text("x")
        with pytest.raises(FileExistsError):
            fm.create_file(str(f), "y")

    def test_create_overwrite_needs_confirm(self, workspace, fm):
        f = workspace / "exists.py"
        f.write_text("x")
        with pytest.raises(ConfirmationRequired):
            fm.create_file(str(f), "y", overwrite=True, confirmed=False)

    def test_create_overwrite_confirmed(self, workspace, fm):
        f = workspace / "exists.py"
        f.write_text("x")
        fm.create_file(str(f), "y", overwrite=True, confirmed=True)
        assert f.read_text() == "y"

    def test_delete_requires_confirm(self, workspace, fm):
        f = workspace / "del.txt"
        f.write_text("x")
        with pytest.raises(ConfirmationRequired):
            fm.delete_file(str(f), confirmed=False)

    def test_delete_confirmed(self, workspace, fm):
        f = workspace / "del.txt"
        f.write_text("x")
        fm.delete_file(str(f), confirmed=True)
        assert not f.exists()

    def test_delete_nonexistent_raises(self, workspace, fm):
        with pytest.raises(FileNotFoundError):
            fm.delete_file(str(workspace / "nope.txt"), confirmed=True)

    def test_delete_creates_backup(self, workspace, fm):
        f = workspace / "backup_me.txt"
        f.write_text("precious data")
        fm.delete_file(str(f), confirmed=True)
        backups = list((workspace / ".bantz_backups").rglob("*.bak"))
        assert len(backups) >= 1


# ─────────────────────────────────────────────────────────────────
# Undo
# ─────────────────────────────────────────────────────────────────

class TestUndo:

    def test_undo_write(self, workspace, fm):
        f = workspace / "test.txt"
        f.write_text("original")
        fm.write_file(str(f), "modified")
        edit = fm.undo_last_edit()
        assert edit is not None
        assert f.read_text() == "original"

    def test_undo_create(self, workspace, fm):
        f = workspace / "created.py"
        fm.create_file(str(f), "# content")
        assert f.exists()
        fm.undo_last_edit()
        assert not f.exists()

    def test_undo_empty_returns_none(self, workspace, fm):
        assert fm.undo_last_edit() is None

    def test_multiple_undos(self, workspace, fm):
        f = workspace / "test.txt"
        f.write_text("v1")
        fm.write_file(str(f), "v2")
        fm.write_file(str(f), "v3")
        fm.undo_last_edit()
        assert f.read_text() == "v2"
        fm.undo_last_edit()
        assert f.read_text() == "v1"


# ─────────────────────────────────────────────────────────────────
# Directory listing / search
# ─────────────────────────────────────────────────────────────────

class TestDirectoryOps:

    def test_list_directory(self, workspace, fm):
        (workspace / "a.py").write_text("")
        (workspace / "b.js").write_text("")
        (workspace / "sub").mkdir()
        entries = fm.list_directory()
        names = [e["name"] for e in entries]
        assert "a.py" in names
        assert "b.js" in names
        assert "sub" in names

    def test_list_directory_recursive(self, workspace, fm):
        (workspace / "sub").mkdir()
        (workspace / "sub" / "deep.py").write_text("")
        entries = fm.list_directory(".", recursive=True)
        paths = [e["path"] for e in entries]
        assert any("deep.py" in p for p in paths)

    def test_search_files_by_glob(self, workspace, fm):
        (workspace / "a.py").write_text("")
        (workspace / "b.py").write_text("")
        (workspace / "c.js").write_text("")
        results = fm.search_files("*.py")
        assert len(results) == 2

    def test_search_files_by_content(self, workspace, fm):
        (workspace / "has_it.py").write_text("def target_func(): pass")
        (workspace / "no_it.py").write_text("def other(): pass")
        results = fm.search_files("*.py", content_pattern="target_func")
        assert len(results) == 1
        assert "has_it.py" in results[0]

    def test_create_directory(self, workspace, fm):
        fm.create_directory("new_dir/sub")
        assert (workspace / "new_dir" / "sub").is_dir()


# ─────────────────────────────────────────────────────────────────
# File info
# ─────────────────────────────────────────────────────────────────

class TestFileInfo:

    def test_get_file_info(self, workspace, fm):
        f = workspace / "test.py"
        f.write_text("hello world")
        info = fm.get_file_info(str(f))
        assert isinstance(info, FileInfo)
        assert info.name == "test.py"
        assert info.size == 11
        assert info.is_file is True
        assert info.extension == ".py"

    def test_file_info_to_dict(self, workspace, fm):
        f = workspace / "test.py"
        f.write_text("x")
        info = fm.get_file_info(str(f))
        d = info.to_dict()
        assert "path" in d
        assert "size" in d
        assert d["is_file"] is True

    def test_file_exists(self, workspace, fm):
        f = workspace / "exists.txt"
        f.write_text("")
        assert fm.file_exists(str(f)) is True
        assert fm.file_exists(str(workspace / "nope.txt")) is False


# ─────────────────────────────────────────────────────────────────
# Backup management
# ─────────────────────────────────────────────────────────────────

class TestBackupManagement:

    def test_list_backups(self, workspace, fm):
        f = workspace / "test.txt"
        f.write_text("v1")
        fm.write_file(str(f), "v2")
        fm.write_file(str(f), "v3")
        backups = fm.list_backups(str(f))
        assert len(backups) >= 2

    def test_restore_from_backup(self, workspace, fm):
        f = workspace / "test.txt"
        f.write_text("original")
        fm.write_file(str(f), "changed")
        fm.restore_from_backup(str(f))
        assert f.read_text() == "original"

    def test_restore_no_backup_raises(self, workspace, fm):
        f = workspace / "no_backup.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="No backup found"):
            fm.restore_from_backup(str(f))

    def test_max_backups_cleanup(self, workspace):
        policy = SecurityPolicy(workspace_root=workspace)
        fm = FileManager(workspace_root=workspace, security=policy, max_backups_per_file=3)
        f = workspace / "test.txt"
        f.write_text("v0")
        for i in range(6):
            fm.write_file(str(f), f"v{i+1}")
        backups = fm.list_backups(str(f))
        assert len(backups) <= 3
