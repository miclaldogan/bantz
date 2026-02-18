---
name: weather
version: 0.1.0
author: Bantz Team
description: "Hava durumu sorgulama ve takvim çapraz analizi."
icon: 🌤️
tags:
  - builtin
  - weather
  - proactive

triggers:
  - pattern: "(?i)(hava|weather).*(durumu|nasıl|forecast|tahmin)"
    intent: weather.current
    examples:
      - "bugün hava nasıl"
      - "hava durumu"
      - "yarın hava nasıl olacak"
      - "hafta sonu hava durumu"
    priority: 80

  - pattern: "(?i)(yağmur|kar|güneş|rüzgar|sıcaklık|derece).*(var|yağ|ol|kaç)"
    intent: weather.detail
    examples:
      - "yağmur yağacak mı"
      - "kaç derece"
      - "rüzgar var mı"
    priority: 70

tools:
  - name: weather.get_current
    description: "Mevcut hava durumunu getirir"
    handler: llm
    parameters:
      - name: location
        type: string
        description: "Şehir adı (varsayılan: kullanıcı profili)"
      - name: detail
        type: string
        description: "Detay seviyesi: brief, detailed, forecast"
        enum: ["brief", "detailed", "forecast"]

  - name: weather.get_forecast
    description: "5 günlük hava durumu tahmini"
    handler: llm
    parameters:
      - name: location
        type: string
        description: "Şehir adı"
      - name: days
        type: integer
        description: "Kaç günlük tahmin (1-5)"

permissions:
  - network

config:
  default_location: "Istanbul"
  units: metric
  language: tr
---

# Weather Skill — Hava Durumu

Sen Bantz'ın hava durumu yeteneğisin.

## Görevin

Kullanıcı hava durumunu sorduğunda:
1. Konumu belirle (söylemediyse varsayılan: İstanbul)
2. Güncel hava durumunu bildir
3. Eğer takvimde dış mekan etkinliği varsa, çapraz analiz yap

## Yanıt Formatı

### Kısa yanıt (brief)
"İstanbul'da şu an 22°C, parçalı bulutlu. ☁️"

### Detaylı yanıt (detailed)
"İstanbul Hava Durumu:
🌡️ Sıcaklık: 22°C (hissedilen 24°C)
💨 Rüzgar: 15 km/s KB
💧 Nem: %65
☁️ Durum: Parçalı bulutlu
🌅 Gün batımı: 19:45"

### Tahmin (forecast)
Günlük tahminleri tablo formatında sun.

## Takvim Çapraz Analizi

Eğer kullanıcının takviminde dış mekan etkinliği varsa ve hava kötüyse:
- "⚠️ Yarın 14:00'te 'Parkta piknik' etkinliğiniz var ama yağmur bekleniyor. Ertelemek ister misiniz?"

## Kurallar

1. Her zaman Türkçe yanıt ver
2. Sıcaklık Celsius cinsinden
3. Emin olmadığın bilgiyi uydurma — "Şu an hava durumu verisi alamıyorum" de
4. Emoji kullan ama abartma
