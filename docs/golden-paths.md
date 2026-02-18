# Golden Path Definitions (Issue #1220)

> **North Star:** "Bantz ile günlük takvim + mail yönetimimi yapacağım — 2 golden path kusursuz çalışacak."

---

## Golden Path #1: Calendar / Agenda

**Senaryo:** Kullanıcı günlük takvimini yönetir.

### Akış
1. `"bugün ajandamı çıkar"` → tüm etkinlikler listelenir
2. `"yarın 15:00'e toplantı ekle"` → onay sorulur (confirmation firewall)
3. `"evet"` → etkinlik oluşturulur, saat + title gösterilir
4. `"yarınki planım ne"` → yeni eklenen dahil tümü gösterilir
5. `"saat kaçtaymış o toplantı"` → 15:00 cevabı döner (anaphoric follow-up)

### Gerekli Tool Chain
| Adım | Route | Tool | Intent |
|------|-------|------|--------|
| 1 | calendar | calendar.list_events | list |
| 2 | calendar | calendar.create_event | create |
| 3 | (confirmation) | calendar.create_event | confirmed |
| 4 | calendar | calendar.list_events | list |
| 5 | calendar | (anaphoric) | detail |

### Edge Cases
- Timezone: `Europe/Istanbul` default
- Boş takvim: "Bugün için etkinlik yok" mesajı
- Çakışma: aynı saatte etkinlik varsa uyarı
- Period-of-day: "yarın sabah" → 09:00 (Issue #1255)

### Başarı Kriterleri
- 10/10 deterministik çalışır
- Onay istenen noktalar doğru (gereksiz onay yok)
- Halüsinasyon yok (tool sonucu olmadan saat uydurulmaz)

---

## Golden Path #2: Inbox Triage

**Senaryo:** Kullanıcı mail kutusunu yönetir.

### Akış
1. `"son maillerimi özetle"` → 5 mail summary (subject + sender + 1-line)
2. `"başka var mı"` → sonraki 5 mail (pagination)
3. `"tübitaktan gelen var mı"` → filtrelenmiş query
4. `"github mailinin içeriğini özetle"` → specific mail body
5. `"buna cevap taslağı hazırla"` → draft (onay ile)

### Gerekli Tool Chain
| Adım | Route | Tool | Intent |
|------|-------|------|--------|
| 1 | gmail | gmail.list_messages | list |
| 2 | gmail | gmail.list_messages | list (pagination) |
| 3 | gmail | gmail.list_messages | query |
| 4 | gmail | gmail.get_message | detail |
| 5 | gmail | gmail.create_draft | draft |

### Edge Cases
- Boş inbox: "Gelen kutunuz boş" mesajı
- Typo toleransı: "tübirak" → "tübitak" fuzzy match (Issue #1256)
- Turkish İ lowering: TÜBİTAK → tübitak tokenization
- Pagination: "başka mail var mı" → continuation support

### Başarı Kriterleri
- Yanlışlıkla mail göndermiyor (asla)
- Taslaklar tutarlı formatta, editlemesi kolay
- 10 farklı mail query'si test edilmiş
- Halüsinasyon yok (tool yoksa mail içeriği uydurulmaz)

---

## Sprint Metrikleri

### 1. Pipeline Success Rate
```
success_rate = successful_turns / total_turns
```
Hedef: ≥ 95% (golden path senaryolarında 100%)

### 2. Confirmation Triggered Count
```
confirmation_rate = confirmation_turns / total_turns
```
Hedef: Sadece destructive/moderate tool'larda tetiklenmeli

### 3. End-to-End Latency Breakdown
```
total = router_ms + tool_ms + finalize_ms
```
| Phase | p50 Target | p95 Target |
|-------|-----------|-----------|
| Router | < 500ms | < 1000ms |
| Tool | < 2000ms | < 5000ms |
| Finalize | < 2000ms | < 4000ms |
| Total | < 5000ms | < 10000ms |

### Metrikler Nerede?
- JSONL: `artifacts/logs/turn_metrics.jsonl`
- Rapor: `python -m bantz.metrics.pipeline_metrics`
- CI gate: `python -m bantz.metrics.gates`
