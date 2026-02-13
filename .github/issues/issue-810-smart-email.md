---
title: "[Feature] Mail Optimizasyonu — Otomatik Yanıt + Akıllı Mail Yönetimi"
labels: "type:feature, priority:P1, area:skill, milestone:v2"
assignees: "miclaldogan"
issue_number: 810
---

## Hedef

Gmail entegrasyonunu "oku" seviyesinden "akıllı yönetim" seviyesine çıkarmak: otomatik yanıt üretimi, mail önceliklendirme, toplu mail yönetimi, ve başkalarına mail gönderme.

## Arka Plan

Kullanıcı vizyonu: "Maillerimdeki her şeye erişimi olacak, maillerimi optimize edebilecek, otomatik yanıtlar üretebilecek, başkalarına mail gönderebilecek"

Mevcut durum: Gmail API'si var (1,184 satır), okuma/arama/etiketleme/draft çalışıyor. Email draft flow var (956 satır).

**Eksik**: Akıllı önceliklendirme, otomatik yanıt önerisi, toplu mail yönetimi, ve kişi/bağlam bazlı yanıt stili.

## Kapsam

### Dahil

- **Mail önceliklendirme**: Aciliyet × önem × kişi skoru → sıralama
- **Otomatik yanıt önerisi**: "Bu maile şu şekilde yanıt verebilirsiniz" + onay
- **Toplu mail özeti**: "Bugün 15 mail geldi, 3'ü acil, özeti..."
- **Mail gönderme**: "Ahmet'e şu konuda mail at" → draft → onay → gönder
- **Kişi bazlı ton ayarı**: Hocaya resmi, arkadaşa informal
- **Takip hatırlatma**: "3 gündür yanıt gelmedi, hatırlatma atayım mı?"
- **Contacts entegrasyonu**: İsimden e-posta çözümleme

### Hariç

- Mail şablonları (ayrı issue)
- Spam filtreleme (Gmail zaten yapıyor)

## Akış Örnekleri

```
Kullanıcı: "Mailimi kontrol et"
Bantz: "Efendim, son 24 saatte 15 mail gelmiş:
  🔴 ACİL (2):
    1. Prof. Yılmaz — 'Proje teslim tarihi değişti' (2 saat önce)
    2. GitHub — 'Security alert: dependency vulnerability' (5 saat önce)
  🟡 ÖNEMLİ (3):
    1. Ahmet — 'Toplantı notu' (dün akşam)
    2. LinkedIn — '5 yeni bağlantı isteği'
    3. Google Calendar — 'Yarın 3 toplantı hatırlatması'
  ⚪ DİĞER (10): Newsletter'lar, bildirimler...

  Prof. Yılmaz'ın mailine yanıt hazırlayayım mı?"

Kullanıcı: "Evet, nazik bir şekilde teslim tarihi için teşekkür et"
Bantz: "Taslağı hazırladım:

  'Sayın Prof. Yılmaz,
   Bilgilendirmeniz için teşekkür ederim. Yeni teslim tarihini
   not aldım ve buna göre çalışmamı planlayacağım.
   Saygılarımla'

  Göndereyim mi?"
```

## Kabul Kriterleri

- [ ] Mail önceliklendirme çalışıyor (acil/önemli/diğer)
- [ ] Otomatik yanıt taslağı üretiliyor (confirmation firewall ile)
- [ ] Mail gönderme çalışıyor (draft → onay → send)
- [ ] Kişi bazlı ton ayarı (resmi/informal)
- [ ] Toplu mail özeti (günlük digest)
- [ ] Takip hatırlatma ("3 gündür yanıt yok")
- [ ] İsimden e-posta çözümleme (contacts)
- [ ] Gemini quality tier ile mail yazımı
- [ ] Test yazıldı

## Bağımlılıklar

- Mevcut `google/gmail.py` ve `email/draft_flow.py` genişletilecek
- Mevcut `contacts/` modülü kullanılacak
- Gmail OAuth write scope eklenmeli

## Tahmini Süre: 3-4 gün
