# Contributing to Bantz

Bantz'a katkıda bulunmak istediğin için teşekkürler! 🎉

Bu doküman, projeye nasıl katkıda bulunabileceğini adım adım anlatır.

---

## 🚀 Hızlı Başlangıç

### 1. Repo'yu klonla

```bash
git clone git@github.com:miclaldogan/bantz.git
cd bantz
```

### 2. Python ortamını kur

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-all.txt
pip install -e .
```

### 3. Testleri çalıştır

```bash
pytest tests/ -v --tb=short
```

Tüm testler geçiyorsa, koda başlamaya hazırsın! ✅

---

## 🌳 Branch Kuralları

| Branch | Amaç |
|--------|-------|
| `main` | Stable release — doğrudan push yapma |
| `dev` | Aktif geliştirme — tüm PR'lar buraya açılır |
| `fix/XXX-kısa-açıklama` | Bug fix branch'leri |
| `feat/XXX-kısa-açıklama` | Yeni özellik branch'leri |
| `chore/XXX-kısa-açıklama` | Refactor, temizlik, CI/CD |

### Yeni bir branch oluştur

```bash
git checkout dev
git pull origin dev
git checkout -b fix/123-kisa-aciklama dev
```

> ⚠️ **Her zaman `dev` branch'inden türet. Asla `main`'den branch açma.**

---

## ✍️ Commit Mesajları

[Conventional Commits](https://www.conventionalcommits.org/) formatını kullanıyoruz:

```
tip(kapsam): kısa açıklama (#issue-no)
```

### Tipler

| Tip | Kullanım |
|-----|----------|
| `fix` | Bug düzeltme |
| `feat` | Yeni özellik |
| `refactor` | Davranış değiştirmeyen kod iyileştirmesi |
| `test` | Test ekleme/düzeltme |
| `docs` | Dokümantasyon |
| `chore` | CI/CD, bağımlılık, yapılandırma |

### Örnekler

```
fix(voice): guard barge-in state with threading.Lock (#759)
feat(calendar): add all-day event detection (#750)
test(scheduler): add ReminderManager unit tests (#758)
refactor(privacy): tighten IP regex to reject version strings (#748)
```

---

## 🔀 Pull Request Süreci

1. **Branch'ini oluştur** ve değişikliklerini yap
2. **Testleri çalıştır** — kırık test ile PR açma
3. **Push et** ve `dev` branch'ine PR aç
4. PR template'ini eksiksiz doldur
5. Review bekle — en az **1 onay** gerekli
6. Merge sonrası branch otomatik silinir

### PR Kontrol Listesi

- [ ] Testler geçiyor (`pytest tests/ -v`)
- [ ] Yeni kod için test yazıldı
- [ ] Commit mesajları conventional format'ta
- [ ] İlgili issue linkli (`Closes #XXX`)

---

## 🧪 Test Kuralları

- Her yeni özellik/fix için test yaz
- Test dosyaları: `tests/test_<modül_adı>.py`
- `pytest` kullanıyoruz, `unittest` değil
- `tmp_path` fixture'ını kullan, hardcoded path yazma
- `assert True` gibi boş assertion'lar yasak — gerçek değerleri kontrol et

```bash
# Tek bir test dosyası çalıştır
pytest tests/test_scheduler.py -v

# Belirli bir test
pytest tests/test_ipc.py::TestEncoding::test_roundtrip_state -v
```

---

## 📁 Proje Yapısı

```
src/bantz/
├── brain/          # LLM orchestration, tiered quality
├── core/           # Event bus, config, plugin system
├── google/         # Calendar, Gmail integration
├── ipc/            # Browser overlay IPC protocol
├── privacy/        # PII redaction, data masking
├── router/         # Intent routing, policy engine
├── scheduler/      # Reminders, check-ins
├── security/       # Action classifier, audit, permissions
├── tools/          # Tool registry, result formatting
└── voice/          # TTS, STT, wake word, barge-in, FSM
```

---

## 🎨 Kod Stili

- **Python 3.10+** — type hint kullan
- **Docstring**: Google style
- **Line length**: 100 karakter (soft limit)
- **Import sırası**: stdlib → third-party → local
- **Dil**: Kod ve değişken adları İngilizce, kullanıcıya dönük string'ler Türkçe

```python
def _parse_time(self, time_str: str) -> Optional[datetime]:
    """Parse Turkish time string like '5 dakika sonra' or 'yarın 09:00'."""
    ...
```

---

## 🔒 Güvenlik

Güvenlik açığı bulduysan **issue açma** — bunun yerine [SECURITY.md](SECURITY.md) dosyasındaki talimatları takip et.

---

## 💬 İletişim

- Sorular için [GitHub Discussions](https://github.com/miclaldogan/bantz/discussions) kullan
- Bug raporları için [issue aç](https://github.com/miclaldogan/bantz/issues/new?template=bug_report.md)

---

Hoş geldin, iyi kodlamalar! 🚀
