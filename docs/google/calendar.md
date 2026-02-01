# Google Calendar

Kod: `src/bantz/google/calendar.py`

## Env

- `BANTZ_GOOGLE_CLIENT_SECRET` (varsayılan: `~/.config/bantz/google/client_secret.json`)
- `BANTZ_GOOGLE_TOKEN_PATH` (varsayılan: `~/.config/bantz/google/token.json`)
- `BANTZ_GOOGLE_CALENDAR_ID` (varsayılan: `primary`)

## Fonksiyonlar

- `list_events(...)`
- `find_free_slots(...)`
- `create_event(...)` (write)
- `update_event(...)` (write)
- `delete_event(...)` (write)

## Smoke test

```bash
pip install -e ".[calendar]"

# Önerilen: CLI
bantz google auth calendar --write
bantz google calendar list --max-results 10

# Alternatif: script smoke
python scripts/smoke_calendar_list_events.py
python scripts/smoke_calendar_create_event.py  # dikkat: write
```
