---
name: system-info
version: 1.0.0
author: Bantz Team
description: "Sistem bilgisi ve sağlık kontrolü — CPU, RAM, disk, GPU durumu."
icon: 🖥️
tags:
  - builtin
  - system
  - monitoring

triggers:
  - pattern: "(?i)(sistem|system|bilgisayar|pc).*(durumu|bilgi|info|sağlık|health|nasıl)"
    intent: system.info
    examples:
      - "sistem durumu"
      - "bilgisayarım nasıl"
      - "system info"
      - "pc sağlık kontrolü"
    priority: 70

  - pattern: "(?i)(cpu|ram|bellek|disk|gpu|işlemci).*(kullanım|durum|doluluk|kaç|ne\\s*kadar)"
    intent: system.detail
    examples:
      - "CPU kullanımı kaç"
      - "RAM ne kadar dolu"
      - "disk durumu"
      - "GPU sıcaklığı"
    priority: 65

  - pattern: "(?i)(pil|batarya|şarj|battery).*(durumu|kaç|yüzde)"
    intent: system.battery
    examples:
      - "pil durumu"
      - "şarj yüzde kaç"
    priority: 65

tools:
  - name: system.health_check
    description: "Kapsamlı sistem sağlık kontrolü"
    handler: builtin:system.status
    parameters:
      - name: include_env
        type: boolean
        description: "Ortam değişkenlerini dahil et"

permissions:
  - system

config:
  show_gpu: true
  show_battery: true
---

# System Info Skill — Sistem Bilgisi

Sen Bantz'ın sistem izleme yeteneğisin.

## Görevin

Kullanıcı sistem durumunu sorduğunda anlaşılır, Türkçe bir özet sun.

## Yanıt Formatı

```
🖥️ Sistem Durumu

🔲 CPU: %45 kullanım (Intel i7-12700H, 8 çekirdek)
🧠 RAM: 12.4 GB / 16 GB (%77)
💾 Disk: 234 GB / 512 GB (%46)
🎮 GPU: RTX 4060 — 42°C, %15 VRAM
🔋 Pil: %82 (şarj oluyor)
⏱️ Uptime: 3 gün 7 saat
```

## Kurallar

1. Türkçe yanıt ver
2. Yüzdeleri vurgula
3. Kritik durumları uyar (%90+ CPU/RAM/Disk → ⚠️)
4. GPU yoksa GPU satırını gösterme
5. Dizüstü değilse pil satırını gösterme
