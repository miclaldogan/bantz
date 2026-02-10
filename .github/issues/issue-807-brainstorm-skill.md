---
title: "[Skill] Beyin Fırtınası Modu — Yapılandırılmış Düşünce Partneri"
labels: "type:feature, priority:P2, area:skill, milestone:v2"
assignees: "miclaldogan"
issue_number: 807
---

## Hedef

"Hadi beyin fırtınası yapalım" dendiğinde yapılandırılmış bir düşünce ortağı olarak çalışan brainstorming skill'i.

## Arka Plan

Kullanıcı vizyonu: "Ben ona şöyle bir fikrim var hadi beyin fırtınası yapalım dediğimde bunu yapabilecek"

Bu, Bantz'ın sadece görev yürüten değil, **düşünce partneri** olmasını sağlayan bir skill. Multi-turn konuşma ve Gemini quality tier gerektirir.

## Kapsam

### Dahil

- **Beyin fırtınası başlatma**: "hadi beyin fırtınası yapalım" → mod aktif
- **Yapılandırılmış akış**: Fikir toplama → Gruplama → Değerlendirme → Aksiyon planı
- **Teknikler**: Mind mapping, SWOT, 6 şapka, pro/con analizi
- **Multi-turn konuşma**: Mod içinde follow-up sorular, derinleştirme
- **Çıktı formatı**: Markdown rapor + opsiyonel takvim aksiyonları
- **Memory entegrasyonu**: Önceki brainstorm'lar hatırlansın

### Hariç

- Görsel mind map (UI gerektirir)
- Ekip brainstorm (multi-user)

## Akış Örneği

```
Kullanıcı: "Bir fikrim var, hadi beyin fırtınası yapalım"
Bantz: "Tabii efendim! Fikriniz nedir, başlayalım 🧠"

Kullanıcı: "Üniversitede bir yapay zeka kulübü kurmak istiyorum"
Bantz: "Harika bir fikir! Bunu birkaç açıdan düşünelim:

📋 TEMEL SORULAR:
1. Hedef kitleniz kim? (Mühendislik, tüm bölümler?)
2. Ne sıklıkta toplanmak istersiniz?
3. Bütçe/sponsorluk düşünüyor musunuz?

Bunları konuşalım, sonra bir eylem planı çıkaralım."

Kullanıcı: "Tüm bölümlerden, haftada bir, sponsorluk olsa güzel olur"
Bantz: "Anladım! İşte bir çerçeve:

🎯 SWOT ANALİZİ:
Güçlü: Yapay zeka trending, geniş ilgi
Zayıf: Teknik seviye farklılıkları
Fırsat: Şirket sponsorlukları, hackathon'lar
Tehdit: Sürdürülebilirlik, ilgi kaybı

📅 EYLEM PLANI:
1. Bu hafta: Üniversite kulüp kurallarını araştır
2. Gelecek hafta: 5 potansiyel üyeyle konuş
3. 2 hafta: Tanıtım afişi + ilk toplantı planı

Takvime ekleyeyim mi?"
```

## Kabul Kriterleri

- [ ] "beyin fırtınası" / "brainstorm" trigger'ı çalışıyor
- [ ] Multi-turn konuşma modu aktif kalıyor
- [ ] En az 2 teknik (SWOT, pro/con) uygulanabiliyor
- [ ] Eylem planı çıktısı Markdown formatında
- [ ] Takvime aksiyon ekleme opsiyonu
- [ ] Gemini quality tier ile çalışıyor (derin düşünme)
- [ ] Brainstorm hafızası (önceki oturumlar hatırlanıyor)
- [ ] Test yazıldı

## Bağımlılıklar

- Mevcut brain pipeline (quality tier)
- Memory sistemi

## Tahmini Süre: 2-3 gün
