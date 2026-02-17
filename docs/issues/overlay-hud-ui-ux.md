# Bantz Overlay HUD — UI/UX Issue Tracker

> **Epic:** Bantz Overlay HUD — Terminal Estetiğinde Gelişmiş Masaüstü Asistanı UI
> **Son Güncelleme:** 2025-02-17

---

## 🔥 Kritik Teşhis (Neden Sadece Dikdörtgen Görünüyor)

Overlay'da sadece boş turuncu dikdörtgen görünmesinin 3+1 sebebi vardı (hepsi çözüldü ✅):

1. ~~**Daemon bağlantısı yok** → panellere veri gelmiyor → hiçbiri gösterilmiyor~~ → **Demo mode eklendi** ✅
2. ~~**Demo/Mock veri modu yok** → IPC mesajı olmadan paneller populate olmuyor~~ → **`demo-mode.js` oluşturuldu** ✅
3. ~~**`briefing_start` mesajı gerekli** → `playBootSequence()` tetiklenmiyor~~ → **Demo mode auto-start** ✅
4. ~~**Three.js ES module loading** hatalı~~ → **`three.core.min.js` vendor'a kopyalandı + `app://` protocol handler eklendi** ✅
5. ~~**Panel element getter eksik** → LayoutEngine panelleri kaydedemiyordu~~ → **Wrapper sınıflara `.element` getter eklendi** ✅

---

## 📋 Master Checklist

### Phase 0: Temel Altyapı & Hata Düzeltme

- [x] **#OVR-001** — Terminal panel bileşeni (TerminalPanel) ✅
- [x] **#OVR-002** — Panel layout motoru (PanelLayoutEngine) ✅
- [x] **#OVR-003** — HUD panel temel CSS (glass morphism, CRT scanlines) ✅
- [x] **#OVR-004** — Demo/Mock veri modu ekle (daemon olmadan test) ✅ `demo-mode.js` oluşturuldu
- [x] **#OVR-005** — Three.js modül yükleme hatası düzelt ✅ `three.core.min.js` + `app://` protocol
- [x] **#OVR-006** — Panelleri boot sequence olmadan da göster (auto-show) ✅ Demo mode `_forceShowPanels()`
- [x] **#OVR-007** — Panel wrapper sınıflarına `.element` getter ekle ✅ LayoutEngine registration fix

### Phase 1: Particle Küre (Merkez Ana Öğe)

- [x] **#OVR-010** — Fibonacci sphere particle dağıtımı ✅
- [x] **#OVR-011** — Three.js Points ile render ✅
- [x] **#OVR-012** — Mouse hover scatter/dust etkisi ✅
- [x] **#OVR-013** — State animasyonları (idle/wake/listen/think/speak) ✅
- [x] **#OVR-014** — Küre görünür durumda mı doğrula (runtime test) ✅ canvasCount:1, 560 particles
- [ ] **#OVR-015** — Küre boyutunu viewport'a göre responsif yap
- [ ] **#OVR-016** — Küre idle animasyonu iyileştir (daha organik hareket)

### Phase 2: Terminal Alt-Paneller (Kenarlardan Taşan)

- [x] **#OVR-020** — Haber Akışı paneli (NewsFeedPanel) ✅
- [x] **#OVR-021** — Günlük Ajanda paneli (DailyTasksPanel) ✅
- [x] **#OVR-022** — Sistem Durumu paneli (SystemStatusPanel) ✅
- [x] **#OVR-023** — Haber görseli popup (NewsImagePopup) ✅
- [ ] **#OVR-024** — Panel konumlandırma fine-tune (taşma miktarları)
- [ ] **#OVR-025** — Panel'lerin dikdörtgenden dışarı taşma görselliği doğrula
- [ ] **#OVR-026** — Panel boyut/konum animasyonları pürüzsüz mü test et
- [ ] **#OVR-027** — Panel hover efekti: border glow intensify

### Phase 3: Konuşma & Metin Çıkışı (Alt Bölüm)

- [x] **#OVR-030** — Typewriter daktilo yazı efekti ✅
- [x] **#OVR-031** — Reasoning chain (düşünce zinciri) muted text ✅
- [x] **#OVR-032** — TTS ses senkronizasyonu ✅
- [ ] **#OVR-033** — Typewriter token hızını ayarla (30ms → gerçekçi)
- [ ] **#OVR-034** — Reasoning chain fade in/out animasyonu doğrula
- [ ] **#OVR-035** — Konuşma + reasoning aynı anda çalışıyor mu test et

### Phase 4: Glitch & CRT Efektleri

- [x] **#OVR-040** — CRT scanline overlay ✅
- [x] **#OVR-041** — Chromatic aberration (RGB shift) ✅
- [x] **#OVR-042** — Random flicker efekti ✅
- [x] **#OVR-043** — Screen noise overlay (SVG filter) ✅
- [x] **#OVR-044** — Wake flicker burst ✅
- [ ] **#OVR-045** — Glitch efekti yoğunluk seviyeleri test (subtle/moderate/intense)
- [ ] **#OVR-046** — Glitch turuncu renk tonuyla uyumlu mu kontrol et
- [ ] **#OVR-047** — Prefers-reduced-motion desteği doğrula

### Phase 5: Panel Geçiş Animasyonları

