---
title: "[Core] Proaktif Zeka Motoru — Scheduler + Akıl Yürütme + Bildirim"
labels: "type:feature, priority:P1, area:core, milestone:v2"
assignees: "miclaldogan"
issue_number: 806
---

## Hedef

Bantz'ın sadece tepkisel (kullanıcı sorunca çalışan) değil, **proaktif** olmasını sağlamak. Kendi başına durumları analiz edip kullanıcıya önerilerde bulunabilmeli.

## Arka Plan

Kullanıcı vizyonu: "Bugün dışarı çıkmak istiyordunuz ancak hava çok iyi gözükmüyor, eğer bir taşıt kullanmayacaksanız planınızı iptal edebilirim"

Bu tarz akıl yürütme, birden fazla kaynağı (takvim + hava durumu + kullanıcı tercihleri) birleştirip proaktif öneri üretmeyi gerektirir.

## Kapsam

### Dahil

- **Proaktif görev kuyruğu**: Zamanlı kontroller (sabah brifing, hava kontrolü, ödev hatırlatma)
- **Çapraz analiz motoru**: Birden fazla tool sonucunu birleştirip akıl yürütme
- **Bildirim sistemi**: Önemli bulgularda kullanıcıyı bilgilendirme (CLI, API, notification)
- **Cron-bazlı scheduler**: Configurable zamanlama (sabah 8 haber, her saat hava, vb.)
- **Notification policy**: Her şeyi bildirme, sadece "önemli" olanları bildir
- **Öneri üretme**: "Planınızı iptal edebilirim" tarzı actionable öneriler

### Hariç

- Push notification (mobil — ayrı issue)
- UI notification panel (ayrı issue)

## Teknik Tasarım

```python
# src/bantz/proactive/engine.py

class ProactiveEngine:
    """Periyodik kontroller + çapraz analiz + bildirim."""

    def __init__(self, brain, scheduler, memory, notification_bus):
        self.checks = [
            MorningBriefing(schedule="08:00"),      # Sabah: takvim + hava + haberler
            WeatherCalendarCross(schedule="*/60"),   # Her saat: hava × takvim
            AssignmentReminder(schedule="*/120"),    # Her 2 saat: classroom deadline
            EmailDigest(schedule="12:00,18:00"),     # Öğlen+akşam: mail özeti
        ]

    async def run_check(self, check: ProactiveCheck):
        context = await check.gather_data(self.brain)     # Tool sonuçlarını topla
        analysis = await check.analyze(context)           # Çapraz akıl yürütme
        if analysis.importance >= check.threshold:
            notification = check.format_notification(analysis)
            await self.notification_bus.emit(notification)

class ProactiveCheck(ABC):
    schedule: str           # Cron expression
    threshold: float        # Min importance to notify (0.0-1.0)
    tools_needed: list      # Hangi tool'lar gerekli

    async def gather_data(self, brain) -> dict: ...
    async def analyze(self, data: dict) -> Analysis: ...
    def format_notification(self, analysis: Analysis) -> Notification: ...
```

### Sabah Brifing Örneği:

```
08:00 → MorningBriefing tetiklenir
  ├── calendar.list_events(today) → 3 toplantı
  ├── weather.get_forecast(İstanbul, 1) → 5°C, yağmur
  ├── news.get_briefing(interests) → 5 önemli haber
  ├── classroom.list_assignments(due_soon) → 1 ödev (yarın son gün)
  └── gmail.unread_count() → 12 okunmamış
  │
  ├── Çapraz analiz: 14:00 toplantı dışarıda + yağmur → UYARI
  ├── Ödev hatırlatma: yarın son gün → ÖNEMLİ
  │
  └── Bildirim:
      "Günaydın efendim! Bugün 3 toplantınız var.
       ⚠️ Saat 14:00'teki buluşmanız dışarıda ama yağmur bekleniyor.
       📚 Veri Yapıları ödevi yarın son gün, henüz teslim etmemişsiniz.
       📧 12 okunmamış mailiniz var, 2'si acil görünüyor.
       📰 Yapay zeka dünyasında önemli gelişme: [başlık]"
```

## Kabul Kriterleri

- [ ] ProactiveEngine çalışıyor ve periyodik kontroller tetikleniyor
- [ ] En az 3 proaktif kontrol implement edilmiş (sabah brifing, hava×takvim, mail özeti)
- [ ] Çapraz analiz yapılıyor (birden fazla tool sonucu birleşiyor)
- [ ] Bildirim kuyruğu çalışıyor (CLI + API)
- [ ] Notification policy configurable (threshold, schedule)
- [ ] Actionable öneriler üretiliyor ("iptal edebilirim", "erteleyebilirim")
- [ ] Mevcut scheduler entegrasyonu
- [ ] Test yazıldı

## Bağımlılıklar

- Issue #803 (Weather Skill) — hava×takvim çapraz analizi için
- Issue #804 (News Tracker) — sabah haber brifing için
- Issue #805 (Classroom) — ödev hatırlatma için
- Mevcut `scheduler/` modülü genişletilecek

## Tahmini Süre: 5-7 gün
