---
name: file-search
version: 0.1.0
author: Bantz Team
description: "🔍 Semantic File Search — local filesystem indexing and semantic retrieval."
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
  - pattern: "(?i)(file|document|presentation|report|doc).*(find|search|where|which)"
    intent: file_search.find
    examples:
      - "where was that presentation I made last month"
      - "find the budget report"
      - "search for that PDF"
      - "I had something about this topic in my notes"
    priority: 80

  - pattern: "(?i)(index|scan|update files)"
    intent: file_search.index
    examples:
      - "index my files"
      - "scan my documents"
    priority: 60

tools:
  - name: file_search.query
    description: "Semantic file search — find files using natural language query"
    handler: llm
    parameters:
      - name: query
        type: string
        description: "Natural language search query"
      - name: file_types
        type: string
        description: "File types: pdf, docx, txt, all"
        enum: ["pdf", "docx", "txt", "md", "all"]
      - name: directory
        type: string
        description: "Search directory (default: ~/Documents)"

  - name: file_search.index
    description: "Index local filesystem for search"
    handler: system
    risk: medium
    parameters:
      - name: directories
        type: array
        description: "List of directories to index"
      - name: force
        type: boolean
        description: "Rebuild index from scratch"

  - name: file_search.recent
    description: "List recently modified files"
    handler: system
    parameters:
      - name: days
        type: integer
        description: "Number of days to look back"
      - name: file_type
        type: string
        description: "File type filter"

notes: |
  Phase G+ feature. Will be activated after Ingest Store EPIC is complete.
  PDF → text extraction (pdfplumber), DOCX → python-docx, TXT → direct read.
  Embedding: sentence-transformers or Ollama embedding endpoint.
  Index: SQLite FTS5 + embedding vector table.
