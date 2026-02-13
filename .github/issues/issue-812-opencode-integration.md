---
title: "[Feature] OpenCode Entegrasyonu — Kod Yazma Skill'i"
labels: "type:feature, priority:P2, area:skill, milestone:v2-future"
assignees: "miclaldogan"
issue_number: 812
---

## Hedef

OpenCode reposunu Bantz'a entegre ederek kod yazma, düzenleme, ve proje oluşturma yeteneği kazandırmak.

## Arka Plan

Kullanıcı vizyonu: "OpenCode reposunu da ilerleyen süreçlerde kod yazma skill'i için direkt olarak repomıza dahil edeceğiz"

OpenCode (github.com/opencode-ai/opencode) bir CLI tabanlı AI coding agent. Bantz'a entegre edildiğinde:
- "Şu Python scripti yaz" → kod yazma
- "Bu dosyadaki bug'ı bul ve düzelt" → kod düzeltme
- Self-evolving agent'ın skill yazma yeteneği (Issue #811)

## Kapsam

### Dahil

- **OpenCode CLI entegrasyonu**: Subprocess veya library olarak çağırma
- **Kod yazma tool'u**: `coding.write_file`, `coding.edit_file`, `coding.run`
- **Proje oluşturma**: "Python projesi oluştur" → scaffold
- **Kod inceleme**: "Bu kodu incele" → analysis + öneriler
- **Sandbox çalışma**: Kod çalıştırma sandbox'ta

### Hariç

- OpenCode'un full IDE deneyimi (bu bir tool, IDE değil)
- Remote code execution
- Production deployment

## Kabul Kriterleri

- [ ] "Kod yaz" / "script oluştur" intent'i tanınıyor
- [ ] OpenCode CLI veya API çağrılabiliyor
- [ ] Yazılan kod sandbox'ta çalıştırılabiliyor
- [ ] Kod inceleme önerisi verilebiliyor
- [ ] Güvenlik: sadece izin verilen dizinlerde çalışıyor
- [ ] Test yazıldı

## Bağımlılıklar

- Issue #801 (Skill Architecture) — skill olarak tanımlanacak
- OpenCode kurulumu
- Mevcut `coding/` modülü genişletilecek

## Tahmini Süre: 1 hafta
