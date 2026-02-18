# Boot Logo — Kullanım Notu

## Genel Bakış

Bantz Overlay, açılış sırasında (`phase-boot`) tam ekran bir boot animasyonu gösterir.
Bu animasyonun merkezinde `bantz_no_bg_KEEP_SMILE_CLEAN.png` logosu yer alır.

## Asset Pipeline (Issue #1464)

```
docs/bantz_no_bg_KEEP_SMILE_CLEAN.png   ← orijinal kaynak (repository referansı)
bantz-overlay/assets/                   ← canonical source-of-truth
    bantz_no_bg_KEEP_SMILE_CLEAN.png
    bantz.png
    tray-icon.svg
         │
         │  npm run copy-assets
         ▼
bantz-overlay/src/renderer/assets/      ← build artifact (git'te takip edilir)
    bantz_no_bg_KEEP_SMILE_CLEAN.png    (1x)
    bantz_no_bg_KEEP_SMILE_CLEAN@2x.png (2x HiDPI alias)
    bantz.png
```

## Logo Değiştirme

1. Yeni PNG dosyasını `bantz-overlay/assets/` klasörüne koy
2. `cd bantz-overlay && npm run copy-assets` çalıştır
3. `src/renderer/assets/` klasörünü **doğrudan düzenleme**

## Fallback Stratejisi

Logo dosyası yüklenemezse (`onerror`) otomatik olarak metin tabanlı lockup gösterilir:

```
  ██████╗  █████╗ ███╗   ██╗████████╗███████╗
  ██╔══██╗██╔══██╗████╗  ██║╚══██╔══╝╚══███╔╝
  ██████╔╝███████║██╔██╗ ██║   ██║     ███╔╝
  ██╔══██╗██╔══██║██║╚██╗██║   ██║    ███╔╝
  ██████╔╝██║  ██║██║ ╚████║   ██║   ███████╗
  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚══════╝
```

→ CSS sınıfı: `.boot-text` (styles.css içinde tanımlı)

**Kabul kriteri:** Boot ekranı hiçbir koşulda beyaz ekran veya JS hatası üretmez.

## HiDPI (Retina) Desteği

`<picture>` elementi ile `@2x` varyant otomatik seçilir:

```html
<picture>
  <source srcset="assets/bantz_no_bg_KEEP_SMILE_CLEAN@2x.png 2x,
                  assets/bantz_no_bg_KEEP_SMILE_CLEAN.png 1x" type="image/png" />
  <img src="assets/bantz_no_bg_KEEP_SMILE_CLEAN.png" ... />
</picture>
```

Orijinal logo 1600×679px olduğundan, `@2x` slot için aynı dosya yeterlidir
(800px display size × 2 = 1600px).

## Build Doğrulama

```bash
cd bantz-overlay
npm run copy-assets     # asset'leri kopyala
npm run build:linux     # AppImage üret
ls dist/                # bantz-overlay çıktısını kontrol et
```

electron-builder `extraResources` konfigürasyonu sayesinde tüm `*.png` / `*.webp` / `*.svg` 
dosyaları pakete dahil edilir.
