"""Tests for Issue #415: Thread safety for DialogSummaryManager.

Tests cover:
  - Lock existence and type
  - Concurrent add_turn from multiple threads
  - Concurrent add_turn + to_prompt_block reads
  - Concurrent add_turn + clear
  - Concurrent add_turn + get_latest
  - No data corruption under stress
  - Backward compatibility (single-thread still works)
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pytest

from bantz.brain.memory_lite import CompactSummary, DialogSummaryManager


# ======================================================================
# Helpers
# ======================================================================


def _make_summary(turn: int, intent: str = "test", action: str = "tested") -> CompactSummary:
    return CompactSummary(
        turn_number=turn,
        user_intent=intent,
        action_taken=action,
        timestamp=datetime(2025, 1, 15, 10, 0, 0),
    )


# ======================================================================
# Lock Tests
# ======================================================================


class TestLockExists:
    def test_has_lock(self):
        m = DialogSummaryManager()
        assert hasattr(m, "_lock")
        assert isinstance(m._lock, type(threading.Lock()))

    def test_lock_is_per_instance(self):
        m1 = DialogSummaryManager()
        m2 = DialogSummaryManager()
        assert m1._lock is not m2._lock


# ======================================================================
# Concurrent add_turn Tests
# ======================================================================


class TestConcurrentAddTurn:
    def test_many_threads_add_turn(self):
        """100 threads adding turns concurrently — no crash, no corruption."""
        m = DialogSummaryManager(max_tokens=10000, max_turns=200)
        errors: list[str] = []

        def worker(turn_id: int):
            try:
                m.add_turn(_make_summary(turn_id, f"intent-{turn_id}", f"action-{turn_id}"))
            except Exception as e:
                errors.append(f"Thread {turn_id}: {e}")

        threads = []
        for i in range(100):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Errors: {errors}"
        # All 100 turns should be present (max_turns=200)
        assert len(m) == 100

    def test_concurrent_add_with_eviction(self):
        """Concurrent adds with max_turns=5 — should not exceed limit."""
        m = DialogSummaryManager(max_tokens=10000, max_turns=5)

        def worker(turn_id: int):
            m.add_turn(_make_summary(turn_id))

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(worker, i) for i in range(50)]
            for f in as_completed(futures):
                f.result()  # Raise if any exception

        assert len(m) <= 5

    def test_concurrent_add_no_duplicate_turns(self):
        """Each turn should appear at most once in the summary list."""
        m = DialogSummaryManager(max_tokens=10000, max_turns=1000)

        def worker(turn_id: int):
            m.add_turn(_make_summary(turn_id, f"unique-{turn_id}"))

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i) for i in range(50)]
            for f in as_completed(futures):
                f.result()

        intents = [s.user_intent for s in m.summaries]
        # Each intent should be unique
        assert len(intents) == len(set(intents))


# ======================================================================
# Concurrent Read + Write Tests
# ======================================================================


class TestConcurrentReadWrite:
    def test_add_and_prompt_block_concurrent(self):
        """Read to_prompt_block while another thread is adding turns."""
        m = DialogSummaryManager(max_tokens=10000, max_turns=100)
        errors: list[str] = []
        stop = threading.Event()

        def writer():
            for i in range(50):
                try:
                    m.add_turn(_make_summary(i, f"w-{i}"))
                except Exception as e:
                    errors.append(f"Writer: {e}")
            stop.set()

        def reader():
            while not stop.is_set():
                try:
                    block = m.to_prompt_block()
                    # Should be valid string or empty
                    assert isinstance(block, str)
                except Exception as e:
                    errors.append(f"Reader: {e}")

        writer_t = threading.Thread(target=writer)
        reader_t = threading.Thread(target=reader)

        writer_t.start()
        reader_t.start()
        writer_t.join(timeout=5)
        reader_t.join(timeout=5)

        assert not errors, f"Errors: {errors}"

    def test_add_and_get_latest_concurrent(self):
        """get_latest while another thread adds turns."""
        m = DialogSummaryManager(max_tokens=10000, max_turns=100)
        errors: list[str] = []
        stop = threading.Event()

        def writer():
            for i in range(50):
                m.add_turn(_make_summary(i))
            stop.set()

        def reader():
            while not stop.is_set():
                try:
                    latest = m.get_latest()
                    assert latest is None or isinstance(latest, CompactSummary)
                except Exception as e:
                    errors.append(f"Reader: {e}")

        writer_t = threading.Thread(target=writer)
        reader_t = threading.Thread(target=reader)

        writer_t.start()
        reader_t.start()
        writer_t.join(timeout=5)
        reader_t.join(timeout=5)

        assert not errors

    def test_add_and_len_concurrent(self):
        """len() while another thread adds turns."""
        m = DialogSummaryManager(max_tokens=10000, max_turns=100)
        errors: list[str] = []
        stop = threading.Event()

        def writer():
            for i in range(50):
                m.add_turn(_make_summary(i))
            stop.set()

        def reader():
            while not stop.is_set():
                try:
                    length = len(m)
                    assert 0 <= length <= 100
                except Exception as e:
                    errors.append(str(e))

        writer_t = threading.Thread(target=writer)
        reader_t = threading.Thread(target=reader)

        writer_t.start()
        reader_t.start()
        writer_t.join(timeout=5)
        reader_t.join(timeout=5)

        assert not errors


# ======================================================================
# Concurrent add_turn + clear Tests
# ======================================================================


class TestConcurrentClear:
    def test_add_and_clear_concurrent(self):
        """clear() during concurrent add_turn — no crash."""
        m = DialogSummaryManager(max_tokens=10000, max_turns=100)
        errors: list[str] = []

        def writer():
            for i in range(50):
                try:
                    m.add_turn(_make_summary(i))
                except Exception as e:
                    errors.append(f"Writer: {e}")

        def clearer():
            for _ in range(10):
                try:
                    m.clear()
                    time.sleep(0.001)
                except Exception as e:
                    errors.append(f"Clearer: {e}")

        writer_t = threading.Thread(target=writer)
        clearer_t = threading.Thread(target=clearer)

        writer_t.start()
        clearer_t.start()
        writer_t.join(timeout=5)
        clearer_t.join(timeout=5)

        assert not errors


# ======================================================================
# Backward Compatibility Tests
# ======================================================================


class TestBackwardCompatibility:
    def test_single_thread_add_and_read(self):
        """Normal single-threaded usage still works."""
        m = DialogSummaryManager(max_tokens=500, max_turns=5)
        m.add_turn(_make_summary(1, "greeting", "greeted back"))
        m.add_turn(_make_summary(2, "calendar", "listed events"))

        assert len(m) == 2
        block = m.to_prompt_block()
        assert "DIALOG_SUMMARY" in block
        assert "greeting" in block
        assert "calendar" in block

    def test_clear_works(self):
        m = DialogSummaryManager()
        m.add_turn(_make_summary(1))
        m.clear()
        assert len(m) == 0
        assert m.to_prompt_block() == ""

    def test_get_latest_works(self):
        m = DialogSummaryManager()
        assert m.get_latest() is None
        m.add_turn(_make_summary(1, "first"))
        m.add_turn(_make_summary(2, "second"))
        assert m.get_latest().user_intent == "second"

    def test_max_turns_eviction(self):
        m = DialogSummaryManager(max_turns=3)
        for i in range(5):
            m.add_turn(_make_summary(i + 1, f"intent-{i}"))
        assert len(m) == 3

    def test_str_returns_prompt_block(self):
        m = DialogSummaryManager()
        m.add_turn(_make_summary(1, "test"))
        assert str(m) == m.to_prompt_block()


# ======================================================================
# Stress Test
# ======================================================================


class TestStress:
    def test_high_concurrency_mixed_operations(self):
        """20 writers + 10 readers + 5 clearers = 35 concurrent threads."""
        m = DialogSummaryManager(max_tokens=10000, max_turns=200)
        errors: list[str] = []
        stop = threading.Event()

        def writer(tid: int):
            for i in range(20):
                try:
                    m.add_turn(_make_summary(tid * 100 + i, f"w{tid}-{i}"))
                except Exception as e:
                    errors.append(f"W{tid}: {e}")

        def reader(tid: int):
            while not stop.is_set():
                try:
                    _ = m.to_prompt_block()
                    _ = len(m)
                    _ = m.get_latest()
                except Exception as e:
                    errors.append(f"R{tid}: {e}")

        def clearer(tid: int):
            for _ in range(3):
                try:
                    time.sleep(0.002)
                    m.clear()
                except Exception as e:
                    errors.append(f"C{tid}: {e}")

        threads = []
        for i in range(20):
            threads.append(threading.Thread(target=writer, args=(i,)))
        for i in range(10):
            threads.append(threading.Thread(target=reader, args=(i,)))
        for i in range(5):
            threads.append(threading.Thread(target=clearer, args=(i,)))

        for t in threads:
            t.start()

        # Wait for writers to finish
        for t in threads[:20]:
            t.join(timeout=10)

        stop.set()
        for t in threads[20:]:
            t.join(timeout=5)

        assert not errors, f"Errors ({len(errors)}): {errors[:5]}"
