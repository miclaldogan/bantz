# Bantz – Issue Backlog (Draft)

> Jarvis v2 roadmap dokümanı: [docs/jarvis-roadmap-v2.md](docs/jarvis-roadmap-v2.md)

---

## ⚡ vLLM Runtime Notice

**Effective Date:** 2026-01-31

Bantz uses **vLLM** for local LLM inference:
- ✅ OpenAI API compatible (`/v1/chat/completions`)
- ✅ Prefix caching + batching
- ✅ Local baseline: 3B vLLM (speed-first) + quality tier via Gemini (cloud)

---

## P0 — Calendar Router & Menu Fallback (2026-02)

Bu bölüm, "Takvim mi sohbet mi?" menüsünün **normal akışta asla görünmemesi** için gereken işleri takip eder.

- P0: Router fallback menü çıkarmasın (parse fail/unknown → smalltalk fallback)
	- Spec: [docs/issues/2026-02-router-no-menus.md](docs/issues/2026-02-router-no-menus.md)
	- GitHub issue açmak için:
		- `gh issue create --title "Router fallback: no user-facing menus" --body-file docs/issues/2026-02-router-no-menus.md`

- P0: Router strict JSON + heuristics (temp=0, max_tokens küçük)
	- Spec: [docs/issues/2026-02-router-strict-json.md](docs/issues/2026-02-router-strict-json.md)
	- GitHub issue açmak için:
		- `gh issue create --title "Router: strict JSON + heuristics" --body-file docs/issues/2026-02-router-strict-json.md`

- P1: Tiered LLM demo (3B router + Gemini quality)
	- Spec: [docs/issues/2026-02-tiered-gemini-demo.md](docs/issues/2026-02-tiered-gemini-demo.md)
	- GitHub issue açmak için:
		- `gh issue create --title "Tiered LLM demo: fast router + quality writing" --body-file docs/issues/2026-02-tiered-gemini-demo.md`

## Epic V2 — “Jarvis Seviye” Roadmap (Phases 0–8 + UI/Voice)

Bu bölüm, v2 mimarisi için **faz bazlı** epic issue’ları takip etmek içindir. Detaylar roadmap dokümanında.

