# Bantz → Jarvis Seviye Roadmap (v2)

Bu doküman, mevcut repo üstünde (repo sıfırlamadan) **Jarvis seviyesine** ilerlemek için aşırı detaylı yol haritasıdır.

Temel strateji:
- Repo aynı kalsın (history/issues boşa gitmesin)
- Büyük değişiklikleri **v2 mimarisi** olarak modülerleştirerek sok
- İstenirse monorepo içinde ayrı paket: `packages/bantz-core` (çekirdek), tool’lar, UI, voice

> Not: “düşünce zinciri” burada modelin iç muhakemesi değil; **iş günlüğü + plan adımları** şeklinde tasarlanır.

---

## Faz 0 — Ürün Tanımı ve “Done” kriterleri (1–2 gün)

**Hedef:** Ne yapınca “Jarvis MVP oldu” diyeceğiz?

### Kullanım senaryoları (Acceptance test)

1) “Bantz, OpenAI CEO yeni model dedi, araştır”
- ~0.2 sn: ACK (“Başlıyorum efendim.”)
- 3–10 sn: en az 2 kaynak bulur
- Kaynakları overlay’de kart olarak gösterir
- 30 sn: özet + “confidence” + tarih/saat

2) “Bugün dışarı çıkabilir miyim?”
- Weather tool → risk çıkarımı (yağış/rüzgar)
- “Takvime bakmamı ister misin?” şeklinde izinli proaktif öneri

3) “Çarşambaya ödev yetişecek, roadmap hazırla”
- Plan çıkarır
- Takvim/iş yükü analizine geçmeden önce izin ister
- Günlere bölünmüş çıktı + buffer time

### Çıktı standartları
- Her görev: `Plan → Action → Observation → Result` log formatında izlenebilir
- “Chain-of-thought” yerine: plan adımları + tool gözlemleri + karar gerekçeleri

---

## Faz 1 — Mimariyi “Agent OS” haline getirme (1 hafta)

**Hedef:** Tool’ların güvenilir çalıştığı bir orkestrasyon çekirdeği.

### 1.1. Proje yapısı (monorepo önerisi)
- `packages/`
  - `bantz-core/` (orchestrator, memory, policy, agent)
  - `bantz-tools/` (web, browser, weather, calendar, docs)
  - `bantz-ui/` (overlay panel)
  - `bantz-voice/` (wakeword, asr, tts, barge-in)
- `apps/`
  - `desktop/` (PyQt app)
  - `daemon/` (arka servis)

### 1.2. Event Bus + Job Manager (en kritik)
- Olay tipleri: `ACK, PROGRESS, FOUND, SUMMARIZING, QUESTION, RESULT, ERROR, RETRY, PAUSE, RESUME, CANCEL`
- Job state machine: `created → running → waiting_user → verifying → done/failed`

### 1.3. Interrupt / Barge-in
- Kullanıcı araya girince:
  - `PAUSE current` + `START child job (priority high)`
  - veya policy’ye göre `CANCEL`

**Done kriteri:**
- Uzun işte overlay + ses sürekli güncellenir
- “bekle” dediğinde job durur / alt job açılır

---

## Faz 2 — Tool Runtime: Güvenilir yürütme + fallback (1–2 hafta)

**Hedef:** Tarayıcı/requests/OS tool’ları kırılınca sistem ölmesin.

### 2.1. Tool arayüz standardı
Her tool sözleşmesi:
- `spec()` → name, input schema, risk level, requires_permission
- `run(input, context) -> ToolResult`

ToolResult:
- `status, data, citations, artifacts, logs, retryable`

### 2.2. Retry + Timeout + Circuit Breaker
- Timeout default: 20–60 sn
- Retry: exponential backoff (1s, 3s, 7s)
- Circuit breaker: aynı domain 3 hata → fallback

### 2.3. Web tool’ları katmanı
- `WebSearchTool` (requests/serp + reader)
- `BrowserAutomationTool` (Playwright/Selenium)
- `PageReaderTool` (readability + html2text)
- `SourceRanker` (domain güven skoru, tarih, çakışma)

**Done kriteri:**
- Browser takılsa bile requests fallback ile devam
- Her sonuç citation (URL + başlık + tarih) içerir

---

## Faz 3 — Bilgi doğrulama & kaynak yönetimi (1 hafta)

**Hedef:** “Jarvis doğru bilgi veriyor” hissi.

### 3.1. Cite-first pipeline
Query → 5–10 kaynak → filtrele → 2–4 seç → özetle

### 3.2. Çelişki tespiti
- Aynı iddia farklı mı?
- Tarihler tutuyor mu?
- Çelişki varsa açıkça söyle + neden emin olunamadığını belirt

### 3.3. Confidence score (heuristic)
- 2+ bağımsız güvenilir kaynak → 80+
- tek kaynak → 50–60
- yalnız sosyal medya → 30–40

**Done kriteri:**
- Sonuçlar kaynaklı
- Çelişki olursa gizlemez

---

## Faz 4 — Bellek & kişiselleştirme (2 hafta)

**Hedef:** Sürekli aynı kişiyle yaşayan asistan.

### 4.1. 3 katman bellek
1) Session memory (RAM)
2) Profile memory (kalıcı ayarlar)
3) Episodic memory (olay bazlı + vector)

