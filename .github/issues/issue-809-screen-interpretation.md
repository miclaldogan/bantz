---
title: "[Feature] Ekran Görüntüsü + Yorumlama — 'Ekranımda ne görüyorsun?'"
labels: "type:feature, priority:P2, area:skill, milestone:v2"
assignees: "miclaldogan"
issue_number: 809
---

## Hedef

"Ekranımda ne görüyorsun?" dendiğinde ekran görüntüsü alıp yorumlama, ve ekran bazlı yardım sunma.

## Arka Plan

Kullanıcı vizyonu: "Ekranımda ne görüyorsun dediğimde ekran görüntüsü alıp onu yorumlayabilmeli"

Mevcut durum: `vision/` modülünde (4,008 satır):
- `capture.py` — mss ile ekran yakalama ✅
- `document.py` — PyMuPDF ile PDF analizi ✅
- `ocr.py` — pytesseract ile OCR ✅
- `google_vision.py` — Google Vision API ✅
- `tools.py` — 8+ vision tool tanımlı ✅

**Eksik olan**: Ekran görüntüsünü LLM'e gönderip **anlamsal yorumlama** yaptırmak. OCR var ama "ne görüyorum" analizi yok.

## Kapsam

### Dahil

- **Ekran yakalama → Gemini Vision ile yorumlama** (multimodal)
- **Doğal dil açıklama**: "Ekranda VS Code açık, Python dosyası düzenleniyor, 3 hata var"
- **Bağlamsal yardım**: Ekrandaki hataya yardım önerisi
- **Belirli alan yakalama**: "Sol üst köşedeki grafiği açıkla"
- **Screenshot hafızası**: Son ekran görüntülerini hatırlama

### Hariç

- Sürekli ekran izleme (privacy)
- Video analizi
- Ekran paylaşımı

## Akış

```
1. Kullanıcı: "Ekranımda ne görüyorsun?"
2. vision.capture_screen() → screenshot.png
3. Gemini Vision API (multimodal): "Bu ekran görüntüsünü Türkçe yorumla"
4. Yanıt: "Efendim, ekranda VS Code açık görünüyor.
   Python dosyası 'server.py' düzenleniyor.
   Sol panelde 3 hata (kırmızı), 2 uyarı (sarı) görünüyor.
   Hata 1: 'ImportError' — 142. satırda. Yardımcı olmamı ister misiniz?"
```

## Kabul Kriterleri

- [ ] "ekranımda ne var" / "ekranıma bak" komutu çalışıyor
- [ ] Ekran yakalanıp Gemini Vision'a gönderiliyor
- [ ] Türkçe doğal dil yorumlama dönüyor
- [ ] Bağlamsal yardım önerisi sunuluyor (hata varsa fix önerisi)
- [ ] İzin isteme: "Ekran görüntüsü alabilir miyim?" (first time)
- [ ] Belirli alan yakalama destekleniyor
- [ ] Test yazıldı

## Bağımlılıklar

- Mevcut `vision/` modülü (capture, OCR)
- Gemini Vision API (multimodal model)
- `BANTZ_CLOUD_ENABLED=true` gerekli (cloud gönderimi)

## Tahmini Süre: 2-3 gün (mevcut altyapı güçlü)
