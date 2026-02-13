# Calendar & Gmail Issues (Epic)

**Created:** 31 Ocak 2026  
**Owner:** @miclaldogan  
**Status:** Draft → Ready for GitHub  
**Total Issues:** 15 (#162-#176)

---

## 📅 Calendar Issues (#162-#167)

### Issue #162: Calendar Event Modification/Update Tool

**Epic:** Calendar Integration  
**Priority:** P1  
**Complexity:** Medium (3-5 days)  
**Dependencies:** Existing calendar read/create tools

#### Problem
Kullanıcı oluşturduğu etkinliği değiştirmek istediğinde (zaman, yer, başlık) şu an delete + recreate yapıyor. Google Calendar API'de PATCH endpoint'i var ama henüz tool olarak implement edilmemiş.

**User Story:**
```
"Yarınki toplantıyı saat 15:00'e ertele"
"Pazartesi 10'daki görüşmenin yerini Zoom'a çevir"
"Cuma saat 14'teki etkinliğin adını 'Sprint Planning' yap"
```

#### Acceptance Criteria
- [ ] `calendar_update(event_id, updates)` tool function
- [ ] Updates dict: `{summary?, start?, end?, location?, description?}`
- [ ] Partial update support (sadece değişen field'lar)
- [ ] Policy check: MODERATE risk (write operation)
- [ ] Confirmation prompt: "Toplantıyı değiştirmek istiyorsunuz, onaylıyor musunuz?"
- [ ] Error handling: event_id bulunamadı, invalid time range
- [ ] Unit test: 5+ senaryolar (başlık, zaman, yer, combo)
- [ ] Integration test: gerçek Calendar API ile dry-run

#### Technical Details
```python
# src/bantz/google/calendar.py
def update_event(
    *,
    event_id: str,
    calendar_id: str = "primary",
    summary: Optional[str] = None,
    start: Optional[str] = None,  # RFC3339
    end: Optional[str] = None,
    location: Optional[str] = None,
    description: Optional[str] = None,
    service = None,
) -> dict:
    """Update an existing calendar event with PATCH API."""
    body = {}
    if summary is not None:
        body["summary"] = summary
    if start and end:
        body["start"] = {"dateTime": _normalize_rfc3339(start)}
        body["end"] = {"dateTime": _normalize_rfc3339(end)}
    if location is not None:
        body["location"] = location
    if description is not None:
        body["description"] = description
    
    return service.events().patch(
        calendarId=calendar_id,
        eventId=event_id,
        body=body
    ).execute()
```

#### Router Integration
```json
{
  "route": "calendar",
  "calendar_intent": "update",
  "tool_plan": [
    {"tool": "calendar_list", "params": {"time_min": "tomorrow 00:00"}},
    {"tool": "calendar_update", "params": {"event_id": "...", "start": "2026-02-01T15:00:00+03:00"}}
  ],
  "requires_confirmation": true
}
```

---

### Issue #163: Calendar Event Deletion/Cancellation Tool

**Epic:** Calendar Integration  
**Priority:** P1  
**Complexity:** Small (1-2 days)  
**Dependencies:** calendar_list (event_id lookup)

#### Problem
Kullanıcı etkinliği iptal etmek istediğinde şu an manuel silmesi gerekiyor. DELETE endpoint simple ama risk sınıfı DESTRUCTIVE olduğu için double confirmation lazım.

**User Stories:**
```
"Yarınki toplantıyı iptal et"
"Cuma 14:00'deki görüşmeyi sil"
"Sprint retro etkinliğini kaldır"
```

#### Acceptance Criteria
- [ ] `calendar_delete(event_id)` tool function
- [ ] Policy: DESTRUCTIVE risk → **2-step confirmation**
- [ ] First prompt: "Toplantıyı silmek istiyorsunuz, emin misiniz?"
- [ ] Second prompt: "Son kez soruyorum, gerçekten silmek istiyor musunuz?"
- [ ] Error handling: event_id not found, API errors
- [ ] Audit log: deleted event details (summary, time) saved to memory
- [ ] Undo mechanism (future): store deleted event JSON for 24h
- [ ] Unit test: mock deletion + confirmation flow
- [ ] Integration test: dry-run + real delete (test calendar)

#### Technical Details
```python
def delete_event(*, event_id: str, calendar_id: str = "primary", service = None) -> dict:
    """Delete a calendar event (DESTRUCTIVE - requires double confirm)."""
    # Get event details before deletion for audit log
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    
    return {
        "status": "deleted",
        "deleted_event": {
            "summary": event.get("summary"),
            "start": event.get("start", {}).get("dateTime"),
            "end": event.get("end", {}).get("dateTime"),
        }
    }
```

---

### Issue #164: Calendar Multi-Day Event Support (All-Day Events)

**Epic:** Calendar Integration  
**Priority:** P2  
**Complexity:** Medium (3-4 days)  
**Dependencies:** Existing calendar tools

#### Problem
Şu an sadece time-based events (start/end dateTime) destekleniyor. All-day events (date only) Google Calendar'da farklı format kullanıyor (`start.date` vs `start.dateTime`). Kullanıcı "yarın tüm gün toplantı" dediğinde broken.

**User Stories:**
```
"Pazartesi tüm gün konferans ekle"
"23-25 Şubat arası tatil işaretle"
"Cuma günü home office olarak belirt"
```

#### Acceptance Criteria
- [ ] `calendar_create` all-day event support: `{"date": "2026-02-03"}`
- [ ] Multi-day span: `start.date = "2026-02-23"`, `end.date = "2026-02-26"` (exclusive)
- [ ] Router intent: "tüm gün", "all day", "bütün gün" detection
- [ ] `calendar_list` all-day event parsing (currently returns `None` for date-only)
- [ ] Busy interval calculation: all-day blocks entire 00:00-23:59
- [ ] Unit test: single day, multi-day, date boundary edge cases
- [ ] Integration test: create + list + verify all-day format

#### Technical Details
```python
# All-day event format
{
  "summary": "Konferans",
  "start": {"date": "2026-02-03"},  # No dateTime
  "end": {"date": "2026-02-04"}     # Exclusive (next day)
}

# Multi-day all-day event
{
  "summary": "Tatil",
  "start": {"date": "2026-02-23"},
  "end": {"date": "2026-02-26"}  # Feb 23-25 (3 days)
}
```

---

### Issue #165: Calendar Recurring Events (RRULE Support)

**Epic:** Calendar Integration  
**Priority:** P2  
**Complexity:** Large (5-7 days)  
**Dependencies:** calendar_create, RFC5545 RRULE library

#### Problem
Kullanıcı tekrarlayan etkinlik oluşturmak istediğinde (her hafta, her ay, vb.) şu an desteklenmiyor. Google Calendar API `recurrence` field'ı RFC5545 RRULE string'leri kullanıyor.

**User Stories:**
```
"Her Pazartesi saat 10'da standup ekle"
"Ayın ilk Cuma günü retrospektif koy"
"Her gün sabah 9'da email check etkinliği"
"15 Şubat'tan itibaren her hafta Çarşamba code review"
```

#### Acceptance Criteria
- [ ] RRULE generation: `FREQ=WEEKLY;BYDAY=MO` (her Pazartesi)
- [ ] Router intent detection: "her", "tekrarlayan", "recurring", "weekly"
- [ ] Frequency patterns: DAILY, WEEKLY, MONTHLY
- [ ] BYDAY support: MO, TU, WE, TH, FR, SA, SU
- [ ] COUNT/UNTIL termination: "10 hafta boyunca", "Mart sonuna kadar"
- [ ] `calendar_create` recurrence parameter: `["RRULE:FREQ=WEEKLY;BYDAY=MO"]`
- [ ] Error handling: invalid RRULE format
- [ ] Unit test: 8+ RRULE patterns (daily, weekly, monthly, BYDAY combos)
- [ ] Integration test: create recurring + list instances

#### Technical Details
```python
# Weekly recurring event (every Monday at 10:00)
{
  "summary": "Standup",
  "start": {"dateTime": "2026-02-03T10:00:00+03:00"},
  "end": {"dateTime": "2026-02-03T10:30:00+03:00"},
  "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=10"]
}

# Monthly recurring (first Friday)
{
  "recurrence": ["RRULE:FREQ=MONTHLY;BYDAY=1FR"]
}
```

**Library:** Consider `python-dateutil` for RRULE parsing/generation

---

### Issue #166: Calendar Time Zone Intelligence (Multi-TZ Support)

**Epic:** Calendar Integration  
**Priority:** P2  
**Complexity:** Medium (4-5 days)  
**Dependencies:** Timezone database (pytz/zoneinfo)

#### Problem
Şu an hardcoded `timezone.utc` veya sistem timezone'u kullanılıyor. Kullanıcı farklı zaman dilimlerinde etkinlik oluşturmak istediğinde (seyahat, global meetings) broken.

**User Stories:**
```
"New York saati ile saat 15'te meeting ekle"
"Pacific Time 9 AM'de call koy"
"İstanbul saati ile yarın 18:00 yemek"
"Londra saatiyle Pazartesi 14:00 demo"
```

#### Acceptance Criteria
- [ ] Timezone detection from natural language: "New York", "PST", "GMT+1"
- [ ] Timezone mapping: "Istanbul" → "Europe/Istanbul", "PST" → "America/Los_Angeles"
- [ ] RFC3339 timezone conversion: user input → correct offset
- [ ] Display timezone in confirmation: "New York saati (UTC-5) ile 15:00"
- [ ] Daylight Saving Time (DST) awareness
- [ ] Calendar API `timeZone` field support
- [ ] Unit test: 10+ timezone scenarios (EST, PST, CET, JST, etc.)
- [ ] Error handling: ambiguous timezone names

#### Technical Details
```python
from zoneinfo import ZoneInfo

# Convert "New York 15:00" to RFC3339
tz = ZoneInfo("America/New_York")
dt = datetime(2026, 2, 3, 15, 0, tzinfo=tz)
rfc3339 = dt.isoformat()  # "2026-02-03T15:00:00-05:00"

# Calendar API event
{
  "start": {
    "dateTime": "2026-02-03T15:00:00-05:00",
    "timeZone": "America/New_York"
  }
}
```

**Timezone Aliases:**
```python
TZ_ALIASES = {
    "new york": "America/New_York",
    "pst": "America/Los_Angeles",
    "istanbul": "Europe/Istanbul",
    "london": "Europe/London",
}
```

---

### Issue #167: Calendar Smart Conflict Detection & Auto-Rescheduling

**Epic:** Calendar Integration  
**Priority:** P1  
**Complexity:** Large (6-8 days)  
**Dependencies:** calendar_list, busy interval logic

#### Problem
Kullanıcı etkinlik oluşturmaya çalıştığında çakışma olursa "busy" hatası alıyor ama alternatif önerilmiyor. Jarvis "akıllı asistan" olarak boş slotları önermeli.

**User Stories:**
```
"Yarın saat 14'te 1 saatlik toplantı ekle"
→ Jarvis: "14:00'te başka bir toplantınız var. 15:30 veya 16:00 uygun mu?"

"Bu hafta John ile görüşme ayarla"
→ Jarvis: "Pazartesi 10:00, Çarşamba 14:00 veya Cuma 11:00 boş."
```

#### Acceptance Criteria
- [ ] Conflict detection: new event overlaps existing events
- [ ] Busy interval merge: combine overlapping events
- [ ] Smart slot finder: find next 3 available slots (configurable duration)
- [ ] Preferred time windows: "morning" (08:00-12:00), "afternoon" (13:00-18:00)
- [ ] Multi-day search: if today full, check tomorrow, next 7 days
- [ ] Confirmation with alternatives: "14:00 dolu, 15:30 nasıl?"
- [ ] Auto-reschedule mode (future): "En yakın boş slota koy"
- [ ] Unit test: overlapping events, gap finding, edge cases (end of day)
- [ ] Integration test: real calendar + conflict scenarios

#### Technical Details
```python
def find_available_slots(
    *,
    start_date: date,
    end_date: date,
    duration_minutes: int = 60,
    preferred_hours: tuple[int, int] = (8, 18),
    max_slots: int = 3,
) -> list[dict]:
    """Find available time slots in calendar."""
    # 1. Fetch events in date range
    # 2. Build busy intervals
    # 3. Find gaps >= duration_minutes within preferred_hours
    # 4. Return top max_slots options
    
    return [
        {"start": "2026-02-03T15:30:00+03:00", "end": "2026-02-03T16:30:00+03:00"},
        {"start": "2026-02-03T17:00:00+03:00", "end": "2026-02-03T18:00:00+03:00"},
    ]
```

---

## 📧 Gmail Issues (#168-#176)

### Issue #168: Gmail OAuth Setup & Authentication Flow

**Epic:** Gmail Integration  
**Priority:** P0 (Foundation)  
**Complexity:** Medium (3-4 days)  
**Dependencies:** Google Cloud Console project, OAuth2 client

#### Problem
Gmail API kullanmak için OAuth2 authentication gerekiyor. Google Calendar ile aynı pattern ama farklı scope'lar. Initial setup + token refresh logic lazım.

**Scope Requirements:**
```python
GMAIL_READONLY_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.metadata"
]

GMAIL_SEND_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose"
]

GMAIL_MODIFY_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify"  # Label, archive, delete
]
```

#### Acceptance Criteria
- [ ] Google Cloud Console project setup guide (docs)
- [ ] OAuth2 client credentials: `client_secret_gmail.json`
- [ ] Token storage: `~/.config/bantz/google/gmail_token.json`
- [ ] Automatic token refresh (60-day expiry handling)
- [ ] Scope escalation: start readonly → upgrade to send when needed
- [ ] `src/bantz/google/gmail_auth.py` module
- [ ] Environment variables: `BANTZ_GMAIL_CLIENT_SECRET`, `BANTZ_GMAIL_TOKEN_PATH`
- [ ] Unit test: mock OAuth flow
- [ ] Integration test: real OAuth (manual, documented in guide)

#### Technical Details
```python
# src/bantz/google/gmail_auth.py
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

def authenticate_gmail(*, scopes: list[str], token_path: str, secret_path: str):
    """Gmail OAuth2 authentication with token refresh."""
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, scopes)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(secret_path, scopes)
            creds = flow.run_local_server(port=0)
        
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    
    return build("gmail", "v1", credentials=creds)
```

---

### Issue #169: Gmail Inbox Listing & Unread Count Tool

**Epic:** Gmail Integration  
**Priority:** P0  
**Complexity:** Small (2-3 days)  
**Dependencies:** #168 (Gmail auth)

#### Problem
Kullanıcı "okunmamış emaillerim var mı?" dediğinde Jarvis cevap veremiyor. Basic inbox listing + unread count gerekiyor.

**User Stories:**
```
"Okunmamış emaillerim var mı?"
→ "5 okunmamış mail var efendim."

"En son gelen 3 maili söyle"
→ "1. Ali'den: Proje güncelleme, 2. ..."
```

#### Acceptance Criteria
- [ ] `gmail_list_messages(max_results=10, unread_only=False)` tool
- [ ] Return: `[{id, threadId, from, subject, snippet, date}]`
- [ ] Unread count: `q="is:unread"` query
- [ ] Pagination support: nextPageToken handling
- [ ] Date parsing: RFC2822 → human readable
- [ ] Snippet truncation: max 100 chars
- [ ] Policy: SAFE (read-only)
- [ ] Unit test: mock Gmail API responses
- [ ] Integration test: real inbox (test account)

#### Technical Details
```python
def list_messages(*, max_results: int = 10, unread_only: bool = False, service):
    """List Gmail inbox messages."""
    query = "is:unread" if unread_only else "in:inbox"
    
    results = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=max_results
    ).execute()
    
    messages = []
    for msg in results.get("messages", []):
        detail = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()
        
        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        messages.append({
            "id": msg["id"],
            "from": headers.get("From"),
            "subject": headers.get("Subject"),
            "snippet": detail.get("snippet", "")[:100],
            "date": headers.get("Date"),
        })
    
    return {"messages": messages, "unread_count": len(results.get("messages", []))}
```

---

### Issue #170: Gmail Message Reading & Thread View

**Epic:** Gmail Integration  
**Priority:** P1  
**Complexity:** Medium (3-4 days)  
**Dependencies:** #169 (list messages)

#### Problem
Kullanıcı specific bir emaili okumak istediğinde sadece snippet görüyor. Full body + attachments info lazım. Thread view için multi-message context.

**User Stories:**
```
"Ali'den gelen maili oku"
→ (Full email body + attachments list)

"Bu emaile cevapları göster"
→ (Thread içindeki tüm mesajlar)
```

#### Acceptance Criteria
- [ ] `gmail_get_message(message_id)` tool
- [ ] Full body extraction: plain text + HTML fallback
- [ ] Attachment detection: `[{filename, mimeType, size}]`
- [ ] Thread expansion: get all messages in thread
- [ ] Base64 decoding (Gmail API returns base64url)
- [ ] Large body handling: truncate after 5000 chars (with "..." indicator)
- [ ] Policy: SAFE (read-only)
- [ ] Unit test: plain text, HTML, attachments, thread
- [ ] Integration test: real messages

#### Technical Details
```python
def get_message(*, message_id: str, service) -> dict:
    """Get full Gmail message with body and attachments."""
    msg = service.users().messages().get(
        userId="me",
        id=message_id,
        format="full"
    ).execute()
    
    # Extract body (plain text preferred, HTML fallback)
    body = ""
    if "parts" in msg["payload"]:
        for part in msg["payload"]["parts"]:
            if part["mimeType"] == "text/plain":
                body = base64.urlsafe_b64decode(part["body"]["data"]).decode()
                break
    
    # Extract attachments
    attachments = []
    for part in msg["payload"].get("parts", []):
        if "filename" in part and part["filename"]:
            attachments.append({
                "filename": part["filename"],
                "mimeType": part["mimeType"],
                "size": part["body"].get("size", 0)
            })
    
    return {
        "id": msg["id"],
        "threadId": msg["threadId"],
        "body": body[:5000],  # Truncate
        "attachments": attachments
    }
```

---

### Issue #171: Gmail Send Email Tool (Compose & Send)

**Epic:** Gmail Integration  
**Priority:** P1  
**Complexity:** Medium (4-5 days)  
**Dependencies:** #168 (auth with send scope)

#### Problem
Kullanıcı email göndermek istediğinde Jarvis yapamıyor. Gmail API `messages.send` endpoint'i RFC2822 format istiyor (MIME encoding).

**User Stories:**
```
"Ali'ye mail gönder: proje bitti, tebrikler"
"john@example.com adresine demo linki yolla"
"Ekibe özet maili at: bugün 5 issue kapandı"
```

#### Acceptance Criteria
- [ ] `gmail_send(to, subject, body, cc=None, bcc=None)` tool
- [ ] MIME message construction: RFC2822 format
- [ ] Base64url encoding (Gmail API requirement)
- [ ] Multiple recipients: comma-separated or list
- [ ] CC/BCC support
- [ ] Policy: MODERATE risk (send operation)
- [ ] Confirmation prompt: "Ali'ye mail göndermek istiyorsunuz, onaylıyor musunuz?"
- [ ] Draft save option (future): save as draft first
- [ ] Unit test: MIME generation, encoding
- [ ] Integration test: send real test email

#### Technical Details
```python
import base64
from email.mime.text import MIMEText

def send_email(*, to: str, subject: str, body: str, service) -> dict:
    """Send Gmail message."""
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    
    return service.users().messages().send(
        userId="me",
        body={"raw": raw}
    ).execute()
```

---

### Issue #172: Gmail Draft Management (Save & Edit Drafts)

**Epic:** Gmail Integration  
**Priority:** P2  
**Complexity:** Medium (3-4 days)  
**Dependencies:** #171 (send email)

#### Problem
Kullanıcı email göndermeden önce taslak kaydetmek istiyor. Gmail API `drafts` endpoint'i var ama henüz tool yok.

**User Stories:**
```
"Ali'ye mail taslağı hazırla: proje güncellemesi"
"Taslaklarımı göster"
"2. taslağı gönder"
"3. taslağı sil"
```

#### Acceptance Criteria
- [ ] `gmail_create_draft(to, subject, body)` tool
- [ ] `gmail_list_drafts(max_results=10)` tool
- [ ] `gmail_update_draft(draft_id, updates)` tool
- [ ] `gmail_send_draft(draft_id)` tool → convert to sent message
- [ ] `gmail_delete_draft(draft_id)` tool
- [ ] Policy: SAFE (drafts), MODERATE (send draft)
- [ ] Unit test: CRUD operations on drafts
- [ ] Integration test: create + edit + send workflow

#### Technical Details
```python
def create_draft(*, to: str, subject: str, body: str, service) -> dict:
    """Create Gmail draft."""
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    
    return service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}}
    ).execute()
```

---

### Issue #173: Gmail Label & Archive Management

**Epic:** Gmail Integration  
**Priority:** P2  
**Complexity:** Small (2-3 days)  
**Dependencies:** #169 (list messages)

#### Problem
Kullanıcı emaili organize etmek istiyor: label ekle, archive, mark as read/unread. Gmail API `modify` endpoint'i label değişikliği yapıyor.

**User Stories:**
```
"Bu maili 'önemli' label'ı ekle"
"Okunmamış maillerimi oku olarak işaretle"
"Ali'den gelen tüm mailleri arşivle"
```

#### Acceptance Criteria
- [ ] `gmail_add_label(message_id, label)` tool
- [ ] `gmail_remove_label(message_id, label)` tool
- [ ] `gmail_archive(message_id)` tool → remove INBOX label
- [ ] `gmail_mark_read(message_id)` / `gmail_mark_unread(message_id)` tools
- [ ] Label list: fetch available labels (INBOX, SPAM, TRASH, custom)
- [ ] Batch operations: modify multiple messages at once
- [ ] Policy: SAFE (labels), MODERATE (archive)
- [ ] Unit test: label operations
- [ ] Integration test: real label modifications

#### Technical Details
```python
def add_label(*, message_id: str, label: str, service) -> dict:
    """Add label to Gmail message."""
    return service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": [label]}
    ).execute()

def archive_message(*, message_id: str, service) -> dict:
    """Archive message (remove INBOX label)."""
    return service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"removeLabelIds": ["INBOX"]}
    ).execute()
```

---

### Issue #174: Gmail Smart Search & Filter Tool

**Epic:** Gmail Integration  
**Priority:** P1  
**Complexity:** Medium (3-4 days)  
**Dependencies:** #169 (list messages)

#### Problem
Kullanıcı "geçen hafta Ali'den gelen mailleri bul" dediğinde basic list yetersiz. Gmail API query syntax (from:, subject:, after:, before:) kullanmalı.

**User Stories:**
```
"Ali'den gelen mailleri bul"
"Geçen hafta proje hakkında gelen mailler"
"Attachment'lı tüm maillerimi göster"
"John veya Mary'den gelen okunmamış mailler"
```

#### Acceptance Criteria
- [ ] Natural language → Gmail query conversion
- [ ] Query patterns: `from:`, `to:`, `subject:`, `after:`, `before:`, `has:attachment`
- [ ] Date parsing: "geçen hafta" → `after:2026-01-24`
- [ ] Multi-criteria: `from:ali subject:proje after:2026-01-24`
- [ ] Saved search templates: frequent patterns (inbox zero, unread from boss)
- [ ] Policy: SAFE (search)
- [ ] Unit test: 10+ query patterns
- [ ] Integration test: real search queries

#### Technical Details
```python
# Natural language → Gmail query mapping
NL_TO_QUERY = {
    "Ali'den": "from:ali@example.com",
    "geçen hafta": f"after:{(date.today() - timedelta(days=7)).isoformat()}",
    "attachment": "has:attachment",
    "okunmamış": "is:unread",
}

def search_messages(*, query: str, max_results: int = 20, service) -> list:
    """Search Gmail with advanced query syntax."""
    # Convert NL to Gmail query
    gmail_query = convert_nl_to_query(query)
    
    results = service.users().messages().list(
        userId="me",
        q=gmail_query,
        maxResults=max_results
    ).execute()
    
    return process_messages(results.get("messages", []), service)
```

---

### Issue #175: Gmail Attachment Download & Preview

**Epic:** Gmail Integration  
**Priority:** P2  
**Complexity:** Medium (4-5 days)  
**Dependencies:** #170 (message reading)

#### Problem
Kullanıcı emaildeki attachment'ı indirmek veya preview yapmak istiyor. Gmail API attachment'ları base64 encoded döndürüyor.

**User Stories:**
```
"Bu maildeki PDF'i indir"
"Attachment'ları göster"
"İlk attachment'ı aç"
```

#### Acceptance Criteria
- [ ] `gmail_download_attachment(message_id, attachment_id, save_path)` tool
- [ ] Base64 decoding + file write
- [ ] Attachment metadata: filename, size, mimeType
- [ ] Preview support (future): images inline, PDFs viewer
- [ ] Virus scan warning: "Attachment downloaded, scan before opening"
- [ ] Size limit: warn if >10MB
- [ ] Policy: MODERATE (download to disk)
- [ ] Unit test: mock attachment download
- [ ] Integration test: real attachment (test account)

#### Technical Details
```python
def download_attachment(
    *,
    message_id: str,
    attachment_id: str,
    save_path: str,
    service
) -> dict:
    """Download Gmail attachment."""
    attachment = service.users().messages().attachments().get(
        userId="me",
        messageId=message_id,
        id=attachment_id
    ).execute()
    
    data = base64.urlsafe_b64decode(attachment["data"])
    
    with open(save_path, "wb") as f:
        f.write(data)
    
    return {
        "status": "downloaded",
        "path": save_path,
        "size": len(data)
    }
```

---

### Issue #176: Gmail Auto-Reply & Smart Reply Suggestions

**Epic:** Gmail Integration  
**Priority:** P2  
**Complexity:** Large (5-7 days)  
**Dependencies:** #170 (read message), #171 (send), LLM integration

#### Problem
Kullanıcı emaile hızlı cevap vermek istiyor. LLM ile context-aware reply draft oluştur + Gmail Smart Reply API integration (if available).

**User Stories:**
```
"Bu maile cevap ver: toplantı tamam"
"Ali'ye otomatik teşekkür maili yolla"
"Toplantı davetini kabul et (reply)"
```

#### Acceptance Criteria
- [ ] `gmail_generate_reply(message_id, user_intent)` tool
- [ ] LLM prompt: original email + user intent → reply draft
- [ ] Smart reply suggestions: 3 options (short, medium, detailed)
- [ ] Quote original message option
- [ ] Reply-all vs reply-to-sender detection
- [ ] Policy: MODERATE (generates draft first, requires confirmation)
- [ ] Integration: Gmail Smart Reply API (if quota allows)
- [ ] Unit test: reply generation logic
- [ ] Integration test: generate + send reply workflow

#### Technical Details
```python
def generate_reply(*, message_id: str, user_intent: str, llm_service, gmail_service) -> dict:
    """Generate smart reply using LLM."""
    # 1. Get original message
    original = get_message(message_id=message_id, service=gmail_service)
    
    # 2. LLM prompt
    prompt = f"""
    Original email:
    From: {original['from']}
    Subject: {original['subject']}
    Body: {original['body']}
    
    User wants to reply: {user_intent}
    
    Generate a professional email reply in Turkish.
    """
    
    reply_body = llm_service.generate(prompt)
    
    # 3. Create draft
    draft = create_draft(
        to=original["from"],
        subject=f"Re: {original['subject']}",
        body=reply_body,
        service=gmail_service
    )
    
    return {
        "draft_id": draft["id"],
        "preview": reply_body[:200]
    }
```

---

## Summary Table

| Issue # | Title | Priority | Complexity | Estimate |
|---------|-------|----------|------------|----------|
| #162 | Calendar Event Modification/Update | P1 | Medium | 3-5 days |
| #163 | Calendar Event Deletion/Cancellation | P1 | Small | 1-2 days |
| #164 | Calendar Multi-Day Events (All-Day) | P2 | Medium | 3-4 days |
| #165 | Calendar Recurring Events (RRULE) | P2 | Large | 5-7 days |
| #166 | Calendar Timezone Intelligence | P2 | Medium | 4-5 days |
| #167 | Calendar Conflict Detection & Auto-Reschedule | P1 | Large | 6-8 days |
| #168 | Gmail OAuth Setup & Auth Flow | P0 | Medium | 3-4 days |
| #169 | Gmail Inbox Listing & Unread Count | P0 | Small | 2-3 days |
| #170 | Gmail Message Reading & Thread View | P1 | Medium | 3-4 days |
| #171 | Gmail Send Email Tool | P1 | Medium | 4-5 days |
| #172 | Gmail Draft Management | P2 | Medium | 3-4 days |
| #173 | Gmail Label & Archive Management | P2 | Small | 2-3 days |
| #174 | Gmail Smart Search & Filter | P1 | Medium | 3-4 days |
| #175 | Gmail Attachment Download & Preview | P2 | Medium | 4-5 days |
| #176 | Gmail Auto-Reply & Smart Reply | P2 | Large | 5-7 days |

**Total:** 15 issues, ~51-70 days effort (with parallelization: ~4-6 weeks)

---

## Implementation Roadmap

### Phase 1: Calendar Enhancements (Week 1-2)
1. #163: Delete tool (destructive, quick win)
2. #162: Update tool (modify operations)
3. #167: Conflict detection (smart scheduling)

### Phase 2: Gmail Foundation (Week 2-3)
1. #168: OAuth setup (prerequisite)
2. #169: Inbox listing (basic read)
3. #170: Message reading (full context)

### Phase 3: Gmail Core Features (Week 3-4)
1. #171: Send email (compose)
2. #174: Smart search (filter)
3. #173: Labels & archive (organize)

### Phase 4: Advanced Features (Week 5-6)
1. #164: All-day events
2. #165: Recurring events
3. #172: Gmail drafts
4. #175: Attachments
5. #176: Auto-reply

### Phase 5: Polish & Timezone (Week 6+)
1. #166: Timezone intelligence
2. Integration tests
3. Documentation updates

---

## Testing Strategy

**Each issue requires:**
- [ ] Unit tests (mock APIs)
- [ ] Integration tests (real APIs, test accounts)
- [ ] Router integration tests (JSON schema validation)
- [ ] Confirmation flow tests (policy checks)
- [ ] Error handling scenarios (API failures, invalid inputs)

**Test accounts needed:**
- Gmail test account (disposable, for send/receive tests)
- Google Calendar test calendar (separate from personal)

---

## Dependencies

**External APIs:**
- Google Calendar API v3
- Gmail API v1
- Google OAuth2

**Python Libraries:**
```txt
google-auth>=2.0.0
google-auth-oauthlib>=0.5.0
google-auth-httplib2>=0.1.0
google-api-python-client>=2.0.0
python-dateutil>=2.8.0  # RRULE support
pytz>=2021.3  # Timezone support
```

**Configuration Files:**
- `~/.config/bantz/google/client_secret_gmail.json`
- `~/.config/bantz/google/gmail_token.json`
- `~/.config/bantz/google/calendar_token.json` (existing)

---

## Notes

- **Security:** Gmail send/modify operations require 2-step confirmation (destructive risk)
- **Rate limits:** Gmail API quota: 1 billion quota units/day (reasonable for single user)
- **Scope escalation:** Start with readonly, upgrade to send/modify when needed
- **Calendar vs Gmail auth:** Separate token files, different scopes
- **RRULE library:** Consider `python-dateutil` or custom parser
- **Timezone:** Use `zoneinfo` (Python 3.9+) for DST-aware conversions

**Ready for GitHub issue creation! 🚀**
