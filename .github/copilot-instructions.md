# Copilot Code Review Instructions — Bantz

Bu dosya, GitHub Copilot'un PR review'larında kullanacağı custom instructions'ları tanımlar.

## Proje Bağlamı

Bantz, Linux masaüstü için yerel çalışan, Türkçe bir AI asistan platformudur.
- **Python 3.10+**, asyncio-based
- **LLM Backend:** Ollama (qwen2.5-coder:7b router) + Gemini 2.0 Flash (finalizer)
- **~76 registered tools** (Gmail, Calendar, system, browser, voice, etc.)
- **SQLite** data layer (WAL journal mode, thread-safe)
- **Test framework:** pytest + pytest-asyncio

## Review Kuralları

### Güvenlik (EN ÖNEMLİ)
- Hardcoded credentials, API keys, tokens **kesinlikle olmamalı**
- `eval()`, `exec()`, `os.system()` kullanımı açıkça gerekçelendirilmeli
- SQL injection riski: tüm sorgular parametreli olmalı (`?` placeholder)
- File path traversal: kullanıcı girdisinden gelen path'ler `Path.resolve()` ile doğrulanmalı
- Google OAuth token'ları, refresh token'ları `config/` dışında saklanmamalı

### Thread Safety
- `threading.Lock` kullanımı: SQLite erişimi, shared state mutasyonu
- `asyncio.Lock` vs `threading.Lock` karıştırılmamalı
- Global mutable state (module-level dict/list) kullanımı sorgulanmalı

### Error Handling
- Tüm harici API çağrıları (Ollama, Gemini, Google API) try/except ile sarılmalı
- Bare `except:` kullanılmamalı, en azından `except Exception:`
- `finally:` blokları resource cleanup için kullanılmalı
- Fallback mekanizması: servis çökünce ne olacağı tanımlı olmalı

### Code Quality
- Public fonksiyonlar docstring'e sahip olmalı
- Type hints tercih edilmeli (strict zorunlu değil)
- Magic number'lar constant'a çıkarılmalı
- Dosya uzunluğu 500 satırı geçince bölünme önerilmeli
- Circular import riski varsa belirtilmeli

### Test Expectations
- Yeni public API → en az 1 happy path + 1 error case testi
- Mock kullanımı: harici servisler (Ollama, Google API) mock'lanmalı
- Async test'ler `@pytest.mark.asyncio` dekoratörü ile işaretlenmeli
- `tmp_path` fixture'ı dosya testleri için kullanılmalı

### Proje Konvansiyonları
- Commit mesajı: `type(scope): description` formatı (feat, fix, refactor, test, docs, chore)
- Branch adı: `feature/ISSUE_NUMBER-short-description` veya `fix/ISSUE_NUMBER-short-description`
- İmport sırası: stdlib → third-party → local (isort uyumlu)
- Logging: `structlog` veya `logging` modülü, print() yerine logger kullanılmalı
- Config: environment variable veya `config/` dizini, hardcoded değerler değil
