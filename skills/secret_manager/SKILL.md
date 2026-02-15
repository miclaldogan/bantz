---
name: secret-manager
version: 0.1.0
author: Bantz Team
description: "🔐 Secret Manager — secure password management via KeePass/Bitwarden CLI."
icon: 🔐
status: planned
tags:
  - future
  - security
  - secrets

dependencies:
  - epic: "EPIC 4 — Policy Engine"
    status: partial

triggers:
  - pattern: "(?i)(password|secret|key|credential).*(what|get|find|show|copy)"
    intent: secret.retrieve
    examples:
      - "what was the server password"
      - "get the AWS access key"
      - "find that password"
    priority: 90

  - pattern: "(?i)(password|secret).*(create|generate)"
    intent: secret.generate
    examples:
      - "generate a strong password"
      - "create a 16-character password"
    priority: 75

tools:
  - name: secret.retrieve
    description: "Secure password/secret retrieval — requires confirmation"
    handler: system
    risk: high
    confirm: true
    parameters:
      - name: query
        type: string
        description: "Secret name or description to search"
      - name: vault
        type: string
        description: "Vault name (default: default)"

  - name: secret.generate
    description: "Strong password generator"
    handler: system
    risk: low
    parameters:
      - name: length
        type: integer
        description: "Password length (default: 20)"
      - name: charset
        type: string
        description: "Character set: alphanumeric, full, pin"
        enum: ["alphanumeric", "full", "pin"]

  - name: secret.list
    description: "List vault entries (names only, NOT values)"
    handler: system
    risk: medium
    parameters:
      - name: vault
        type: string
        description: "Vault name"
      - name: filter
        type: string
        description: "Name filter"

notes: |
  Phase G+ feature. HIGH risk — policy engine must be fully active.
  Clipboard copy → auto-clear after 30 seconds.
  KeePass: keepassxc-cli | Bitwarden: bw CLI.
  Secret values must NEVER be logged or published to event bus.
