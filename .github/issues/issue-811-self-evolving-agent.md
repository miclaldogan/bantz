---
title: "[Architecture] Self-Evolving Agent — Kendi Kendine Skill Ekleme"
labels: "type:feature, priority:P2, area:architecture, milestone:v2-future"
assignees: "miclaldogan"
issue_number: 811
---

## Hedef

Bantz'ın ihtiyaç duyduğu skill'leri kendi kendine oluşturabilmesi. Kullanıcı "hava durumunu öğrenebilir misin?" dediğinde, Bantz'ın otomatik olarak weather skill'i yazıp kurması.

## Arka Plan

Kullanıcı vizyonu: "İlerleyen süreçlerde kendisi kendi kendisine skill ekleyebilir olmalı"

Bu, Bantz'ın en gelişmiş hedeflerinden biri. OpenCode entegrasyonu (kod yazma) + SKILL.md declarative formatı bir araya geldiğinde mümkün olacak.

## Kapsam

### Dahil

- **Skill ihtiyaç tespiti**: "Bu görevi yapacak bir skill'im yok" farkındalığı
- **Skill scaffolding**: SKILL.md template oluşturma (LLM ile)
- **Script yazma**: Gerekli Python/Bash helper scriptleri üretme
- **Skill doğrulama**: Oluşturulan skill'i test etme (sandbox)
- **Kullanıcı onayı**: "Weather skill'i oluşturdum, kurayım mı?"
- **Skill versiyonlama**: Otomatik oluşturulan skill'lerin versiyon takibi

### Hariç

- Karmaşık API entegrasyonları (OAuth gerektiren skill'leri otomatik kuramaz)
- Güvenlik açığı oluşturabilecek skill'ler (sandbox zorunlu)

## Kabul Kriterleri

- [ ] "X yapabilir misin?" → skill yok → "Skill oluşturayım mı?" akışı
- [ ] SKILL.md otomatik generate ediliyor
- [ ] Helper script sandbox'ta test ediliyor
- [ ] Kullanıcı onayı sonrası skill aktif oluyor
- [ ] Skill versiyonlama çalışıyor
- [ ] Test yazıldı

## Bağımlılıklar

- Issue #801 (Skill Architecture) — **ZORUNLU**: Declarative skill formatı olmadan bu yapılamaz
- Issue #812 (OpenCode Entegrasyonu) — kod yazma yeteneği
- Mevcut `security/sandbox.py` — güvenli çalıştırma

## ⚠️ Güvenlik Notları

- Otomatik oluşturulan skill'ler SANDBOX'ta çalıştırılmalı
- Ağ erişimi, dosya sistemi erişimi → kullanıcı onayı şart
- Shell command çalıştırma → DENY by default

## Öncelik: P2 — Temel skill mimarisi ve OpenCode entegrasyonundan sonra

## Tahmini Süre: 1-2 hafta (bağımlılıklar tamamlandıktan sonra)
