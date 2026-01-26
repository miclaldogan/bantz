# Bantz Browser

Bantz'ın kendi tarayıcı kabuğu - Electron tabanlı, Bantz Core ile entegre.

## Özellikler (v0.1.0)

- 🌐 **Gerçek tarayıcı**: Chromium tabanlı, tam web desteği
- 📋 **Sayfa tarama**: Tıklanabilir elementleri listele
- 🖱️ **Element kontrolü**: ID ile tıkla, yaz
- 💬 **Bantz Panel**: Sağ tarafta komut paneli
- 🔗 **Core entegrasyonu**: Unix socket üzerinden daemon ile iletişim
- 🍪 **Kalıcı profil**: Cookie ve oturum bilgileri saklanır

## Kurulum

```bash
cd bantz-browser
npm install
```

## Çalıştırma

```bash
# Önce Bantz Core daemon'u başlat
systemctl --user start bantz

# Sonra browser'ı aç
npm start

# Geliştirme modu (DevTools açık)
npm run dev
```

## Klavye Kısayolları

| Kısayol | Aksiyon |
|---------|---------|
| `Ctrl+B` | Bantz panelini aç/kapat |
| `Ctrl+L` | URL çubuğuna odaklan |
| `Ctrl+K` | Komut girişine odaklan |
| `F5` | Sayfayı yenile |
| `Alt+←` | Geri git |
| `Alt+→` | İleri git |
| `Escape` | Web sayfasına odaklan |

## Panel Komutları

### Navigasyon
- `git <url>` - URL'ye git
- `aç <site>` - Site aç (protocol eklenir)
- `geri` / `geri dön` - Önceki sayfaya dön
- `ileri` - Sonraki sayfaya git
- `yenile` - Sayfayı yenile

### Sayfa Tarama
- `sayfayı tara` / `tara` - Tıklanabilir elementleri listele
- `daha fazla` / `daha` - Sonraki 10 elementi göster
- `detay <N>` - Element N'nin detaylarını göster

### Element Etkileşimi
- `<N>'ye tıkla` / `tıkla <N>` - Element N'ye tıkla
- `<N>'ye yaz: <metin>` - Element N'ye metin yaz

### Hızlı Butonlar
Panel altındaki butonlar:
- 📋 **Tara** - Sayfayı tara
- ⬇️ **Daha** - Daha fazla göster
- ◀️ **Geri** - Geri git
- 🔄 **Yenile** - Yenile

## Mimari

```
bantz-browser/
├── src/
│   ├── main/
│   │   ├── main.js        # Electron main process
│   │   └── preload.js     # Secure IPC bridge
│   └── renderer/
│       ├── index.html     # UI yapısı
│       ├── styles.css     # Stiller
│       ├── renderer.js    # UI mantığı
│       └── webview-preload.js  # Sayfa içi script
├── assets/
│   └── icon.png           # Uygulama ikonu
└── package.json
```

## Core İletişimi

Browser, Bantz Core daemon'a Unix socket üzerinden bağlanır:
- Socket: `/tmp/bantz_sessions/default.sock`
- Format: JSON mesajlar

```javascript
// Browser'dan Core'a:
{ "command": "sayfayı tara" }

// Core'dan Browser'a:
{ "ok": true, "text": "...", "action": { "type": "scan" } }
```

## Sonraki Adımlar (v0.2+)

- [ ] Çoklu sekme desteği
- [ ] Geçmiş paneli
- [ ] Yer imleri
- [ ] Element overlay (sayfada ID etiketleri)
- [ ] Sesli komut entegrasyonu
- [ ] LLM entegrasyonu (proaktif öneriler)
