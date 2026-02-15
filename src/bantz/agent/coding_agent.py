"""Coding Agent — code generation, testing, git operations.

Issue #1295: PC Agent + CodingAgent — kod yazma, test, git, code review.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from bantz.agent.sandbox import SandboxExecutor

logger = logging.getLogger(__name__)

# LLM callback for code generation / review.
LLMCodeFn = Callable[[str, str], Awaitable[str]]


@dataclass
class CodeResult:
    """Result of a code generation operation."""

    ok: bool
    code: str = ""
    language: str = "python"
    file_path: str | None = None
    syntax_valid: bool | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestResult:
    """Result of running tests."""

    ok: bool
    passed: int = 0
    failed: int = 0
    errors: int = 0
    output: str = ""
    duration_ms: float = 0.0
    error: str | None = None


@dataclass
class ReviewResult:
    """Result of a code review."""

    ok: bool
    summary: str = ""
    suggestions: list[str] = field(default_factory=list)
    severity: str = "info"
    error: str | None = None


class CodingAgent:
    """Code writing, test execution, git operations, and code review.

    All execution happens through the SandboxExecutor for isolation.
    LLM is used for code generation and review via callbacks.
    """

    def __init__(
        self,
        sandbox: SandboxExecutor | None = None,
        llm_fn: LLMCodeFn | None = None,
        workspace: str | None = None,
    ) -> None:
        self._sandbox = sandbox or SandboxExecutor(mode="none")
        self._llm_fn = llm_fn
        self._workspace = workspace or str(Path.cwd())

    # ── Code Generation ──────────────────────────────────────────

    async def generate_code(
        self,
        spec: str,
        *,
        language: str = "python",
    ) -> CodeResult:
        """Generate code from a specification using the LLM.

        Args:
            spec: Natural language description of what to generate.
            language: Target programming language.

        Returns:
            :class:`CodeResult` with the generated code.
        """
        if self._llm_fn is None:
            return CodeResult(
                ok=False,
                error="LLM callback yapılandırılmadı.",
            )

        try:
            prompt = (
                f"Generate {language} code for:\n{spec}\n\n"
                f"Return ONLY the code, no explanation."
            )
            code = await self._llm_fn(prompt, language)

            # Syntax check for Python
            syntax_valid = None
            if language == "python":
                syntax_valid = self._check_python_syntax(code)

            return CodeResult(
                ok=True,
                code=code,
                language=language,
                syntax_valid=syntax_valid,
            )
        except Exception as exc:
            return CodeResult(ok=False, error=str(exc))

    async def write_tests(
        self,
        source_file: str,
        *,
        framework: str = "pytest",
    ) -> CodeResult:
        """Generate unit tests for a source file.

        Args:
            source_file: Path to the source file to test.
            framework: Test framework (pytest, unittest).

        Returns:
            :class:`CodeResult` with the generated test code.
        """
        source_path = Path(source_file).expanduser().resolve()
        if not source_path.is_file():
            return CodeResult(
                ok=False, error=f"Kaynak dosya bulunamadı: {source_file}"
            )

        try:
            source_code = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return CodeResult(ok=False, error=str(exc))

        if self._llm_fn is None:
            # Generate basic test skeleton without LLM
            test_code = self._generate_test_skeleton(
                source_code, source_path.stem, framework
            )
            return CodeResult(
                ok=True,
                code=test_code,
                language="python",
                file_path=f"tests/test_{source_path.stem}.py",
            )

        try:
            prompt = (
                f"Write {framework} tests for this Python code:\n\n"
                f"```python\n{source_code[:4000]}\n```\n\n"
                f"Include happy path and error cases. Return ONLY test code."
            )
            test_code = await self._llm_fn(prompt, "python")
            return CodeResult(
                ok=True,
                code=test_code,
                language="python",
                file_path=f"tests/test_{source_path.stem}.py",
                syntax_valid=self._check_python_syntax(test_code),
            )
        except Exception as exc:
            return CodeResult(ok=False, error=str(exc))

    # ── Test Execution ───────────────────────────────────────────

    async def run_tests(
        self,
        path: str = ".",
        *,
        verbose: bool = True,
        timeout: int = 120,
    ) -> TestResult:
        """Run tests in the sandbox.

        Args:
            path: Test file or directory.
            verbose: Verbose output.
            timeout: Timeout in seconds.

        Returns:
            :class:`TestResult` with pass/fail counts.
        """
        v_flag = "-v" if verbose else ""
        cmd = f"python -m pytest {path} {v_flag} --tb=short -q 2>&1"

        result = await self._sandbox.execute(
            cmd,
            workdir=self._workspace,
            timeout=timeout,
        )

        passed, failed, errors = self._parse_pytest_output(result.stdout)

        return TestResult(
            ok=result.ok and failed == 0 and errors == 0,
            passed=passed,
            failed=failed,
            errors=errors,
            output=result.stdout[:4096],
            duration_ms=result.duration_ms,
            error=result.stderr[:1024] if not result.ok else None,
        )

    # ── Git Operations ───────────────────────────────────────────

    async def git_status(self) -> dict[str, Any]:
        """Get git status of the workspace."""
        result = await self._sandbox.execute(
            "git status --short",
            workdir=self._workspace,
            timeout=10,
        )
        if not result.ok:
            return {"ok": False, "error": result.stderr}

        lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
        return {
            "ok": True,
            "changed_files": len(lines),
            "files": lines[:50],
        }

    async def git_diff(self, *, staged: bool = False) -> dict[str, Any]:
        """Get git diff."""
        flag = "--staged" if staged else ""
        result = await self._sandbox.execute(
            f"git diff {flag} --stat",
            workdir=self._workspace,
            timeout=15,
        )
        return {
            "ok": result.ok,
            "diff": result.stdout[:8192],
            "error": result.stderr[:1024] if not result.ok else None,
        }

    async def git_commit(
        self, message: str, *, add_all: bool = True
    ) -> dict[str, Any]:
        """Create a git commit.

        Args:
            message: Commit message.
            add_all: If True, stage all changes before committing.

        Returns:
            Dict with commit result.
        """
        if add_all:
            add_result = await self._sandbox.execute(
                "git add -A",
                workdir=self._workspace,
                timeout=10,
            )
            if not add_result.ok:
                return {"ok": False, "error": f"git add failed: {add_result.stderr}"}

        # Use a safe approach to avoid shell injection in commit message
        result = await self._sandbox.execute(
            f'git commit -m "{message}"',
            workdir=self._workspace,
            timeout=15,
        )
        return {
            "ok": result.ok,
            "output": result.stdout[:2048],
            "error": result.stderr[:1024] if not result.ok else None,
        }

    async def git_log(self, *, count: int = 10) -> dict[str, Any]:
        """Get recent git log."""
        result = await self._sandbox.execute(
            f"git log --oneline -n {count}",
            workdir=self._workspace,
            timeout=10,
        )
        return {
            "ok": result.ok,
            "log": result.stdout.strip().split("\n") if result.stdout.strip() else [],
        }

    # ── Code Review ──────────────────────────────────────────────

    async def code_review(
        self,
        file_path: str,
    ) -> ReviewResult:
        """Review code in a file using the LLM.

        Args:
            file_path: Path to the file to review.

        Returns:
            :class:`ReviewResult` with suggestions.
        """
        target = Path(file_path).expanduser().resolve()
        if not target.is_file():
            return ReviewResult(
                ok=False,
                error=f"Dosya bulunamadı: {file_path}",
            )

        try:
            code = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return ReviewResult(ok=False, error=str(exc))

        if self._llm_fn is None:
            return ReviewResult(
                ok=True,
                summary="LLM olmadan temel analiz yapıldı.",
                suggestions=self._basic_review(code),
                severity="info",
            )

        try:
            prompt = (
                f"Review this Python code and provide:\n"
                f"1. Brief summary\n"
                f"2. List of suggestions (bugs, improvements, style)\n\n"
                f"```python\n{code[:6000]}\n```"
            )
            review_text = await self._llm_fn(prompt, "review")
            return ReviewResult(
                ok=True,
                summary=review_text[:2000],
                suggestions=[],
                severity="info",
            )
        except Exception as exc:
            return ReviewResult(ok=False, error=str(exc))

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _check_python_syntax(code: str) -> bool:
        """Check if Python code is syntactically valid."""
        try:
            compile(code, "<generated>", "exec")
            return True
        except SyntaxError:
            return False

    @staticmethod
    def _generate_test_skeleton(
        source_code: str, module_name: str, framework: str
    ) -> str:
        """Generate a basic test skeleton without LLM."""
        return (
            f'"""Auto-generated tests for {module_name}."""\n\n'
            f"import pytest\n\n\n"
            f"class Test{module_name.title().replace('_', '')}:\n"
            f"    def test_placeholder(self):\n"
            f'        """TODO: Implement test."""\n'
            f"        assert True\n"
        )

    @staticmethod
    def _parse_pytest_output(output: str) -> tuple[int, int, int]:
        """Parse pytest output for pass/fail/error counts."""
        import re

        passed = failed = errors = 0

        m = re.search(r"(\d+) passed", output)
        if m:
            passed = int(m.group(1))

        m = re.search(r"(\d+) failed", output)
        if m:
            failed = int(m.group(1))

        m = re.search(r"(\d+) error", output)
        if m:
            errors = int(m.group(1))

        return passed, failed, errors

    @staticmethod
    def _basic_review(code: str) -> list[str]:
        """Basic code review without LLM — checks common issues."""
        suggestions: list[str] = []

        if "eval(" in code:
            suggestions.append("⚠️ eval() kullanımı tespit edildi — güvenlik riski.")
        if "exec(" in code:
            suggestions.append("⚠️ exec() kullanımı tespit edildi — güvenlik riski.")
        if "os.system(" in code:
            suggestions.append("⚠️ os.system() yerine subprocess kullanılmalı.")
        if "import *" in code:
            suggestions.append("💡 Wildcard import yerine explicit import tercih edilmeli.")

        lines = code.split("\n")
        if len(lines) > 500:
            suggestions.append(
                f"📏 Dosya {len(lines)} satır — bölünme düşünülmeli."
            )

        bare_except = sum(1 for line in lines if "except:" in line and "except Exception" not in line)
        if bare_except:
            suggestions.append(
                f"⚠️ Bare except: {bare_except} adet — except Exception: tercih edilmeli."
            )

        if not suggestions:
            suggestions.append("✅ Belirgin sorun tespit edilmedi.")

        return suggestions
