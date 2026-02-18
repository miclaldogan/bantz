"""CodeEditor deep tests (Issue #854).

Covers:
- Diff parsing and application
- Function / class replacement
- Line-level insert / delete / replace
- Batch edits
- Search-and-replace
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bantz.coding.editor import CodeEditor, DiffHunk, DiffResult
from bantz.coding.files import FileManager
from bantz.coding.security import SecurityPolicy


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


@pytest.fixture
def editor(workspace):
    policy = SecurityPolicy(workspace_root=workspace)
    fm = FileManager(workspace_root=workspace, security=policy)
    return CodeEditor(file_manager=fm)


# ─────────────────────────────────────────────────────────────────
# Diff parsing
# ─────────────────────────────────────────────────────────────────

class TestDiffParsing:

    def test_parse_single_hunk(self, editor):
        diff = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+modified\n"
            " line3\n"
        )
        hunks = editor._parse_diff(diff)
        assert len(hunks) == 1
        assert hunks[0].old_start == 1
        assert hunks[0].old_count == 3
        assert hunks[0].new_count == 3

    def test_parse_multiple_hunks(self, editor):
        diff = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,3 +1,3 @@\n"
            " a\n"
            "-b\n"
            "+B\n"
            " c\n"
            "@@ -10,3 +10,3 @@\n"
            " x\n"
            "-y\n"
            "+Y\n"
            " z\n"
        )
        hunks = editor._parse_diff(diff)
        assert len(hunks) == 2

    def test_parse_empty_diff(self, editor):
        hunks = editor._parse_diff("")
        assert hunks == []

    def test_parse_no_hunks(self, editor):
        diff = "--- a/file\n+++ b/file\n"
        hunks = editor._parse_diff(diff)
        assert hunks == []


# ─────────────────────────────────────────────────────────────────
# Applying diffs
# ─────────────────────────────────────────────────────────────────

class TestApplyDiff:

    def test_apply_simple_diff(self, workspace, editor):
        f = workspace / "test.py"
        f.write_text("line1\nline2\nline3\n")

        diff = (
            "--- a/test.py\n"
            "+++ b/test.py\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+modified\n"
            " line3\n"
        )
        result = editor.apply_diff(str(f), diff)
        assert result.success
        assert result.hunks_applied == 1
        assert "modified" in f.read_text()

    def test_apply_bad_diff_returns_failure(self, workspace, editor):
        f = workspace / "test.py"
        f.write_text("hello\n")
        result = editor.apply_diff(str(f), "nothing valid here")
        assert not result.success
        assert result.hunks_applied == 0

    def test_apply_diff_nonexistent_file(self, workspace, editor):
        result = editor.apply_diff(str(workspace / "nope.py"), "@@ -1 +1 @@\n-x\n+y\n")
        assert not result.success


# ─────────────────────────────────────────────────────────────────
# create_diff
# ─────────────────────────────────────────────────────────────────

class TestCreateDiff:

    def test_create_diff(self, workspace, editor):
        diff = editor.create_diff("test.txt", "a\nb\nc\n", "a\nB\nc\n")
        assert "-b" in diff
        assert "+B" in diff

    def test_create_diff_identical(self, workspace, editor):
        diff = editor.create_diff("test.txt", "same\n", "same\n")
        assert diff == ""  # no diff for identical content

    def test_create_diff_addition(self, workspace, editor):
        diff = editor.create_diff("test.txt", "a\n", "a\nb\n")
        assert "+b" in diff


# ─────────────────────────────────────────────────────────────────
# Line operations
# ─────────────────────────────────────────────────────────────────

class TestLineOperations:

    def test_insert_at_line(self, workspace, editor):
        f = workspace / "test.py"
        f.write_text("L1\nL2\nL3\n")
        editor.insert_at_line(str(f), 2, "INSERTED\n")
        lines = f.read_text().splitlines()
        assert "INSERTED" in lines

    def test_insert_after(self, workspace, editor):
        f = workspace / "test.py"
        f.write_text("L1\nL2\nL3\n")
        editor.insert_at_line(str(f), 2, "AFTER\n", after=True)
        lines = f.read_text().splitlines()
        idx = lines.index("AFTER")
        assert idx == 2  # after line 2

    def test_delete_lines(self, workspace, editor):
        f = workspace / "test.py"
        f.write_text("A\nB\nC\nD\nE\n")
        editor.delete_lines(str(f), 2, 4)
        lines = f.read_text().splitlines()
        assert lines == ["A", "E"]

    def test_delete_single_line(self, workspace, editor):
        f = workspace / "test.py"
        f.write_text("A\nB\nC\n")
        editor.delete_lines(str(f), 2, 2)
        lines = f.read_text().splitlines()
        assert lines == ["A", "C"]

    def test_replace_lines(self, workspace, editor):
        f = workspace / "test.py"
        f.write_text("A\nB\nC\nD\nE\n")
        editor.replace_lines(str(f), 2, 4, "REPLACED\n")
        lines = f.read_text().splitlines()
        assert "REPLACED" in lines
        assert "B" not in lines
        assert "C" not in lines
        assert "D" not in lines


# ─────────────────────────────────────────────────────────────────
# Function / Class Replacement
# ─────────────────────────────────────────────────────────────────

class TestFunctionReplacement:

    def test_replace_python_function(self, workspace, editor):
        f = workspace / "mod.py"
        f.write_text(
            "def foo():\n"
            "    return 1\n"
            "\n"
            "def bar():\n"
            "    return 2\n"
        )
        new_func = "def foo():\n    return 42\n"
        ok = editor.replace_function(str(f), "foo", new_func, language="python")
        assert ok
        content = f.read_text()
        assert "return 42" in content
        assert "return 2" in content  # bar untouched

    def test_replace_function_not_found(self, workspace, editor):
        f = workspace / "mod.py"
        f.write_text("def bar():\n    pass\n")
        with pytest.raises(ValueError, match="Function not found"):
            editor.replace_function(str(f), "nonexistent", "def x(): pass", language="python")

    def test_replace_class(self, workspace, editor):
        f = workspace / "mod.py"
        f.write_text(
            "class Foo:\n"
            "    x = 1\n"
            "\n"
            "class Bar:\n"
            "    y = 2\n"
        )
        new_cls = "class Foo:\n    x = 99\n"
        ok = editor.replace_class(str(f), "Foo", new_cls, language="python")
        assert ok
        content = f.read_text()
        assert "x = 99" in content
        assert "y = 2" in content

    def test_auto_detect_language(self, workspace, editor):
        f = workspace / "test.py"
        f.write_text("def hello():\n    pass\n")
        new_func = "def hello():\n    return 'hi'\n"
        ok = editor.replace_function(str(f), "hello", new_func)
        assert ok

    def test_detect_language_mapping(self, editor):
        assert editor._detect_language(".py") == "python"
        assert editor._detect_language(".js") == "javascript"
        assert editor._detect_language(".ts") == "typescript"
        assert editor._detect_language(".go") == "go"
        assert editor._detect_language(".rs") == "rust"
        assert editor._detect_language(".xyz") == "unknown"


# ─────────────────────────────────────────────────────────────────
# Batch / Multi-file edits
# ─────────────────────────────────────────────────────────────────

class TestBatchEdits:

    def test_batch_edit_multiple_files(self, workspace, editor):
        f1 = workspace / "a.py"
        f2 = workspace / "b.py"
        f1.write_text("old1")
        f2.write_text("old2")
        results = editor.batch_edit([
            {"file_path": str(f1), "old_str": "old1", "new_str": "new1"},
            {"file_path": str(f2), "old_str": "old2", "new_str": "new2"},
        ])
        assert len(results) == 2
        assert all(r["success"] for r in results)
        assert f1.read_text() == "new1"
        assert f2.read_text() == "new2"

    def test_batch_edit_partial_failure(self, workspace, editor):
        f1 = workspace / "a.py"
        f1.write_text("hello")
        results = editor.batch_edit([
            {"file_path": str(f1), "old_str": "hello", "new_str": "world"},
            {"file_path": str(workspace / "nope.py"), "old_str": "x", "new_str": "y"},
        ])
        assert results[0]["success"] is True
        assert results[1]["success"] is False


class TestSearchAndReplace:

    def test_search_and_replace(self, workspace, editor):
        (workspace / "a.py").write_text("old_name = 1\nold_name = 2")
        (workspace / "b.py").write_text("keep = 1")
        results = editor.search_and_replace("old_name", "new_name", file_pattern="*.py")
        assert any(r["replacements"] == 2 for r in results)
        assert "new_name = 1" in (workspace / "a.py").read_text()

    def test_search_and_replace_regex(self, workspace, editor):
        (workspace / "c.py").write_text("foo123 bar456")
        results = editor.search_and_replace(
            r"[a-z]+\d+", "REPLACED", file_pattern="*.py", is_regex=True
        )
        assert any(r["replacements"] > 0 for r in results)
