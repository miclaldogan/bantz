---
title: "[Skill] Haber Takibi — Proaktif Gündem Özeti + İnteraktif Soru-Cevap"
labels: "type:feature, priority:P1, area:skill, milestone:v2"
assignees: "miclaldogan"
issue_number: 804
---

## Hedef

Bantz'ın sürekli gündem takip etmesi, kullanıcının ilgi alanlarına göre haberleri filtreleyip özetlemesi, ve "bu haberin detayı neydi?" diye sorulduğunda interaktif soru-cevap yapması.

## Arka Plan

Kullanıcı vizyonu: "Gündemi takip edecek sürekli, gündemde benimle alakalı haberleri okuyup (Türkiye gündemi, yapay zeka haberleri gibi), özetini çıkartacak, kendince önemli bulduğu kısımları bana anlatacak, ve 'şu haberin içeriği tam olarak neydi' dediğimde hem link vererek hem de sorularıma yanıt verecek"

Mevcut durum: `skills/news.py` (browser scraping) ve `skills/news_rss.py` (RSS) var ama:
- Proaktif takip yok (sadece sorulunca çalışıyor)
- Kişiselleştirilmiş filtreleme yok
- İnteraktif soru-cevap yok
- Haber hafızası yok

## Kapsam

### Dahil

- **Haber kaynakları**: RSS (NTV, Hürriyet, TechCrunch, The Verge, HackerNews) + web scraping
- **İlgi alanı profili**: Kullanıcı profili'nde tanımlı konular (yapay zeka, teknoloji, Türkiye gündemi, vb.)
- **Periyodik tarama**: Arka planda her 30dk (configurable) haber taraması
- **Akıllı filtreleme**: İlgi alanına göre skor + önem sıralaması
- **Günlük brifing**: Sabah otomatik haber özeti (proaktif)
- **İnteraktif soru-cevap**: "bu haber hakkında daha fazla bilgi ver" → link + detaylı analiz
- **Haber hafızası**: Okunan haberler memory'ye kaydedilsin, tekrar sorulduğunda hatırlasın
- **Kaynak gösterme**: Her haberde URL + kaynak + tarih

### Hariç

- Haber push notification (mobil — ayrı issue)
- Sosyal medya monitoring (ayrı issue)
- Video haber analizi

## Akış

```
[Arka Plan Taraması]
  │
  ├── Her 30dk: RSS + web kaynaklarını tara
  ├── İlgi alanı profili ile filtrele
  ├── Önem skoru hesapla (kaynak güvenilirliği × ilgi alanı eşleşmesi × güncellik)
  └── Önemli haberler → proaktif bildirim kuyruğu

[Kullanıcı Sorgusu]
  │
  ├── "bugünkü haberler ne?" → Filtrelenmiş günlük brifing
  ├── "yapay zeka haberleri var mı?" → Konu bazlı arama
  ├── "bu haberin detayı neydi?" → Context'ten haber bul → full article → QA
  └── "link gönder" → URL paylaş

[İnteraktif Soru-Cevap]
  │
  ├── Haber içeriğini context'e yükle (progressive loading)
  ├── Kullanıcının sorularını cevapla (Gemini quality tier)
  └── Follow-up desteği: "peki bunun Türkiye'ye etkisi ne?"
```

## İlgi Alanı Profili Örnek

```yaml
# ~/.config/bantz/news_profile.yaml
interests:
  - topic: "yapay zeka"
    keywords: ["AI", "LLM", "GPT", "Claude", "Gemini", "makine öğrenmesi"]
    priority: high
  - topic: "Türkiye gündemi"
    keywords: ["Türkiye", "TBMM", "ekonomi", "döviz"]
    priority: medium
  - topic: "teknoloji"
    keywords: ["startup", "Apple", "Google", "Microsoft"]
    priority: medium
sources:
  - url: "https://feeds.bbci.co.uk/turkce/rss.xml"
    trust: high
  - url: "https://news.ycombinator.com/rss"
    trust: high
  - url: "https://www.ntv.com.tr/son-dakika.rss"
    trust: medium
scan_interval_minutes: 30
daily_briefing_time: "08:00"
max_articles_per_briefing: 10
```

## Kabul Kriterleri

- [ ] RSS + web scraping kaynaklardan haber toplama çalışıyor
- [ ] İlgi alanı profili okunuyor ve haberler filtreleniyor
- [ ] Arka plan periyodik tarama çalışıyor (scheduler entegrasyonu)
- [ ] "bugünkü haberler" komutu filtrelenmiş özet veriyor
- [ ] "bu haberin detayı?" → tam haber çekme + QA modu
- [ ] Her haberde kaynak URL + tarih gösteriliyor
- [ ] Haber hafızası (memory'ye kayıt) çalışıyor
- [ ] Sabah otomatik brifing (proaktif notification)
- [ ] En az 5 Türkçe kaynak entegre
- [ ] Test yazıldı

## Bağımlılıklar

- Issue #801 (Skill Architecture) — tercihen
- Issue #806 (Proaktif Zeka) — sabah brifing için
- Mevcut `skills/news.py` ve `skills/news_rss.py` refactor edilecek

## Tahmini Süre: 4-5 gün
