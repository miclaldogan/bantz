---
name: finance
version: 0.1.0
author: Bantz Team
description: "💰 Finans takibi — banka mail'lerinden harcama analizi, bütçe takibi."
icon: 💰
status: planned
tags:
  - future
  - finance
  - gmail-dependent

dependencies:
  - epic: "EPIC 1 — Ingest Store"
    status: pending
  - epic: "EPIC 5 — Gmail Enhanced"
    status: partial

triggers:
  - pattern: "(?i)(harcama|gider|bütçe|finans|para|maaş|fatura).*(özet|rapor|analiz|ne kadar|listele)"
    intent: finance.summary
    examples:
      - "bu ayki harcamalarım ne kadar"
      - "bütçe durumum nasıl"
      - "fatura özetini çıkar"
      - "en çok neye para harcıyorum"
    priority: 75

  - pattern: "(?i)(banka|hesap|kredi|kart).*(bilgi|kontrol|hareket)"
    intent: finance.bank
    examples:
      - "banka hesap hareketlerim"
      - "kredi kartı ekstresi"
    priority: 70

tools:
  - name: finance.parse_expenses
    description: "Banka mail'lerinden harcamaları parse et"
    handler: llm
    risk: medium
    parameters:
      - name: period
        type: string
        description: "Dönem: this_month, last_month, this_week"
        enum: ["this_month", "last_month", "this_week", "custom"]
      - name: source
        type: string
        description: "Kaynak: gmail, manual"
        enum: ["gmail", "manual"]

  - name: finance.monthly_summary
    description: "Aylık harcama özeti + kategori breakdown"
    handler: llm
    parameters:
      - name: month
        type: string
        description: "Ay (YYYY-MM formatı, boş = bu ay)"

  - name: finance.budget_alert
    description: "Bütçe aşım kontrolü ve uyarı"
    handler: llm
    parameters:
      - name: category
        type: string
        description: "Harcama kategorisi (boş = tüm kategoriler)"

  - name: finance.categorize
    description: "Harcamayı kategorize et (yemek, ulaşım, eğlence, vb.)"
    handler: llm
    parameters:
      - name: description
        type: string
        description: "Harcama açıklaması"
      - name: amount
        type: number
        description: "Tutar (TL)"

graph_schema:
  nodes:
    - label: Transaction
      properties: [amount, currency, date, description, category]
    - label: Category
      properties: [name, budget_limit]
    - label: Merchant
      properties: [name, type]
  edges:
    - type: BELONGS_TO
      from: Transaction
      to: Category
    - type: PAID_TO
      from: Transaction
      to: Merchant

notes: |
  Faz G+ özelliği. Banka mail'lerinden regex + LLM ile harcama parse'lama.
  Ingest Store ve Gmail Enhanced EPIC'leri tamamlandıktan sonra aktive edilecek.
  İlk versiyon: mail regex → harcama listesi → kategori LLM.
  Sonraki versiyon: graf entegrasyonu ile merchant analizi.
