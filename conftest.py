# Root-level conftest: skip legacy vLLM test files that require
# optional modules not installed in the standard CI environment.
collect_ignore = [
    "tests/test_vllm_autotune.py",
    "tests/test_issue_442_vllm_watchdog.py",
    "tests/test_issue_461_vllm_watchdog.py",
    "tests/test_confirmation_natural_language.py",
    "tests/test_elongated_confirmation.py",
    "tests/test_ttft_monitoring.py",
]
