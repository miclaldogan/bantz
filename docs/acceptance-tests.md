# Acceptance Tests - Jarvis V2

> Bu doküman V2 MVP için detaylı acceptance test senaryolarını içerir.
> 
> Bağlantılı: [jarvis-roadmap-v2.md](jarvis-roadmap-v2.md)

---

## Senaryo 1: Araştırma + Özet

**Komut:** "Bantz, OpenAI CEO yeni model dedi, araştır"

### Akış

```
┌─────────────────────────────────────────────────────────────┐
│  User: "Bantz, OpenAI CEO yeni model dedi, araştır"        │
│                                                             │
│  [0.0s] Wake word algılandı                                │
│  [0.1s] ASR tamamlandı                                     │
│  [0.2s] Bantz: "Araştırıyorum efendim..."        ← ACK     │
│                                                             │
│  [3-10s] Web araması yapılıyor...                          │
│         → Event: source.found (kaynak 1)                   │
│         → Event: source.found (kaynak 2)                   │
│         → Overlay: Kaynak kartları gösteriliyor            │
│                                                             │
│  [15-30s] Kaynaklar karşılaştırılıyor...                   │
│          → Event: summarizing                               │
│          → Özet hazırlanıyor                               │
│                                                             │
│  [≤30s] Bantz: "OpenAI CEO Sam Altman, yeni GPT-5         │
│          modelini duyurdu. Reuters ve TechCrunch'a         │
│          göre..."                                           │
│         → Overlay: Özet + Confidence + Timestamp           │
└─────────────────────────────────────────────────────────────┘
```

### Metrikler

| Metrik | Hedef | Ölçüm Yöntemi | Tolerans |
|--------|-------|---------------|----------|
| ACK süresi | ≤ 200ms | `time.time()` delta: voice_end → tts_start | +50ms |
| İlk kaynak bulma | 3-10s | Event timestamp: `source.found` | - |
| Kaynak sayısı | ≥ 2 | `len(result.sources)` | - |
| Özet süresi | ≤ 30s | Event timestamp: `result.ready` | +5s |
| Confidence score | 0.0-1.0 | `result.confidence` | - |

### Overlay Gereksinimleri

| Element | Gerekli Alanlar | Örnek |
|---------|-----------------|-------|
| Kaynak Kartı | başlık, URL, tarih, domain | "OpenAI announces...", reuters.com, 2026-01-27 |
| Özet Paneli | text, confidence, timestamp | "GPT-5 duyuruldu...", 0.85, 14:32 |
| Status Ticker | current_step | "Kaynaklar karşılaştırılıyor..." |

### Test Kodu

```python
async def test_scenario_1_research_and_summarize():
    """Senaryo 1: Araştırma + Özet"""
    query = "OpenAI CEO yeni model dedi, araştır"
    
    start_time = time.time()
    
    # ACK timing
    ack_event = await wait_for_event("ack")
    ack_time_ms = (ack_event.timestamp - start_time) * 1000
    assert ack_time_ms <= 200, f"ACK too slow: {ack_time_ms}ms"
    
    # Source collection
    sources = []
    async for event in event_stream(timeout=15):
        if event.type == "source.found":
            sources.append(event.data)
    assert len(sources) >= 2, f"Not enough sources: {len(sources)}"
    
    # Summary timing
    result_event = await wait_for_event("result.ready", timeout=30)
    summary_time = result_event.timestamp - start_time
    assert summary_time <= 30, f"Summary too slow: {summary_time}s"
    
    # Content validation
    result = result_event.data
    assert "confidence" in result
    assert 0.0 <= result["confidence"] <= 1.0
    assert "sources" in result
    assert len(result["sources"]) >= 2
```

---

## Senaryo 2: Hava + Takvim Entegrasyonu

**Komut:** "Bugün dışarı çıkabilir miyim?"

### Akış