- [x] **#OVR-050** — Slide-in/out animasyonlar ✅
- [x] **#OVR-051** — Boot sequence (sıralı panel açılış) ✅
- [x] **#OVR-052** — CRT power-off dismiss efekti ✅
- [x] **#OVR-053** — State change koreografi ✅
- [ ] **#OVR-054** — Boot sequence zamanlamasını test et (~2s)
- [ ] **#OVR-055** — Panel geçişlerinde stutter var mı kontrol et

### Phase 6: Tasarım Polish & UX

- [ ] **#OVR-060** — Renk paleti tam uyumlu mu (turuncu + cyan harmoni)
- [ ] **#OVR-061** — Font yükleme: JetBrains Mono system fallback doğrula
- [ ] **#OVR-062** — Panel kenarlıkları: keskin köşeler (border-radius: 0px) ✅
- [ ] **#OVR-063** — Scrollbar stilleri: thin, cyan, rounded ✅
- [ ] **#OVR-064** — Küçük ekranlarda (<800px) panel collapse testi
- [ ] **#OVR-065** — HUD panel boyutu (65vw × 55vh) optimal mi
- [ ] **#OVR-066** — Transparent background masaüstünde düzgün çalışıyor mu (X11/Wayland)

### Phase 7: Etkileşim & Erişilebilirlik

- [ ] **#OVR-070** — Mouse enter/leave click-through geçişi sorunsuz mu
- [ ] **#OVR-071** — Panel hover pause (otomatik scroll durma)
- [ ] **#OVR-072** — News tooltip hover doğru konumlanıyor mu
- [ ] **#OVR-073** — Küre mouse scatter responsif mi (lag yok mu)
- [ ] **#OVR-074** — Keyboard shortcut (Super+Shift+B) toggle çalışıyor mu

---

## 🎯 Öncelik Sırası

| Öncelik | Issue | Açıklama |
|---------|-------|----------|
| ✅ P0 | OVR-004 | ~~Demo mode~~ ÇÖZÜLDÜ |
| ✅ P0 | OVR-005 | ~~Three.js modül yükleme~~ ÇÖZÜLDÜ |
| ✅ P0 | OVR-006 | ~~Panel auto-show~~ ÇÖZÜLDÜ |
| ✅ P0 | OVR-007 | ~~Panel element getter~~ ÇÖZÜLDÜ |
| ✅ P1 | OVR-014 | ~~Küre runtime doğrulama~~ ÇÖZÜLDÜ |
| 🟡 P1 | OVR-024-027 | Panel konumlandırma fine-tune |
| 🟡 P1 | OVR-033-035 | Typewriter + reasoning test |
| 🟢 P2 | OVR-045-047 | Glitch efekt polish |
| 🟢 P2 | OVR-060-066 | Tasarım polish |
| 🔵 P3 | OVR-070-074 | Etkileşim fine-tune |

---

## 🏗️ Teknik Mimari Özet

```
index.html
├── styles.css (CSS variables, glass morphism, CRT, animations)
├── components/ (regular scripts — window.* globals)
│   ├── terminal-panel.js   — Base reusable panel bileşeni
│   ├── panel-layout.js     — Slot-based layout motoru
│   ├── news-feed.js        — Haber akışı paneli
│   ├── news-image-popup.js — Görsel popup
│   ├── daily-tasks.js      — Günlük ajanda paneli
│   ├── system-status.js    — Hava + sistem durumu paneli
│   ├── typewriter.js       — Daktilo metin çıkışı
│   ├── reasoning-chain.js  — Düşünce zinciri
│   ├── glitch-effects.js   — CRT/noise/chromatic efektleri
│   ├── panel-transitions.js — Animasyon koreografi
│   └── tts-sync.js         — TTS ses senkronizasyon
├── components/ (ES modules — import/export)
│   ├── particle-sphere.js  — Three.js particle küre
│   ├── particle-scatter.js — Mouse hover dust efekti
│   └── sphere-state.js     — Küre state animasyonları
├── vendor/
│   ├── three.min.js        — Three.js r182 (ESM, re-exports core)
│   └── three.core.min.js   — Three.js r182 core (self-contained)
└── renderer.js (ES module — ana orchestrator)
```

## 📌 Sonraki Adım

**Tüm P0 blokerleri çözüldü** (2025-02-17):

- `#OVR-004` — Demo Mode oluşturuldu (`demo-mode.js`)
- `#OVR-005` — Three.js modül zinciri düzeltildi (`three.core.min.js` + `app://` protocol)
- `#OVR-006` — Panel auto-show: demo mode 3 saniye sonra otomatik başlıyor
- `#OVR-007` — Panel wrapper `.element` getter: LayoutEngine artık panelleri buluyor

**Doğrulama logları:**
```
[Sphere] Initialized: 560 particles ✅
[PanelLayout] Registered "news-feed" → slot "right" ✅
[PanelLayout] Registered "daily-tasks" → slot "left" ✅
[PanelLayout] Registered "system-status" → slot "bottom-left" ✅
[DemoMode] ═══ DEMO MODE ACTIVE ═══ ✅
panelCount: 3, canvasCount: 1 ✅
```

Artık `npm run dev` ile overlay'ı çalıştırıp tüm bileşenleri
daemon olmadan test edebilirsiniz.
