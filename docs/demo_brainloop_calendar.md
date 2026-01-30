# BrainLoop Calendar Demo (Issue #100)

LLM-powered calendar assistant demo with Ollama integration.

## Quick Start

```bash
# 1. Start Ollama
ollama serve

# 2. Pull model (if not already available)
ollama pull qwen2.5:3b-instruct

# 3. Run dry-run demo (no writes)
python3 scripts/demo_calendar_brainloop.py --dry-run --interactive

# 4. Try some queries:
USER: Bu akşam planım var mı?
USER: Yarın sabah 10:45'te 30 dakika toplantı ekle
USER: 1  # Confirm
```

## Features

- **LLM-enabled BrainLoop**: Uses Ollama for natural language understanding
- **JSON repair**: Tolerates malformed LLM outputs (#86)
- **Policy confirmation**: Asks user before writing to calendar (#87, #102)
- **Event stream**: ACK/PROGRESS/FOUND/RESULT logging (#88)
- **Time-aware**: Understands "bu akşam", "yarın sabah", etc. (#101)
- **Jarvis tone**: Consistent "Efendim" responses (#102)

## Command-line Options

```bash
python3 scripts/demo_calendar_brainloop.py [options]

Options:
  --ollama-url URL         Ollama API URL (default: http://127.0.0.1:11434)
  --ollama-model MODEL     Model name (default: qwen2.5:3b-instruct)
  --dry-run                Safe mode - no real writes
  --run                    Enable real calendar writes (requires confirmation)
  --debug                  Show transcript + event stream logs
  --script FILE            Read conversation from file
  --interactive            Force interactive terminal mode
  --calendar-id ID         Google Calendar ID (default: primary)
  --tz TIMEZONE            Timezone (default: Europe/Istanbul)
```

## Acceptance Criteria (Issue #100)

- [x] BrainLoop calls at least one tool per user input
- [x] "3:45 yap" triggers `calendar.create_event` with policy confirmation
- [x] `--debug` shows transcript + event stream logs
- [x] JSON repair (#86) tolerates malformed LLM outputs
- [x] Policy engine (#87) gates tool execution
- [x] Event stream (#88) shows ACK/PROGRESS/FOUND/RESULT

## Recommended Models

- **qwen2.5:7b-instruct** - Best accuracy
- **qwen2.5:3b-instruct** - Fast, occasionally confused but usable
- **qwen2.5:14b-instruct** - Highest quality (requires more RAM)

## Example Session

```
$ python3 scripts/demo_calendar_brainloop.py --dry-run --interactive

BANTZ (BrainLoop): Hazırım efendim.
BANTZ (BrainLoop): Not: dry-run modundayım; takvime yazma yapılmaz.

USER: Bu akşam planım var mı?
ACK: Anladım efendim.
PROGRESS: Tool çalıştırılıyor: calendar.list_events
FOUND: calendar.list_events
RESULT: Bu akşam için plan görünmüyor.
BANTZ: Bu akşam için plan görünmüyor.

USER: Yarın sabah 10:45'te 30 dakika toplantı ekle
QUESTION: Efendim, takvime 10:45–11:15 "toplantı" ekliyorum. Onaylıyor musunuz? (1/0)
BANTZ: Efendim, takvime 10:45–11:15 "toplantı" ekliyorum. Onaylıyor musunuz? (1/0)

USER: 1
ACK: Anladım efendim.
PROGRESS: Tool çalıştırılıyor: calendar.create_event
FOUND: calendar.create_event
RESULT: Dry-run: 'toplantı' 10:45–11:15 eklenecekti.
BANTZ: Dry-run: 'toplantı' 10:45–11:15 eklenecekti.
```

## Architecture

```
User Input
    ↓
BrainLoop
    ↓
JarvisRepairingLLMAdapter → Ollama (qwen2.5)
    ↓
validate_or_repair_action (JSON repair #86)
    ↓
PolicyEngine (confirmation gate #87)
    ↓
Calendar Tools (list_events, create_event, find_free_slots)
    ↓
EventBus (ACK/PROGRESS/FOUND/RESULT #88)
    ↓
Response
```

## Related Issues

- #86 - JSON validator + auto-repair
- #87 - Policy guardrail for tool execution
- #88 - Event stream for BrainLoop
- #101 - Evening time window (18:00-24:00)
- #102 - Policy confirmation UX (Jarvis tone)
- Epic #98 - Calendar conversation demo