- V2-0: Faz 0 — Ürün tanımı + Done kriterleri (#30: https://github.com/miclaldogan/bantz/issues/30)
- V2-1: Faz 1 — Agent OS çekirdeği (Event Bus + Job Manager + Interrupt/Barge-in) (#31: https://github.com/miclaldogan/bantz/issues/31)
- V2-2: Faz 2 — Tool Runtime (retry/timeout/circuit breaker + web tools katmanı) (#32: https://github.com/miclaldogan/bantz/issues/32)
- V2-3: Faz 3 — Cite-first doğrulama + çelişki + confidence (#33: https://github.com/miclaldogan/bantz/issues/33)
- V2-4: Faz 4 — Memory (session/profile/episodic + write policy + retrieval) (#36: https://github.com/miclaldogan/bantz/issues/36)
- V2-5: Faz 5 — Gizlilik & güvenlik (permission engine + secrets vault + audit log) (#37: https://github.com/miclaldogan/bantz/issues/37)
- V2-6: Faz 6 — Conversation engine (state machine + barge-in + feedback standardı) (#38: https://github.com/miclaldogan/bantz/issues/38)
- V2-7: Faz 7 — Doküman/PDF/DOC anlama (pipeline + hybrid cloud permission) (#39: https://github.com/miclaldogan/bantz/issues/39)
- V2-8: Faz 8 — Agentic automation v1 (PEV + templates + fail-safe) (#40: https://github.com/miclaldogan/bantz/issues/40)
- UI-2: Jarvis Panel v0 (animations + cards + image slots + ticker + event stream) (#34: https://github.com/miclaldogan/bantz/issues/34)
- Voice-2: Attention Gate (wakeword-only during tasks + pause/resume + engaged window) (#35: https://github.com/miclaldogan/bantz/issues/35)


Bu liste iki kaynaktan birleşik:
- Repo içi teknik borç / buglar (benim taramada bulduklarım)
- Senin açtığın “Jarvis vizyonu” issue’ları (multi-step agent, mouse/keyboard, screen feedback, memory vb.)

Öncelik skalası:
- **P0**: bug / kırık akış / temel Jarvis hissi için şart
- **P1**: büyük UX/agent kabiliyeti artışı
- **P2**: kalite/ölçeklenebilirlik/iyileştirme
- **P3**: ileri seviye/opsiyonel

---

## Epic J — “Iron Man Jarvis” Web Research + Haber Akışı

Bu epic senin tarif ettiğin ana vizyon: 
"Bantz bugünkü haberlerde ne var?" → "Şimdi sizin için arıyorum efendim" → sonuçları ekranda göster → sayfada kal → "şu CEO olayı ne?" → içerikten anlayıp özetle/açıkla.

### J1) News briefing: kaynak seç → ara → sonuçları ekrana getir
**Öncelik:** P0

**Amaç:** Kullanıcı “bugünkü haberlerde ne var?” dediğinde Bantz, belirlenen kaynaklarda arayıp sonuç listesini overlay’de gösterebilsin.

**Kapsam (minimal):**
- 1–2 kaynakla başla (örn. Google News veya tek bir haber sitesi).
- “Arıyorum efendim…” → “Sonuçlar burada efendim.” gibi net UX metinleri.
- Sonuç listesi: başlık + kısa snippet + (gerekirse) numara ile seçim.

**Kabul kriteri:**
- Komut: “bugünkü haberlerde ne var” → tarayıcıda arama açar ve overlay’de 5–10 sonuç listeler.
- Kullanıcı “3. sonucu aç” dediğinde ilgili sayfayı açar.

---

### J2) Sayfa içeriği çıkarma (article extraction)
**Öncelik:** P0

**Neden:** Gerçek Jarvis deneyimi için “sayfanın içeriğini anlayıp” cevap vermesi gerekiyor. Şu an extension tarafı daha çok scan/click/type odaklı; içerik çıkarma/okuma yok.

**Kapsam:**
- Extension’dan Python’a “readability-like” metin çıkarma (title + main text) mesajı.
- Minimum: `document.title` + sayfadaki ana metin (ör. `article`, `main`, `p` birleşimi) ve karakter limiti.

**Kabul kriteri:**
- Komut: “bu haberi oku/özetle” → sayfanın ana metnini alır.
- Metin alınamazsa kullanıcıya “Bu sayfadan metin çekemedim” şeklinde net hata.

---

### J3) “Anlat/Özetle” modu: sayfada kal + LLM ile açıklama
**Öncelik:** P0

**Amaç:** Kullanıcı sayfadayken “şunu anlayamadım anlat” dediğinde Bantz, sayfa metnini bağlam alıp açıklama/özet üretsin ve sesli+görsel sunabilsin.

**Kapsam:**
- LLM prompt: (1) kaynak metin, (2) kullanıcı sorusu, (3) cevap stili (kısa/uzun).
- TTS: özetin sesli okunması (mevcut Piper TTS).
- Overlay: uzun metin için “paged/scrollable” veya en azından kısaltılmış + “devamı”.

**Kabul kriteri:**
- “Bu CEO olayı ne?” → Bantz önce “Arıyorum efendim” der, sonra 1–2 paragraf açıklama üretir.
- Cevap: kısa istenince 1–2 cümle, detay istenince uzun.

---

### J4) Transparent “Jarvis ekranı” (sonuç paneli)
**Öncelik:** P1

**Amaç:** Sonuçları “transparent tarzı” ekrana getirme.

**Not:** Şu an iki overlay var gibi: IPC overlay (PyQt5) ve extension in-page overlay. Jarvis ekranı için tek bir “source of truth” seçilmeli.

**Kabul kriteri:**
- Haber sonuçları ve özetler, kullanıcı çalışırken ekranın bir köşesinde okunabilir şekilde görünür.
- Kullanıcı “kapat/gizlen/sağ üste geç” ile yönetebilir.

---

### J5) “Kaza oldu neler var?”: olay araştırma (query expansion)
**Öncelik:** P1

**Amaç:** Kullanıcı muğlak bir olay söylediğinde Bantz soru sorabilsin veya otomatik netleştirsin.

**Kabul kriteri:**
- Konum/tarih belirsizse 1 net soru sorar (en fazla 1–2 soru).
- Netleşince arayıp sonuçları listeler.

---

## Epic K — Agent Framework (Jarvis davranışı)

### K1) Multi-step task execution (plan → adım → sonuç)
**Öncelik:** P0

**Neden:** Senin tarif ettiğin akış (ara → sonuç göster → aç → oku → özetle → devam) birden fazla adım.

**Kabul kriteri:**
- Bantz her adımda overlay state günceller: listening → thinking("Arıyorum") → speaking("Sonuçlar") gibi.
- Adımlar cancel/skip ile kontrol edilebilir.

---

### K2) Tool set: browser + page_read + summarize + open_result
**Öncelik:** P0

**Kabul kriteri:**
- LLM (veya router) şu araçları çağırarak görevi tamamlayabilir: `browser_open/search`, `page_extract`, `summarize`, `click/open`.

---

### K3) Persona / konuşma stili kontrolü (kısa/uzun)
**Öncelik:** P1

**Kabul kriteri:**
- Varsayılan: 1–2 cümle.
- “detaylı anlat” gibi tetikleyicilerde uzun cevap.

---

## Epic A — “İnsan Gibi Input” (Desktop + Browser)

### A1) Browser typing: insan gibi yaz + yazıyı gör (extension)
**Öncelik:** P1

**Neden:** Şu an extension `typeText()` direkt `value = text` yapıyor; “insan gibi yazma” hissi yok ve kullanıcı yazılanı akışta göremiyor. Ayrıca Python tarafı `submit` parametresi gönderse bile extension zincirinde (daemon→ws→background→content) Enter/submit uygulanmıyor.

**Kapsam:**
- Extension tarafında (content.js) “human typing” uygula: karakter karakter yaz, configurable hız/jitter.
- Yazma sırasında küçük bir overlay satırı göster: `Yazıyorum: …` (mevcut in-page overlay içine eklenebilir).
- `submit: true` geldiğinde Enter gönder (end-to-end: Python bridge → background.js → content.js).

**Kabul kriteri:**
- `browser_type` intent’i tetiklendiğinde metin karakter karakter yazılır (ör. 50–120ms arası jitter).
- Yazma sırasında overlay’de en azından kısaltılmış metin görünür.
- Yazma bittiğinde overlay otomatik kapanır veya eski haline döner.
- `browser_type` “submit” gerektiren akışlarda (örn. arama kutusu) Enter gerçekten basılır.

İlgili yerler:
- bantz-extension/content.js → `typeText()` ve overlay fonksiyonları
- src/bantz/browser/extension_bridge.py → `request_type(... submit=...)`
- src/bantz/router/engine.py → `browser_type`
- bantz-extension/background.js → `case 'type'` mesaj aktarımı

---

### A2) Desktop typing: insan gibi yaz + yazıyı gör (xdotool)
**Öncelik:** P1

**Neden:** `app_type` şu an `xdotool type` ile yazıyor, fakat (a) Wayland’da çalışmayabilir, (b) yazma süreci görünmüyor.

**Kapsam:**
- `xdotool type --delay <ms>` ile “human-ish” typing.
- Yazma başlamadan önce OS overlay’de (IPC overlay) `Yazıyorum: ...` göster.

**Kabul kriteri:**
- X11 ortamında `app_type` komutu “gözle görülür şekilde” yazma animasyonuyla çalışır.
- Yazma sırasında overlay’de metin görünür; bitince overlay state normale döner.

İlgili yerler:
- src/bantz/skills/pc.py → `type_text()`
- src/bantz/server.py / src/bantz/router/engine.py → overlay hook kullanım noktaları
- src/bantz/ipc/protocol.py → gerekirse yeni `OverlayState` / event

---

### A3) Wayland desteği: input otomasyonu stratejisi
**Öncelik:** P1

**Neden:** `xdotool`/global key hook gibi şeyler Wayland’da kısıtlı.

**Kapsam (öneri):**
- Minimum: Wayland’da `app_type/app_submit` komutları için “desteklenmiyor / alternatif” mesajı + dokümantasyon.
- Orta: `wtype` (sway/wlroots) veya `ydotool` seçenekleri.

**Kabul kriteri:**
- Wayland tespitinde doğru fallback/uyarı.
- Desteklenen Wayland backend’inde `type` ve `enter` çalışır.

---

### A4) Advanced mouse & keyboard kontrolü (desktop)
**Öncelik:** P1

**Neden:** “Mouse kullanır gibi keyboard kullanır gibi” Jarvis hissi için şart; şu an PC tarafında ağırlık `wmctrl/xdotool` ve text/enter ile sınırlı.

**Kapsam (minimal başlayıp büyüyen):**
- Minimal: klavye kısayolları (Alt+Tab, Ctrl+L, Ctrl+T, Ctrl+W, Ctrl+C/V) için güvenli allowlist.
- Orta: mouse move/click (X11’de) + hareketin “insan gibi” olması.
- Görsel feedback: IPC overlay’de “tıklıyorum / yazıyorum / hedef pencere” bilgisi.

**Kabul kriteri:**
- X11’de en az 5 temel kısayol çalışır ve policy ile confirm gate’den geçer.
- Mouse click eylemleri loglanır ve overlay’de kısa feedback verir.

---

## Epic B — Browser Agent (Firefox + Extension)

### B1) `browser_go_back` implementasyonu
**Öncelik:** P0 (Jarvis web akışını blokluyor)

**Neden:** NLU’da `browser_back` var ama `browser_go_back()` “henüz desteklenmiyor” diyor.

**Kapsam:**
- Extension’a `history.back()` komutu ekle.
- Python bridge’de `go_back` komutunu ilet.

**Kabul kriteri:**
- `geri dön` komutu Firefox’ta geri gider.

İlgili yerler:
- src/bantz/browser/skills.py → `browser_go_back`
- src/bantz/browser/extension_bridge.py / bantz-extension/background.js / content.js

---

### B2) Scan/pagination mimarisi düzelt
**Öncelik:** P0 (Jarvis panel/sonuç listesi için blokaj)

**Neden:** Server pagination `get_page_memory()` bekliyor ama Firefox+extension yolunda bu `None` dönüyor. Bu yüzden “daha fazla” akışı fiilen bozuk.

**Kapsam:**
- Tek kaynak seç: ya extension’ın son scan datasını server tarafında cache’le, ya `page_memory` katmanını yeniden bağla.
- `server.py` pagination komutları bu kaynağı kullansın.

**Kabul kriteri:**
- `sayfayı tara` → 10 öğe gösterir.
- `daha fazla` → sonraki 10.
- `önceki` → önceki 10.

İlgili yerler:
- src/bantz/server.py → `_format_scan_result/_paginate_next/_paginate_prev`
- src/bantz/browser/extension_bridge.py → `_last_scan` zaten var

---

### B3) `browser_ai_chat` bugfix: `open_url_in_firefox` yok
**Öncelik:** P0 (crash bug)

**Neden:** src/bantz/browser/skills.py içinde çağrılan fonksiyon tanımlı değil.

**Kabul kriteri:**
- `ai_chat` intent’i crash etmez; doğru URL’i açar.

---

### B4) Extension Bridge stabilite: Native Messaging / reconnect / telemetry
**Öncelik:** P2

**Neden:** WebSocket köprüsü iyi bir başlangıç ama uzun vadede kopma/reconnect/versiyon uyumu ve güvenlik için daha sağlam bir yol gerekebilir.

**Kabul kriteri:**
- Bağlantı kopunca otomatik reconnect; daemon “extension bağlı” durumunu doğru gösterir.
- (Opsiyonel) Native Messaging POC çalışır veya net şekilde scope dışı bırakılır.

---

## Epic C — Overlay / UX

### C1) “Typing” state’i (IPC overlay)
**Öncelik:** P1

**Neden:** Şu an overlay sadece wake/listening/thinking/speaking. Yazma gibi eylemler için ayrı state daha iyi UX verir.

**Kapsam:**
- `OverlayState.TYPING` ekle (opsiyonel).
- UI’da ikon/renk/mətn ile göster.

**Kabul kriteri:**
- Yazma sırasında overlay state `typing` olur ve metin görünür.

---

### C2) Overlay bağımlılıklarını paketle (PyQt5)
**Öncelik:** P1

**Neden:** Overlay PyQt5 kullanıyor ama pyproject extra’larında görünmüyor; fresh install’da overlay açılmayabilir.

**Kabul kriteri:**
- `pip install 'bantz[ui]'` gibi bir extra ile overlay dependencies gelir.

---

### C3) Screen capture & visual feedback (opsiyonel, incremental)
**Öncelik:** P2

**Neden:** “Ne yaptığını görebileyim” isteğini güçlendirir. Ancak bu büyük scope; önce typed feedback ve hedef pencere/URL bilgisiyle başlanmalı.

**Kapsam (öneri):**
- Minimal: overlay’de aktif pencere + aktif URL + son eylem.
- Orta: ekran görüntüsü alma (örn. `mss`) + overlay’de küçük preview.

**Kabul kriteri:**
- Minimal seviye bile kullanıcıya “ne yapıyorum” hissini verir (yazıyorum/tıklıyorum/odaklandım).

---

## Epic D — LLM / Agent Mode

### D1) Dev Bridge’i gerçek “agent mode” yap
**Öncelik:** P0

**Neden:** Şu an `DevBridge` stub.

**Kapsam (öneri):**
- Minimal: kullanıcıdan gelen dev isteğini plan + adım listesine çevir, dosya öner, ama otomatik yazma opsiyonel.
- Orta: repo içinde “issue generator” tool’u (markdown output).

**Kabul kriteri:**
- Dev mode’da “X’i refactor et” gibi isteklere plan+diff taslağı üretir.

İlgili yerler:
- src/bantz/router/dev_bridge.py

---

### D2) Agent framework: multi-step task planning/execution
**Öncelik:** P1

**Neden:** Şu an zincir/queue var ama “otonom plan + adım adım tool çağırma” yok.

**Kabul kriteri:**
- Bir görev “plan → adımlar → çalıştır/iptal/atla” olarak yürütülür.
- Her adım loglanır; policy/confirm gate ile entegre olur.

---

### D3) Coding Agent (repo içinde)
**Öncelik:** P1

**Kapsam:** dosya okuma/yazma/diff, komut çalıştırma, proje bağlamı.

**Kabul kriteri:**
- Dev mode’da “şu dosyayı değiştir” gibi bir istekten patch taslağı üretilir.
- Güvenlik: tehlikeli shell komutları policy ile confirm/deny olur.

---

### D4) NLU iyileştirme (LLM destekli, guardrailed)
**Öncelik:** P2

**Neden:** Regex tabanlı NLU güzel ama ölçeklenince bakım zor.

**Kabul kriteri:**
- Regex “ground truth” kalır; LLM sadece fallback/slot extraction olarak çalışır.
- Yanlış intent oranı düşer (ölçüm/log ile).

---

## Epic E — Paketleme / Kurulum

### E1) `websockets` dependency/extra
**Öncelik:** P0

**Neden:** Extension bridge `websockets` yoksa devre dışı.

**Kabul kriteri:**
- `pip install 'bantz[browser]'` sonrası ws bridge çalışır.

---

### E2) “Playwright kalıntıları” temizliği
**Öncelik:** P0

**Neden:** Repo içinde Playwright controller var, server shutdown yolu hâlâ onu import ediyor; bazı comment’ler Playwright’a göre.

**Kabul kriteri:**
- Tek browser backend net: Firefox+extension.
- Gereksiz Playwright kodu ya kaldırılır ya da açıkça “legacy” diye izole edilir.

İlgili yerler:
- src/bantz/browser/controller.py
- src/bantz/server.py

---

### E3) Kurulum profili: `bantz[voice]`, `bantz[llm]`, `bantz[ui]`, `bantz[browser]`
**Öncelik:** P1

**Neden:** Şu an optional-deps var ama UI/browser parçaları eksik/dağınık kalabilir.

**Kabul kriteri:**
- README’de net kurulum matrisi olur.
- Her mod (voice/browser/ui) tek komutla kurulabilir.

---

## Epic F — Memory / Personality

### F1) Conversational memory (persisted)
**Öncelik:** P1

**Neden:** “Benimle konuşacağım, keyif alacağım” için session dışı hafıza lazım.

**Kabul kriteri:**
- Uzun vadeli tercih/hatırlanacak notlar SQLite/JSONL gibi yerde saklanır.
- Gizlilik: kullanıcı açıkça “hatırla” demeden otomatik kişisel veri saklama yapılmaz (veya setting ile kontrol edilir).

---

## Epic G — Observability / Safety

### G1) Action audit log + replay-safe
**Öncelik:** P2

**Kabul kriteri:**
- Her “mouse/keyboard/browser click/type” aksiyonu loglanır.
- Hassas metinler (şifre vb.) maskelenebilir.

---

### G2) Security & privacy hardening
**Öncelik:** P2

**Kabul kriteri:**
- Policy kuralları genişler (özellikle desktop automation).
- “Asla” yasakları netleşir (sudo vb.).

---

## Epic H — Voice

### H1) Continuous listening kalite iyileştirmesi (VAD)
**Öncelik:** P2

**Kabul kriteri:**
- Gürültüde false trigger azalır.
- “Wake → dinle → işlem → konuş” döngüsü stabil.

---

## Epic I — Analytics / Learning (opsiyonel)

### I1) Komut başarı oranı / autocorrect öğrenme
**Öncelik:** P3

**Kabul kriteri:**
- Başarısız intent’ler etiketlenir; autocorrect alias listesi veriye göre büyütülür.

---

## Hızlı Notlar (Gözlemler)
- Policy ve confirm gate iyi bir temel; bunu “mouse/keyboard agent” büyüdükçe daha da kritik olacak.
- Voice tarafında autocorrect + LLM rewrite ikilisi var; ileride tek bir “normalize pipeline” altında birleştirmek faydalı.
