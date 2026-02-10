---
title: "[Skill] Hava Durumu — Weather API + Takvim Çapraz Analiz"
labels: "type:feature, priority:P1, area:skill, milestone:v2"
assignees: "miclaldogan"
issue_number: 803
---

## Hedef

Hava durumu sorgulama skill'i: konum bazlı forecast, takvimle çapraz analiz, ve proaktif öneri ("hava kötü, dışarı planınızı iptal edebilirim").

## Arka Plan

Kullanıcı vizyonu: "Bugün dışarı çıkmak istiyordunuz ancak hava çok iyi gözükmüyor, eğer bir taşıt kullanmayacaksanız planınızı iptal edebilirim"

Bu, Bantz'ın sadece tepkisel değil **proaktif** olmasının ilk adımı. Hava durumunu takvimle birleştirip akıl yürütme yapması gerekiyor.

## Kapsam

### Dahil

- **OpenWeatherMap API entegrasyonu** (free tier, 1000 call/day)
- **Konum yönetimi**: Profil'deki varsayılan konum + sorgu bazlı konum
- **Forecast**: Bugün, yarın, 5 günlük
- **Takvim çapraz analizi**: Dış mekan etkinliği + kötü hava → uyarı
- **Proaktif öneri**: "Yağmur var, şemsiye alın" veya "Planınızı erteleyebilirim"
- **Doğal dil yanıt**: Türkçe, Jarvis tarzı

### Hariç

- Konum GPS takibi (şimdilik profil bazlı)
- Hava durumu widget/UI

## Teknik Detay

```python
# SKILL.md olarak tanımlanacak (Issue #801'e bağımlı)
# Fallback: hardcoded skill olarak da çalışabilmeli

tools:
  - weather.get_current(location) → {temp, humidity, wind, description, icon}
  - weather.get_forecast(location, days) → [{date, temp_min, temp_max, rain_prob, desc}]
  - weather.check_outdoor_safety(location, date) → {safe: bool, reason: str, suggestion: str}
```

### Akıl Yürütme Akışı:

```
1. Kullanıcı: "bugün dışarı çıkabilir miyim?"
2. weather.get_current(İstanbul) → 5°C, yağmur, rüzgar 40km/h
3. calendar.list_events(today) → [{title: "Parkta yürüyüş", location: "Maçka Parkı"}]
4. Akıl yürütme: Dış mekan + kötü hava → UYARI
5. Yanıt: "Efendim, bugün İstanbul'da yağmur bekleniyor ve rüzgar 40km/h.
   Saat 3'teki 'Parkta yürüyüş' planınız için pek uygun değil.
   İsterseniz yarına erteleyebilirim — yarın 12°C ve güneşli görünüyor."
```

## Kabul Kriterleri

- [ ] `weather.get_current` ve `weather.get_forecast` tool'ları çalışıyor
- [ ] OpenWeatherMap API key env'den okunuyor (`BANTZ_WEATHER_API_KEY`)
- [ ] Takvim çapraz analizi yapılıyor (dış mekan etkinliği + kötü hava)
- [ ] Proaktif öneri üretiliyor (plan iptal/erteleme)
- [ ] Türkçe doğal dil yanıt
- [ ] 5 günlük forecast destekleniyor
- [ ] API key yoksa graceful fallback (hata mesajı)
- [ ] Rate limiting (free tier sınırları)
- [ ] Test yazıldı

## Bağımlılıklar

- Issue #801 (Skill Architecture) — ideal, ama bağımsız da yapılabilir
- OpenWeatherMap free API key

## Tahmini Süre: 2-3 gün
