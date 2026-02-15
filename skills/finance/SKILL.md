---
name: finance
version: 0.1.0
author: Bantz Team
description: "💰 Finance Tracker — expense analysis from bank emails, budget tracking."
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
  - pattern: "(?i)(expense|spending|budget|finance|money|salary|bill).*(summary|report|analysis|how much|list)"
    intent: finance.summary
    examples:
      - "how much did I spend this month"
      - "what's my budget status"
      - "show my bill summary"
      - "what am I spending the most on"
    priority: 75

  - pattern: "(?i)(bank|account|credit|card).*(info|check|transactions)"
    intent: finance.bank
    examples:
      - "show my bank transactions"
      - "credit card statement"
    priority: 70

tools:
  - name: finance.parse_expenses
    description: "Parse expenses from bank emails"
    handler: llm
    risk: medium
    parameters:
      - name: period
        type: string
        description: "Period: this_month, last_month, this_week"
        enum: ["this_month", "last_month", "this_week", "custom"]
      - name: source
        type: string
        description: "Source: gmail, manual"
        enum: ["gmail", "manual"]

  - name: finance.monthly_summary
    description: "Monthly expense summary with category breakdown"
    handler: llm
    parameters:
      - name: month
        type: string
        description: "Month (YYYY-MM format, empty = current month)"

  - name: finance.budget_alert
    description: "Budget threshold check and alerts"
    handler: llm
    parameters:
      - name: category
        type: string
        description: "Expense category (empty = all categories)"

  - name: finance.categorize
    description: "Categorize an expense (food, transport, entertainment, etc.)"
    handler: llm
    parameters:
      - name: description
        type: string
        description: "Expense description"
      - name: amount
        type: number
        description: "Amount (TRY)"

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
  Phase G+ feature. Parse expenses from bank emails using regex + LLM.
  Will be activated after Ingest Store and Gmail Enhanced EPICs are complete.
  First version: email regex → expense list → category LLM.
  Next version: graph integration for merchant analysis.
