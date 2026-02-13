"""E2E test suite — conftest (fixtures only).

Imports from e2e_framework.py and provides pytest fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure e2e dir is importable
_e2e_dir = Path(__file__).resolve().parent
if str(_e2e_dir) not in sys.path:
    sys.path.insert(0, str(_e2e_dir))

from e2e_framework import (  # noqa: E402
    E2ETestRunner,
    MockLLMProvider,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
MOCK_RESPONSES_PATH = str(FIXTURES_DIR / "mock_llm_responses.json")


@pytest.fixture
def mock_llm():
    """MockLLMProvider loaded with golden responses."""
    return MockLLMProvider(MOCK_RESPONSES_PATH)


@pytest.fixture
def e2e_runner(tmp_path):
    """E2ETestRunner with mock LLM and tmp report path."""
    report_path = str(tmp_path / "e2e_report.json")
    runner = E2ETestRunner(
        mock_responses_path=MOCK_RESPONSES_PATH,
        report_path=report_path,
    )
    runner.setup()
    yield runner
    runner.teardown()
