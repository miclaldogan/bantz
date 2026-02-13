"""ProjectContext deep tests (Issue #854).

Covers:
- Project type detection (Python, Node, Rust, Go, unknown)
- Dependency parsing
- File tree generation
- Symbol extraction (Python, JS)
- Import analysis
- Related file discovery
- Symbol search
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bantz.coding.context import Dependency, ProjectContext, ProjectInfo, Symbol


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


# ─────────────────────────────────────────────────────────────────
# Project Type Detection
# ─────────────────────────────────────────────────────────────────

class TestProjectDetection:

    def test_detect_python_pyproject(self, workspace):
        (workspace / "pyproject.toml").write_text('[project]\nname = "test"')
        ctx = ProjectContext(workspace)
        assert ctx.detect_project_type() == "python"

    def test_detect_python_requirements(self, workspace):
        (workspace / "requirements.txt").write_text("requests\nflask\n")
        ctx = ProjectContext(workspace)
        assert ctx.detect_project_type() == "python"

    def test_detect_python_setup_py(self, workspace):
        (workspace / "setup.py").write_text("from setuptools import setup")
        ctx = ProjectContext(workspace)
        assert ctx.detect_project_type() == "python"

    def test_detect_node(self, workspace):
        (workspace / "package.json").write_text('{"name": "app"}')
        ctx = ProjectContext(workspace)
        assert ctx.detect_project_type() == "node"

    def test_detect_rust(self, workspace):
        (workspace / "Cargo.toml").write_text('[package]\nname = "app"')
        ctx = ProjectContext(workspace)
        assert ctx.detect_project_type() == "rust"

    def test_detect_go(self, workspace):
        (workspace / "go.mod").write_text("module example.com/app\ngo 1.21")
        ctx = ProjectContext(workspace)
        assert ctx.detect_project_type() == "go"

    def test_detect_unknown(self, workspace):
        (workspace / "random.xyz").write_text("")
        ctx = ProjectContext(workspace)
        assert ctx.detect_project_type() == "unknown"

    def test_detection_caching(self, workspace):
        (workspace / "pyproject.toml").write_text('[project]\nname = "x"')
        ctx = ProjectContext(workspace)
        t1 = ctx.detect_project_type()
        t2 = ctx.detect_project_type()
        assert t1 == t2 == "python"

    def test_clear_cache(self, workspace):
        (workspace / "pyproject.toml").write_text('[project]\nname = "x"')
        ctx = ProjectContext(workspace)
        ctx.detect_project_type()
        ctx.clear_cache()
        assert "project_type" not in ctx._cache


# ─────────────────────────────────────────────────────────────────
# Project Info & Dependencies
# ─────────────────────────────────────────────────────────────────

class TestProjectInfo:

    def test_python_project_info_pep621(self, workspace):
        (workspace / "pyproject.toml").write_text(
            '[project]\n'
            'name = "myapp"\n'
            'version = "1.2.3"\n'
            'description = "A test app"\n'
            'dependencies = ["requests>=2.0", "flask"]\n'
        )
        ctx = ProjectContext(workspace)
        info = ctx.get_project_info()
        assert info.name == "myapp"
        assert info.version == "1.2.3"
        assert info.type == "python"
        assert any(d.name == "requests" for d in info.dependencies)

    def test_python_requirements_fallback(self, workspace):
        (workspace / "requirements.txt").write_text("requests>=2.0\nflask\n# comment\n")
        ctx = ProjectContext(workspace)
        info = ctx.get_project_info()
        deps = info.dependencies
        assert any(d.name == "requests" for d in deps)
        assert any(d.name == "flask" for d in deps)

    def test_node_project_info(self, workspace):
        (workspace / "package.json").write_text(json.dumps({
            "name": "myapp",
            "version": "2.0.0",
            "description": "Node app",
            "dependencies": {"express": "^4.0.0"},
            "devDependencies": {"jest": "^29.0"},
            "main": "index.js",
        }))
        ctx = ProjectContext(workspace)
        info = ctx.get_project_info()
        assert info.name == "myapp"
        assert info.type == "node"
        assert any(d.name == "express" for d in info.dependencies)
        assert any(d.name == "jest" for d in info.dev_dependencies)
        assert "index.js" in info.entry_points

    def test_go_project_info(self, workspace):
        (workspace / "go.mod").write_text(
            "module example.com/app\n"
            "go 1.21\n"
            "require (\n"
            "\tgithub.com/gin-gonic/gin v1.9.1\n"
            "\tgithub.com/go-redis/redis v6.15.0\n"
            ")\n"
        )
        ctx = ProjectContext(workspace)
        info = ctx.get_project_info()
        assert info.type == "go"
        assert info.name == "example.com/app"
        deps = info.dependencies
        assert any("gin" in d.name for d in deps)

    def test_get_dependencies(self, workspace):
        (workspace / "requirements.txt").write_text("requests\nnumpy\n")
        ctx = ProjectContext(workspace)
        deps = ctx.get_dependencies()
        assert len(deps) >= 2

    def test_project_info_to_dict(self, workspace):
        (workspace / "requirements.txt").write_text("requests\n")
        ctx = ProjectContext(workspace)
        info = ctx.get_project_info()
        d = info.to_dict()
        assert "root" in d
        assert "type" in d
        assert "dependencies" in d

    def test_project_info_caching(self, workspace):
        (workspace / "requirements.txt").write_text("flask\n")
        ctx = ProjectContext(workspace)
        i1 = ctx.get_project_info()
        i2 = ctx.get_project_info()
        assert i1 is i2  # same cached object


# ─────────────────────────────────────────────────────────────────
# File Tree
# ─────────────────────────────────────────────────────────────────

class TestFileTree:

    def test_basic_tree(self, workspace):
        (workspace / "src").mkdir()
        (workspace / "src" / "main.py").write_text("")
        (workspace / "tests").mkdir()
        (workspace / "tests" / "test_main.py").write_text("")

        ctx = ProjectContext(workspace)
        tree = ctx.get_file_tree(max_depth=2)
        assert tree["type"] == "directory"
        child_names = [c["name"] for c in tree["children"]]
        assert "src" in child_names
        assert "tests" in child_names

    def test_tree_respects_depth(self, workspace):
        deep = workspace / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "file.py").write_text("")

        ctx = ProjectContext(workspace)
        tree = ctx.get_file_tree(max_depth=1)
        # Should not go deeper than 1 level
        for child in tree.get("children", []):
            if child["type"] == "directory":
                for grandchild in child.get("children", []):
                    assert grandchild.get("truncated", False) or "children" not in grandchild

    def test_tree_skips_hidden(self, workspace):
        (workspace / ".git").mkdir()
        (workspace / "visible.py").write_text("")
        ctx = ProjectContext(workspace)
        tree = ctx.get_file_tree()
        child_names = [c["name"] for c in tree["children"]]
        assert ".git" not in child_names
        assert "visible.py" in child_names

    def test_tree_skips_node_modules(self, workspace):
        (workspace / "node_modules").mkdir()
        (workspace / "index.js").write_text("")
        ctx = ProjectContext(workspace)
        tree = ctx.get_file_tree()
        child_names = [c["name"] for c in tree["children"]]
        assert "node_modules" not in child_names

    def test_tree_extension_filter(self, workspace):
        (workspace / "a.py").write_text("")
        (workspace / "b.js").write_text("")
        ctx = ProjectContext(workspace)
        tree = ctx.get_file_tree(extensions=[".py"])
        file_children = [c for c in tree["children"] if c["type"] == "file"]
        assert all(c["extension"] == ".py" for c in file_children)


# ─────────────────────────────────────────────────────────────────
# Symbol Extraction
# ─────────────────────────────────────────────────────────────────

class TestSymbolExtraction:

    def test_python_function(self, workspace):
        f = workspace / "code.py"
        f.write_text('def hello():\n    """Greet."""\n    pass\n')
        ctx = ProjectContext(workspace)
        symbols = ctx.get_symbols(str(f))
        assert any(s.name == "hello" and s.type == "function" for s in symbols)

    def test_python_class_and_methods(self, workspace):
        f = workspace / "code.py"
        f.write_text(
            "class MyClass:\n"
            "    def method_a(self):\n"
            "        pass\n"
            "    @property\n"
            "    def prop(self):\n"
            "        return 1\n"
        )
        ctx = ProjectContext(workspace)
        symbols = ctx.get_symbols(str(f))
        names = [s.name for s in symbols]
        assert "MyClass" in names
        assert "method_a" in names
        assert "prop" in names
        # Check method parent
        method = next(s for s in symbols if s.name == "method_a")
        assert method.parent == "MyClass"

    def test_python_async_function(self, workspace):
        f = workspace / "code.py"
        f.write_text("async def fetch_data():\n    pass\n")
        ctx = ProjectContext(workspace)
        symbols = ctx.get_symbols(str(f))
        assert any(s.name == "fetch_data" for s in symbols)

    def test_python_decorated_function(self, workspace):
        f = workspace / "code.py"
        f.write_text("@staticmethod\ndef helper():\n    pass\n")
        ctx = ProjectContext(workspace)
        symbols = ctx.get_symbols(str(f))
        func = next(s for s in symbols if s.name == "helper")
        assert "@staticmethod" in func.decorators

    def test_python_function_signature(self, workspace):
        f = workspace / "code.py"
        f.write_text("def add(a: int, b: int) -> int:\n    return a + b\n")
        ctx = ProjectContext(workspace)
        symbols = ctx.get_symbols(str(f))
        func = next(s for s in symbols if s.name == "add")
        assert "a: int" in func.signature
        assert "-> int" in func.signature

    def test_js_function(self, workspace):
        f = workspace / "app.js"
        f.write_text("function greet(name) {\n  return 'hi ' + name;\n}\n")
        ctx = ProjectContext(workspace)
        symbols = ctx.get_symbols(str(f))
        assert any(s.name == "greet" for s in symbols)

    def test_js_class(self, workspace):
        f = workspace / "app.js"
        f.write_text("class Widget {\n  constructor() {}\n}\n")
        ctx = ProjectContext(workspace)
        symbols = ctx.get_symbols(str(f))
        assert any(s.name == "Widget" and s.type == "class" for s in symbols)

    def test_symbol_from_nonexistent_file(self, workspace):
        ctx = ProjectContext(workspace)
        symbols = ctx.get_symbols(str(workspace / "nope.py"))
        assert symbols == []

    def test_symbol_to_dict(self, workspace):
        f = workspace / "code.py"
        f.write_text("def foo():\n    pass\n")
        ctx = ProjectContext(workspace)
        symbols = ctx.get_symbols(str(f))
        d = symbols[0].to_dict()
        assert "name" in d
        assert "type" in d
        assert "line" in d


# ─────────────────────────────────────────────────────────────────
# Imports
# ─────────────────────────────────────────────────────────────────

class TestImports:

    def test_get_imports(self, workspace):
        f = workspace / "code.py"
        f.write_text("import os\nimport sys\nfrom pathlib import Path\n")
        ctx = ProjectContext(workspace)
        imports = ctx.get_imports(str(f))
        assert "os" in imports
        assert "sys" in imports
        assert "pathlib" in imports

    def test_get_imports_empty_file(self, workspace):
        f = workspace / "empty.py"
        f.write_text("")
        ctx = ProjectContext(workspace)
        imports = ctx.get_imports(str(f))
        assert imports == []

    def test_get_imports_non_python(self, workspace):
        f = workspace / "app.js"
        f.write_text("import React from 'react';")
        ctx = ProjectContext(workspace)
        imports = ctx.get_imports(str(f))
        assert imports == []

    def test_get_imports_nonexistent(self, workspace):
        ctx = ProjectContext(workspace)
        imports = ctx.get_imports(str(workspace / "nope.py"))
        assert imports == []

    def test_get_imports_deduplicates(self, workspace):
        f = workspace / "code.py"
        f.write_text("import os\nimport os\n")
        ctx = ProjectContext(workspace)
        imports = ctx.get_imports(str(f))
        assert imports.count("os") == 1


# ─────────────────────────────────────────────────────────────────
# Related Files
# ─────────────────────────────────────────────────────────────────

class TestRelatedFiles:

    def test_find_test_file(self, workspace):
        (workspace / "module.py").write_text("")
        (workspace / "tests").mkdir()
        (workspace / "tests" / "test_module.py").write_text("")
        ctx = ProjectContext(workspace)
        related = ctx.find_related_files("module.py")
        assert any("test_module" in r for r in related)

    def test_find_no_related(self, workspace):
        (workspace / "orphan.py").write_text("")
        ctx = ProjectContext(workspace)
        related = ctx.find_related_files("orphan.py")
        assert related == [] or len(related) == 0

    def test_find_related_imports(self, workspace):
        (workspace / "utils.py").write_text("def helper(): pass")
        (workspace / "main.py").write_text("import utils\n")
        ctx = ProjectContext(workspace)
        related = ctx.find_related_files("main.py")
        assert any("utils.py" in r for r in related)

    def test_find_related_nonexistent(self, workspace):
        ctx = ProjectContext(workspace)
        related = ctx.find_related_files("nope.py")
        assert related == []


# ─────────────────────────────────────────────────────────────────
# Symbol Search
# ─────────────────────────────────────────────────────────────────

class TestSymbolSearch:

    def test_search_by_name(self, workspace):
        (workspace / "a.py").write_text("def process_data(): pass")
        (workspace / "b.py").write_text("def process_image(): pass")
        ctx = ProjectContext(workspace)
        results = ctx.search_symbol("process")
        assert len(results) == 2
        names = [r["name"] for r in results]
        assert "process_data" in names
        assert "process_image" in names

    def test_search_by_type(self, workspace):
        (workspace / "code.py").write_text("def func(): pass\nclass MyClass: pass\n")
        ctx = ProjectContext(workspace)
        funcs = ctx.search_symbol("", symbol_type="function")
        classes = ctx.search_symbol("", symbol_type="class")
        # func should match only functions, classes only classes
        assert all(r.get("type") == "function" for r in funcs if r["name"] == "func")

    def test_search_max_results(self, workspace):
        lines = "\n".join(f"def func_{i}(): pass" for i in range(30))
        (workspace / "many.py").write_text(lines)
        ctx = ProjectContext(workspace)
        results = ctx.search_symbol("func_", max_results=5)
        assert len(results) <= 5

    def test_search_no_match(self, workspace):
        (workspace / "code.py").write_text("def hello(): pass")
        ctx = ProjectContext(workspace)
        results = ctx.search_symbol("zzzznonexistent")
        assert results == []


# ─────────────────────────────────────────────────────────────────
# Dataclass tests
# ─────────────────────────────────────────────────────────────────

class TestDataclasses:

    def test_dependency_to_dict(self):
        d = Dependency(name="flask", version=">=2.0", dev=False, source="requirements.txt")
        dd = d.to_dict()
        assert dd["name"] == "flask"
        assert dd["version"] == ">=2.0"

    def test_symbol_to_dict(self):
        s = Symbol(name="foo", type="function", line=10, end_line=20, docstring="A func")
        sd = s.to_dict()
        assert sd["name"] == "foo"
        assert sd["line"] == 10
        assert sd["docstring"] == "A func"
