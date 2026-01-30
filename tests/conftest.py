from __future__ import annotations

import asyncio

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
