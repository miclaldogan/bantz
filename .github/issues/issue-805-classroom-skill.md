---
title: "[Skill] Google Classroom — Ödev Kontrolü + Doküman Analizi"
labels: "type:feature, priority:P1, area:skill, milestone:v2"
assignees: "miclaldogan"
issue_number: 805
---

## Hedef

Google Classroom API entegrasyonu ile ödev kontrolü, doküman (PDF/Word) okuma ve özet çıkarma, takvime ödev deadline'ı ekleme.

## Arka Plan

Kullanıcı vizyonu: "Classroom'dan ödevim var mı dediğimde kontrol edebilecek, PDF/Word dokümanlar varsa bunları okuyup anlayıp özet çıkartabilecek, takvimime de ekleyebilecek"

Mevcut durum: Google Calendar ve Gmail OAuth zaten var. Vision modülü PDF okuyabiliyor. Classroom API henüz yok.

## Kapsam

### Dahil

- **Google Classroom API OAuth2** — readonly scope ile ders ve ödev listeleme
- **Ödev listeleme**: Aktif ödevler, teslim tarihleri, durumları
- **Doküman analizi**: Ödev eklerindeki PDF/Word/Google Docs dosyalarını oku
- **Özet çıkarma**: Ödevin ne istediğini, değerlendirme kriterlerini, deadline'ı çıkar
- **Takvime ekleme**: Ödev deadline'larını otomatik Google Calendar'a ekle
- **Proaktif hatırlatma**: "Yarın son gün, henüz teslim etmemişsiniz"

### Hariç

- Ödev yapma/teslim etme (sadece okuma)
- Ödev yanıtı oluşturma (ayrı issue)
- Canlı ders takibi

## Teknik Detay

```python
tools:
  - classroom.list_courses() → [{id, name, section, state}]
  - classroom.list_assignments(course_id, status="active") →
      [{id, title, description, due_date, max_points, attachments, state}]
  - classroom.get_assignment_detail(course_id, assignment_id) →
      {full details + attachment content}
  - classroom.check_submission_status(course_id, assignment_id) →
      {submitted: bool, grade: optional, late: bool}
```

### Akış:

```
1. Kullanıcı: "Classroom'da ödevim var mı?"
2. classroom.list_courses() → 3 ders bulundu
3. classroom.list_assignments(each_course, status="active") → 2 aktif ödev
4. Ödev 1: "Veri Yapıları - Ağaç Traversal Raporu" (deadline: 14 Şubat)
   - Ek: "odev_kilavuzu.pdf"
   - vision.read_document("odev_kilavuzu.pdf") → kılavuz içeriği
   - Özet: "Binary tree traversal algoritmalarını karşılaştıran 5 sayfalık rapor"
5. calendar.create_event("Ödev: Ağaç Traversal Raporu - SON GÜN", date="2026-02-14")
6. Yanıt: "Efendim, 2 aktif ödeviniz var:
   1. Veri Yapıları - Ağaç Traversal Raporu (14 Şubat)
      PDF'yi okudum: Binary tree traversal karşılaştırması, 5 sayfa istiyor.
   2. Yapay Zeka - Perceptron Ödevi (17 Şubat)
   İkisini de takviminize ekledim."
```

## OAuth Scope

```python
CLASSROOM_SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
]
```

## Kabul Kriterleri

- [ ] Google Classroom OAuth2 authentication çalışıyor
- [ ] Ders listeleme çalışıyor
- [ ] Aktif ödev listeleme çalışıyor (deadline, durum)
- [ ] PDF/Word ekleri okunup özet çıkarılıyor (mevcut vision modülü ile)
- [ ] Ödev deadline'ları takvime ekleniyor
- [ ] "Classroom'da ödevim var mı?" sorusu doğal dil yanıt veriyor
- [ ] Teslim durumu kontrol edilebiliyor
- [ ] Google Docs ekleri destekleniyor
- [ ] Test yazıldı

## Bağımlılıklar

- `google-api-python-client` (zaten var)
- `google-auth-oauthlib` (zaten var)
- Mevcut `google/auth.py` OAuth altyapısına Classroom scope eklenmeli
- Mevcut `vision/` modülü PDF okuma için kullanılacak

## Tahmini Süre: 3-4 gün
