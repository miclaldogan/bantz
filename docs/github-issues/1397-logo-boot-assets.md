# Issue Draft — Overlay Boot Logo & Asset Pipeline

## Summary
Boot sequence’de kullanılan BANTZ logo dosyalarının (`bantz.png`, `bantz_no_bg_KEEP_SMILE_CLEAN.png`) üretim pipeline’ında resmi asset olarak yönetilmesi.

## Context
- Şu an dosyalar renderer assets’e kopyalanarak kullanılıyor.
- Uzun vadede logo varyantları, boyut optimizasyonu ve versiyonlama tek noktada tutulmalı.

## Scope
1. Logo dosyalarını tek bir canonical assets klasörüne taşı (source-of-truth).
2. Build sırasında renderer assets’e otomatik kopyalama/packaging adımı.
3. HiDPI için alternatif boyutlar (1x/2x) ve opsiyonel WebP.
4. Boot sequence için fallback logo stratejisi (dosya yoksa metin tabanlı lockup).
5. Tasarım dokümanına hangi logo hangi fazda kullanılıyor bilgisi.

## Acceptance Criteria
- [ ] Boot ekranında logo yolu hard-fail üretmez; fallback vardır.
- [ ] Asset yolu değişince CI/build kırılmaz.
- [ ] Paket çıktısında gerekli logo dosyaları doğrulanır.
- [ ] `README` veya `docs` içinde boot-logo kullanım notu bulunur.

## Assets
- `docs/bantz.png`
- `docs/bantz_no_bg_KEEP_SMILE_CLEAN.png`

## Notes
- Bu issue #1397 epik alt görevi olarak takip edilebilir.
