---
title: "[Feature] Günlük Program Yönetimi — 'Bugün ne yapmam gerekiyor?'"
labels: "type:feature, priority:P1, area:skill, milestone:v2"
assignees: "miclaldogan"
issue_number: 813
---

## Hedef

"Bugün yapmam gereken işler var mı?" dendiğinde, tüm kaynaklardan (takvim, classroom, mail, reminders) bilgi toplayıp bütünsel bir günlük program sunmak.

## Arka Plan

Kullanıcı vizyonu: "Bantz bugün yapmam gereken işler var mı dediğimde programıma baştan sona hakim olacak"

Mevcut durum: `skills/daily.py`'de temel daily briefing var ama:
- Sadece takvim kontrol ediyor
- Classroom, mail, reminders entegre değil
- Önceliklendirme yok
- Gün planı önerisi yok

## Kapsam

### Dahil

- **Çoklu kaynak toplama**: Calendar + Gmail + Classroom + Reminders + Hava durumu
- **Akıllı önceliklendirme**: Deadline × önem × aciliyet
- **Gün planı önerisi**: Saatlere göre optimize edilmiş plan
- **Çakışma tespiti**: Overlapping toplantılar, çok sıkışık program uyarısı
- **Enerji optimizasyonu**: "Sabah zor iş, öğleden sonra toplantı" tarzı öneriler
- **Follow-up**: "Bu toplantıyı ertele" → takvim güncelleme

### Hariç

- Pomodoro timer (ayrı issue)
- Haftalık/aylık planlama (ayrı issue)

## Akış Örneği

```
Kullanıcı: "Bugün ne yapmam gerekiyor?"
Bantz: "Günaydın efendim! İşte bugünkü programınız:

📅 TAKVİM (3 etkinlik):
  09:00 — Veri Yapıları dersi (online)
  14:00 — Proje toplantısı (Zoom)
  18:00 — Spor salonu

📚 ÖDEVLER (1 yaklaşan):
  ⚠️ Yapay Zeka ödevi — YARIN SON GÜN
  → Henüz teslim edilmemiş

📧 MAILLER (2 yanıt bekleyen):
  → Prof. Yılmaz'a yanıt (2 gündür bekliyor)
  → Staj başvurusu geri dönüşü

🌦️ HAVA: 8°C, parçalı bulutlu (spor için uygun)

💡 ÖNERİ: Ödeve sabah 10-13 arası yoğunlaşmanızı öneririm.
   Toplantı 14:00'te olduğu için tam zamanınız var.
   Toplantı sonrası 16:00'da Prof. Yılmaz'a yanıt yazabiliriz.

Planı onaylıyor musunuz?"
```

## Kabul Kriterleri

- [ ] "bugün ne yapmam gerek" / "günlük programım" intent'i çalışıyor
- [ ] Calendar, Gmail, Classroom (varsa) bilgileri toplanıyor
- [ ] Önceliklendirme yapılıyor (acil/önemli/normal)
- [ ] Gün planı önerisi sunuluyor
- [ ] Çakışma tespiti çalışıyor
- [ ] Hava durumu bağlamı ekleniyor (varsa)
- [ ] Follow-up aksiyonlar sunuluyor ("ertele", "mail yaz", "hatırlat")
- [ ] Test yazıldı

## Bağımlılıklar

- Issue #803 (Weather) — hava bağlamı
- Issue #805 (Classroom) — ödev bilgisi
- Issue #810 (Smart Email) — mail durumu
- Mevcut `skills/daily.py` refactor edilecek

## Tahmini Süre: 3-4 gün
