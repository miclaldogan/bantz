---
title: "[Architecture] Declarative Skill Sistemi — SKILL.md bazlı kolay skill ekleme"
labels: "type:feature, priority:P0, area:architecture, milestone:v2"
assignees: "miclaldogan"
issue_number: 801
---

## Hedef

Bantz'a yeni skill eklemek için **Python kodu yazmaya gerek kalmadan**, SKILL.md dosyası ile declarative skill tanımlama sistemi kurmak. OpenClaw'dan ilham alarak ama Bantz'ın 3B router + Gemini mimarisine uygun.

## Arka Plan

Şu an Bantz'da skill eklemek için:
1. `src/bantz/skills/` altına Python modülü yaz
2. `agent/builtin_tools.py`'ye 69 tool'luk listeye ekle
3. `agent/registry.py`'de runtime handler bağla
4. `routing/preroute.py`'ye keyword ekle
5. `nlu/hybrid.py`'ye regex pattern ekle

Bu 5 adım, yeni skill eklemeyi çok zorlaştırıyor. OpenClaw'da ise bir `SKILL.md` dosyası bırakmak yeterli.

## Kapsam

### Dahil

- **SKILL.md formatı**: YAML frontmatter (name, description, triggers, tools, permissions) + Markdown instructions
- **Skill dizin yapısı**: `~/.config/bantz/skills/<skill-name>/SKILL.md`
- **Auto-discovery**: Startup'ta ve runtime'da skill dizinlerini tara
- **Progressive loading**: Sadece tetiklendiğinde SKILL.md body'si context'e yüklensin
- **Built-in skill'leri migrate et**: news, daily, pc, summarizer → SKILL.md formatına
- **Skill CLI**: `bantz skill list`, `bantz skill install <path/url>`, `bantz skill create <name>`
- **Planner entegrasyonu**: Skill tool'ları otomatik olarak planner catalog'a eklensin

### Hariç

- Online skill registry (ayrı issue)
- Self-generating skill (ayrı issue)
- Mobile skill management

## Teknik Tasarım

```
~/.config/bantz/skills/
├── weather/
│   ├── SKILL.md          # Frontmatter + instructions
│   ├── scripts/          # Opsiyonel Python/Bash helper
│   └── references/       # Domain dokümanları
├── news-tracker/
│   ├── SKILL.md
│   └── templates/
└── classroom/
    ├── SKILL.md
    └── scripts/
```

### SKILL.md Örnek Format:

```markdown
---
name: weather
version: 1.0.0
description: Hava durumu sorgulama ve takvimle çapraz akıl yürütme
triggers:
  - "hava durumu"
  - "dışarı çıkabilir miyim"
  - "bugün hava nasıl"
tools:
  - name: weather.get_forecast
    params: {location: string, days: int}
    risk: safe
  - name: weather.get_current
    params: {location: string}
    risk: safe
permissions:
  - network
  - calendar.read
priority: normal
language: tr
---

## Davranış

Kullanıcı hava durumunu sorduğunda:
1. Konumunu belirle (varsayılan: profil konumu)
2. OpenWeatherMap API ile hava durumunu çek
3. Eğer takvimde dış mekan etkinliği varsa, çapraz analiz yap
4. Kötü hava + dış mekan planı varsa proaktif uyarı ver

## Yanıt Formatı
- Sıcaklık, nem, rüzgar, yağış olasılığı
- Takvim çapraz analizi (varsa)
- Öneri (şemsiye al, planı iptal et, vb.)
```

## Kabul Kriterleri

- [ ] `~/.config/bantz/skills/` dizini taranıyor ve skill'ler yükleniyor
- [ ] SKILL.md frontmatter parse ediliyor (YAML)
- [ ] Trigger'lar NLU'ya otomatik ekleniyor
- [ ] Tool tanımları planner catalog'a ekleniyor
- [ ] Progressive loading: body sadece tetiklendiğinde yükleniyor
- [ ] `bantz skill list` çalışıyor
- [ ] `bantz skill create weather` scaffold oluşturuyor
- [ ] En az 2 mevcut skill (news, daily) migrate edilmiş
- [ ] Test yazıldı

## Bağımlılıklar

- Yok (temel mimari değişiklik, ilk yapılması gereken)

## Öncelik: P0 — Diğer tüm skill issue'ları buna bağımlı

## Tahmini Süre: 1 hafta
