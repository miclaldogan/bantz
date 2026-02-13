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

## create_event - Recurring Events Support (Issue #165)

`create_event` now supports **recurring events** using RFC5545 RRULE format.

### RRULE Format

Recurring events use RRULE strings in the `recurrence` parameter:
- Format: `"RRULE:FREQ=<frequency>;[parameters]"`
- Frequencies: `DAILY`, `WEEKLY`, `MONTHLY`, `YEARLY`
- Termination: `COUNT=<n>` (number of occurrences) or `UNTIL=<datetime>` (end date)
- Weekdays: `BYDAY=MO,TU,WE,TH,FR,SA,SU`
- Monthly patterns: `BYDAY=1FR` (first Friday), `BYDAY=-1MO` (last Monday), `BYMONTHDAY=15` (15th)
- Interval: `INTERVAL=2` (every 2 weeks/months/etc)

### Python Examples

```python
from bantz.google.calendar import create_event, build_rrule_daily, build_rrule_weekly, build_rrule_monthly

# Daily recurring event (10 occurrences)
create_event(
    summary="Daily Standup",
    start="2026-02-23T10:00:00+03:00",
    duration_minutes=30,
    recurrence=["RRULE:FREQ=DAILY;COUNT=10"]
)

# Using helper function
create_event(
    summary="Daily Standup",
    start="2026-02-23T10:00:00+03:00",
    duration_minutes=30,
    recurrence=[build_rrule_daily(count=10)]
)

# Weekly on Monday (8 weeks)
create_event(
    summary="Monday Team Meeting",
    start="2026-02-23T14:00:00+03:00",
    duration_minutes=60,
    recurrence=[build_rrule_weekly(byday=["MO"], count=8)]
)

# Weekly on Mon/Wed/Fri (12 occurrences)
create_event(
    summary="Workout Session",
    start="2026-02-23T18:00:00+03:00",
    duration_minutes=60,
    recurrence=[build_rrule_weekly(byday=["MO", "WE", "FR"], count=12)]
)

# Bi-weekly on Tuesday (5 occurrences)
create_event(
    summary="Sprint Planning",
    start="2026-02-24T10:00:00+03:00",
    duration_minutes=120,
    recurrence=[build_rrule_weekly(byday=["TU"], count=5, interval=2)]
)

# Monthly on first Friday (12 months)
create_event(
    summary="Monthly Retrospective",
    start="2026-02-06T15:00:00+03:00",
    duration_minutes=120,
    recurrence=[build_rrule_monthly(byday="1FR", count=12)]
)

# Monthly on last Monday (6 months)
create_event(
    summary="Monthly Review",
    start="2026-02-24T14:00:00+03:00",
    duration_minutes=60,
    recurrence=[build_rrule_monthly(byday="-1MO", count=6)]
)

# Monthly on 15th day (12 months)
create_event(
    summary="Monthly Report",
    start="2026-02-15T09:00:00+03:00",
    duration_minutes=30,
    recurrence=[build_rrule_monthly(bymonthday=15, count=12)]
)

# Until a specific date
create_event(
    summary="Project Check-in",
    start="2026-02-23T11:00:00+03:00",
    duration_minutes=30,
    recurrence=["RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20260430T110000Z"]
)

# Recurring all-day event
create_event(
    summary="Daily Task Block",
    start="2026-02-23",
    all_day=True,
    recurrence=[build_rrule_daily(count=30)]
)
```

### Helper Functions

Three helper functions simplify RRULE generation:

#### `build_rrule_daily(count=None, until=None)`
```python
from bantz.google.calendar import build_rrule_daily

# 10 days
rrule = build_rrule_daily(count=10)
# "RRULE:FREQ=DAILY;COUNT=10"

# Until March 1st
rrule = build_rrule_daily(until="20260301T000000Z")
# "RRULE:FREQ=DAILY;UNTIL=20260301T000000Z"
```

#### `build_rrule_weekly(byday, count=None, until=None, interval=1)`
```python
from bantz.google.calendar import build_rrule_weekly

# Every Monday, 10 times
rrule = build_rrule_weekly(byday=["MO"], count=10)
# "RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=10"

# Mon/Wed/Fri, 8 times
rrule = build_rrule_weekly(byday=["MO", "WE", "FR"], count=8)
# "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=8"

# Every 2 weeks on Tuesday, 5 times
rrule = build_rrule_weekly(byday=["TU"], count=5, interval=2)
# "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=TU;COUNT=5"
```

#### `build_rrule_monthly(byday=None, bymonthday=None, count=None, until=None)`
```python
from bantz.google.calendar import build_rrule_monthly

# First Friday, 12 months
rrule = build_rrule_monthly(byday="1FR", count=12)
# "RRULE:FREQ=MONTHLY;BYDAY=1FR;COUNT=12"

# Last Monday, 6 months
rrule = build_rrule_monthly(byday="-1MO", count=6)
# "RRULE:FREQ=MONTHLY;BYDAY=-1MO;COUNT=6"

# 15th of each month, 12 months
rrule = build_rrule_monthly(bymonthday=15, count=12)
# "RRULE:FREQ=MONTHLY;BYMONTHDAY=15;COUNT=12"
```

### User Story Examples (Turkish)

```python
# "Her Pazartesi saat 10'da standup ekle"
create_event(
    summary="Daily Standup",
    start="2026-02-23T10:00:00+03:00",
    duration_minutes=15,
    recurrence=[build_rrule_weekly(byday=["MO"], count=10)]
)

# "Ayın ilk Cuma günü retrospektif koy"
create_event(
    summary="Retrospektif",
    start="2026-02-06T15:00:00+03:00",
    duration_minutes=120,
    recurrence=[build_rrule_monthly(byday="1FR", count=12)]
)

# "Her gün sabah 9'da email check"
create_event(
    summary="Email Check",
    start="2026-02-23T09:00:00+03:00",
    duration_minutes=30,
    recurrence=[build_rrule_daily(count=30)]
)

# "15 Şubat'tan itibaren her hafta Çarşamba"
create_event(
    summary="Haftalık Toplantı",
    start="2026-02-19T14:00:00+03:00",
    duration_minutes=60,
    recurrence=["RRULE:FREQ=WEEKLY;BYDAY=WE;UNTIL=20260515T140000Z"]
)

# "Her 2 haftada bir Salı sprint planning"
create_event(
    summary="Sprint Planning",
    start="2026-02-24T10:00:00+03:00",
    duration_minutes=120,
    recurrence=[build_rrule_weekly(byday=["TU"], count=6, interval=2)]
)
```

### Validation

The `recurrence` parameter is validated:
- Must be a list of strings
- Each string must start with `"RRULE:"`
- Each string must contain `"FREQ="`
- Helper functions validate parameters (e.g., weekday codes, day ranges)

```python
# Invalid examples (will raise ValueError)
create_event(
    summary="Test",
    start="2026-02-23T10:00:00+03:00",
    recurrence="RRULE:FREQ=DAILY;COUNT=10"  # ❌ Not a list
)

create_event(
    summary="Test",
    start="2026-02-23T10:00:00+03:00",
    recurrence=["FREQ=DAILY;COUNT=10"]  # ❌ Missing "RRULE:" prefix
)

build_rrule_weekly(byday=["MONDAY"], count=10)  # ❌ Invalid weekday (use "MO")
build_rrule_monthly(byday="1FR", bymonthday=15, count=12)  # ❌ Cannot use both
```
