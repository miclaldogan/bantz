---
title: "[Feature] Mobil İstemci — Telefon API Client (Flutter/React Native Lite)"
labels: "type:feature, priority:P2, area:mobile, milestone:v2-future"
assignees: "miclaldogan"
issue_number: 815
---

## Hedef

REST API (Issue #802) üzerinden Bantz ile iletişim kuran basit bir telefon uygulaması.

## Arka Plan

Kullanıcı vizyonu: "Telefonuma küçük bir şey kurarız, o da bilgisayarıma istek atar API yoluyla"

İlk aşamada basit bir chat arayüzü yeterli. Bilgisayardaki Bantz daemon'una HTTP/WS üzerinden bağlanacak.

## Kapsam

### Dahil (MVP)

- **Basit chat UI**: Mesaj gönder/al (material design)
- **REST API bağlantısı**: Issue #802'deki endpoint'lere bağlanma
- **WebSocket streaming**: Yanıt stream'i gerçek zamanlı
- **Bildirim**: Proaktif mesajlar push notification olarak
- **Bağlantı durumu**: Online/offline gösterge
- **QR ile pairing**: Bilgisayardaki API URL + token QR ile aktarma

### Hariç (MVP dışı)

- Ses giriş/çıkış (v2'de)
- Ekran yakalama
- Widget'lar

## Teknoloji Seçenekleri

| Seçenek | Pro | Con |
|---------|-----|-----|
| Flutter | Tek codebase, hızlı | Dart öğrenme |
| React Native | JS bilgisi var | Bundle boyutu |
| PWA | Sıfır install | Push notification kısıtlı |
| Telegram Bot | Zaten hazır platform | Bağımlılık |

**Öneri**: İlk aşama PWA (web app), sonra Flutter native app.

## Kabul Kriterleri

- [ ] Telefondan Bantz'a mesaj gönderilip yanıt alınabiliyor
- [ ] Streaming yanıtlar gerçek zamanlı görünüyor
- [ ] Proaktif bildirimler alınıyor
- [ ] QR ile kolay pairing
- [ ] Offline durumda hata mesajı

## Bağımlılıklar

- Issue #802 (REST API) — **ZORUNLU**

## Tahmini Süre: 1 hafta (PWA MVP)
