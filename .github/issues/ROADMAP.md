# 🗺️ Bantz Issue Roadmap — Hayalden Gerçeğe

> Oluşturulma: 11 Şubat 2026
> Toplam: 15 issue — 3 katmanda organize

---

## 📊 Mevcut Durum Özeti

| Metrik | Değer |
|--------|-------|
| **Toplam Python kodu** | ~140,000 satır |
| **Modül sayısı** | 381 Python dosyası, 39 alt paket |
| **Kapatılmış issue** | 412 (tamamı çözülmüş) |
| **Stub/boş dosya** | 0 (her şey implement) |
| **Test dosyası** | 277 test dosyası, 7,500+ test |

---

## 🎯 Hedef vs Mevcut Durum Matrisi

| Hayal | Mevcut | Eksik | Issue |
|-------|--------|-------|-------|
| "Bugün ne yapmam gerek?" → tam program hakimiyeti | Basit daily briefing | Çoklu kaynak toplama, önceliklendirme, gün planı | #813 |
| Mail kontrolü, optimizasyon, otomatik yanıt, gönderme | Gmail CRUD var | Akıllı önceliklendirme, otomatik yanıt, takip | #810 |
| Classroom ödev kontrolü + doküman analizi | ❌ Yok | Tamamı | #805 |
| Beyin fırtınası partneri | ❌ Yok | Tamamı | #807 |
| "Ekranımda ne görüyorsun?" | Vision modülü var | LLM yorumlama eksik | #809 |
| Hava durumu + proaktif öneri | ❌ Yok | Tamamı | #803 |
| Proaktif akıl yürütme | Reaktif çalışıyor | Çapraz analiz, proaktif motor | #806 |
| Haber takibi + interaktif QA | Basit RSS var | Proaktif takip, filtreleme, QA | #804 |
| Gece kendi kendine çalışma | PEV framework var | Otonom mod, checkpoint, sabah rapor | #808 |
| Kolay skill ekleme mimarisi | Plugin var ama zor | SKILL.md declarative format | #801 |
| Kendi kendine skill ekleme | ❌ Yok | Tamamı | #811 |
| Mesaj ile kontrol (telefon) | Unix socket only | REST API + mobil client | #802, #815 |
| OpenCode kod yazma | Coding modülü var | OpenCode entegrasyonu | #812 |
| 69 tool çalışır hale gelsin | 15/69 runtime handler | 54 eksik handler | #814 |

---

## 🏗️ Uygulama Sırası (Bağımlılık Grafiği)

```
KATMAN 0 — TEMEL MİMARİ (Paralel yapılabilir, 1. hafta)
├── #801 Declarative Skill Sistemi ←── Diğer tüm skill'ler buna bağımlı
└── #802 REST API ←── Mobil istemci buna bağımlı

KATMAN 1 — CORE SKILL'LER (Paralel yapılabilir, 2-3. hafta)
├── #803 Hava Durumu Skill'i
├── #804 Haber Takibi + Proaktif Gündem
├── #805 Google Classroom
├── #810 Akıllı Mail Yönetimi
├── #814 Tool Gap Kapatma (69 tool)
├── #807 Beyin Fırtınası Modu
└── #809 Ekran Yorumlama

KATMAN 2 — ENTEGRASYON & ZEKA (3-4. hafta)
├── #806 Proaktif Zeka Motoru ←── #803 + #804 + #805 + #810'a bağımlı
├── #813 Günlük Program Yönetimi ←── #803 + #805 + #810'a bağımlı
└── #808 Otonom Gece Modu ←── #806'ya bağımlı

KATMAN 3 — GELİŞMİŞ ÖZELLİKLER (5+ hafta)
├── #811 Self-Evolving Agent ←── #801 + #812'ye bağımlı
├── #812 OpenCode Entegrasyonu
└── #815 Mobil İstemci ←── #802'ye bağımlı
```

---

## ⏱️ Tahmini Zaman Çizelgesi

| Hafta | Issue'lar | Toplam Gün |
|-------|----------|------------|
| **Hafta 1** | #801 (Skill Arch) + #802 (REST API) | 7-10 gün |
| **Hafta 2-3** | #803 + #804 + #805 + #810 + #814 | 15-20 gün |
| **Hafta 3** | #807 + #809 | 4-6 gün |
| **Hafta 4** | #806 + #813 | 8-11 gün |
| **Hafta 5** | #808 (Otonom) | 5-7 gün |
| **Hafta 6+** | #811 + #812 + #815 | 15-20 gün |

**Toplam MVP (Katman 0-2): ~4-5 hafta**
**Tam vizyon (Katman 0-3): ~7-8 hafta**

---

## 🔗 Issue Listesi (Hızlı Erişim)

| # | Başlık | Öncelik | Katman |
|---|--------|---------|--------|
| 801 | Declarative Skill Sistemi (SKILL.md) | P0 | 0 |
| 802 | REST API + Telefon Erişimi | P0 | 0 |
| 803 | Hava Durumu Skill'i | P1 | 1 |
| 804 | Haber Takibi + İnteraktif QA | P1 | 1 |
| 805 | Google Classroom Entegrasyonu | P1 | 1 |
| 806 | Proaktif Zeka Motoru | P1 | 2 |
| 807 | Beyin Fırtınası Modu | P2 | 1 |
| 808 | Otonom Gece Modu | P1 | 2 |
| 809 | Ekran Görüntüsü Yorumlama | P2 | 1 |
| 810 | Akıllı Mail Yönetimi | P1 | 1 |
| 811 | Self-Evolving Agent | P2 | 3 |
| 812 | OpenCode Entegrasyonu | P2 | 3 |
| 813 | Günlük Program Yönetimi | P1 | 2 |
| 814 | Tool Gap Kapatma (69 tool) | P1 | 1 |
| 815 | Mobil İstemci | P2 | 3 |
