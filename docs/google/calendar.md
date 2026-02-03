# Google Calendar

Kod: `src/bantz/google/calendar.py`

## Env

- `BANTZ_GOOGLE_CLIENT_SECRET` (varsayılan: `~/.config/bantz/google/client_secret.json`)
- `BANTZ_GOOGLE_TOKEN_PATH` (varsayılan: `~/.config/bantz/google/token.json`)
- `BANTZ_GOOGLE_CALENDAR_ID` (varsayılan: `primary`)

## Fonksiyonlar

- `list_events(...)` - Liste calendar events
- `find_free_slots(...)` - Find available time slots
- `create_event(...)` (write) - Create new event
- `update_event(...)` (write) - **Update event with partial updates (Issue #163)**
- `delete_event(...)` (write) - Delete event

## update_event - Partial Update Support (Issue #163)

`update_event` now supports **partial updates** - only specified fields are modified.

### Examples

```python
from bantz.google.calendar import update_event

# Update only the title
update_event(
    event_id="evt_abc123",
    summary="Updated Sprint Planning"
)

# Update only the location
update_event(
    event_id="evt_abc123",
    location="Zoom (updated link)"
)

# Update only the time (both start and end required together)
update_event(
    event_id="evt_abc123",
    start="2026-02-10T15:00:00+03:00",
    end="2026-02-10T16:00:00+03:00"
)

# Update multiple fields at once
update_event(
    event_id="evt_abc123",
    summary="Q1 Review Meeting",
    location="Conference Room B",
    description="Please prepare Q1 metrics",
    start="2026-02-10T14:00:00+03:00",
    end="2026-02-10T15:30:00+03:00"
)
```

### Parameters

- `event_id` (required): Google Calendar event ID
- `summary` (optional): New event title
- `start` (optional): RFC3339 start datetime (**requires `end`**)
- `end` (optional): RFC3339 end datetime (**requires `start`**)
- `location` (optional): Event location
- `description` (optional): Event description
- `calendar_id` (optional): Calendar ID (default: primary)

### Rules

- At least one field must be provided for update
- If `start` is provided, `end` must also be provided (and vice versa)
- `end` must be after `start`
- Empty summary is not allowed

### CLI Usage

```bash
# Update only title
bantz google calendar update --event-id evt_123 --summary "New Title" --yes

# Update only location
bantz google calendar update --event-id evt_123 --location "Office 301" --yes

# Update time (both start and end required)
bantz google calendar update \
  --event-id evt_123 \
  --start "2026-02-10T15:00:00+03:00" \
  --end "2026-02-10T16:00:00+03:00" \
  --yes

# Update multiple fields
bantz google calendar update \
  --event-id evt_123 \
  --summary "Updated Meeting" \
  --location "Zoom" \
  --description "New agenda" \
  --yes
```

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
