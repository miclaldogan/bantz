# Bantz v1.0 Roadmap — GAIA-Inspired Platform Evolution

> **Issue:** [#1300](https://github.com/miclaldogan/bantz/issues/1300)
> **Status:** Active
> **Last updated:** 2025-06-16

This document tracks the Bantz v1.0 roadmap — a phased evolution from
desktop assistant to a GAIA-inspired AI platform. Each phase builds on
the infrastructure established by the previous one.

**Total EPICs:** 12 | **Phases:** 8 (Faz 0 + A–F + G+)

---

## Faz 0 — Data Platform Design (Prerequisite)

| # | Issue | Status |
|---|-------|--------|
| [#1302](https://github.com/miclaldogan/bantz/issues/1302) | Canonical Data Platform Schema v0 | ✅ Done |
| [#1303](https://github.com/miclaldogan/bantz/issues/1303) | Label Standardization — type:epic + area:* + status:* | ⬜ Planned |

**Goal:** All Faz A EPICs share a common database schema and consistent
project management labels.

**Deliverables:**
- [docs/data-platform-schema.md](data-platform-schema.md) — Canonical schema reference
- `src/bantz/data/migrations/` — Versioned migration system

---

## Faz A — Data Platform (Core Infrastructure)

| # | EPIC | Status |
|---|------|--------|
| [#1288](https://github.com/miclaldogan/bantz/issues/1288) | Ingest Store + TTL Cache + Fingerprint | ✅ Done |
| [#1290](https://github.com/miclaldogan/bantz/issues/1290) | Observability — Runs/ToolCalls/Artifacts DB + Metrics | ⬜ Planned |
| [#1291](https://github.com/miclaldogan/bantz/issues/1291) | Policy Engine v2 — Risk Tiers + Param Edit + Redact + Presets | ⬜ Planned |
| [#1297](https://github.com/miclaldogan/bantz/issues/1297) | Event Bus — Async Pub/Sub Internal Communication | ⬜ Planned |
| [#1298](https://github.com/miclaldogan/bantz/issues/1298) | Graceful Degradation — Circuit Breaker + Health Monitor + Fallback | ⬜ Planned |
| [#1289](https://github.com/miclaldogan/bantz/issues/1289) | Graph Memory — GraphStore Interface + Hybrid Retrieval | ⬜ Planned |

### Recommended Order

```
Ingest Store ✅ → Observability → Policy Engine v2 → Event Bus → Graceful Degradation → Graph Memory
```

**Rationale:**
1. ~~Ingest Store~~ ✅ — Core data layer (done)
2. **Observability** — Debugging cache/TTL without logging is impractical
3. **Policy Engine v2** — Security layer must be in place before send/execute grows
4. **Event Bus** — Loose coupling between modules; Graceful Degradation needs events
5. **Graceful Degradation** — Gains meaning together with Bus + Policy
6. **Graph Memory** — Last; data flow must stabilize first to avoid "low quality data" graph bloat

### Dependency Graph

```
Ingest Store (✅) ──┬──► Observability ──► Policy Engine v2
                    │                              │
                    │         Event Bus ◄───────────┘
                    │            │
                    │    Graceful Degradation
                    │            │
                    └───► Graph Memory (last)
```

---

## Faz B — Google Suite Expansion

| # | EPIC | Status |
|---|------|--------|
| [#1292](https://github.com/miclaldogan/bantz/issues/1292) | Google Suite Super-Connector — Unified OAuth + Contacts/Tasks/Keep/Classroom | ⬜ Planned |

**Dependency:** Faz A complete (at minimum: Ingest Store + Observability + Policy)
**Absorbs:** #840 (Classroom)

---

## Faz C — Daily Brief & Proactivity

| # | EPIC | Status |
|---|------|--------|
| [#1293](https://github.com/miclaldogan/bantz/issues/1293) | Proactive Secretary Engine — Daily Brief + Signal + Suggestion | ⬜ Planned |

**Dependency:** Faz A (Event Bus, Ingest Store) + Faz B (Google Suite connectors)
**Absorbs:** #838 (Weather), #839 (News Tracking)

---

## Faz D — Controlled Messaging

| # | EPIC | Status |
|---|------|--------|
| [#1294](https://github.com/miclaldogan/bantz/issues/1294) | Controlled Messaging — Read → Draft → Confirm → Send Pipeline | ⬜ Planned |

**Dependency:** Faz A (Policy Engine) + Faz B (Gmail channel)

---

## Faz E — PC Agent & CodingAgent

| # | EPIC | Status |
|---|------|--------|
| [#1295](https://github.com/miclaldogan/bantz/issues/1295) | PC Agent + CodingAgent — Sandbox Execution + Safety Guardrails | ⬜ Planned |

**Dependency:** Faz A (Policy Engine, Observability)
**Related:** #842 (Screen Interpretation)

---

## Faz F — Music

| # | EPIC | Status |
|---|------|--------|
| [#1296](https://github.com/miclaldogan/bantz/issues/1296) | Music Control — Spotify/Local Player + Context-Aware Suggestions | ⬜ Planned |

**Dependency:** Faz C (Proactive engine — for context-aware suggestions)

---

## Faz G+ — Future Capabilities

| # | EPIC | Status |
|---|------|--------|
| [#1299](https://github.com/miclaldogan/bantz/issues/1299) | Future Capabilities — Finance, File Search, Secret Manager, Travel, Health | ⬜ Planned |

---

## Progress Summary

| Phase | EPICs | Completed | Status |
|-------|-------|-----------|--------|
| Faz 0 | 2 | 1 | 🟡 In Progress |
| Faz A | 6 | 1 | 🟡 In Progress |
| Faz B | 1 | 0 | ⬜ Not Started |
| Faz C | 1 | 0 | ⬜ Not Started |
| Faz D | 1 | 0 | ⬜ Not Started |
| Faz E | 1 | 0 | ⬜ Not Started |
| Faz F | 1 | 0 | ⬜ Not Started |
| Faz G+ | 1 | 0 | ⬜ Not Started |

## Existing Issue Integration

| Existing Issue | Absorbed Into |
|---------------|---------------|
| #1280 — Semantic Memory / RAG | → #1289 Graph Memory |
| #840 — Google Classroom | → #1292 Google Suite Super-Connector |
| #839 — News Tracking | → #1293 Proactive Secretary (signal collector) |
| #838 — Weather | → #1293 Proactive Secretary (signal collector) |
| #842 — Screen Interpretation | → #1295 PC Agent (screenshot) |
| #841 — Brainstorming | Remains independent |
| #1211 — PDF summarization | Remains independent |

---

## References

- [Architecture](architecture.md) — System architecture overview
- [Data Platform Schema](data-platform-schema.md) — Canonical database schema
- [Jarvis Roadmap v2](jarvis-roadmap-v2.md) — Earlier V2 roadmap (superseded by this)