```
┌─────────────────────────────────────────────────────────────┐
│  User: "Bugün dışarı çıkabilir miyim?"                     │
│                                                             │
│  [0.2s] Bantz: "Bakıyorum efendim..."            ← ACK     │
│                                                             │
│  [1-3s] Weather tool çağrılıyor...                         │
│         → Sonuç: 18°C, %30 yağmur                          │
│                                                             │
│  [3s] Bantz: "Bugün 18 derece, hafif yağmur olasılığı     │
│        var. Takvimize bakabilir miyim planlarınız          │
│        için?"                              ← İZİN İSTEME   │
│                                                             │
│  User: "Evet, bak"                                          │
│                                                             │
│  [5s] Calendar tool çağrılıyor...                          │
│        → Sonuç: 14:00 toplantı, 18:00 boş                  │
│                                                             │
│  [7s] Bantz: "14:00'te toplantınız var ama akşam           │
│        boşsunuz. Yağmur ihtimali düşük, şemsiyeyle         │
│        çıkabilirsiniz."                                     │
└─────────────────────────────────────────────────────────────┘
```

### Permission Flow

```python
# Permission check
permission_request = PermissionRequest(
    action="calendar_access",
    level=PermissionLevel.MEDIUM,
    description="Takvimize bakabilir miyim?",
    remember_key="calendar_read"
)

# User'a sormalı (MEDIUM level, ilk sefer)
decision = await permission_engine.check(permission_request)
if not decision.allowed:
    # Ask user
    user_response = await ask_user("Takvimize bakabilir miyim?")
    if user_response.positive:
        await permission_engine.remember_choice(
            permission_request, 
            allowed=True,
            duration=timedelta(days=7)  # 1 hafta hatırla
        )
```

### Test Kodu

```python
async def test_scenario_2_weather_calendar_permission():
    """Senaryo 2: Hava + Takvim + İzin İsteme"""
    query = "Bugün dışarı çıkabilir miyim?"
    
    # Weather tool should be called first (LOW permission)
    weather_event = await wait_for_event("tool.called", 
                                          filter=lambda e: e.data["tool"] == "weather")
    assert weather_event is not None
    
    # Permission should be requested for calendar (MEDIUM)
    permission_event = await wait_for_event("permission.requested")
    assert permission_event.data["action"] == "calendar_access"
    assert permission_event.data["level"] == "medium"
    
    # Simulate user approval
    await simulate_user_response("evet")
    
    # Calendar tool should be called after approval
    calendar_event = await wait_for_event("tool.called",
                                           filter=lambda e: e.data["tool"] == "calendar")
    assert calendar_event is not None
    
    # Final result should combine both
    result = await wait_for_event("result.ready")
    assert "hava" in result.data["text"].lower() or "derece" in result.data["text"]
    assert "toplantı" in result.data["text"].lower() or "takvim" in result.data["text"]
```

---

## Senaryo 3: Roadmap/Plan Oluşturma

**Komut:** "Çarşambaya ödev yetişecek, roadmap hazırla"

### Akış

```
┌─────────────────────────────────────────────────────────────┐
│  User: "Çarşambaya ödev yetişecek, roadmap hazırla"        │
│                                                             │
│  [0.2s] Bantz: "Planı hazırlıyorum efendim..."    ← ACK    │
│                                                             │
│  [1s] Deadline analizi: Bugün Pazartesi → Çarşamba = 2 gün│
│                                                             │
│  [2s] Bantz: "Takvim ve mevcut iş yükünüze bakabilir      │
│        miyim daha iyi bir plan yapabilmek için?"           │
│                                                  ← İZİN    │
│                                                             │
│  User: "Bak"                                                │
│                                                             │
│  [4s] Calendar + Tasks analizi...                          │
│        → Progress event: "Takvim analiz ediliyor..."       │
│        → Progress event: "Plan oluşturuluyor..."           │
│                                                             │
│  [8s] Bantz: "İşte planınız:                               │
│        - Pazartesi: Araştırma + outline (3 saat)           │
│        - Salı: Yazım (4 saat)                              │
│        - Çarşamba sabah: Son kontrol + buffer (2 saat)     │
│        Toplam 9 saat, buffer dahil."                       │
│                                                             │
│  Overlay: Gün-gün plan kartları gösteriliyor               │
└─────────────────────────────────────────────────────────────┘
```

