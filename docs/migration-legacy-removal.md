# Legacy Code Removal — Migration Guide (Issue #851)

## What changed

### 1. `BANTZ_USE_LEGACY` environment variable removed
The Brain runtime is now the **only** command handler. Setting `BANTZ_USE_LEGACY=1`
no longer has any effect.

**Action required**: Remove `BANTZ_USE_LEGACY` from your `.env`, `bantz-env`,
systemd service files, or Docker Compose environment sections.

### 2. Legacy framing fallback removed
`BantzServer._recv_framed()` no longer accepts unframed (raw) messages.
All clients **must** use length-prefixed framing (4-byte big-endian header).

**Action required**: Update any custom IPC clients to use framed protocol.
The `bantz-browser` extension and CLI client already use framing.

### 3. v0 modules deleted
| Deleted file | Replacement |
|-------------|-------------|
| `document/ingest_v0.py` | `document/ingest.py` (v1 pipeline) |
| `voice/attention_gate_v0.py` | `voice/attention_gate.py` (FSM v1) |

**Action required**: Update any imports from `ingest_v0` or `attention_gate_v0`
to use the v1 modules.

### 4. JARVIS alias fixed
`voice_style.JARVIS` now consistently points to `JarvisVoice` (was being
overwritten by `VoiceStyle`).

### 5. `legacy_parse_intent` removed from nlu/bridge.py
The bridge module no longer imports `legacy_parse_intent` at the top level.
Fallback paths now use a local import of `parse_intent` from `bantz.router.nlu`.

**Action required**: If you imported `legacy_parse_intent` from `bridge`, use
`from bantz.router.nlu import parse_intent` directly instead.
