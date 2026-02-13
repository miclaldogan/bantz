# Bantz Tool Kataloğu

> Planner'ın kullanabildiği tüm araçlar, parametreleri ve risk seviyeleri.

**Risk Seviyeleri:**
- 🟢 **LOW** — Salt okunur, veri kaybı riski yok
- 🟡 **MED** — Yazma / silme içerir, onay (confirmation) gerektirir
- ⚪ **—** — Risk seviyesi tanımsız (browser/PC/file/terminal)

---

## 📅 Calendar (Google)

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `calendar.list_events` | Google Calendar'dan etkinlik listele | 🟢 LOW | `calendar_id`, `max_results`, `time_min`, `time_max`, `query`, `single_events`, `show_deleted`, `order_by` |
| `calendar.find_free_slots` | Belirli süre için müsait zaman dilimlerini bul | 🟢 LOW | `time_min`, `time_max`, `duration_minutes`, `suggestions`, `preferred_start`, `preferred_end`, `calendar_id` |
| `calendar.create_event` | Etkinlik oluştur (zamanlı/tüm gün/tekrarlı) | 🟡 MED | `summary`, `start`, `end`, `duration_minutes`, `description`, `attendees`, `location`, `all_day`, `recurrence` |
| `calendar.delete_event` | Etkinlik sil | 🟡 MED | `event_id`, `calendar_id` |
| `calendar.update_event` | Etkinliği kısmen güncelle | 🟡 MED | `event_id`, `summary`, `start`, `end`, `location`, `description`, `attendees` |

## 📅 Planning (Calendar)

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `calendar.plan_create` | PlanDraft'tan deterministik etkinlik planı oluştur (dry-run) | 🟢 LOW | `plan_draft`, `time_min`, `time_max` |
| `calendar.plan_apply` | PlanDraft uygula, etkinlikleri yaz | 🟡 MED | `plan_draft`, `time_min`, `time_max`, `dry_run`, `calendar_id` |

## 📧 Gmail — Okuma

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `gmail.list_messages` | Gelen kutusundan mesaj listele | 🟢 LOW | `max_results`, `unread_only`, `page_token` |
| `gmail.unread_count` | Okunmamış mesaj sayısını getir | 🟢 LOW | — |
| `gmail.get_message` | Mesaj gövdesini oku, ekleri tespit et | 🟢 LOW | `message_id`, `expand_thread`, `max_thread_messages` |

## 📧 Gmail — Akıllı Arama

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `gmail.parse_search_query` | Doğal dili Gmail arama sorgusuna çevir | 🟢 LOW | `text`, `reference_date`, `inbox_only` |
| `gmail.smart_search` | Doğal dil filtresiyle Gmail ara | 🟢 LOW | `query_nl`, `max_results`, `page_token`, `inbox_only`, `template_name`, `reference_date` |

## 📧 Gmail — Arama Şablonları

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `gmail.search_template_save` | Arama şablonu kaydet (isim → sorgu) | 🟢 LOW | `name`, `query` |
| `gmail.search_template_get` | Kayıtlı şablonu getir | 🟢 LOW | `name` |
| `gmail.search_template_list` | Şablonları listele | 🟢 LOW | `prefix`, `limit` |
| `gmail.search_template_delete` | Şablonu sil | 🟢 LOW | `name` |

## 📧 Gmail — Etiket & Arşiv

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `gmail.list_labels` | Gmail etiketlerini listele | 🟢 LOW | — |
| `gmail.add_label` | Mesaja etiket ekle | 🟢 LOW | `message_id`, `label` |
| `gmail.remove_label` | Mesajdan etiket kaldır | 🟢 LOW | `message_id`, `label` |
| `gmail.archive` | Mesajı arşivle (INBOX etiketini kaldır) | 🟡 MED | `message_id` |
| `gmail.mark_read` | Mesajı okundu işaretle | 🟢 LOW | `message_id` |
| `gmail.mark_unread` | Mesajı okunmadı işaretle | 🟢 LOW | `message_id` |
| `gmail.batch_modify` | Toplu etiket ekle/kaldır | 🟡 MED | `message_ids`, `add_labels`, `remove_labels` |

## 📧 Gmail — Gönderme

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `gmail.send` | E-posta oluştur ve gönder | 🟡 MED | `to`, `subject`, `body`, `cc`, `bcc` |
| `gmail.send_to_contact` | Kayıtlı kişiye e-posta gönder | 🟡 MED | `contact_name`, `subject`, `body`, `cc`, `bcc` |

## 📧 Gmail — Taslaklar

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `gmail.create_draft` | Taslak oluştur | 🟢 LOW | `to`, `subject`, `body` |
| `gmail.list_drafts` | Taslakları listele | 🟢 LOW | `max_results`, `page_token` |
| `gmail.update_draft` | Taslağı güncelle | 🟢 LOW | `draft_id`, `updates` |
| `gmail.send_draft` | Taslağı gönder | 🟡 MED | `draft_id` |
| `gmail.delete_draft` | Taslağı sil | 🟢 LOW | `draft_id` |

