"""
Gmail inbox synchronizer — pulls messages into IngestStore.

Periodically fetches Gmail messages via the Google API and writes
them into the IngestStore with sender-based classification labels.

The sync is **incremental**: it tracks a high-water-mark (latest
message timestamp) and only fetches newer messages on subsequent runs.

Usage::

    syncer = GmailSyncer(store)
    await syncer.sync()           # one-shot
    await syncer.start_periodic() # background loop

Each ingested message gets classification metadata::

    meta = {
        "category": "github",         # from SenderClassifier
        "confidence": 0.95,
        "message_id": "18f3a...",
        "thread_id": "18f3a...",
        "from": "noreply@github.com",
        "sender_name": "GitHub",
        "to": "user@example.com",
        "labels": ["INBOX", "UNREAD"],
        "is_unread": True,
        "has_attachments": False,
        "sync_source": "gmail_sync",
    }
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from bantz.data.ingest_store import DataClass, IngestStore
from bantz.data.sync.classifier import SenderClassifier

# GraphBridge is optional — imported lazily to avoid circular deps at module level
_GraphBridgeClass: Any = None


def _get_graph_bridge_class() -> Any:
    global _GraphBridgeClass
    if _GraphBridgeClass is None:
        try:
            from bantz.data.graph_bridge import GraphBridge  # noqa: PLC0415
            _GraphBridgeClass = GraphBridge
        except Exception:
            pass
    return _GraphBridgeClass

logger = logging.getLogger(__name__)

# Sync config defaults
_DEFAULT_SYNC_INTERVAL = 300       # 5 minutes
_DEFAULT_MAX_MESSAGES = 50         # messages per sync pass
_DEFAULT_INITIAL_FETCH = 100       # first-time sync depth
_INGEST_SOURCE = "gmail"

# Issue #1366: Rate limit / retry config
_MAX_RETRIES = 3
_INITIAL_BACKOFF_SEC = 2.0         # doubles on each retry
_RATE_LIMIT_CODES = {429, 403}     # Google API rate limit HTTP codes


def _parse_sender(from_header: str) -> tuple[str, str]:
    """Extract (sender_name, sender_email) from a From header.

    Examples::

        'John Doe <john@example.com>' → ('John Doe', 'john@example.com')
        'john@example.com'            → ('', 'john@example.com')
        'GitHub <noreply@github.com>' → ('GitHub', 'noreply@github.com')
    """
    import re
    if not from_header:
        return "", ""
    stripped = from_header.strip()
    if not stripped:
        return "", ""

    # Pattern: "Name" <email> or Name <email>
    match = re.match(r'^"?([^"<]+)"?\s*<([^>]+@[^>]+)>$', stripped)
    if match:
        name = match.group(1).strip().strip('"')
        email = match.group(2).strip()
        return name, email

    # Plain email address (no angle brackets)
    if "@" in stripped and "<" not in stripped:
        return "", stripped

    # Fallback
    return "", stripped


class GmailSyncer:
    """Incremental Gmail → IngestStore synchronizer.

    Parameters
    ----------
    store : IngestStore
        Target ingest store.
    classifier : SenderClassifier, optional
        Custom classifier instance.  Defaults to standard rules.
    sync_interval : int
        Seconds between periodic syncs.
    max_messages : int
        Max messages to fetch per sync pass.
    """

    def __init__(
        self,
        store: IngestStore,
        *,
        classifier: Optional[SenderClassifier] = None,
        sync_interval: int = _DEFAULT_SYNC_INTERVAL,
        max_messages: int = _DEFAULT_MAX_MESSAGES,
        graph_bridge: Optional[Any] = None,
    ) -> None:
        self._store = store
        self._classifier = classifier or SenderClassifier()
        self._sync_interval = sync_interval
        self._max_messages = max_messages
        self._last_sync: float = 0.0
        self._running = False
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._graph_bridge: Optional[Any] = graph_bridge

        # Sync stats
        self._total_synced = 0
        self._total_classified: Dict[str, int] = {}
        self._total_graph_edges = 0

    # ── Public API ────────────────────────────────────────────

    async def sync(self) -> Dict[str, Any]:
        """Run a single sync pass.  Returns stats dict."""
        logger.info("[GmailSync] Starting sync pass...")
        start = time.time()

        try:
            messages = await self._fetch_messages()
            if not messages:
                logger.info("[GmailSync] No new messages to sync.")
                return {"ok": True, "synced": 0, "elapsed_ms": 0}

            ingested = 0
            categories: Dict[str, int] = {}

            for msg in messages:
                record_id = self._ingest_message(msg)
                if record_id:
                    ingested += 1
                    cat = msg.get("_category", "uncategorized")
                    categories[cat] = categories.get(cat, 0) + 1

            # Issue #1472: link senders into the knowledge graph
            graph_edges = await self._index_senders(messages)

            elapsed_ms = int((time.time() - start) * 1000)
            self._last_sync = time.time()
            self._total_synced += ingested
            self._total_graph_edges += graph_edges

            for cat, count in categories.items():
                self._total_classified[cat] = self._total_classified.get(cat, 0) + count

            logger.info(
                "[GmailSync] Synced %d messages in %dms — categories: %s — graph_edges: %d",
                ingested, elapsed_ms, categories, graph_edges,
            )
            return {
                "ok": True,
                "synced": ingested,
                "categories": categories,
                "elapsed_ms": elapsed_ms,
                "graph_edges": graph_edges,
            }

        except Exception as e:
            logger.error("[GmailSync] Sync failed: %s", e, exc_info=True)
            return {"ok": False, "error": str(e), "synced": 0}

    async def start_periodic(self) -> None:
        """Start periodic background sync.  Call once at boot."""
        if self._running:
            logger.warning("[GmailSync] Already running.")
            return
        self._running = True
        self._task = asyncio.create_task(self._periodic_loop())
        logger.info(
            "[GmailSync] Periodic sync started (interval=%ds)",
            self._sync_interval,
        )

    async def stop(self) -> None:
        """Stop the periodic sync loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[GmailSync] Stopped.")

    @property
    def stats(self) -> Dict[str, Any]:
        """Return cumulative sync stats."""
        return {
            "total_synced": self._total_synced,
            "categories": dict(self._total_classified),
            "last_sync": self._last_sync,
            "is_running": self._running,
            "total_graph_edges": self._total_graph_edges,
        }

    async def _index_senders(self, messages: List[Dict[str, Any]]) -> int:
        """Link Gmail senders to Person contact nodes in the knowledge graph.

        For each fetched message a ``Person`` node is upserted (merge-by-email)
        via ``GraphBridge.on_tool_result`` so the orchestrator can resolve
        natural-language references like "Ahmet'in maili" to a concrete sender.

        Duplicate senders within the same batch are deduplicated by the
        underlying GraphStore's ``upsert_node(unique_key='email')``.

        Uses ``self._graph_bridge`` if injected; otherwise attempts lazy
        initialisation with the default SQLite graph store.  If the graph
        is unavailable this method silently returns 0.

        Parameters
        ----------
        messages:
            Enriched message dicts produced by ``_fetch_messages``.

        Returns
        -------
        int
            Number of graph edges created/updated in this batch.
        """
        if not messages:
            return 0

        bridge = self._graph_bridge
        if bridge is None:
            BridgeCls = _get_graph_bridge_class()
            if BridgeCls is None:
                return 0
            try:
                bridge = await BridgeCls.create_default()
                self._graph_bridge = bridge
            except Exception as exc:
                logger.warning("[GmailSync] GraphBridge lazy init failed: %s", exc)
                return 0

        if not bridge.enabled:
            return 0

        total_edges = 0
        for msg in messages:
            sender_email = msg.get("_sender_email") or ""
            if not sender_email:
                continue
            try:
                edges = await bridge.on_tool_result(
                    "gmail.list_messages",
                    {},
                    {
                        "message_id": msg.get("id", ""),
                        "from": msg.get("from", ""),
                        "to": msg.get("to", []),
                        "subject": msg.get("subject", ""),
                        "date": msg.get("date", ""),
                        "snippet": msg.get("snippet", ""),
                    },
                )
                total_edges += edges
            except Exception as exc:
                logger.warning(
                    "[GmailSync] Graph indexing failed for sender %s: %s",
                    sender_email, exc,
                )

        if total_edges > 0:
            logger.debug(
                "[GmailSync] Indexed %d senders into graph (%d edges)",
                len(messages), total_edges,
            )
        return total_edges

    # ── Private helpers ───────────────────────────────────────

    async def _periodic_loop(self) -> None:
        """Background loop: sync → sleep → repeat."""
        while self._running:
            try:
                await self.sync()
            except Exception as e:
                logger.error("[GmailSync] Periodic sync error: %s", e)
            await asyncio.sleep(self._sync_interval)

    async def _fetch_messages(self) -> List[Dict[str, Any]]:
        """Fetch recent messages from Gmail API.

        Runs the blocking Google API call in an executor thread
        to avoid blocking the event loop.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._fetch_messages_sync)

    def _fetch_messages_sync(self) -> List[Dict[str, Any]]:
        """Synchronous Gmail API fetch with exponential backoff (Issue #1366).

        Retries up to _MAX_RETRIES times on 429/403 rate limit errors
        with exponential backoff (2s → 4s → 8s).
        """
        try:
            from bantz.google.gmail import gmail_list_messages
        except ImportError:
            logger.warning("[GmailSync] bantz.google.gmail not available")
            return []

        last_error: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                result = gmail_list_messages(
                    max_results=self._max_messages,
                    interactive=False,
                )

                if not result.get("ok"):
                    error_msg = result.get("error", "")
                    # Check for rate limit in error message
                    if "429" in str(error_msg) or "quota" in str(error_msg).lower():
                        backoff = _INITIAL_BACKOFF_SEC * (2 ** attempt)
                        logger.warning(
                            "[GmailSync] Rate limited (attempt %d/%d), backing off %.1fs: %s",
                            attempt + 1, _MAX_RETRIES + 1, backoff, error_msg,
                        )
                        time.sleep(backoff)
                        continue
                    logger.warning("[GmailSync] gmail_list_messages failed: %s", error_msg)
                    return []

                break  # Success
            except Exception as e:
                last_error = e
                error_str = str(e)
                # Check for HTTP status code in exception
                is_rate_limit = any(
                    code_str in error_str
                    for code_str in ("429", "403", "rateLimitExceeded", "userRateLimitExceeded")
                )
                if is_rate_limit and attempt < _MAX_RETRIES:
                    backoff = _INITIAL_BACKOFF_SEC * (2 ** attempt)
                    logger.warning(
                        "[GmailSync] Rate limit exception (attempt %d/%d), backing off %.1fs: %s",
                        attempt + 1, _MAX_RETRIES + 1, backoff, e,
                    )
                    time.sleep(backoff)
                    continue
                logger.error("[GmailSync] Gmail API error: %s", e, exc_info=True)
                return []
        else:
            # All retries exhausted
            logger.error(
                "[GmailSync] All %d retries exhausted. Last error: %s",
                _MAX_RETRIES + 1, last_error,
            )
            return []

        raw_messages = result.get("messages", [])
        enriched: List[Dict[str, Any]] = []

        for msg in raw_messages:
            if not isinstance(msg, dict):
                continue

            from_header = msg.get("from") or ""
            sender_name, sender_email = _parse_sender(from_header)
            subject = msg.get("subject") or ""

            # Classify the sender
            category, confidence = self._classifier.classify_with_confidence(
                sender=sender_email,
                sender_name=sender_name,
                subject=subject,
            )

            msg["_sender_name"] = sender_name
            msg["_sender_email"] = sender_email
            msg["_category"] = category
            msg["_confidence"] = confidence

            enriched.append(msg)

        return enriched

    def _ingest_message(self, msg: Dict[str, Any]) -> Optional[str]:
        """Ingest a single classified message into the store."""
        from_header = msg.get("from") or ""
        sender_name = msg.get("_sender_name") or ""
        sender_email = msg.get("_sender_email") or ""
        category = msg.get("_category", "uncategorized")
        confidence = msg.get("_confidence", 0.0)

        content = {
            "message_id": msg.get("id", ""),
            "from": from_header,
            "sender_name": sender_name,
            "sender_email": sender_email,
            "subject": msg.get("subject", ""),
            "snippet": msg.get("snippet", ""),
            "date": msg.get("date", ""),
            "category": category,
        }

        meta = {
            "category": category,
            "confidence": confidence,
            "message_id": msg.get("id", ""),
            "from": from_header,
            "sender_name": sender_name,
            "sender_email": sender_email,
            "sync_source": "gmail_sync",
        }

        summary = f"[{category}] {sender_name or sender_email}: {msg.get('subject', '')}"

        try:
            return self._store.ingest(
                content=content,
                source=_INGEST_SOURCE,
                data_class=DataClass.EPHEMERAL,
                summary=summary,
                meta=meta,
            )
        except Exception as e:
            logger.warning("[GmailSync] Failed to ingest message %s: %s", msg.get("id"), e)
            return None