### 4.2. Memory write policy
- Yazılır: kullanıcı tercihleri, tekrar eden görevler
- Yazılmaz: hassas içerik, tek seferlik gereksiz detay

### 4.3. Retrieval stratejisi
- Her görev başında 3–5 snippet getir
- Snippet format: `fact, source, timestamp, confidence, ttl`

**Done kriteri:**
- Tekrarlı işlerde hızlanır
- İzin tercihleri otomatik uygulanır

---

## Faz 5 — Gizlilik & güvenlik (1–2 hafta)

**Hedef:** Tam otomasyon güvenli olsun.

### 5.1. Permission Policy Engine
Risk seviyeleri:
- `LOW`: hava durumu, genel arama
- `MED`: link açma, dosya indirme
- `HIGH`: login/e-posta/drive/ödeme

Kurallar:
- HIGH her zaman sor
- MED ilk sefer sor + “hatırla” opsiyonu
- LOW sormadan çalış

### 5.2. Secrets Vault
- API key plaintext değil
- Log redaction

### 5.3. Audit log
“Bantz bugün ne yaptı?”
- açılan domainler
- indirilen dosyalar
- kullanılan tool’lar
- hata/retry geçmişi

**Done kriteri:**
- Kritik aksiyon izinli
- Loglar hassas veri sızdırmaz

---

## Faz 6 — Konuşma motoru: akış, barge-in, duygu (1–2 hafta)

### 6.1. Conversation state machine
`idle → listening → thinking → speaking → idle`

Follow-up window (örn 10 sn): kullanıcı devam ederse yeni wake word isteme

### 6.2. Barge-in
TTS konuşurken kullanıcı konuşursa:
- TTS dur
- yeni job
- eski job `PAUSE` veya `CANCEL`

### 6.3. Feedback cümleleri standardı
- “Araştırıyorum efendim…”
- “Kaynakları karşılaştırıyorum…”
- “Özetliyorum…”
- “Bir noktayı netleştirmem gerekiyor…”

**Done kriteri:**
- Robotik değil
- Uzun işlerde sessizlik yok

---

## Faz 7 — Doküman/PDF/DOC anlama (2–3 hafta)

Pipeline:
1) Dosyayı bul
2) Metni çıkar (pdf/docx/OCR sınırlı)
3) Yapılandır: başlıklar, görev listesi, teslim tarihi, değerlendirme
4) Özet + eylem planı

Hibrit model kuralı:
- Local model “yetersiz güven” verirse:
  - buluta göndermek için izin ister (HIGH)
  - cloud sadece bu adımda

**Done kriteri:**
- PDF’den checklist çıkarır
- Roadmap üretir

---

## Faz 8 — Agentic automation v1 (2–4 hafta)

### 8.1. Planner–Executor–Verifier (PEV)
- Planner: 3–8 adım
- Executor: adım adım
- Verifier: çıktı yeterli mi? eksikse adım ekle

### 8.2. Task templates
- Research task
- Scheduling task
- Document task
- Browser form task

### 8.3. Fail-safe
2 kere başarısız → seçenek sun:
- “Şöyle deneyebilirim”
- “Manuel devam edelim mi?”

**Done kriteri:**
- Classroom benzeri multi-step işlerde plan+execute+verify
- Hata olunca alternatif sunar

---

## Yeni Faz UI-2 — Jarvis Panel (v0)

**UI hedefleri**
- Merkezde panel (perde/iris açılma)
- Sol/sağ kolon: kaynak kartları + başlık + tarih
- Alt/sağ ticker: kısa status (“Scanning…”, “Comparing…”, “Summarizing…”)
- Görsel slotları: thumbnail/hero

**Teknik (PyQt)**
- `QPropertyAnimation` ile iris/perde
- opacity + slide
- card stack + hero image
- event bus’tan UI’ye stream

**UX kuralı**
- Modelin iç muhakemesi yok
- Sadece: plan adımları, tool durumları, bulgular (kaynak+tarih), görseller

---

## Yeni Faz Voice-2 — Attention Gate + Wakeword-only during tasks

**Dinleme modları**
- Hot mic kapalı (varsayılan): sadece wake word
- Engaged mode (wake sonrası 10–20 sn): follow-up için normal konuşma
- Task-running mode: görev sürerken **sadece wake word** (default hedef)

**Interrupt policy**
- Normal konuşma: ignore
- “hey bantz”:
  1) TTS varsa kes
  2) current job `PAUSE`
  3) “Efendim” → yeni komut

Komut bitince:
- paused job `RESUME` veya
- uzun/critical işlerde iptal sorusu

---

## v2 ‘Jarvis hissini uçuran’ ek parçalar
- Task Queue + Priority
- Background jobs (sessiz mod)
- Notification policy
- Safe mode / Risk scoring
- “Source Pack” yapısı (NewsPack, WeatherPack, CalendarPack, DocPack)
- Cache + reuse

---

## Branch/PR stratejisi
- `main` stabil kalsın
- v2 geliştirme: `dev/v2-core` branch
- İlk PR: sadece folder restructure + orchestrator skeleton + event protocol
- Sonra: tool runtime → memory → policy → UI/voice fazları
