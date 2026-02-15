---
name: reporter
version: 0.1.0
author: Bantz Team
description: "📊 Report Generator — weekly/monthly activity reports, productivity analysis."
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
  - pattern: "(?i)(report|statistics|summary|analytics).*(generate|create|prepare|show|weekly|monthly)"
    intent: reporter.generate
    examples:
      - "generate weekly report"
      - "show my activity summary this month"
      - "show tool usage statistics"
      - "prepare my productivity report"
    priority: 75

  - pattern: "(?i)(export|PDF|markdown).*(report|summary)"
    intent: reporter.export
    examples:
      - "export the report as PDF"
      - "markdown format report"
    priority: 70

tools:
  - name: reporter.weekly
    description: "Generate weekly activity report"
    handler: llm
    parameters:
      - name: week
        type: string
        description: "Week (ISO format, empty = this week)"
      - name: include_tools
        type: boolean
        description: "Include tool usage statistics"

  - name: reporter.monthly
    description: "Generate monthly activity report"
    handler: llm
    parameters:
      - name: month
        type: string
        description: "Month (YYYY-MM, empty = this month)"

  - name: reporter.productivity
    description: "Productivity analysis — meeting/work ratio"
    handler: llm
    parameters:
      - name: period
        type: string
        description: "Period: this_week, last_week, this_month"
        enum: ["this_week", "last_week", "this_month"]

  - name: reporter.export
    description: "Export report as PDF or Markdown"
    handler: system
    risk: medium
    parameters:
      - name: report_type
        type: string
        description: "Report type: weekly, monthly, productivity"
        enum: ["weekly", "monthly", "productivity"]
      - name: format
        type: string
        description: "Output format"
        enum: ["pdf", "markdown", "html"]

notes: |
  Phase G+ feature. Depends on Observability EPIC.
  Tool usage statistics → from observability DB.
  Calendar analysis → meeting/work ratio from Calendar API.
  PDF export: weasyprint or reportlab.
  Markdown export: jinja2 templates.
