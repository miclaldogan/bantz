"""OpenCode Coding Skill — kod yazma, düzenleme, proje oluşturma (Issue #846).

Kullanıcı "kod yaz", "script oluştur", "bu kodu incele" gibi
komutlar verdiğinde çalışan entegre coding skill.

Özellikler
──────────
- Kod yazma / düzenleme (CodingToolExecutor üzerinden)
- Proje scaffold: Python / Node.js / HTML şablonları
- Kod inceleme: ast analiz + öneriler
- Sandbox çalıştırma: güvenli subprocess ile kod çalıştırma
- Intent tanıma: coding.* intent pattern'leri
"""

from __future__ import annotations

import ast
import logging
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

_ALLOWED_DIRS: list[Path] = [
    Path.home() / "Projeler",
    Path.home() / "Projects",
    Path.home() / "Desktop",
    Path.home() / "Masaüstü",
    Path.home() / "Documents",
    Path.home() / "Belgeler",
    Path.home() / "code",
]

_SANDBOX_TIMEOUT = 30  # seconds
_MAX_OUTPUT_CHARS = 10_000

# ── Intent patterns (Turkish + English) ──────────────────────────────

CODING_INTENTS = [
    r"(?i)\b(kod|code)\s*(yaz|oluştur|üret|generate|write|create)\b",
    r"(?i)\b(script|betik)\s*(yaz|oluştur|create)\b",
    r"(?i)\b(proje|project)\s*(oluştur|kur|create|scaffold|init)\b",
    r"(?i)\b(bu\s*kod|this\s*code)\w*\s*(incele|review|analiz|analyze)\b",
    r"(?i)\b(dosya|file)\s*(oluştur|yaz|create|write)\b",
    r"(?i)\b(fonksiyon|function|sınıf|class)\s*(yaz|oluştur|ekle)\b",
    r"(?i)\bcoding\.",
]


def is_coding_intent(text: str) -> bool:
    """Check whether *text* looks like a coding request."""
    return any(re.search(p, text) for p in CODING_INTENTS)


# ── Security helpers ─────────────────────────────────────────────────

def _is_allowed_path(path: Path) -> bool:
    """Return True if *path* is under an allowed directory."""
    resolved = path.resolve()
    for allowed in _ALLOWED_DIRS:
        try:
            if resolved == allowed.resolve() or allowed.resolve() in resolved.parents:
                return True
        except (OSError, ValueError):
            continue
    return False


def _sanitize_code(code: str) -> str | None:
    """Basic safety lint — returns warning message or None if OK."""
    dangerous = [
        (r"\bos\.system\b", "os.system kullanımı yasak — subprocess tercih edin"),
        (r"\beval\s*\(", "eval() kullanımı yasak"),
        (r"\bexec\s*\(", "exec() kullanımı yasak"),
        (r"\b__import__\s*\(", "__import__ kullanımı yasak"),
        (r"\bshutil\.rmtree\b", "shutil.rmtree tehlikeli — onay gerekli"),
        (r"rm\s+-rf", "rm -rf komutu engellendi"),
    ]
    for pattern, msg in dangerous:
        if re.search(pattern, code):
            return msg
    return None


# ── Project scaffolding ──────────────────────────────────────────────

@dataclass
class ProjectTemplate:
    """A project scaffold template."""
    name: str
    description: str
    language: str
    files: Dict[str, str] = field(default_factory=dict)


_TEMPLATES: Dict[str, ProjectTemplate] = {
    "python": ProjectTemplate(
        name="python",
        description="Python projesi (src layout + pyproject.toml)",
        language="python",
        files={
            "pyproject.toml": textwrap.dedent("""\
                [build-system]
                requires = ["setuptools>=68.0"]
                build-backend = "setuptools.backends._legacy:_Backend"

                [project]
                name = "{project_name}"
                version = "0.1.0"
                requires-python = ">=3.10"
                """),
            "src/{project_name}/__init__.py": '"""Top-level package."""\n',
            "src/{project_name}/main.py": textwrap.dedent("""\
                \"\"\"Main entry point.\"\"\"

                def main() -> None:
                    print("Merhaba, dünya!")

                if __name__ == "__main__":
                    main()
                """),
            "tests/__init__.py": "",
            "tests/test_main.py": textwrap.dedent("""\
                from {project_name}.main import main

                def test_main(capsys):
                    main()
                    assert "Merhaba" in capsys.readouterr().out
                """),
            "README.md": "# {project_name}\n\nYeni proje.\n",
            ".gitignore": "__pycache__/\n*.pyc\n.venv/\ndist/\n*.egg-info/\n",
        },
    ),
    "node": ProjectTemplate(
        name="node",
        description="Node.js projesi (ESM + package.json)",
        language="javascript",
        files={
            "package.json": textwrap.dedent("""\
                {{
                  "name": "{project_name}",
                  "version": "0.1.0",
                  "type": "module",
                  "main": "src/index.js",
                  "scripts": {{
                    "start": "node src/index.js",
                    "test": "node --test tests/"
                  }}
                }}
                """),
            "src/index.js": 'console.log("Merhaba, dünya!");\n',
            "tests/index.test.js": textwrap.dedent("""\
                import {{ describe, it }} from "node:test";
                import assert from "node:assert/strict";

                describe("{project_name}", () => {{
                  it("should work", () => {{
                    assert.ok(true);
                  }});
                }});
                """),
            "README.md": "# {project_name}\n\nYeni Node.js projesi.\n",
            ".gitignore": "node_modules/\ndist/\n",
        },
    ),
    "html": ProjectTemplate(
        name="html",
        description="Statik HTML web sayfası",
        language="html",
        files={
            "index.html": textwrap.dedent("""\
                <!DOCTYPE html>
                <html lang="tr">
                <head>
                  <meta charset="UTF-8">
                  <meta name="viewport" content="width=device-width,initial-scale=1">
                  <title>{project_name}</title>
                  <link rel="stylesheet" href="style.css">
                </head>
                <body>
                  <h1>{project_name}</h1>
                  <script src="app.js"></script>
                </body>
                </html>
                """),
            "style.css": "body { font-family: sans-serif; margin: 2rem; }\n",
            "app.js": 'console.log("{project_name} loaded");\n',
        },
    ),
}


