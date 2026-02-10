---
title: "[Feature] Planner-Runtime Tool Gap Kapatma — 69 → 69 Çalışan Tool"
labels: "type:feature, priority:P1, area:tools, milestone:v2"
assignees: "miclaldogan"
issue_number: 814
---

## Hedef

Planner catalog'unda tanımlı 69 tool'dan sadece ~15'inin runtime handler'ı var. Bu gap'i kapatmak.

## Arka Plan

`agent/builtin_tools.py`'de 69 tool JSON schema ile tanımlı (LLM bunları görebiliyor ve plan yapabiliyor), ama `agent/registry.py`'de sadece ~15 tool'un gerçek handler'ı var. LLM "browser.click" planladığında ama runtime handler yoksa → hata.

## Eksik Runtime Handler'lar

### Browser Tool'ları (~11 tanımlı, kısmen handler var)
- [ ] `browser.open` — URL açma (handler var ama browser bridge eksik durumlar var)
- [ ] `browser.scan` — sayfa tarama
- [ ] `browser.click` — element tıklama
- [ ] `browser.type` — metin yazma
- [ ] `browser.scroll` — scroll
- [ ] `browser.search` — arama
- [ ] `browser.back` — geri gitme
- [ ] `browser.info` — sayfa bilgisi
- [ ] `browser.detail` — detay çekme
- [ ] `browser.wait` — bekleme

### PC Control Tool'ları (~4 tanımlı)
- [ ] `pc.hotkey` — klavye kısayolu
- [ ] `pc.mouse_move` — fare hareket
- [ ] `pc.mouse_click` — fare tıklama
- [ ] `pc.mouse_scroll` — fare scroll

### Dosya İşlemleri (~6 tanımlı)
- [ ] `file.read` — dosya okuma
- [ ] `file.write` — dosya yazma
- [ ] `file.edit` — dosya düzenleme
- [ ] `file.create` — dosya oluşturma
- [ ] `file.search` — dosya arama

### Terminal (~3 tanımlı)
- [ ] `terminal.run` — komut çalıştırma
- [ ] `terminal.background` — arka plan komut
- [ ] `terminal.list` — aktif process'ler

## Kabul Kriterleri

- [ ] 69 tool'un en az 40'ının runtime handler'ı var
- [ ] Browser tool'ları browser extension bridge ile çalışıyor
- [ ] PC control tool'ları xdotool/wmctrl ile çalışıyor
- [ ] Dosya tool'ları sandbox içinde çalışıyor (güvenlik)
- [ ] Terminal tool'ları policy.json kurallarına uyuyor
- [ ] Her tool'un risk sınıflandırması doğru (tools/metadata.py)
- [ ] Test yazıldı

## Bağımlılıklar

- Mevcut `tools/metadata.py` risk sınıflandırmaları
- Mevcut `config/policy.json` güvenlik kuralları
- Mevcut `bantz-extension/` browser bridge

## Tahmini Süre: 1 hafta
