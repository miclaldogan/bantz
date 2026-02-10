---
title: "[Feature] REST API + Telefon İstemcisi — Dışarıdan HTTP erişimi"
labels: "type:feature, priority:P0, area:core, milestone:v2"
assignees: "miclaldogan"
issue_number: 802
---

## Hedef

Bantz'a HTTP REST API ekleyerek telefon, tablet veya herhangi bir cihazdan mesaj gönderilebilir hale getirmek. Şu an sadece Unix socket var — bu sadece aynı makineden çalışıyor.

## Arka Plan

Kullanıcı vizyonu: "Telefonuma küçük bir şey kurarız, o da bilgisayarıma istek atar API yoluyla"

Şu an `server.py` (877 satır) bir Unix socket daemon. Dışarıdan erişim yok. Mesaj tabanlı kontrol için HTTP API şart.

## Kapsam

### Dahil

- **FastAPI/Starlette tabanlı HTTP server** — `/api/v1/chat`, `/api/v1/status`, `/api/v1/skills`
- **WebSocket endpoint** — streaming yanıtlar için `/ws/chat`
- **Auth layer** — Bearer token veya API key bazlı (basit ama güvenli)
- **Mevcut brain pipeline entegrasyonu** — HTTP request → BantzServer → brain → response
- **CORS ayarları** — telefon istemcisi için
- **Health endpoint** — `/api/v1/health`
- **Proaktif bildirim endpoint'i** — `/api/v1/notifications` (SSE veya WS)

### Hariç

- Telefon uygulaması (ayrı issue)
- Web UI dashboard (ayrı issue)
- Multi-user (tek kullanıcı, kişisel asistan)

## API Tasarımı

```
POST /api/v1/chat
{
  "message": "bugün neler var takvimimde?",
  "stream": false,
  "session_id": "optional"
}

→ 200 OK
{
  "response": "Bugün 3 toplantınız var...",
  "tools_used": ["calendar.list_events"],
  "tier": "quality",
  "latency_ms": 1250
}

GET  /api/v1/health          → {"status": "ok", "vllm": true, "gemini": true}
GET  /api/v1/skills          → [{"name": "weather", "status": "active"}, ...]
GET  /api/v1/notifications   → SSE stream (proaktif bildirimler)
WS   /ws/chat                → streaming chat
```

## Kabul Kriterleri

- [ ] `bantz --serve --http` ile HTTP server başlıyor (varsayılan port 8088)
- [ ] `POST /api/v1/chat` mesaj gönderip yanıt alınabiliyor
- [ ] WebSocket `/ws/chat` ile streaming çalışıyor
- [ ] Bearer token auth aktif (env: `BANTZ_API_TOKEN`)
- [ ] Mevcut brain pipeline aynen kullanılıyor (code duplication yok)
- [ ] Health endpoint vLLM ve Gemini durumunu raporluyor
- [ ] curl ile test edilebilir
- [ ] Test yazıldı

## Bağımlılıklar

- `fastapi` ve `uvicorn` dependency olarak eklenmeli
- Mevcut `server.py` Unix socket logic'i korunmalı (ek olarak HTTP)

## Öncelik: P0 — Telefon erişimi ve otomasyon için temel

## Tahmini Süre: 3-4 gün
