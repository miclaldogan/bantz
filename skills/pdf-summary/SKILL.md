# PDF Summary Skill — Issue #1211

## Triggers
- "PDF'i özetle", "belgeyi oku", "dosyayı analiz et"
- "attachment'ı aç", "eki oku", "PDF içeriği ne"
- "summarize the PDF", "read the document", "what does the attachment say"
- "belgeyi açıp bana ne yazdığını söyle"

## Tools

| Tool | Açıklama |
|------|----------|
| `pdf.extract_text` | PDF dosyasından metin çıkar |
| `pdf.summarize` | PDF'den metin çıkar + özet hazırla |
| `pdf.from_attachment` | Gmail ekinden PDF indir + metin çıkar |

## Instructions

Bu skill, kullanıcının PDF dosyalarını okumasını ve özetlemesini sağlar.

### Akış
1. Kullanıcı bir email eki veya dosya yolu belirtir
2. `pdf.from_attachment` veya `pdf.extract_text` ile metin çıkarılır
3. Çıkarılan metin finalizer LLM'e gönderilir
4. LLM Türkçe özet üretir

### Kurallar
- Maksimum 50MB PDF (güvenlik limiti)
- Maksimum 200 sayfa (performans limiti)
- Metin 100K karakter ile sınırlı (LLM context)
- Geçici dosyalar işlem sonrası temizlenir
- Gmail eklerinde `pdf.from_attachment` kullanılır (download + extract tek adım)

## Slot Extraction

| Slot | Tip | Kaynak |
|------|-----|--------|
| `path` | string | Kullanıcı girdisi veya önceki tool sonucu |
| `message_id` | string | Gmail mesaj bağlamından |
| `attachment_id` | string | Gmail ek bağlamından |
| `language` | string | Varsayılan "tr", kullanıcı belirtebilir |

## Proactive

- Email okunduğunda PDF eki varsa otomatik özet öner
- "Bu emailin PDF ekini okumamı ister misiniz?" şeklinde proaktif öneri