## 📧 Gmail — Ek & Yanıt

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `gmail.download_attachment` | Eki diske indir | 🟡 MED | `message_id`, `attachment_id`, `save_path`, `overwrite` |
| `gmail.smart_reply` | 3 yanıt önerisi üret ve taslak oluştur | 🟡 MED | `message_id`, `user_intent`, `base`, `reply_all`, `include_quote` |

## 👤 Kişiler (Lokal)

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `contacts.upsert` | Kişi kaydet (isim → e-posta) | 🟢 LOW | `name`, `email`, `notes` |
| `contacts.resolve` | İsimden e-posta çöz | 🟢 LOW | `name` |
| `contacts.list` | Kişileri listele | 🟢 LOW | `prefix`, `limit` |
| `contacts.delete` | Kişi sil | 🟢 LOW | `name` |

## 🌐 Browser

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `browser_open` | URL aç (Firefox extension bridge) | ⚪ | `url` |
| `browser_scan` | Sayfadaki tıklanabilir öğeleri listele | ⚪ | — |
| `browser_click` | Index veya metin ile öğe tıkla | ⚪ | `index`, `text` |
| `browser_type` | Sayfaya metin yaz | ⚪ | `text`, `index` |
| `browser_back` | Tarayıcıda geri git | ⚪ | — |
| `browser_info` | Sayfa bilgisi (başlık/URL/site) | ⚪ | — |
| `browser_detail` | Taranmış öğe hakkında detay | ⚪ | `index` |
| `browser_wait` | Birkaç saniye bekle (1–30) | ⚪ | `seconds` |
| `browser_search` | Sayfa/site içinde arama | ⚪ | `query` |
| `browser_scroll_down` | Sayfada aşağı kaydır | ⚪ | — |
| `browser_scroll_up` | Sayfada yukarı kaydır | ⚪ | — |

## 🖥️ PC / Input

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `pc_hotkey` | Güvenli kısayol tuşu bas | ⚪ | `combo` |
| `pc_mouse_move` | Fareyi ekran koordinatına taşı | ⚪ | `x`, `y`, `duration_ms` |
| `pc_mouse_click` | Fare tıkla | ⚪ | `x`, `y`, `button`, `double` |
| `pc_mouse_scroll` | Fare tekerleği kaydır | ⚪ | `direction`, `amount` |

## 📋 Pano (Clipboard)

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `clipboard_set` | Panoya metin kopyala | ⚪ | `text` |
| `clipboard_get` | Pano içeriğini oku | ⚪ | — |

## 📝 Dosya / Kod Düzenleme

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `file_read` | Dosya oku (satır aralığı destekler) | ⚪ | `path`, `start_line`, `end_line` |
| `file_write` | Dosyaya yaz (backup oluşturur) | ⚪ | `path`, `content` |
| `file_edit` | Dosyada string değiştir | ⚪ | `path`, `old_string`, `new_string` |
| `file_create` | Yeni dosya oluştur | ⚪ | `path`, `content` |
| `file_undo` | Son düzenlemeyi geri al (backup'tan) | ⚪ | `path` |
| `file_search` | İsim veya içerik ile dosya ara | ⚪ | `pattern`, `content` |
| `code_format` | Kodu formatla (black/prettier vb.) | ⚪ | `path` |
| `code_replace_function` | Dosyadaki bir fonksiyonu tamamen değiştir | ⚪ | `path`, `function_name`, `new_code` |

## 🖥️ Terminal

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `terminal_run` | Shell komutu çalıştır | ⚪ | `command`, `timeout` |
| `terminal_background` | Arka plan komutu başlat | ⚪ | `command` |
| `terminal_background_list` | Arka plan süreçlerini listele | ⚪ | — |
| `terminal_background_kill` | Arka plan sürecini durdur | ⚪ | `id` |

## 🏗️ Proje Bağlamı

| Araç | Açıklama | Risk | Parametreler |
|------|----------|------|-------------|
| `project_info` | Proje bilgisi (tip, isim, bağımlılıklar) | ⚪ | — |
| `project_tree` | Proje dosya ağacı | ⚪ | `max_depth` |
| `project_symbols` | Dosyadan semboller (fonksiyon, sınıf) | ⚪ | `path` |
| `project_search_symbol` | Projede sembol ara | ⚪ | `name`, `type` |

---

## Özet

| Risk | Araç Sayısı | Onay Gerekli? |
|------|-------------|---------------|
| 🟢 LOW | 27 | Hayır |
| 🟡 MED | 10 | Evet — confirmation firewall |
| ⚪ Tanımsız | 32 | Kontekste göre değişir |
| **Toplam** | **69** | |
