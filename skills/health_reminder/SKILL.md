---
name: health-reminder
version: 0.1.0
author: Bantz Team
description: "💊 Sağlık Hatırlatıcı — ilaç, su, ergonomi ve aktivite hatırlatmaları."
icon: 💊
status: planned
tags:
  - future
  - health
  - scheduler-dependent

dependencies:
  - epic: "EPIC 6 — Scheduler"
    status: pending

triggers:
  - pattern: "(?i)(ilaç|vitamin|hap).*(hatırlat|ekle|ne zaman|aldım mı)"
    intent: health.medication
    examples:
      - "ilaçımı hatırlat"
      - "vitamin almayı unuttum mu"
      - "sabah ilacımı ekle"
    priority: 80

  - pattern: "(?i)(su iç|mola ver|dinlen|ergonomi|oturma süresi)"
    intent: health.wellness
    examples:
      - "su içme hatırlatması kur"
      - "kaç saattir oturuyorum"
      - "mola zamanım geldi mi"
    priority: 70

tools:
  - name: health.add_medication
    description: "İlaç/vitamin hatırlatması ekle"
    handler: system
    parameters:
      - name: name
        type: string
        description: "İlaç/vitamin adı"
      - name: schedule
        type: string
        description: "Program: sabah, öğle, akşam, veya cron"
      - name: dose
        type: string
        description: "Doz bilgisi"

  - name: health.water_reminder
    description: "Su içme hatırlatması (Pomodoro tarzı interval)"
    handler: system
    parameters:
      - name: interval_minutes
        type: integer
        description: "Hatırlatma aralığı (dakika, varsayılan: 45)"
      - name: daily_goal_ml
        type: integer
        description: "Günlük hedef (ml, varsayılan: 2500)"

  - name: health.ergonomics
    description: "Ergonomi uyarısı — oturma süresi takibi"
    handler: system
    parameters:
      - name: max_sitting_minutes
        type: integer
        description: "Maks oturma süresi (varsayılan: 90 dakika)"

  - name: health.daily_log
    description: "Günlük sağlık log'u (ilaç alındı, su içildi, vb.)"
    handler: system
    parameters:
      - name: action
        type: string
        description: "Yapılan eylem"
        enum: ["medication_taken", "water_drunk", "break_taken", "exercise"]

notes: |
  Faz G+ özelliği. Düşük karmaşıklık — Scheduler EPIC'ine bağımlı.
  cron-tabanlı hatırlatmalar + D-Bus notification.
  İlaç takibi: SQLite'da medication_log tablosu.
  Ergonomi: X11/Wayland idle time API'den oturma süresi hesaplama.
