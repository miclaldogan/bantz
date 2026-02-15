---
name: secret-manager
version: 0.1.0
author: Bantz Team
description: "🔐 Secret Manager — KeePass/Bitwarden CLI ile güvenli parola yönetimi."
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
  - pattern: "(?i)(şifre|parola|password|secret|key).*(neydi|getir|bul|göster|kopyala)"
    intent: secret.retrieve
    examples:
      - "Ali'nin server şifresi neydi"
      - "AWS access key'i getir"
      - "o parolayı bul"
    priority: 90

  - pattern: "(?i)(şifre|parola).*(oluştur|üret|generate)"
    intent: secret.generate
    examples:
      - "güçlü bir şifre üret"
      - "16 karakterlik parola oluştur"
    priority: 75

tools:
  - name: secret.retrieve
    description: "Güvenli parola/secret retrieval — onay gerektirir"
    handler: system
    risk: high
    confirm: true
    parameters:
      - name: query
        type: string
        description: "Aranacak secret adı veya açıklaması"
      - name: vault
        type: string
        description: "Vault adı (varsayılan: default)"

  - name: secret.generate
    description: "Güçlü parola üretici"
    handler: system
    risk: low
    parameters:
      - name: length
        type: integer
        description: "Parola uzunluğu (varsayılan: 20)"
      - name: charset
        type: string
        description: "Karakter seti: alphanumeric, full, pin"
        enum: ["alphanumeric", "full", "pin"]

  - name: secret.list
    description: "Vault'taki secret listesi (isimleri, değerleri DEĞİL)"
    handler: system
    risk: medium
    parameters:
      - name: vault
        type: string
        description: "Vault adı"
      - name: filter
        type: string
        description: "İsim filtresi"

notes: |
  Faz G+ özelliği. HIGH risk — policy engine tam olarak aktif olmalı.
  Clipboard'a kopyalama → 30sn sonra otomatik temizleme.
  KeePass: keepassxc-cli | Bitwarden: bw CLI.
  Secret değerleri ASLA log'lanmamalı, event bus'a yazılmamalı.
