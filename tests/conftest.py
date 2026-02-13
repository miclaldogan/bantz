from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _ensure_event_loop_for_sync_tests():
    """Ensure asyncio.get_event_loop() works in sync tests.

    Some synchronous tests call `asyncio.get_event_loop().run_until_complete(...)`.
    With pytest + pytest-asyncio, the default loop may be cleared between tests.
    We create a loop when missing and clean it up after the test.
    """

    created_loop: asyncio.AbstractEventLoop | None = None
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        created_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(created_loop)

    yield

    if created_loop is not None:
        if not created_loop.is_closed():
            created_loop.close()
        # Prevent returning a closed loop in later tests
        asyncio.set_event_loop(None)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run tests marked with @pytest.mark.integration or @pytest.mark.vllm.",
    )
    parser.addoption(
        "--run-regression",
        action="store_true",
        default=False,
        help="Run tests marked with @pytest.mark.regression.",
    )
    parser.addoption(
        "--run-benchmark",
        action="store_true",
        default=False,
        help="Run tests marked with @pytest.mark.benchmark.",
    )
    parser.addoption(
        "--run-golden-path",
        action="store_true",
        default=False,
        help="Run golden path E2E tests (Issue #1226). Must pass for merge.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_integration = bool(config.getoption("--run-integration"))
    run_regression = bool(config.getoption("--run-regression"))
    run_benchmark = bool(config.getoption("--run-benchmark"))
    run_golden_path = bool(config.getoption("--run-golden-path"))

    deselected: list[pytest.Item] = []
    selected: list[pytest.Item] = []

    for item in items:
        if not run_integration and (item.get_closest_marker("integration") or item.get_closest_marker("vllm")):
            deselected.append(item)
            continue
        if not run_regression and item.get_closest_marker("regression"):
            deselected.append(item)
            continue
        if not run_benchmark and item.get_closest_marker("benchmark"):
            deselected.append(item)
            continue
        if not run_golden_path and item.get_closest_marker("golden_path"):
            deselected.append(item)
            continue
        selected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


class _OpenAIMockHandler(BaseHTTPRequestHandler):
    server_version = "bantz-vllm-mock/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        # Keep pytest output clean.
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/v1/models":
            model_name = getattr(self.server, "model_name", "Qwen/Qwen2.5-3B-Instruct")
            self._send_json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": model_name,
                            "object": "model",
                            "created": int(time.time()),
                            "owned_by": "mock-vllm",
                        }
                    ],
                },
            )
            return

        self._send_json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._send_json(404, {"error": {"message": "not found"}})
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"

        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": {"message": "invalid json"}})
            return

        model_name = getattr(self.server, "model_name", "Qwen/Qwen2.5-3B-Instruct")
        requested_model = str(req.get("model") or "").strip()
        if requested_model and requested_model != model_name:
            self._send_json(
                404,
                {
                    "error": {
                        "message": "model not found: 404",
                        "type": "invalid_request_error",
                        "code": "model_not_found",
                    }
                },
            )
            return

        messages = req.get("messages") or []
        response_format = req.get("response_format") or {}

        # Extract last user message content
        last_user = ""
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                last_user = str(msg.get("content") or "")
                break

        if isinstance(response_format, dict) and response_format.get("type") == "json_object":
            content = json.dumps(
                {"route": "smalltalk", "confidence": 1.0, "reply": "ok"},
                ensure_ascii=False,
            )
        elif "count from 1 to 5" in last_user.lower():
            content = "1 2 3 4 5"
        elif "capital of france" in last_user.lower():
            content = "Paris"
        elif last_user.strip():
            content = f"Mock response: {last_user.strip()}"
        else:
            content = "Mock response"

        self._send_json(
            200,
            {
                "id": f"chatcmpl-mock-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )


@pytest.fixture(scope="session")
def vllm_mock_server_url() -> str:
    """Start a tiny OpenAI-compatible mock server for vLLM integration tests."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAIMockHandler)
    server.model_name = "Qwen/Qwen2.5-3B-Instruct"  # type: ignore[attr-defined]

    host, port = server.server_address
    url = f"http://{host}:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # Basic readiness check
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    else:
        server.shutdown()
        raise RuntimeError("Failed to start vLLM mock server")

    yield url

    server.shutdown()
    server.server_close()
