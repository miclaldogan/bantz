# Bantz Overlay — Asset Source of Truth

Bu klasör, overlay uygulamasının **canonical kaynak asset'lerini** içerir.

## Boot Logo Varyantları

| Dosya | Kullanım | Boyut |
|---|---|---|
| `bantz_no_bg_KEEP_SMILE_CLEAN.png` | Boot ekranı (primary, şeffaf arka plan) | 1600×679 @ 8-bit RGBA |
| `bantz.png` | Fallback / tray icon kaynağı | 1600×679 JPEG |
| `tray-icon.svg` | Tray icon (vektör) | SVG |

## HiDPI Desteği

`scripts/copy-assets.js` çalıştırıldığında:
- `bantz_no_bg_KEEP_SMILE_CLEAN.png` → `src/renderer/assets/bantz_no_bg_KEEP_SMILE_CLEAN.png` (1x)
- `bantz_no_bg_KEEP_SMILE_CLEAN.png` → `src/renderer/assets/bantz_no_bg_KEEP_SMILE_CLEAN@2x.png` (2x, aynı dosya — orijinal 1600px yeterince büyük)

## Otomatik Kopyalama

Asset'ler, build/start öncesi otomatik olarak `src/renderer/assets/` hedefine kopyalanır:

```bash
npm run copy-assets      # manuel
npm run dev              # predev hook ile otomatik
npm run start            # prestart hook ile otomatik
npm run build            # prebuild hook ile otomatik
```

## Önce Buraya Bak

Logo değiştirilecekse:
1. Bu klasördeki (`bantz-overlay/assets/`) dosyayı güncelle
2. `npm run copy-assets` çalıştır
3. `src/renderer/assets/` klasörünü **doğrudan düzenleme** — o klasör build artifact'idir

## Fallback Stratejisi

`index.html` içindeki `<img>` tag'i, dosya yüklenemediğinde otomatik olarak
metin tabanlı lockup'a geçer:

```html
<img src="assets/bantz_no_bg_KEEP_SMILE_CLEAN.png"
     onerror="..." />
```

Fallback: `BANTZ` metni CSS animasyonu ile gösterilir — build kırılmaz.
