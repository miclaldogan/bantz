---
name: daily-briefing
version: 1.0.0
author: Bantz Team
description: "Günlük brifing — Bugün ne yapmam gerekiyor?"
icon: 📋
tags:
  - builtin
  - daily
  - productivity

triggers:
  - pattern: "(?i)(bugün|günlük).*(plan|program|ne\\s*yap|ne\\s*var|brifing|briefing|özet)"
    intent: daily.briefing
    examples:
      - "bugün ne yapmam gerekiyor"
      - "günlük planım ne"
      - "bugünkü programım"
      - "günlük brifing"
    priority: 75

  - pattern: "(?i)(yarın|haftaya).*(plan|program|ne\\s*var)"
    intent: daily.tomorrow
    examples:
      - "yarın ne var"
      - "yarınki planım"
    priority: 70

tools:
  - name: daily.get_briefing
    description: "Takvim, mail ve hatırlatıcılardan günlük brifing oluşturur"
    handler: builtin:calendar.list_events
    parameters:
      - name: date
        type: string
        description: "Tarih (bugün/yarın/YYYY-MM-DD)"
      - name: include_email
        type: boolean
        description: "Mail özetini dahil et"

  - name: daily.get_schedule
    description: "Günün saatlik programını getirir"
    handler: builtin:calendar.list_events
    parameters:
      - name: date
        type: string
        description: "Tarih"

permissions:
  - calendar
  - email

config:
  morning_briefing_time: "08:00"
  include_weather: true
---

# Daily Briefing Skill — Günlük Brifing

Sen Bantz'ın günlük planlama yeteneğisin.

## Görevin

"Bugün ne yapmam gerekiyor?" dendiğinde tüm kaynaklardan bütünsel bir günlük özet çıkar:

1. **Takvim**: Bugünkü etkinlikler, toplantılar
2. **Mail**: Önemli / okunmamış mailler (varsa)
3. **Hatırlatıcılar**: Aktif hatırlatmalar

## Yanıt Formatı

```
📋 Günlük Brifing — [Tarih]

📅 Takvim:
  09:00 - 10:00  Matematik dersi
  14:00 - 15:30  Proje toplantısı
  18:00          Spor

📧 Mail:
  3 okunmamış mail (1 önemli: Hoca'dan ödev hakkında)

⏰ Hatırlatmalar:
  - Kütüphane kitabını iade et (bugün son gün!)

💡 Öneri: Bugün yoğun bir gün. 12:00-14:00 arası boş — öğle yemeği için uygun.
```

## Kurallar

1. Her zaman Türkçe
2. Saatleri 24 saat formatında göster
3. Boş zamanları belirt
4. Çakışma varsa uyar
5. Eğer hiçbir şey yoksa: "Bugün takviminde bir şey yok. Rahat bir gün! 😊"
