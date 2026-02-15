---
name: travel
version: 0.1.0
author: Bantz Team
description: "✈️ Seyahat Asistanı — uçuş/otel/araç kiralama mail takibi ve takvim entegrasyonu."
icon: ✈️
status: planned
tags:
  - future
  - travel
  - gmail-dependent
  - calendar-dependent

dependencies:
  - epic: "EPIC 5 — Gmail Enhanced"
    status: partial
  - epic: "EPIC 2 — Graf Bellek"
    status: pending

triggers:
  - pattern: "(?i)(seyahat|uçuş|gezi|tatil|otel|uçak).*(plan|bilgi|takvim|ne zaman|listele)"
    intent: travel.info
    examples:
      - "seyahat planlarım ne"
      - "uçuş bilgilerimi getir"
      - "tatil takvimimi göster"
      - "otel rezervasyonum var mı"
    priority: 80

  - pattern: "(?i)(check.?in|boarding|uçuş saati|otel giriş)"
    intent: travel.reminder
    examples:
      - "check-in saatim ne zaman"
      - "uçuş saatimi hatırlat"
    priority: 85

tools:
  - name: travel.parse_bookings
    description: "Mail'lerden uçuş/otel/araç kiralama bilgilerini parse et"
    handler: llm
    risk: medium
    parameters:
      - name: period
        type: string
        description: "Dönem: upcoming, past_month, all"
        enum: ["upcoming", "past_month", "all"]

  - name: travel.create_itinerary
    description: "Seyahat takvimi oluştur (Google Calendar'a ekle)"
    handler: system
    risk: medium
    confirm: true
    parameters:
      - name: trip_name
        type: string
        description: "Seyahat adı"

  - name: travel.set_reminders
    description: "Seyahat hatırlatmaları kur (check-in, uçuş, otel)"
    handler: system
    parameters:
      - name: trip_name
        type: string
        description: "Seyahat adı"
      - name: reminder_types
        type: array
        description: "Hatırlatma tipleri: checkin, flight, hotel, car"

graph_schema:
  nodes:
    - label: Trip
      properties: [name, start_date, end_date, destination]
    - label: Hotel
      properties: [name, address, checkin, checkout, confirmation]
    - label: Flight
      properties: [airline, flight_no, departure, arrival, gate]
    - label: Person
      properties: [name, role]
  edges:
    - type: INCLUDES
      from: Trip
      to: Hotel
    - type: INCLUDES
      from: Trip
      to: Flight
    - type: TRAVELS
      from: Person
      to: Trip

notes: |
  Faz G+ özelliği. Yüksek karmaşıklık.
  Gmail'den seyahat mail'lerini (uçak, otel, araç) multi-format parse.
  Google Calendar'a otomatik itinerary oluşturma.
  Proaktif hatırlatmalar: check-in (24h önce), uçuş (3h önce).
