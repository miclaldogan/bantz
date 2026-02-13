# Epic: Boot-time “Jarvis” Always-On Assistant

Goal: When the machine boots, BANTZ starts automatically, greets the user, keeps wake-word listening always-on, prewarms models in the background, and can run common flows (news briefing, system health, calendar, Gmail) with graceful standby/stop.

## Non-goals (v1)
- Perfect wake-word accuracy across noisy environments
- Fully offline “everything” (cloud finalizer like Gemini is allowed)
- Full GUI; terminal + minimal overlay is acceptable

## Success Criteria
- Autostarts on login/boot (systemd user service) and can be stopped/restarted reliably.
- Always-on listening with wake-word; “sleep/standby” stops processing but keeps wake-word.
- <2s perceived readiness: immediate greeting + responsive fallback while models warm.
- Background model prewarm reduces first-turn latency.
- Safe tool execution with confirmations and policy checks.
- Clear logs/metrics for latency and failures.

---

## Issue 1 — Systemd user autostart
**Deliverable**: systemd user service that starts BANTZ on login.
- Add/validate unit under systemd/user/
- Provide install/uninstall scripts and docs
- Healthcheck / restart policy
- Logs to artifacts/logs

## Issue 2 — Boot greeting + state machine
**Deliverable**: deterministic lifecycle states.
- States: `STARTING → WARMING → READY → STANDBY → ERROR`
- Greeting policy (once per session) + “I’m warming up” fallback
- Localized TR responses

## Issue 3 — Model prewarm manager
**Deliverable**: background warming for router + finalizer.
- Router (vLLM): ping + first completion to load weights
- Finalizer (Gemini): availability check + tiny completion
- Exponential backoff and timeout budget
- Metrics: TTFT, warm time, failures

## Issue 4 — Always-on wake-word loop
**Deliverable**: continuous mic loop with wake-word detection.
- Wake-word engine selection + pluggable interface
- Low-power mode behavior
- Adjustable sensitivity + hotword list
- “Standby” keeps wake-word alive

## Issue 5 — Streaming ASR pipeline
**Deliverable**: streaming speech-to-text.
- Pluggable ASR backends
- Partial transcripts and endpointing
- Noise handling + VAD thresholds

## Issue 6 — TTS output + interruption
**Deliverable**: TTS with barge-in.
- Speak greeting + responses
- Stop speaking immediately on wake-word / user interruption
- Audio device selection + recovery

## Issue 7 — Terminal prototype parity (text-first)
**Deliverable**: terminal mode that mirrors always-on behavior.
- Greeting on launch
- Standby mode (wake-word emulation via prefix)
- Prewarm in background
- Tool routing + confirmations

## Issue 8 — Tooling: system health
**Deliverable**: `system.status` tool.
- CPU/RAM/load, optionally disk
- No extra dependencies preferred
- Safe output (no secrets)

## Issue 9 — Tooling: calendar flows
**Deliverable**: end-to-end calendar read + create.
- “today/evening/week” windows
- Create event from natural language
- Confirmations for writes
- Robust timezone handling

## Issue 10 — Tooling: Gmail read-only flows
**Deliverable**: unread count + inbox summaries.
- `gmail.unread_count`, `gmail.list_messages`, safe `gmail.get_message` fallback
- No sending in v1 unless explicitly enabled

## Issue 11 — News briefing pipeline
**Deliverable**: short morning briefing.
- Web search + summarization
- User preferences (topics/sources)
- Caching + rate limiting

## Issue 12 — Policy + confirmation UX
**Deliverable**: consistent confirmation prompts.
- Strict confirmation tokens
- “Are you sure?” UX with context
- Audit trail of tool executions

## Issue 13 — Observability
**Deliverable**: actionable metrics + logs.
- Per-turn latency breakdown (router/tool/finalizer)
- Error reason codes (auth, timeout, rate-limited)
- Simple “status” command

## Issue 14 — Resilience & recovery
**Deliverable**: self-healing behavior.
- Restart audio pipeline on device changes
- Backoff on network failures
- Graceful degradation to text-only

## Issue 15 — Acceptance tests
**Deliverable**: black-box scripts + docs.
- Autostart test
- Wake-word + ASR + TTS smoke
- Calendar/Gmail sandbox verification
- Metrics thresholds
