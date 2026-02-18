# Canonical Data Platform Schema v0

> **Issue:** [#1302](https://github.com/miclaldogan/bantz/issues/1302)
> **Phase:** Faz 0 — Data Platform Design
> **Status:** Draft
> **Last updated:** 2025-06-16

## 1. Purpose

This document defines the **canonical schema** for the Bantz Data Platform.
It consolidates every SQLite table across all subsystems into a single
reference, establishes design principles, and defines the migration strategy
for evolving from the current 11-database layout to a unified platform.

Every Faz A EPIC ([#1288]–[#1298]) must align its tables with this spec.

---

## 2. Design Principles

| # | Principle | Rationale |
|---|-----------|-----------|
| P1 | **Single data directory** | All databases live under `$BANTZ_DATA_DIR` (default `~/.bantz/data/`). |
| P2 | **Logical databases, physical files** | Subsystems may use separate `.db` files for isolation, but schemas are designed as if they coexist in a single DB. FKs are logical. |
| P3 | **TEXT UUIDs for primary keys** | `uuid4().hex` (32-char hex). No `AUTOINCREMENT`. Enables offline generation and future distribution. |
| P4 | **REAL timestamps (epoch seconds)** | `time.time()` — consistent ordering, cheap comparison. Legacy TEXT timestamps are migrated. |
| P5 | **JSON for flexible metadata** | `TEXT` column with JSON payload. Never query inside JSON for hot paths — add indexed columns when needed. |
| P6 | **WAL journal mode** | All databases use `PRAGMA journal_mode=WAL` for concurrent read performance. |
| P7 | **Version-tracked schemas** | Every database has a `schema_version` table. Changes go through the migration system. |
| P8 | **Logical FKs, enforced at app layer** | Cross-database references (e.g., `run_id` in tool_calls → runs) use matching TEXT IDs but are enforced by application code, not SQLite FKs. |

---

## 3. Database Layout

```
~/.bantz/data/
├── ingest.db          ← IngestStore (EPIC #1288 ✅)
├── observability.db   ← RunTracker: runs, tool_calls, artifacts (EPIC #1290)
├── graph.db           ← Graph Memory: nodes, edges (EPIC #1289)
├── memory.db          ← Persistent Memory: user_profile, sessions, memory_items
├── policy.db          ← Policy decisions audit log (EPIC #1291 — new)
├── analytics.db       ← Events, corrections
├── security.db        ← Encrypted key-value store
├── learning.db        ← User profiles, learning data
├── scheduler.db       ← Reminders, checkins
└── snippets.db        ← Snippet store
```

### 3.1 Consolidated vs. Current

The current codebase has **11 independent SQLite databases** with no
unified schema, inconsistent ID strategies, mixed timestamp formats, and
only one subsystem with migrations. The target state retains logical
separation (separate `.db` files for fault isolation) but converges on
shared conventions and a migration system for every database.

| Current Issue | Target Fix |
|---------------|------------|
| Mix of `REAL` and `TEXT` timestamps | Standardize on REAL (epoch seconds) |
| Mix of `uuid4().hex`, `str(uuid4())`, `AUTOINCREMENT` | Standardize on `uuid4().hex` |
| Only `memory/migrations.py` has versioned migrations | Every database gets versioned migrations |
| 2 competing memory schemas (`store.py` vs `migrations.py`) | Single canonical memory schema |
| `tool_trace` (memory) and `tool_calls` (observability) overlap | `tool_calls` is canonical; `tool_trace` deprecated |
| No cross-DB session correlation | `session_id` is a shared logical FK |
| Brain's `memory.db` at `~/.bantz/brain/memory.db` | Move to `~/.bantz/data/memory.db` |

---

## 4. Canonical Table Schemas

### 4.1 Ingest Store (`ingest.db`) — EPIC [#1288] ✅

Fingerprint-deduped, TTL-cached storage for all tool results and API
responses. Source: `src/bantz/data/ingest_store.py`.

```sql
-- schema version: 1
CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);

CREATE TABLE ingest_store (
    id          TEXT PRIMARY KEY,           -- uuid4().hex
    fingerprint TEXT NOT NULL UNIQUE,       -- SHA-256 of canonical content
    data_class  TEXT NOT NULL,              -- EPHEMERAL | SESSION | PERSISTENT
    source      TEXT NOT NULL,              -- tool name or subsystem identifier
    content     TEXT NOT NULL,              -- JSON payload
    summary     TEXT,                       -- LLM-generated summary (nullable)
    created_at  REAL NOT NULL,             -- epoch seconds
    expires_at  REAL,                      -- epoch seconds (NULL = never)
    accessed_at REAL NOT NULL,             -- epoch seconds (updated on access)
    access_count INTEGER NOT NULL DEFAULT 0,
    meta        TEXT                        -- JSON metadata (nullable)
);

CREATE INDEX idx_ingest_class       ON ingest_store(data_class);
CREATE INDEX idx_ingest_source      ON ingest_store(source);
CREATE INDEX idx_ingest_expires     ON ingest_store(expires_at);
CREATE UNIQUE INDEX idx_ingest_fp   ON ingest_store(fingerprint);
```

**Data lifecycle:**

| DataClass | TTL | Examples |
|-----------|-----|----------|
| `EPHEMERAL` | 24 h | Mail listings, search results, API responses |
| `SESSION` | 7 d | In-session decisions, active context fragments |
| `PERSISTENT` | ∞ | Contacts, user preferences, learned knowledge |

---

### 4.2 Observability (`observability.db`) — EPIC [#1290]

Records every user interaction (run), tool invocation (tool_call), and
produced content (artifact). Source: `src/bantz/data/run_tracker.py`.

```sql
-- schema version: 1
CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);

CREATE TABLE runs (
    run_id       TEXT PRIMARY KEY,          -- uuid4().hex
    user_input   TEXT NOT NULL,
    route        TEXT,                      -- router decision (calendar, gmail, …)
    intent       TEXT,                      -- parsed intent
    final_output TEXT,                      -- final user-facing response
    model        TEXT,                      -- model used (qwen2.5-3b, gemini-flash, …)
    total_tokens INTEGER,
    latency_ms   INTEGER,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending | ok | error
    error        TEXT,
    session_id   TEXT,                      -- logical FK → shared session concept
    created_at   REAL NOT NULL
);

CREATE TABLE tool_calls (
    call_id        TEXT PRIMARY KEY,         -- uuid4().hex
    run_id         TEXT NOT NULL,            -- logical FK → runs.run_id
    tool_name      TEXT NOT NULL,
    params         TEXT,                     -- JSON-serialized parameters
    result_hash    TEXT,                     -- SHA-256 of result (for dedup)
    result_summary TEXT,                     -- truncated result for display
    latency_ms     INTEGER,
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending | ok | error
    error          TEXT,
    confirmation   TEXT DEFAULT 'auto',      -- auto | user_confirmed | user_denied
    retry_count    INTEGER DEFAULT 0,
    created_at     REAL NOT NULL
);

CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,            -- uuid4().hex
    run_id      TEXT,                        -- logical FK → runs.run_id
    type        TEXT NOT NULL,               -- summary | transcript | report | draft | …
    title       TEXT,
    content     TEXT,
    summary     TEXT,
    embedding   BLOB,                        -- vector embedding (optional)
    source_ref  TEXT,                        -- origin reference
    mime_type   TEXT,
    size_bytes  INTEGER,
    created_at  REAL NOT NULL
);

-- Indexes
CREATE INDEX idx_runs_session   ON runs(session_id);
CREATE INDEX idx_runs_created   ON runs(created_at);
CREATE INDEX idx_runs_status    ON runs(status);
CREATE INDEX idx_tc_run         ON tool_calls(run_id);
CREATE INDEX idx_tc_tool        ON tool_calls(tool_name);
CREATE INDEX idx_tc_status      ON tool_calls(status);
CREATE INDEX idx_tc_created     ON tool_calls(created_at);
CREATE INDEX idx_art_run        ON artifacts(run_id);
CREATE INDEX idx_art_type       ON artifacts(type);
```

---

### 4.3 Graph Memory (`graph.db`) — EPIC [#1289]

Knowledge graph with canonical node labels and edge relations.
Source: `src/bantz/data/graph_store.py`, `src/bantz/data/graph_backends/sqlite_backend.py`.

```sql
-- schema version: 1
CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);

CREATE TABLE nodes (
    id         TEXT PRIMARY KEY,             -- uuid4().hex
    label      TEXT NOT NULL,                -- one of NODE_LABELS
    properties TEXT NOT NULL DEFAULT '{}',   -- JSON
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE edges (
    id        TEXT PRIMARY KEY,              -- uuid4().hex
    source_id TEXT NOT NULL,                 -- logical FK → nodes.id
    target_id TEXT NOT NULL,                 -- logical FK → nodes.id
    relation  TEXT NOT NULL,                 -- one of EDGE_RELATIONS
    properties TEXT NOT NULL DEFAULT '{}',   -- JSON
    weight    REAL NOT NULL DEFAULT 1.0,
    created_at REAL NOT NULL
);

CREATE UNIQUE INDEX idx_edge_triple ON edges(source_id, target_id, relation);
CREATE INDEX idx_edges_source       ON edges(source_id);
CREATE INDEX idx_edges_target       ON edges(target_id);
CREATE INDEX idx_nodes_label        ON nodes(label);
```

**Canonical labels:**

| Node Labels | Edge Relations |
|-------------|----------------|
| `Person`, `Org`, `Project`, `Document` | `SENT`, `RECEIVED`, `ATTENDS`, `OWNS` |
| `Event`, `Email`, `Task`, `Topic` | `MEMBER_OF`, `ASSIGNED_TO`, `MENTIONS` |
| | `REPLY_TO`, `RELATED_TO`, `SCHEDULED_FOR` |
| | `BLOCKS`, `FOLLOWS_UP`, `LINKED_TO` |
| | `AUTHORED_BY`, `DISCUSSED_IN` |

---

### 4.4 Policy Decisions (`policy.db`) — EPIC [#1291]

Audit log for policy engine decisions. The policy engine itself is
**stateless** (rules loaded from `config/policy.json`), but every
decision is persisted for observability and compliance.

> **Note:** This table is NEW — not yet implemented. Part of the Policy
> Engine v2 EPIC (#1291).

```sql
-- schema version: 1
CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);

CREATE TABLE policy_decisions (
    id          TEXT PRIMARY KEY,             -- uuid4().hex
    run_id      TEXT,                         -- logical FK → runs.run_id
    tool_name   TEXT,                         -- tool being evaluated
    intent      TEXT,                         -- router intent
    pattern     TEXT,                         -- matched pattern (if any)
    decision    TEXT NOT NULL,                -- allow | confirm | deny
    reason      TEXT NOT NULL,                -- human-readable reason
    user_action TEXT,                         -- confirmed | denied | timed_out (nullable)
    risk_level  TEXT,                         -- safe | moderate | destructive
    created_at  REAL NOT NULL
);

CREATE INDEX idx_pd_run      ON policy_decisions(run_id);
CREATE INDEX idx_pd_decision ON policy_decisions(decision);
CREATE INDEX idx_pd_tool     ON policy_decisions(tool_name);
CREATE INDEX idx_pd_created  ON policy_decisions(created_at);
```

**Decision flow:**

```
User Input → Router (intent) → Policy.decide() → (decision, reason)
                                     │
                                     ├─ allow   → execute tool
                                     ├─ confirm → prompt user → confirmed/denied
                                     └─ deny    → reject with reason
```

---

### 4.5 Persistent Memory (`memory.db`)

Consolidated memory store — replaces both `memory/store.py` and
`memory/migrations.py` legacy schemas, plus the brain's separate
`~/.bantz/brain/memory.db`.

```sql
-- schema version: 2  (v1 was the legacy migrations.py schema)
CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);

CREATE TABLE user_profile (
    id         TEXT PRIMARY KEY,              -- uuid4().hex
    key        TEXT NOT NULL UNIQUE,           -- preference key
    value      TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);

CREATE TABLE sessions (
    id          TEXT PRIMARY KEY,              -- uuid4().hex (= session_id elsewhere)
    start_time  REAL NOT NULL,
    end_time    REAL,
    summary     TEXT NOT NULL DEFAULT '',
    turn_count  INTEGER NOT NULL DEFAULT 0,
    metadata    TEXT NOT NULL DEFAULT '{}'     -- JSON
);

CREATE TABLE memory_items (
    id               TEXT PRIMARY KEY,         -- uuid4().hex
    session_id       TEXT,                     -- logical FK → sessions.id
    type             TEXT NOT NULL DEFAULT 'episodic',  -- episodic | semantic | procedural
    content          TEXT NOT NULL DEFAULT '',
    embedding_vector BLOB,                     -- float32 array (optional)
    importance       REAL NOT NULL DEFAULT 0.5,
    created_at       REAL NOT NULL,
    accessed_at      REAL NOT NULL,
    access_count     INTEGER NOT NULL DEFAULT 0,
    tags             TEXT NOT NULL DEFAULT '[]',   -- JSON array
    metadata         TEXT NOT NULL DEFAULT '{}'    -- JSON
);

CREATE TABLE dialog_turns (
    id         TEXT PRIMARY KEY,              -- uuid4().hex
    session_id TEXT NOT NULL,                 -- logical FK → sessions.id
    role       TEXT NOT NULL,                 -- user | assistant
    content    TEXT NOT NULL,
    timestamp  REAL NOT NULL,
    tokens     INTEGER,
    metadata   TEXT NOT NULL DEFAULT '{}'     -- JSON
);

-- Indexes
CREATE INDEX idx_mi_session    ON memory_items(session_id);
CREATE INDEX idx_mi_type       ON memory_items(type);
CREATE INDEX idx_mi_importance ON memory_items(importance);
CREATE INDEX idx_mi_created    ON memory_items(created_at);
CREATE INDEX idx_dt_session    ON dialog_turns(session_id);
CREATE INDEX idx_dt_timestamp  ON dialog_turns(timestamp);
CREATE INDEX idx_up_key        ON user_profile(key);
```

**Migration from legacy:**
- `memory/store.py` `memories` table → `memory_items` (rename + schema adjust)
- `memory/migrations.py` `tool_trace` → **deprecated** (use `observability.db` `tool_calls`)
- `brain/memory_store.py` `sessions`/`turns` → `sessions`/`dialog_turns`
- TEXT timestamps → REAL conversion via migration

---

### 4.6 Analytics (`analytics.db`)

User interaction analytics and voice correction tracking.

```sql
-- schema version: 1
CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);

CREATE TABLE events (
    id         TEXT PRIMARY KEY,              -- uuid4().hex
    event_type TEXT NOT NULL,
    data       TEXT NOT NULL DEFAULT '{}',    -- JSON payload
    source     TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE corrections (
    id              TEXT PRIMARY KEY,          -- uuid4().hex
    original_text   TEXT NOT NULL,
    corrected_text  TEXT NOT NULL,
    correction_type TEXT,                      -- voice | typo | grammar
    source          TEXT,
    created_at      REAL NOT NULL
);

CREATE INDEX idx_events_type    ON events(event_type);
CREATE INDEX idx_events_created ON events(created_at);
CREATE INDEX idx_corr_type      ON corrections(correction_type);
```

---

### 4.7 Security (`security.db`)

Encrypted key-value store for sensitive data (OAuth tokens, API keys).
Source: `src/bantz/security/storage.py`.

```sql
-- schema version: 1
CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);

CREATE TABLE secure_storage (
    key        TEXT PRIMARY KEY,
    value      BLOB NOT NULL,                 -- encrypted payload
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    expires_at REAL,                          -- optional TTL
    tags       TEXT                            -- JSON array for categorization
);

CREATE INDEX idx_ss_expires ON secure_storage(expires_at);
```

---

### 4.8 Learning (`learning.db`)

User behavior profiles and learning data.
Source: `src/bantz/learning/storage.py`.

```sql
-- schema version: 1
CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);

CREATE TABLE profiles (
    user_id    TEXT PRIMARY KEY,
    data       TEXT NOT NULL,                  -- JSON profile data
    updated_at REAL NOT NULL
);

CREATE TABLE learning_data (
    user_id    TEXT NOT NULL,
    data_type  TEXT NOT NULL,                  -- preference | behavior | feedback
    data       TEXT NOT NULL,                  -- JSON payload
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, data_type)
);
```

---

### 4.9 Scheduler (`scheduler.db`)

Reminders and scheduled check-ins.
Source: `src/bantz/scheduler/`.

```sql
-- schema version: 1
CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);

CREATE TABLE reminders (
    id              TEXT PRIMARY KEY,           -- uuid4().hex
    text            TEXT NOT NULL,
    remind_at       REAL NOT NULL,             -- epoch seconds
    created_at      REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | fired | cancelled
    repeat_interval TEXT,                       -- cron-like or duration (nullable)
    snoozed_until   REAL                       -- epoch seconds (nullable)
);

CREATE TABLE checkins (
    id            TEXT PRIMARY KEY,             -- uuid4().hex
    prompt        TEXT NOT NULL,
    schedule      TEXT NOT NULL,                -- cron expression
    next_run_at   REAL NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active',  -- active | paused | deleted
    created_at    REAL NOT NULL,
    last_fired_at REAL
);

CREATE INDEX idx_rem_status   ON reminders(status);
CREATE INDEX idx_rem_remind   ON reminders(remind_at);
CREATE INDEX idx_chk_status   ON checkins(status);
CREATE INDEX idx_chk_next     ON checkins(next_run_at);
```

---

### 4.10 Snippet Store (`snippets.db`)

Dynamic snippet storage for retrieved knowledge fragments.
Source: `src/bantz/memory/snippet_store.py`.

```sql
-- schema version: 1
CREATE TABLE schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);

CREATE TABLE snippets (
    id            TEXT PRIMARY KEY,             -- uuid4().hex
    content       TEXT NOT NULL,
    snippet_type  TEXT NOT NULL,                -- fact | procedure | reference | …
    source        TEXT,
    timestamp     REAL NOT NULL,               -- created_at equivalent
    confidence    REAL NOT NULL DEFAULT 1.0,
    ttl_seconds   REAL,                        -- optional TTL
    tags          TEXT,                         -- JSON array
    metadata      TEXT,                         -- JSON
    access_count  INTEGER NOT NULL DEFAULT 0,
    last_accessed REAL                         -- epoch seconds
);

CREATE INDEX idx_snip_type   ON snippets(snippet_type);
CREATE INDEX idx_snip_source ON snippets(source);
```

---

## 5. Cross-Cutting Concerns

### 5.1 Session Correlation

`session_id` appears in multiple databases and serves as the primary
cross-database correlation key:

```
sessions.id (memory.db)
  ├── runs.session_id (observability.db)
  ├── memory_items.session_id (memory.db)
  ├── dialog_turns.session_id (memory.db)
  └── tool_calls → via run_id → runs.session_id
```

All `session_id` values use `uuid4().hex` format.

### 5.2 Shared Enums

| Enum | Values | Used In |
|------|--------|---------|
| `DataClass` | `EPHEMERAL`, `SESSION`, `PERSISTENT` | ingest_store |
| `run.status` | `pending`, `ok`, `error` | runs, tool_calls |
| `PolicyDecision` | `allow`, `confirm`, `deny` | policy_decisions |
| `risk_level` | `safe`, `moderate`, `destructive` | policy_decisions, policy.json |
| `memory_type` | `episodic`, `semantic`, `procedural` | memory_items |
| `confirmation` | `auto`, `user_confirmed`, `user_denied` | tool_calls |

### 5.3 Timestamp Convention

**Canonical format:** `REAL` — Unix epoch seconds from `time.time()`.

Migration from TEXT timestamps:

```python
import time
from datetime import datetime

def text_to_epoch(text_ts: str) -> float:
    """Convert ISO-format TEXT timestamp to REAL epoch seconds."""
    return datetime.fromisoformat(text_ts).timestamp()
```

### 5.4 ID Generation

**Canonical format:** `uuid4().hex` — 32-character hex string.

```python
from uuid import uuid4
record_id = uuid4().hex  # e.g. "a1b2c3d4e5f6..."
```

Tables using `AUTOINCREMENT` (scheduler legacy) will be migrated to TEXT
UUIDs in future schema versions.

---

## 6. EPIC Cross-Reference

| EPIC | Issue | Tables | Database | Status |
|------|-------|--------|----------|--------|
| Ingest Store | [#1288](https://github.com/miclaldogan/bantz/issues/1288) | `ingest_store` | `ingest.db` | ✅ Done |
| Graph Memory | [#1289](https://github.com/miclaldogan/bantz/issues/1289) | `nodes`, `edges` | `graph.db` | ✅ Done |
| Observability | [#1290](https://github.com/miclaldogan/bantz/issues/1290) | `runs`, `tool_calls`, `artifacts` | `observability.db` | ✅ Done |
| Policy Engine v2 | [#1291](https://github.com/miclaldogan/bantz/issues/1291) | `policy_decisions` | `policy.db` | 🔲 Planned |
| Event Bus | [#1292](https://github.com/miclaldogan/bantz/issues/1292) | _(in-memory, no tables)_ | — | 🔲 Planned |
| Graceful Degradation | [#1293](https://github.com/miclaldogan/bantz/issues/1293) | _(runtime, no schema)_ | — | 🔲 Planned |
| Graph + Ingest Bridge | [#1298](https://github.com/miclaldogan/bantz/issues/1298) | _(uses graph.db + ingest.db)_ | — | ✅ Done |
| Data Platform Schema | [#1302](https://github.com/miclaldogan/bantz/issues/1302) | _(this document)_ | — | 🔲 In Progress |

---

## 7. Migration Strategy

### 7.1 Migration System Design

Every database gets the same version-tracked migration infrastructure,
generalized from the existing `src/bantz/memory/migrations.py`.

```
src/bantz/data/migrations/
├── __init__.py          ← shared migrate() function
├── ingest.py            ← ingest.db migrations
├── observability.py     ← observability.db migrations
├── graph.py             ← graph.db migrations
├── memory.py            ← memory.db migrations (absorbs memory/migrations.py)
├── policy.py            ← policy.db migrations
├── analytics.py         ← analytics.db migrations
├── security.py          ← security.db migrations
├── learning.py          ← learning.db migrations
├── scheduler.py         ← scheduler.db migrations
└── snippets.py          ← snippets.db migrations
```

### 7.2 Shared Migration Runner

```python
# src/bantz/data/migrations/__init__.py

MIGRATIONS: Dict[int, str]  # version → SQL, defined per-module

def migrate(conn: sqlite3.Connection, migrations: Dict[int, str]) -> int:
    """Apply outstanding migrations to the given connection."""
    # 1. Ensure schema_version table exists
    # 2. Read current version
    # 3. Apply migrations in order
    # 4. Record applied version + timestamp
    # 5. Return new version
```

### 7.3 Migration Phases

| Phase | What | When |
|-------|------|------|
| **Phase 0** | Add `schema_version` tables to all existing databases | Faz 0 |
| **Phase 1** | Standardize timestamps (TEXT → REAL) in legacy tables | Faz A |
| **Phase 2** | Standardize IDs (AUTOINCREMENT → uuid4().hex) | Faz A |
| **Phase 3** | Merge `brain/memory.db` into `data/memory.db` | Faz A |
| **Phase 4** | Deprecate `memory/store.py` `memories` table, migrate to `memory_items` | Faz A |
| **Phase 5** | Deprecate `tool_trace` in favor of `tool_calls` | Faz A |
| **Phase 6** | Create `policy.db` with `policy_decisions` table | Faz A (#1291) |

### 7.4 Backward Compatibility

- Migrations are **forward-only** (no rollback). Data backup before migration is recommended.
- Old code using legacy table names will continue to work during the transition period via SQL views:

```sql
-- Compatibility view: maps old 'memories' table to new 'memory_items'
CREATE VIEW IF NOT EXISTS memories AS
    SELECT id, session_id, type, content, importance,
           created_at, accessed_at, access_count, tags, metadata
    FROM memory_items;
```

---

## 8. ER Diagram

```
┌─────────────────┐        ┌──────────────────┐
│   sessions      │        │   user_profile    │
│─────────────────│        │──────────────────│
│ id (PK)         │        │ id (PK)          │
│ start_time      │        │ key (UNIQUE)     │
│ end_time        │        │ value            │
│ summary         │        │ updated_at       │
│ turn_count      │        └──────────────────┘
│ metadata        │
└────────┬────────┘
         │ session_id
    ┌────┴────┬──────────────────┐
    │         │                  │
    ▼         ▼                  ▼
┌─────────┐ ┌──────────────┐ ┌──────────────┐
│  runs   │ │ memory_items │ │ dialog_turns │
│─────────│ │──────────────│ │──────────────│
│ run_id  │ │ id           │ │ id           │
│ user_.. │ │ session_id   │ │ session_id   │
│ route   │ │ type         │ │ role         │
│ intent  │ │ content      │ │ content      │
│ ...     │ │ importance   │ │ timestamp    │
└────┬────┘ │ ...          │ │ ...          │
     │      └──────────────┘ └──────────────┘
     │ run_id
     ├──────────────┬──────────────┐
     ▼              ▼              ▼
┌────────────┐ ┌───────────┐ ┌──────────────────┐
│ tool_calls │ │ artifacts │ │ policy_decisions  │
│────────────│ │───────────│ │──────────────────│
│ call_id    │ │ artifact_ │ │ id               │
│ run_id     │ │ run_id    │ │ run_id           │
│ tool_name  │ │ type      │ │ tool_name        │
│ params     │ │ content   │ │ decision         │
│ status     │ │ ...       │ │ reason           │
│ ...        │ └───────────┘ │ ...              │
└────────────┘               └──────────────────┘

┌─────────────┐    ┌──────────────────┐
│   nodes     │    │     edges        │
│─────────────│    │──────────────────│
│ id (PK)     │◄───│ source_id (FK)   │
│ label       │◄───│ target_id (FK)   │
│ properties  │    │ relation         │
│ created_at  │    │ weight           │
│ updated_at  │    │ ...              │
└─────────────┘    └──────────────────┘

┌──────────────────┐
│  ingest_store    │
│──────────────────│
│ id (PK)          │
│ fingerprint (UQ) │
│ data_class       │
│ source           │
│ content (JSON)   │
│ summary          │
│ expires_at       │
│ ...              │
└──────────────────┘
```

---

## 9. Open Questions

| # | Question | Context |
|---|----------|---------|
| Q1 | Should analytics events be stored in `observability.db` instead of a separate `analytics.db`? | Both track "what happened" — merging could simplify queries. |
| Q2 | Should `snippets` be folded into `ingest_store` with a `data_class` discriminator? | Both store content with TTL and access tracking. |
| Q3 | Should the Event Bus (EPIC #1292) persist events to a table for replay/audit? | Currently in-memory only; persistence would enable audit trails. |
| Q4 | Should `learning.db` tables merge into `memory.db`? | Both are "long-term user knowledge" — semantic overlap. |
| Q5 | Move from multiple `.db` files to a single `bantz.db`? | Simplifies backup/restore but loses fault isolation. |

---

## 10. References

- [Architecture](architecture.md) — System architecture overview
- [Tool Catalog](tool-catalog.md) — Registered tools and risk levels
- [Confirmation Firewall](confirmation-firewall.md) — Policy engine design
- [Issue #1300](https://github.com/miclaldogan/bantz/issues/1300) — Bantz v1.0 Roadmap Master Plan
- [Issue #1302](https://github.com/miclaldogan/bantz/issues/1302) — This document's tracking issue
- [config/policy.json](../config/policy.json) — Policy rules (deny/confirm/allow patterns)
- [src/bantz/data/](../src/bantz/data/) — Data layer source code
- [src/bantz/memory/migrations.py](../src/bantz/memory/migrations.py) — Existing migration system