def scaffold_project(
    project_name: str,
    template: str = "python",
    target_dir: str | Path | None = None,
) -> Dict[str, Any]:
    """Create a project from template.

    Returns:
        {"ok": True, "path": ..., "files_created": [...]} on success.
    """
    tpl = _TEMPLATES.get(template)
    if tpl is None:
        return {"ok": False, "error": f"Bilinmeyen şablon: {template}. Seçenekler: {list(_TEMPLATES)}"}

    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", project_name).lower()

    if target_dir is None:
        target_dir = Path.home() / "Projeler" / safe_name
    else:
        target_dir = Path(target_dir) / safe_name

    if not _is_allowed_path(target_dir):
        return {"ok": False, "error": f"İzin verilmeyen dizin: {target_dir}"}

    if target_dir.exists():
        return {"ok": False, "error": f"Dizin zaten var: {target_dir}"}

    created: list[str] = []
    try:
        for rel_path, content in tpl.files.items():
            fpath = target_dir / rel_path.format(project_name=safe_name)
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content.format(project_name=safe_name), encoding="utf-8")
            created.append(str(fpath.relative_to(target_dir)))
    except Exception as e:
        return {"ok": False, "error": f"Proje oluşturma hatası: {e}"}

    logger.info(f"[CodingSkill] Scaffolded {template} project: {target_dir}")
    return {"ok": True, "path": str(target_dir), "files_created": created, "template": template}


# ── Code review ──────────────────────────────────────────────────────

@dataclass
class ReviewFinding:
    """A single code review finding."""
    line: int
    severity: str  # info | warning | error
    message: str


def review_python_code(code: str, filename: str = "<input>") -> Dict[str, Any]:
    """Static analysis of Python code — returns findings list."""
    findings: List[ReviewFinding] = []

    # Syntax check
    try:
        tree = ast.parse(code, filename=filename)
    except SyntaxError as e:
        return {
            "ok": False,
            "error": f"Söz dizimi hatası satır {e.lineno}: {e.msg}",
            "findings": [{"line": e.lineno or 0, "severity": "error", "message": e.msg}],
        }

    lines = code.splitlines()

    # Walk AST
    for node in ast.walk(tree):
        # Bare except
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            findings.append(ReviewFinding(
                line=node.lineno, severity="warning",
                message="Bare 'except:' — 'except Exception:' kullanın",
            ))

        # Too many arguments
        if isinstance(node, ast.FunctionDef) and len(node.args.args) > 7:
            findings.append(ReviewFinding(
                line=node.lineno, severity="warning",
                message=f"Fonksiyon '{node.name}' çok fazla parametre alıyor ({len(node.args.args)})",
            ))

        # Long function
        if isinstance(node, ast.FunctionDef):
            end_line = getattr(node, "end_lineno", node.lineno)
            if end_line - node.lineno > 50:
                findings.append(ReviewFinding(
                    line=node.lineno, severity="info",
                    message=f"Fonksiyon '{node.name}' çok uzun ({end_line - node.lineno} satır) — parçalamayı düşünün",
                ))

        # Global statement
        if isinstance(node, ast.Global):
            findings.append(ReviewFinding(
                line=node.lineno, severity="info",
                message="'global' kullanımı — kapsülleme tercih edilmeli",
            ))

        # Mutable default argument
        if isinstance(node, ast.FunctionDef):
            for default in node.args.defaults + node.args.kw_defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    findings.append(ReviewFinding(
                        line=node.lineno, severity="warning",
                        message=f"Fonksiyon '{node.name}' — mutable default argument tehlikeli",
                    ))

    # Line-level checks
    for i, line in enumerate(lines, 1):
        if len(line) > 120:
            findings.append(ReviewFinding(line=i, severity="info", message="Satır 120 karakterden uzun"))
        if "TODO" in line or "FIXME" in line or "HACK" in line:
            findings.append(ReviewFinding(line=i, severity="info", message=f"Marker bulundu: {line.strip()[:60]}"))

    return {
        "ok": True,
        "filename": filename,
        "findings": [{"line": f.line, "severity": f.severity, "message": f.message} for f in findings],
        "summary": {
            "total": len(findings),
            "errors": sum(1 for f in findings if f.severity == "error"),
            "warnings": sum(1 for f in findings if f.severity == "warning"),
            "info": sum(1 for f in findings if f.severity == "info"),
        },
    }


