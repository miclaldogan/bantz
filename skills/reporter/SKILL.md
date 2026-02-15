---
name: reporter
version: 0.1.0
author: Bantz Team
description: "📊 Rapor Üretici — haftalık/aylık aktivite raporu, verimlilik analizi."
icon: 📊
status: planned
tags:
  - future
  - reporting
  - analytics

dependencies:
  - epic: "EPIC 3 — Observability"
    status: pending

triggers:
  - pattern: "(?i)(rapor|istatistik|özet|analytics).*(üret|oluştur|hazırla|göster|haftalık|aylık)"
    intent: reporter.generate
    examples:
      - "haftalık rapor oluştur"
      - "bu ayki aktivite özetim"
      - "tool kullanım istatistiklerimi göster"
      - "verimlilik raporumu hazırla"
    priority: 75

  - pattern: "(?i)(export|dışa aktar|PDF|markdown).*(rapor|özet)"
    intent: reporter.export
    examples:
      - "raporu PDF olarak dışa aktar"
      - "markdown formatında rapor"
    priority: 70

tools:
  - name: reporter.weekly
    description: "Haftalık aktivite raporu üret"
    handler: llm
    parameters:
      - name: week
        type: string
        description: "Hafta (ISO format, boş = bu hafta)"
      - name: include_tools
        type: boolean
        description: "Tool kullanım istatistiklerini dahil et"

  - name: reporter.monthly
    description: "Aylık aktivite raporu üret"
    handler: llm
    parameters:
      - name: month
        type: string
        description: "Ay (YYYY-MM, boş = bu ay)"

  - name: reporter.productivity
    description: "Verimlilik analizi — toplantı/çalışma oranı"
    handler: llm
    parameters:
      - name: period
        type: string
        description: "Dönem: this_week, last_week, this_month"
        enum: ["this_week", "last_week", "this_month"]

  - name: reporter.export
    description: "Raporu PDF veya Markdown olarak dışa aktar"
    handler: system
    risk: medium
    parameters:
      - name: report_type
        type: string
        description: "Rapor tipi: weekly, monthly, productivity"
        enum: ["weekly", "monthly", "productivity"]
      - name: format
        type: string
        description: "Çıktı formatı"
        enum: ["pdf", "markdown", "html"]

notes: |
  Faz G+ özelliği. Observability EPIC'ine bağımlı.
  Tool kullanım istatistikleri → observability DB'den.
  Takvim analizi → Calendar API'den toplantı/çalışma oranı.
  PDF export: weasyprint veya reportlab.
  Markdown export: jinja2 template'leri.
