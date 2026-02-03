# Google Calendar

Kod: `src/bantz/google/calendar.py`

## Env

- `BANTZ_GOOGLE_CLIENT_SECRET` (varsayılan: `~/.config/bantz/google/client_secret.json`)
- `BANTZ_GOOGLE_TOKEN_PATH` (varsayılan: `~/.config/bantz/google/token.json`)
- `BANTZ_GOOGLE_CALENDAR_ID` (varsayılan: `primary`)

## Fonksiyonlar

- `list_events(...)` - Liste calendar events
- `find_free_slots(...)` - Find available time slots
- `create_event(...)` (write) - Create new event (supports all-day events - Issue #164)
- `update_event(...)` (write) - **Update event with partial updates (Issue #163)**
- `delete_event(...)` (write) - Delete event

## create_event - All-Day Event Support (Issue #164)

`create_event` now supports **all-day events** in addition to time-based events.

### Time-Based Events (Original)

```python
from bantz.google.calendar import create_event

# With end datetime
create_event(
    summary="Team Meeting",
    start="2026-02-03T14:00:00+03:00",
    end="2026-02-03T15:00:00+03:00"
)

# With duration
create_event(
    summary="Team Meeting",
    start="2026-02-03T14:00:00+03:00",
    duration_minutes=60
)
```

### All-Day Events (New - Issue #164)

```python
# Single-day all-day event
create_event(
    summary="Conference",
    start="2026-02-03",
    all_day=True
)

# Multi-day all-day event
create_event(
    summary="Vacation",
    start="2026-02-23",
    end="2026-02-26",  # Exclusive: Feb 23-25 (3 days)
    all_day=True
)

# All-day event with location and description
create_event(
    summary="Home Office",
    start="2026-02-05",
    all_day=True,
    location="Home",
    description="Working from home today"
)
```

### Parameters

**Time-based events:**
- `start`: RFC3339 datetime with timezone (e.g., "2026-02-03T14:00:00+03:00")
- `end`: RFC3339 datetime (optional if `duration_minutes` provided)
- `duration_minutes`: Duration in minutes (optional if `end` provided)

**All-day events:**
- `all_day=True`: Must be set to `True`
- `start`: Date in YYYY-MM-DD format (e.g., "2026-02-03")
- `end`: Date in YYYY-MM-DD format (optional, exclusive)
  - If not provided, creates single-day event
  - If provided, end date is exclusive (e.g., "2026-02-23" to "2026-02-26" = Feb 23-25)
- `duration_minutes`: Ignored for all-day events

**Common parameters:**
- `summary` (required): Event title
- `calendar_id` (optional): Calendar ID (default: primary)
- `description` (optional): Event description
- `location` (optional): Event location

### Rules

**All-day events:**
- `start` must be in YYYY-MM-DD format
- `end` (if provided) must be in YYYY-MM-DD format
- `end` must be after `start` (at least +1 day)
- `end` is exclusive (next day after last day of event)

**Time-based events:**
- `start` must be RFC3339 with timezone
- Either `end` or `duration_minutes` must be provided
- `end` must be after `start`

### CLI Usage

```bash
# Time-based event
bantz google calendar create \
  --summary "Meeting" \
  --start "2026-02-03T14:00:00+03:00" \
  --duration-minutes 60 \
  --yes

# Single-day all-day event
bantz google calendar create \
  --summary "Conference" \
  --start "2026-02-03" \
  --all-day \
  --yes

# Multi-day all-day event
bantz google calendar create \
  --summary "Vacation" \
  --start "2026-02-23" \
  --end "2026-02-26" \
  --all-day \
  --yes

# All-day event with details
bantz google calendar create \
  --summary "Home Office" \
  --start "2026-02-05" \
  --all-day \
  --location "Home" \
  --description "Working from home" \
  --yes
```

### User Stories Addressed

- ✅ "Pazartesi tüm gün konferans ekle"
- ✅ "23-25 Şubat arası tatil işaretle"
- ✅ "Cuma günü home office olarak belirt"

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
