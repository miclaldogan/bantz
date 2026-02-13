# Changelog

All notable changes to **Bantz** will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/) and the project
adheres to [Semantic Versioning](https://semver.org/).

---

## [0.2.0] — 2025-07-22

### What's New

- **Golden Path Calendar** — `display_hint` on calendar tools; `#N` reference
  resolution (`#2 sil`, `#3'ü güncelle`) across turns; free-slot routing;
  context persistence for follow-up queries (#1224).
- **Golden Path Inbox** — `display_hint` on Gmail tools; draft/reply/detail
  intent mapping; numbered message listing (`#1 sender — subject ✉️`) (#1225).
- **Test Pyramid** — 14 golden-path E2E tests (calendar + inbox + failure
  modes), 10 regression tests covering top 5 recurring bugs.  New
  `--run-golden-path` pytest option (#1226).
- **Onboarding CLI** — `bantz onboard` interactive first-run wizard that checks
  env, GPU, vLLM, Google OAuth and writes config (#1223).
- **Doctor CLI** — `bantz doctor` post-install health-checker: vLLM reachable,
  model loaded, GPU memory, env vars, Google tokens, disk space (#1223).
- **Permission Model** — Capability-based permission model with confirmation
  gate and audit log.  Destructive ops blocked unless explicitly approved
  (#1222).
- **Core Pipeline Hardening** — `trace_id` propagation across every pipeline
  phase; tool-result size limiter prevents context overflow (#1221).
- **Sprint Framework** — Structured sprint planning with issue templates and
  epic tracking (#1220).
- **LanguageBridge** — Transparent TR↔EN translation layer so the 3B English
  model works natively with Turkish input (#1241-#1246).
- **Bug-fix batch** — 15 codebase-audit bugs fixed; 4 runtime bugs fixed
  (#1212-#1219, #1253-#1256).

### Breaking Changes

- `OrchestratorState` has two new fields: `calendar_listed_events` and
  `gmail_listed_messages`.  Code that serialises/deserialises state snapshots
  must account for them.
- `--run-golden-path` / `--run-regression` flags now gate additional test
  markers.  CI pipelines should add these flags to run the full suite.

### Fixed

- Finalizer exceeded 4 096-token context window on small models (#1253).
- Turkish anaphora tokens (`başka`, `içeriğinde`, …) were checked against
  bridge-translated English text instead of original input (#1254).
- Period-of-day words (`sabah`, `akşam`) ignored during time extraction (#1255).
- Turkish İ lowering produced combining dot (U+0307), breaking fuzzy mail
  match (#1256).

---

## [0.1.0] — 2025-06-01

Initial internal release.

- Brain pipeline (Plan → Execute → Finalize)
- vLLM inference with Qwen 2.5½ 3B AWQ
- Gemini 2.0 Flash tiered finalization
- Google Calendar & Gmail tools
- Voice mode (Faster Whisper ASR + Piper TTS)
- Confirmation firewall for destructive ops
- Chromium browser extension
