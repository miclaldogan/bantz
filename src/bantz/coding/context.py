"""Project context understanding (Issue #4).

Features:
- Detect project type (python, node, rust, etc.)
- Parse dependencies (pyproject.toml, package.json, etc.)
- File tree generation
- Symbol extraction (functions, classes, variables)
- Import graph analysis
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class Symbol:
    """A code symbol (function, class, variable)."""
    name: str
    type: str  # function, class, variable, method, property
    line: int
    end_line: Optional[int] = None
    docstring: Optional[str] = None
    signature: Optional[str] = None
    parent: Optional[str] = None  # For methods: parent class name
    decorators: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "line": self.line,
            "end_line": self.end_line,
            "docstring": self.docstring,
            "signature": self.signature,
            "parent": self.parent,
            "decorators": self.decorators,
        }


@dataclass
class Dependency:
    """A project dependency."""
    name: str
    version: Optional[str] = None
    dev: bool = False
    source: str = ""  # pyproject.toml, package.json, etc.
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "dev": self.dev,
            "source": self.source,
        }


@dataclass
class ProjectInfo:
    """Project metadata."""
    root: str
    type: str  # python, node, rust, go, unknown
    name: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    dependencies: list[Dependency] = field(default_factory=list)
    dev_dependencies: list[Dependency] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "type": self.type,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "dependencies": [d.to_dict() for d in self.dependencies],
            "dev_dependencies": [d.to_dict() for d in self.dev_dependencies],
            "entry_points": self.entry_points,
        }


class ProjectContext:
    """Understand project structure and dependencies.
    
    Features:
    - Detect project type from config files
    - Parse dependency files
    - Generate file tree
    - Extract symbols from code files
    - Find related files (imports, tests)
    """
    
    # Project type detection files
    PROJECT_MARKERS = {
        "python": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile"],
        "node": ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
        "rust": ["Cargo.toml", "Cargo.lock"],
        "go": ["go.mod", "go.sum"],
        "ruby": ["Gemfile", "Gemfile.lock", "*.gemspec"],
        "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "dotnet": ["*.csproj", "*.fsproj", "*.sln"],
        "php": ["composer.json", "composer.lock"],
    }
    
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self._cache: dict[str, Any] = {}
    
    def detect_project_type(self) -> str:
        """Detect the primary project type.
        
        Returns:
            Project type string (python, node, rust, etc.)
        """
        if "project_type" in self._cache:
            return self._cache["project_type"]
        
        scores: dict[str, int] = {}
        
        for proj_type, markers in self.PROJECT_MARKERS.items():
            score = 0
            for marker in markers:
                if "*" in marker:
                    # Glob pattern
                    if list(self.root.glob(marker)):
                        score += 1
                else:
                    # Exact file
                    if (self.root / marker).exists():
                        score += 2  # Direct match scores higher
            scores[proj_type] = score
        
        # Get highest scoring type
        if scores:
            best_type = max(scores, key=lambda k: scores[k])
            if scores[best_type] > 0:
                self._cache["project_type"] = best_type
                return best_type
        
        self._cache["project_type"] = "unknown"
        return "unknown"
    
    def get_project_info(self) -> ProjectInfo:
        """Get comprehensive project information.
        
        Returns:
            ProjectInfo with name, version, dependencies
        """
        if "project_info" in self._cache:
            return self._cache["project_info"]
        
        proj_type = self.detect_project_type()
        info = ProjectInfo(
            root=str(self.root),
            type=proj_type,
        )
        
        if proj_type == "python":
            self._parse_python_project(info)
        elif proj_type == "node":
            self._parse_node_project(info)
        elif proj_type == "rust":
            self._parse_rust_project(info)
        elif proj_type == "go":
            self._parse_go_project(info)
        
        self._cache["project_info"] = info
        return info
    
    def _parse_python_project(self, info: ProjectInfo) -> None:
        """Parse Python project files."""
        # Try pyproject.toml first
        pyproject = self.root / "pyproject.toml"
        if pyproject.exists():
            try:
                import tomllib
            except ImportError:
                try:
                    import tomli as tomllib  # type: ignore
                except ImportError:
                    tomllib = None
            
            if tomllib:
                try:
                    data = tomllib.loads(pyproject.read_text())
                    
                    # Poetry style
                    if "tool" in data and "poetry" in data["tool"]:
                        poetry = data["tool"]["poetry"]
                        info.name = poetry.get("name")
                        info.version = poetry.get("version")
                        info.description = poetry.get("description")
                        
                        for name, ver in poetry.get("dependencies", {}).items():
                            if name == "python":
                                continue
                            v = ver if isinstance(ver, str) else ver.get("version", "*")
                            info.dependencies.append(Dependency(name=name, version=v, source="pyproject.toml"))
                        
                        for name, ver in poetry.get("dev-dependencies", {}).items():
                            v = ver if isinstance(ver, str) else ver.get("version", "*")
                            info.dev_dependencies.append(Dependency(name=name, version=v, dev=True, source="pyproject.toml"))
                    
                    # PEP 621 style
                    elif "project" in data:
                        proj = data["project"]
                        info.name = proj.get("name")
                        info.version = proj.get("version")
                        info.description = proj.get("description")
                        
                        for dep in proj.get("dependencies", []):
                            # Parse "package>=1.0" style
                            match = re.match(r"([a-zA-Z0-9_-]+)(.+)?", dep)
                            if match:
                                info.dependencies.append(Dependency(
                                    name=match.group(1),
                                    version=match.group(2) or "*",
                                    source="pyproject.toml",
                                ))
                except Exception:
                    pass
        
        # Fallback to requirements.txt
        req_file = self.root / "requirements.txt"
        if req_file.exists() and not info.dependencies:
            try:
                for line in req_file.read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        match = re.match(r"([a-zA-Z0-9_-]+)(.+)?", line)
                        if match:
                            info.dependencies.append(Dependency(
                                name=match.group(1),
                                version=match.group(2) or "*",
                                source="requirements.txt",
                            ))
            except Exception:
                pass
    
    def _parse_node_project(self, info: ProjectInfo) -> None:
        """Parse Node.js project files."""
        pkg_json = self.root / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text())
                info.name = data.get("name")
                info.version = data.get("version")
                info.description = data.get("description")
                
                for name, ver in data.get("dependencies", {}).items():
                    info.dependencies.append(Dependency(name=name, version=ver, source="package.json"))
                
                for name, ver in data.get("devDependencies", {}).items():
                    info.dev_dependencies.append(Dependency(name=name, version=ver, dev=True, source="package.json"))
                
                # Entry points
                if "main" in data:
                    info.entry_points.append(data["main"])
                if "bin" in data:
                    if isinstance(data["bin"], str):
                        info.entry_points.append(data["bin"])
                    elif isinstance(data["bin"], dict):
                        info.entry_points.extend(data["bin"].values())
            except Exception:
                pass
    
    def _parse_rust_project(self, info: ProjectInfo) -> None:
        """Parse Rust project files."""
        cargo_toml = self.root / "Cargo.toml"
        if cargo_toml.exists():
            try:
                import tomllib
            except ImportError:
                try:
                    import tomli as tomllib  # type: ignore
                except ImportError:
                    tomllib = None
            
            if tomllib:
                try:
                    data = tomllib.loads(cargo_toml.read_text())
                    
                    if "package" in data:
                        pkg = data["package"]
                        info.name = pkg.get("name")
                        info.version = pkg.get("version")
                        info.description = pkg.get("description")
                    
                    for name, ver in data.get("dependencies", {}).items():
                        v = ver if isinstance(ver, str) else ver.get("version", "*")
                        info.dependencies.append(Dependency(name=name, version=v, source="Cargo.toml"))
                    
                    for name, ver in data.get("dev-dependencies", {}).items():
                        v = ver if isinstance(ver, str) else ver.get("version", "*")
                        info.dev_dependencies.append(Dependency(name=name, version=v, dev=True, source="Cargo.toml"))
                except Exception:
                    pass
    
    def _parse_go_project(self, info: ProjectInfo) -> None:
        """Parse Go project files."""
        go_mod = self.root / "go.mod"
        if go_mod.exists():
            try:
                content = go_mod.read_text()
                
                # Parse module name
                match = re.search(r"^module\s+(.+)$", content, re.MULTILINE)
                if match:
                    info.name = match.group(1).strip()
                
                # Parse Go version
                match = re.search(r"^go\s+(\d+\.\d+)$", content, re.MULTILINE)
                if match:
                    info.version = match.group(1)
                
                # Parse require block
                require_match = re.search(r"require\s+\((.*?)\)", content, re.DOTALL)
                if require_match:
                    for line in require_match.group(1).splitlines():
                        line = line.strip()
                        if line and not line.startswith("//"):
                            parts = line.split()
                            if len(parts) >= 2:
                                info.dependencies.append(Dependency(
                                    name=parts[0],
                                    version=parts[1],
                                    source="go.mod",
                                ))
            except Exception:
                pass
    
    def get_dependencies(self) -> list[Dependency]:
        """Get all project dependencies.
        
        Returns:
            List of Dependency objects
        """
        info = self.get_project_info()
        return info.dependencies + info.dev_dependencies
    
    def get_file_tree(
        self,
        max_depth: int = 3,
        *,
        include_hidden: bool = False,
        extensions: Optional[list[str]] = None,
    ) -> dict:
        """Get project file tree as a nested dict.
        
        Args:
            max_depth: Maximum directory depth
            include_hidden: Include dotfiles/dotdirs
            extensions: Filter by extensions (None for all)
            
        Returns:
            Nested dict representing file tree
        """
        def build_tree(path: Path, depth: int) -> dict:
            result: dict = {"name": path.name, "type": "directory", "children": []}
            
            if depth > max_depth:
                result["truncated"] = True
                return result
            
            try:
                entries = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except PermissionError:
                result["error"] = "permission_denied"
                return result
            
            for entry in entries:
                # Skip hidden
                if entry.name.startswith(".") and not include_hidden:
                    continue
                
                # Skip common non-essential dirs
                if entry.name in {"node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build", ".bantz_backups"}:
                    continue
                
                if entry.is_dir():
                    result["children"].append(build_tree(entry, depth + 1))
                elif entry.is_file():
                    # Extension filter
                    if extensions and entry.suffix.lower() not in extensions:
                        continue
                    
                    result["children"].append({
                        "name": entry.name,
                        "type": "file",
                        "extension": entry.suffix,
                        "size": entry.stat().st_size,
                    })
            
            return result
        
        return build_tree(self.root, 0)
    
    def find_related_files(self, file_path: str) -> list[str]:
        """Find files related to a given file.
        
        Finds:
        - Test files
        - Imported modules (for Python)
        - Files importing this file
        
        Args:
            file_path: Path to file
            
        Returns:
            List of related file paths
        """
        p = Path(file_path)
        if not p.is_absolute():
            p = self.root / p
        p = p.resolve()
        
        if not p.exists():
            return []
        
        related = set()
        name = p.stem
        ext = p.suffix.lower()
        
        # Find test files
        test_patterns = [
            f"test_{name}{ext}",
            f"{name}_test{ext}",
            f"tests/test_{name}{ext}",
            f"tests/{name}_test{ext}",
            f"test/test_{name}{ext}",
            f"__tests__/{name}.test{ext}",
            f"{name}.spec{ext}",
        ]
        
        for pattern in test_patterns:
            test_path = self.root / pattern
            if test_path.exists():
                related.add(str(test_path.relative_to(self.root)))
        
        # For Python: find imports
        if ext == ".py":
            try:
                content = p.read_text()
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            # Try to find local module
                            mod_path = self.root / alias.name.replace(".", "/")
                            if mod_path.with_suffix(".py").exists():
                                related.add(str(mod_path.with_suffix(".py").relative_to(self.root)))
                            elif (mod_path / "__init__.py").exists():
                                related.add(str((mod_path / "__init__.py").relative_to(self.root)))
                    
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            mod_path = self.root / node.module.replace(".", "/")
                            if mod_path.with_suffix(".py").exists():
                                related.add(str(mod_path.with_suffix(".py").relative_to(self.root)))
            except Exception:
                pass
        
        return sorted(related)
    
    def get_symbols(self, file_path: str) -> list[Symbol]:
        """Extract symbols (functions, classes) from a file.
        
        Args:
            file_path: Path to file
            
        Returns:
            List of Symbol objects
        """
        p = Path(file_path)
        if not p.is_absolute():
            p = self.root / p
        p = p.resolve()
        
        if not p.exists():
            return []
        
        ext = p.suffix.lower()
        
        if ext == ".py":
            return self._get_python_symbols(p)
        elif ext in {".js", ".jsx", ".ts", ".tsx"}:
            return self._get_js_symbols(p)
        else:
            return []
    
    def _get_python_symbols(self, file_path: Path) -> list[Symbol]:
        """Extract symbols from Python file using AST."""
        try:
            content = file_path.read_text()
            tree = ast.parse(content)
        except Exception:
            return []
        
        symbols = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                decorators = [
                    self._get_decorator_name(d) for d in node.decorator_list
                ]
                
                # Get signature
                args = []
                for arg in node.args.args:
                    arg_str = arg.arg
                    if arg.annotation:
                        arg_str += f": {ast.unparse(arg.annotation)}"
                    args.append(arg_str)
                
                returns = ""
                if node.returns:
                    returns = f" -> {ast.unparse(node.returns)}"
                
                signature = f"def {node.name}({', '.join(args)}){returns}"
                
                # Get docstring
                docstring = ast.get_docstring(node)
                
                symbols.append(Symbol(
                    name=node.name,
                    type="function",
                    line=node.lineno,
                    end_line=node.end_lineno,
                    docstring=docstring,
                    signature=signature,
                    decorators=decorators,
                ))
            
            elif isinstance(node, ast.AsyncFunctionDef):
                decorators = [
                    self._get_decorator_name(d) for d in node.decorator_list
                ]
                
                docstring = ast.get_docstring(node)
                
                symbols.append(Symbol(
                    name=node.name,
                    type="function",
                    line=node.lineno,
                    end_line=node.end_lineno,
                    docstring=docstring,
                    signature=f"async def {node.name}(...)",
                    decorators=decorators,
                ))
            
            elif isinstance(node, ast.ClassDef):
                decorators = [
                    self._get_decorator_name(d) for d in node.decorator_list
                ]
                
                # Get base classes
                bases = [ast.unparse(b) for b in node.bases]
                signature = f"class {node.name}" + (f"({', '.join(bases)})" if bases else "")
                
                docstring = ast.get_docstring(node)
                
                symbols.append(Symbol(
                    name=node.name,
                    type="class",
                    line=node.lineno,
                    end_line=node.end_lineno,
                    docstring=docstring,
                    signature=signature,
                    decorators=decorators,
                ))
                
                # Get methods
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_decorators = [
                            self._get_decorator_name(d) for d in item.decorator_list
                        ]
                        
                        method_type = "method"
                        if "@property" in method_decorators:
                            method_type = "property"
                        elif "@classmethod" in method_decorators:
                            method_type = "classmethod"
                        elif "@staticmethod" in method_decorators:
                            method_type = "staticmethod"
                        
                        symbols.append(Symbol(
                            name=item.name,
                            type=method_type,
                            line=item.lineno,
                            end_line=item.end_lineno,
                            parent=node.name,
                            decorators=method_decorators,
                        ))
        
        return symbols
    
    def _get_js_symbols(self, file_path: Path) -> list[Symbol]:
        """Extract symbols from JavaScript/TypeScript file using regex.
        
        Note: This is a simple regex-based extraction, not a full parser.
        """
        try:
            content = file_path.read_text()
        except Exception:
            return []
        
        symbols = []
        lines = content.splitlines()
        
        # Function patterns
        func_patterns = [
            # function name(...) or async function name(...)
            re.compile(r"^(\s*)(export\s+)?(async\s+)?function\s+(\w+)\s*\("),
            # const/let/var name = function(...) or = (...)
            re.compile(r"^(\s*)(export\s+)?(const|let|var)\s+(\w+)\s*=\s*(async\s+)?(?:function|\()"),
            # Arrow function: const name = async? (...) =>
            re.compile(r"^(\s*)(export\s+)?(const|let|var)\s+(\w+)\s*=\s*(async\s+)?\([^)]*\)\s*=>"),
        ]
        
        # Class pattern
        class_pattern = re.compile(r"^(\s*)(export\s+)?(default\s+)?class\s+(\w+)")
        
        for i, line in enumerate(lines, 1):
            # Check for functions
            for pattern in func_patterns:
                match = pattern.match(line)
                if match:
                    groups = match.groups()
                    name = groups[3] if len(groups) > 3 else groups[-1]
                    symbols.append(Symbol(
                        name=name,
                        type="function",
                        line=i,
                    ))
                    break
            
            # Check for classes
            match = class_pattern.match(line)
            if match:
                name = match.group(4)
                symbols.append(Symbol(
                    name=name,
                    type="class",
                    line=i,
                ))
        
        return symbols
    
    def _get_decorator_name(self, node: ast.expr) -> str:
        """Get decorator name from AST node."""
        if isinstance(node, ast.Name):
            return f"@{node.id}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                return f"@{node.func.id}"
            elif isinstance(node.func, ast.Attribute):
                return f"@{ast.unparse(node.func)}"
        elif isinstance(node, ast.Attribute):
            return f"@{ast.unparse(node)}"
        return "@?"
    
    def get_imports(self, file_path: str) -> list[str]:
        """Get list of imports from a file.
        
        Args:
            file_path: Path to file
            
        Returns:
            List of imported module names
        """
        p = Path(file_path)
        if not p.is_absolute():
            p = self.root / p
        
        if not p.exists() or p.suffix.lower() != ".py":
            return []
        
        try:
            content = p.read_text()
            tree = ast.parse(content)
        except Exception:
            return []
        
        imports = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        
        return sorted(set(imports))
    
    def search_symbol(
        self,
        name: str,
        *,
        symbol_type: Optional[str] = None,
        max_results: int = 20,
    ) -> list[dict]:
        """Search for a symbol across the project.
        
        Args:
            name: Symbol name (partial match)
            symbol_type: Filter by type (function, class, etc.)
            max_results: Maximum results
            
        Returns:
            List of matches with file and symbol info
        """
        proj_type = self.detect_project_type()
        
        # Determine extensions to search
        if proj_type == "python":
            extensions = [".py"]
        elif proj_type == "node":
            extensions = [".js", ".jsx", ".ts", ".tsx"]
        else:
            extensions = [".py", ".js", ".ts"]
        
        results = []
        name_lower = name.lower()
        
        for ext in extensions:
            for file_path in self.root.rglob(f"*{ext}"):
                if len(results) >= max_results:
                    break
                
                # Skip hidden/vendor
                rel_parts = file_path.relative_to(self.root).parts
                if any(p.startswith(".") or p in {"node_modules", "__pycache__", "venv"} for p in rel_parts):
                    continue
                
                try:
                    symbols = self.get_symbols(str(file_path))
                    for sym in symbols:
                        if name_lower in sym.name.lower():
                            if symbol_type and sym.type != symbol_type:
                                continue
                            
                            results.append({
                                "file": str(file_path.relative_to(self.root)),
                                **sym.to_dict(),
                            })
                            
                            if len(results) >= max_results:
                                break
                except Exception:
                    pass
        
        return results
    
    def clear_cache(self) -> None:
        """Clear the context cache."""
        self._cache.clear()
