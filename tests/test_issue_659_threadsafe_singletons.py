# SPDX-License-Identifier: MIT
"""Issue #659: NLU singletons must be thread-safe."""

import threading

from bantz.nlu.bridge import get_nlu, reset_nlu_instance
from bantz.nlu.classifier import get_classifier, reset_classifier_instance


def _collect_instances(factory, count: int = 10):
    barrier = threading.Barrier(count)
    results = [None] * count

    def _worker(idx: int):
        barrier.wait()
        results[idx] = factory()

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return results


def test_bridge_get_nlu_is_thread_safe():
    reset_nlu_instance()
    instances = _collect_instances(get_nlu, count=8)
    ids = {id(x) for x in instances}
    assert len(ids) == 1


def test_classifier_singleton_is_thread_safe():
    reset_classifier_instance()
    instances = _collect_instances(get_classifier, count=8)
    ids = {id(x) for x in instances}
    assert len(ids) == 1