### Progress Events

| Timestamp | Event Type | Message |
|-----------|------------|---------|
| 0.2s | ack | "Planı hazırlıyorum efendim..." |
| 1s | progress | "Deadline analiz ediliyor..." |
| 2s | permission.request | "Takvime bakabilir miyim?" |
| 3s | permission.granted | User approved |
| 4s | progress | "Takvim analiz ediliyor..." |
| 6s | progress | "Plan oluşturuluyor..." |
| 8s | result.ready | Final plan |

### Test Kodu

```python
async def test_scenario_3_roadmap_with_permission():
    """Senaryo 3: Roadmap + Progress + İzin"""
    query = "Çarşambaya ödev yetişecek, roadmap hazırla"
    
    # Collect all progress events
    progress_events = []
    
    async for event in event_stream(timeout=15):
        if event.type == "progress":
            progress_events.append(event)
        elif event.type == "permission.requested":
            # Verify permission is asked before calendar access
            assert event.data["level"] in ["medium", "high"]
            await simulate_user_response("evet")
        elif event.type == "result.ready":
            break
    
    # Should have multiple progress events
    assert len(progress_events) >= 2, "Not enough progress updates"
    
    # Result should contain day-by-day plan
    result = await get_last_result()
    plan_text = result["text"].lower()
    
    # Check for deadline awareness
    assert any(day in plan_text for day in ["pazartesi", "salı", "çarşamba"])
    
    # Check for buffer time mention
    assert "buffer" in plan_text or "kontrol" in plan_text
```

---

## Ortak Gereksinimler

### Event Types

```python
class EventType(Enum):
    ACK = "ack"                      # İlk onay
    PROGRESS = "progress"            # İlerleme güncellemesi
    SOURCE_FOUND = "source.found"    # Kaynak bulundu
    SUMMARIZING = "summarizing"      # Özet hazırlanıyor
    PERMISSION_REQUESTED = "permission.requested"
    PERMISSION_GRANTED = "permission.granted"
    PERMISSION_DENIED = "permission.denied"
    TOOL_CALLED = "tool.called"      # Tool çağrıldı
    TOOL_RESULT = "tool.result"      # Tool sonucu
    RESULT_READY = "result.ready"    # Final sonuç
    ERROR = "error"                  # Hata
```

### Timing Constants

```python
# src/bantz/core/timing.py
class TimingRequirements:
    """V2 MVP timing requirements"""
    
    # ACK (acknowledgment) - TTS "Anladım" response
    ACK_MAX_MS = 200  # 0.2 saniye
    
    # Source finding
    FIRST_SOURCE_MIN_S = 3   # Minimum (gerçekçi beklenti)
    FIRST_SOURCE_MAX_S = 10  # Maximum
    
    # Summary generation
    SUMMARY_MAX_S = 30  # Maximum özet süresi
    
    # Permission
    PERMISSION_PROMPT_REQUIRED = True
    
    # Progress updates
    PROGRESS_UPDATE_INTERVAL_S = 3  # Her 3 saniyede update
    
    # Timeouts
    TOOL_TIMEOUT_S = 60  # Tool execution timeout
    USER_RESPONSE_TIMEOUT_S = 30  # User input bekleme
```

---

## Test Çalıştırma

```bash
# Tüm acceptance testleri
pytest tests/test_acceptance.py -v

# Specific senaryo
pytest tests/test_acceptance.py::test_scenario_1_research_and_summarize -v

# Timing testleri
pytest tests/test_acceptance.py -k "timing" -v
```
