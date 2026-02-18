# Quickstart — 5 Dakikada Bantz

> Sıfırdan çalışır hale getirme rehberi.

## Gereksinimler

| Bileşen | Minimum |
|---------|---------|
| Python  | 3.10+   |
| GPU     | NVIDIA (CUDA), 6 GB+ VRAM (RTX 3060/4060 vb.) |
| OS      | Ubuntu 22.04+ / Fedora 39+ |
| RAM     | 8 GB+ |
| Disk    | ~5 GB (model + bağımlılıklar) |

## Seçenek A: Tek Komut (Önerilen)

```bash
git clone https://github.com/miclaldogan/bantz.git
cd bantz
bash scripts/quickstart.sh
```

Script otomatik olarak:
1. Python sürümünü kontrol eder
2. `.venv` sanal ortam oluşturur
3. Bağımlılıkları yükler
4. Env dosyasını kopyalar
5. vLLM bağlantısını test eder
6. Dizin yapısını hazırlar

## Seçenek B: Docker Compose

```bash
git clone https://github.com/miclaldogan/bantz.git
cd bantz

# Env dosyasını hazırla
cp config/bantz-env.example ~/.config/bantz/env

# vLLM + model'i başlat (ilk seferde model indirilir, ~5 dk)
docker compose up -d

# Health check
curl http://localhost:8001/v1/models

# Bantz'ı çalıştır
pip install -e .
python -m bantz
```

## Seçenek C: Manuel Kurulum

```bash
# 1. Repo
git clone https://github.com/miclaldogan/bantz.git && cd bantz

# 2. Sanal ortam
python3 -m venv .venv && source .venv/bin/activate

# 3. Bağımlılıklar
pip install -e ".[dev]"

# 4. vLLM başlat (ayrı terminal)
pip install vllm
vllm serve Qwen/Qwen2.5-3B-Instruct-AWQ --port 8001

# 5. Env ayarları
mkdir -p ~/.config/bantz
cp config/bantz-env.example ~/.config/bantz/env
nano ~/.config/bantz/env   # GEMINI_API_KEY ekle (opsiyonel)

# 6. Çalıştır
python -m bantz
```

## Modlar

| Komut | Açıklama |
|-------|----------|
| `python -m bantz` | Terminal modu (metin tabanlı) |
| `python -m bantz --voice` | Sesli mod (mikrofon + hoparlör) |
| `python -m bantz --wake` | Wake word modu ("Hey Bantz" ile tetikleme) |
| `python scripts/demo.py` | Otomatik demo akışı |

## İlk Kullanım Checklist

- [ ] Doctor çalıştır → `bantz doctor` (tüm kontrolleri tek seferde yapar)
- [ ] vLLM çalışıyor mu? → `curl http://localhost:8001/v1/models`
- [ ] Env dosyası var mı? → `~/.config/bantz/env`
- [ ] (Opsiyonel) Gemini API key? → `GEMINI_API_KEY=...`
- [ ] (Opsiyonel) Google Calendar/Gmail? → `python -m bantz.google auth`

## Onboarding Wizard

İlk kez kuruluyor ve adım adım rehber isterseniz:

```bash
bantz onboard
```

Wizard sırasıyla kontrol eder: Python sürümü, GPU/CUDA, vLLM bağlantısı,
env dosyası, Google OAuth tokenları.  Eksik adımları otomatik tamamlar.

## Sorun Giderme

**vLLM başlamıyor:**
- CUDA yüklü mü? → `nvidia-smi`
- VRAM yeterli mi? → Qwen 3B AWQ ~3 GB VRAM gerektirir

**Model indirme başarısız:**
- HuggingFace erişimi var mı? → `huggingface-cli whoami`
- Offline mod: modeli manuel indirip `HF_HOME` ile göster

**Import hataları:**
- `pip install -e ".[dev]"` çalıştırdınız mı?
- Doğru venv aktif mi? → `which python`
