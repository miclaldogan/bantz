---
name: file-search
version: 0.1.0
author: Bantz Team
description: "🔍 Semantic dosya arama — yerel dosya sistemi indexleme ve anlamsal arama."
icon: 🔍
status: planned
tags:
  - future
  - search
  - embeddings

dependencies:
  - epic: "EPIC 1 — Ingest Store"
    status: pending

triggers:
  - pattern: "(?i)(dosya|belge|sunum|rapor|döküman).*(bul|ara|nerede|hangisi)"
    intent: file_search.find
    examples:
      - "geçen ay hazırladığım sunum neredeydi"
      - "bütçe raporunu bul"
      - "o PDF'i ara"
      - "notlarımda şu konu vardı"
    priority: 80

  - pattern: "(?i)(indexle|tara|dosyaları güncelle)"
    intent: file_search.index
    examples:
      - "dosyalarımı indexle"
      - "belgeleri tara"
    priority: 60

tools:
  - name: file_search.query
    description: "Semantik dosya arama — anlamsal sorgu ile dosya bul"
    handler: llm
    parameters:
      - name: query
        type: string
        description: "Doğal dilde arama sorgusu"
      - name: file_types
        type: string
        description: "Dosya tipleri: pdf, docx, txt, all"
        enum: ["pdf", "docx", "txt", "md", "all"]
      - name: directory
        type: string
        description: "Arama dizini (varsayılan: ~/Documents)"

  - name: file_search.index
    description: "Yerel dosya sistemi indexleme"
    handler: system
    risk: medium
    parameters:
      - name: directories
        type: array
        description: "İndexlenecek dizinler listesi"
      - name: force
        type: boolean
        description: "Mevcut index'i sıfırdan oluştur"

  - name: file_search.recent
    description: "Son değiştirilen dosyaları listele"
    handler: system
    parameters:
      - name: days
        type: integer
        description: "Son kaç günün dosyaları"
      - name: file_type
        type: string
        description: "Dosya tipi filtresi"

notes: |
  Faz G+ özelliği. Ingest Store EPIC'i tamamlandıktan sonra aktive edilecek.
  PDF → text extraction (pdfplumber), DOCX → python-docx, TXT → direct read.
  Embedding: sentence-transformers veya Ollama embedding endpoint.
  Index: SQLite FTS5 + embedding vektör tablosu.