# ── Sandbox execution ────────────────────────────────────────────────

def run_code_sandbox(
    code: str,
    language: str = "python",
    timeout: int = _SANDBOX_TIMEOUT,
) -> Dict[str, Any]:
    """Execute code in a sandboxed subprocess.

    Safety:
    - Runs in a temp directory
    - Subprocess timeout enforced
    - Output truncated to _MAX_OUTPUT_CHARS
    - No network access hints (not enforced at OS level yet)
    """
    # Safety check
    warning = _sanitize_code(code)
    if warning:
        return {"ok": False, "error": f"Güvenlik uyarısı: {warning}", "blocked": True}

    interpreters = {
        "python": ["python3", "-u"],
        "node": ["node"],
        "javascript": ["node"],
        "bash": ["bash"],
        "sh": ["sh"],
    }

    cmd_prefix = interpreters.get(language)
    if cmd_prefix is None:
        return {"ok": False, "error": f"Desteklenmeyen dil: {language}. Desteklenen: {list(interpreters)}"}

    # Check interpreter exists
    if not shutil.which(cmd_prefix[0]):
        return {"ok": False, "error": f"Yorumlayıcı bulunamadı: {cmd_prefix[0]}"}

    with tempfile.TemporaryDirectory(prefix="bantz_sandbox_") as tmpdir:
        ext_map = {"python": ".py", "node": ".js", "javascript": ".js", "bash": ".sh", "sh": ".sh"}
        ext = ext_map.get(language, ".txt")
        script_path = Path(tmpdir) / f"script{ext}"
        script_path.write_text(code, encoding="utf-8")

        try:
            result = subprocess.run(
                cmd_prefix + [str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmpdir,
                env={**os.environ, "HOME": tmpdir, "TMPDIR": tmpdir},
            )
            stdout = result.stdout[:_MAX_OUTPUT_CHARS]
            stderr = result.stderr[:_MAX_OUTPUT_CHARS]

            return {
                "ok": result.returncode == 0,
                "exit_code": result.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "truncated": len(result.stdout) > _MAX_OUTPUT_CHARS or len(result.stderr) > _MAX_OUTPUT_CHARS,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Zaman aşımı ({timeout}s)", "timeout": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ── Tool registration ────────────────────────────────────────────────

def register_coding_skill_tools(registry: Any) -> None:
    """Register coding skill tools with ToolRegistry."""
    from bantz.agent.tools import Tool

    registry.register(Tool(
        name="coding.scaffold",
        description="Create a new project from a template (python/node/html).",
        parameters={
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "template": {"type": "string", "enum": ["python", "node", "html"], "description": "Template type"},
                "target_dir": {"type": "string", "description": "Target directory (optional)"},
            },
            "required": ["project_name"],
        },
        function=lambda **kw: scaffold_project(
            project_name=kw.get("project_name", ""),
            template=kw.get("template", "python"),
            target_dir=kw.get("target_dir"),
        ),
        risk_level="medium",
        requires_confirmation=True,
    ))

    registry.register(Tool(
        name="coding.review",
        description="Review Python code for issues (bare excepts, long functions, etc.).",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to review"},
                "filename": {"type": "string", "description": "Filename for context"},
            },
            "required": ["code"],
        },
        function=lambda **kw: review_python_code(
            code=kw.get("code", ""),
            filename=kw.get("filename", "<input>"),
        ),
    ))

    registry.register(Tool(
        name="coding.run",
        description="Execute code in a sandboxed environment.",
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code to execute"},
                "language": {"type": "string", "enum": ["python", "node", "bash"], "description": "Programming language"},
            },
            "required": ["code"],
        },
        function=lambda **kw: run_code_sandbox(
            code=kw.get("code", ""),
            language=kw.get("language", "python"),
        ),
        risk_level="high",
        requires_confirmation=True,
    ))

    logger.info("[CodingSkill] 3 coding skill tools registered")
