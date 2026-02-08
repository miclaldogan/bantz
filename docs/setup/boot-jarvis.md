# Boot Jarvis Kurulum Rehberi

Bu rehber **BANTZ**'ın bilgisayar açılışında otomatik başlamasını sağlar.
Adım adım ilerleyerek temiz bir Ubuntu kurulumundan çalışan bir sisteme
ulaşabilirsiniz.

---

## Gereksinimler

| Bileşen          | Minimum                          | Önerilen                          |
|------------------|----------------------------------|-----------------------------------|
| **İşletim Sistemi** | Ubuntu 22.04+ / Linux (systemd) | Ubuntu 24.04 LTS                 |
| **Python**        | 3.11+                            | 3.12                              |
| **GPU**           | —                                | NVIDIA RTX 4060+ (vLLM için)     |
| **RAM**           | 8 GB                             | 16 GB+                            |
| **Disk**          | 20 GB boş                        | 50 GB+                            |
| **Mikrofon**      | USB veya built-in                | USB condenser                     |
| **Hoparlör**      | Herhangi                         | Kulaklık (barge-in için)         |

### Yazılım Gereksinimleri

```bash
# Sistem paketleri
sudo apt update && sudo apt install -y \
    python3-pip python3-venv python3-dev \
    portaudio19-dev ffmpeg git curl \
    libsndfile1 libasound2-dev

# pip güncellemesi
pip install --upgrade pip
```

---

## 1. Proje Kurulumu

```bash
# Depoyu klonla
git clone https://github.com/miclaldogan/bantz.git
cd bantz

# Sanal ortam oluştur
python3 -m venv .venv
source .venv/bin/activate

# Temel bağımlılıklar
pip install -r requirements.txt

# Tüm bağımlılıklar (isteğe bağlı)
pip install -r requirements-all.txt
```

### Proje Yapısını Doğrula

```bash
python -c "from bantz.brain.runtime_factory import create_runtime; print('✓ Runtime OK')"
```

---

## 2. vLLM Kurulumu

BANTZ, yerel LLM çıkarımı için **vLLM** kullanır. İki seçenek vardır:

### A) GPU ile (Önerilen)

```bash
# vLLM kur
pip install vllm

# Modeli indir ve başlat (Qwen2.5-3B-Instruct-AWQ)
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-3B-Instruct-AWQ \
    --quantization awq \
    --port 8001 \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.85
```

> **Not:** İlk çalıştırmada model indirilir (~2 GB). Sonraki başlatmalar
> çok daha hızlıdır.

### B) Docker ile

```bash
cd docker/vllm
docker compose up -d
```

Yapılandırma dosyası: `docker/vllm/docker-compose.yml`

### C) CPU ile (Yavaş — Sadece Test)

```bash
pip install vllm

python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-3B-Instruct \
    --device cpu \
    --port 8001 \
    --max-model-len 2048
```

> ⚠️ CPU modunda yanıt süresi 5–30 saniye arasındadır. Geliştirme/test
> dışında önerilmez.

### Sağlık Kontrolü

```bash
# vLLM durumunu kontrol et
curl -s http://localhost:8001/health | python3 -m json.tool

# veya script ile
python scripts/health_check_vllm.py
```

### .env Ayarları

```bash
# .env dosyasına ekle
BANTZ_VLLM_URL=http://localhost:8001
BANTZ_VLLM_MODEL=Qwen/Qwen2.5-3B-Instruct-AWQ
```

---

## 3. Gemini Kurulumu (Opsiyonel)

Gemini, hibrit orkestratör mimarisinde **finalizer** olarak kullanılır.
Gemini olmadan da çalışabilirsiniz — sadece yerel model kullanılır.

### API Key Alma

1. [Google AI Studio](https://aistudio.google.com/apikey) adresine gidin
2. **Create API Key** tıklayın
3. Anahtarı kopyalayın

### .env Ayarları

```bash
# .env dosyasına ekle
GEMINI_API_KEY=AIzaSy...your-key-here
BANTZ_CLOUD_ENABLED=true

# Model seçimi (varsayılan: gemini-1.5-flash)
BANTZ_GEMINI_MODEL=gemini-1.5-flash
```

### Doğrulama

```bash
python -c "
import os
key = os.getenv('GEMINI_API_KEY', '')
print('✓ Gemini key configured' if key else '✗ No Gemini key')
"
```

> **Gizlilik:** Gemini'ye veri göndermeden önce kullanıcı onayı gerekir.
> Ayrıntılar için [Bölüm 5: Gizlilik Ayarları](#5-gizlilik-ayarları)
> kısmına bakın.

---

## 4. Ses Cihazı Seçimi

### Mevcut Cihazları Listele

```bash
# Python ile
python -c "
import sounddevice as sd
print(sd.query_devices())
"

# veya arecord ile
arecord -l
aplay -l
```

Çıktı örneği:
```
   0 HDA Intel: ALC892 (hw:0,0), ALSA (2 in, 2 out)
   1 USB Audio: USB Microphone (hw:1,0), ALSA (1 in, 0 out)
   2 pulse, PulseAudio (16 in, 16 out)
```

### Cihaz Ayarla

```bash
# .env dosyasına ekle — cihaz index numarasını kullan
BANTZ_MIC_DEVICE=1          # USB mikrofon
BANTZ_SPEAKER_DEVICE=0      # Dahili hoparlör

# veya cihaz adıyla
BANTZ_MIC_DEVICE_NAME="USB Microphone"
```

### Test Et

```bash
# Mikrofon testi (5 saniye kayıt)
python -c "
import sounddevice as sd
import numpy as np
duration = 5
print('5 saniye kayıt yapılıyor...')
recording = sd.rec(int(duration * 16000), samplerate=16000, channels=1)
sd.wait()
peak = np.max(np.abs(recording))
print(f'✓ Kayıt tamamlandı. Peak amplitude: {peak:.4f}')
if peak < 0.01:
    print('⚠️ Mikrofon çok sessiz — bağlantıyı kontrol edin')
else:
    print('✓ Mikrofon düzgün çalışıyor')
"
```

### PulseAudio / PipeWire Ayarları

```bash
# Varsayılan mikrofonu ayarla
pactl set-default-source alsa_input.usb-USB_Microphone-00

# Ses seviyesini kontrol et
pactl get-source-volume @DEFAULT_SOURCE@
```

---

## 5. Gizlilik Ayarları

BANTZ varsayılan olarak **local-only** modda çalışır. Hiçbir veri buluta
gönderilmez.

### Local-Only Mode (Varsayılan)

```bash
# .env — bu varsayılan ayardır, değiştirmeye gerek yok
BANTZ_CLOUD_ENABLED=false
```

Bu modda:
- Tüm LLM çıkarımı yerel vLLM üzerinden yapılır
- Ses işleme tamamen yerel
- Hiçbir veri dışarı çıkmaz

### Cloud Mode Etkinleştirme

```bash
# .env
BANTZ_CLOUD_ENABLED=true
GEMINI_API_KEY=AIzaSy...

# PII redaction (her zaman aktif)
BANTZ_REDACT_PII=true
```

İlk çalıştırmada kullanıcıdan onay istenir:
```
BANTZ: "Efendim, bazı işlemler için bulut hizmeti kullanmam gerekiyor.
        İzin veriyor musunuz? (evet/hayır)"
```

### Onay Yönetimi

```bash
# Onay durumunu görüntüle
python -c "
from bantz.privacy.config import load_privacy_config
cfg = load_privacy_config()
print(f'Cloud mode: {cfg.cloud_mode}')
print(f'Consent given: {cfg.consent_given_at}')
"

# Onayı iptal et
python -c "
from bantz.privacy.consent import ConsentManager
cm = ConsentManager()
cm.revoke_all()
print('✓ Tüm onaylar iptal edildi')
"
```

### Gizlilik Yapılandırma Dosyası

Konum: `~/.config/bantz/privacy.json`

```json
{
  "cloud_mode": false,
  "consent_given_at": null,
  "skills": {
    "calendar": {"cloud_allowed": false},
    "email": {"cloud_allowed": false}
  }
}
```

---

## 6. systemd Servisleri

BANTZ'ı açılışta otomatik başlatmak için systemd kullanılır.

### Servisleri Kur

```bash
# Servis dosyalarını kopyala
mkdir -p ~/.config/systemd/user/

# Ana servis
cp config/bantz.service ~/.config/systemd/user/bantz.service

# Yardımcı servisler
cp systemd/user/bantz-voice-watchdog.service ~/.config/systemd/user/
cp systemd/user/bantz-resume.service ~/.config/systemd/user/
cp systemd/user/bantz-vllm-watchdog.service ~/.config/systemd/user/

# Yolları düzenle (kendi kurulum dizininize göre)
sed -i "s|/home/iclaldogan/Desktop/Bantz|$(pwd)|g" \
    ~/.config/systemd/user/bantz.service
```

### Servisleri Etkinleştir

```bash
# systemd'yi yeniden yükle
systemctl --user daemon-reload

# Servisleri etkinleştir (açılışta başlasın)
systemctl --user enable bantz.service
systemctl --user enable bantz-voice-watchdog.service
systemctl --user enable bantz-resume.service

# Hemen başlat
systemctl --user start bantz.service
```

### Durum Kontrolü

```bash
# Ana servis durumu
systemctl --user status bantz.service

# Tüm BANTZ servisleri
systemctl --user list-units 'bantz*'

# Logları izle
journalctl --user -u bantz.service -f

# Son 50 log satırı
journalctl --user -u bantz.service -n 50 --no-pager
```

### Servisleri Durdur

```bash
# Durdur
systemctl --user stop bantz.service

# Devre dışı bırak (açılışta başlamasın)
systemctl --user disable bantz.service
```

### Lingering (Kullanıcı Oturumu Olmadan Çalışma)

```bash
# Kullanıcı giriş yapmasa bile servislerin çalışmasını sağla
sudo loginctl enable-linger $USER
```

---

## 7. Ortam Değişkenleri Özeti

Tüm ayarları `.env` dosyasında toplayın:

```bash
# === LLM ===
BANTZ_VLLM_URL=http://localhost:8001
BANTZ_VLLM_MODEL=Qwen/Qwen2.5-3B-Instruct-AWQ

# === Gemini (opsiyonel) ===
GEMINI_API_KEY=
BANTZ_CLOUD_ENABLED=false
BANTZ_GEMINI_MODEL=gemini-1.5-flash

# === Ses ===
BANTZ_MIC_DEVICE=1
BANTZ_SPEAKER_DEVICE=0

# === Gizlilik ===
BANTZ_REDACT_PII=true

# === Morning Briefing (opsiyonel) ===
BANTZ_MORNING_BRIEFING=false
BANTZ_BRIEFING_HOUR=08
BANTZ_QUIET_HOURS_START=00:00
BANTZ_QUIET_HOURS_END=07:00

# === Kontroller ===
BANTZ_PTT_KEY=ctrl+space
BANTZ_MUTE_KEY=ctrl+m
BANTZ_STATUS_KEY=ctrl+shift+s

# === Metrikler ===
BANTZ_METRICS_ENABLED=true
BANTZ_LATENCY_BUDGET_MS=3000
```

---

## 8. Smoke Test

Kurulumun çalıştığını doğrulamak için:

### Adım 1: vLLM Kontrolü

```bash
python scripts/health_check_vllm.py
# Beklenen: "vLLM is healthy"
```

### Adım 2: Runtime Kontrolü

```bash
python -c "
from bantz.brain.runtime_factory import create_runtime
rt = create_runtime()
print(f'✓ Runtime: {rt}')
print(f'  Model: {rt.model_id}')
"
```

### Adım 3: Ses Kontrolü

```bash
python -c "
import sounddevice as sd
devices = sd.query_devices()
default_input = sd.query_devices(kind='input')
print(f'✓ Varsayılan mikrofon: {default_input[\"name\"]}')
"
```

### Adım 4: Boot-to-Ready Smoke

```bash
# Tam end-to-end smoke test
python scripts/e2e_run.py
```

### Adım 5: Sistem Sağlık Kontrolü

```bash
python -c "
from bantz.skills.sysinfo import run_health_check
print(run_health_check())
"
```

---

## 9. Troubleshooting

### Servis Başlamıyor

```bash
# Detaylı log
journalctl --user -u bantz.service -n 100 --no-pager

# Yaygın sorunlar:
# 1. Python yolu yanlış → bantz.service dosyasında ExecStart kontrol et
# 2. .venv aktif değil → PYTHONPATH doğru mu?
# 3. Port çakışması → lsof -i :8001
```

**Çözüm:**
```bash
# Servis dosyasındaki yolları kontrol et
cat ~/.config/systemd/user/bantz.service | grep -E "ExecStart|WorkingDirectory"

# Manuel çalıştırıp hatayı gör
cd /path/to/bantz
.venv/bin/python -m bantz.daemon
```

### vLLM Bağlanmıyor

```bash
# Port açık mı?
curl -s http://localhost:8001/health

# Process çalışıyor mu?
ps aux | grep vllm

# GPU memory yeterli mi?
nvidia-smi
```

**Yaygın Hatalar:**
| Hata | Çözüm |
|------|--------|
| `Connection refused` | vLLM çalışmıyor → servisi başlat |
| `CUDA out of memory` | `--gpu-memory-utilization 0.7` ile düşür |
| `Model not found` | Model adını kontrol et, indirmeyi bekle |

### Mikrofon Algılanmıyor

```bash
# Cihazları listele
arecord -l

# PulseAudio durumu
pactl list short sources

# Mikrofon izinlerini kontrol et
groups | grep -E "audio|pulse"
# Yoksa: sudo usermod -aG audio $USER
```

**Çözüm:**
```bash
# PulseAudio yeniden başlat
pulseaudio -k && pulseaudio --start

# ALSA doğrudan test
arecord -d 3 -f S16_LE -r 16000 /tmp/test.wav
aplay /tmp/test.wav
```

### Wake Word Çalışmıyor

```bash
# Mikrofon enerji seviyesini kontrol et
python -c "
import sounddevice as sd
import numpy as np
data = sd.rec(int(2 * 16000), samplerate=16000, channels=1)
sd.wait()
energy = np.sqrt(np.mean(data**2))
print(f'Ses enerjisi: {energy:.6f}')
if energy < 0.001:
    print('⚠️ Mikrofon çok sessiz veya kapalı')
elif energy > 0.1:
    print('⚠️ Ortam çok gürültülü')
else:
    print('✓ Ses seviyesi normal')
"
```

### GPU Algılanmıyor

```bash
# NVIDIA driver kontrolü
nvidia-smi

# CUDA toolkit
nvcc --version

# PyTorch GPU desteği
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}, Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"N/A\"}')"
```

### Yüksek Bellek Kullanımı

```bash
# Sistem durumunu kontrol et
python -c "
from bantz.skills.sysinfo import run_health_check
print(run_health_check())
"

# vLLM bellek kullanımını düşür
# docker-compose.yml veya komut satırında:
#   --gpu-memory-utilization 0.7
#   --max-model-len 2048
```

### Log Dosyaları

```bash
# systemd logları
journalctl --user -u bantz.service --since "1 hour ago"

# Uygulama logları
ls -la artifacts/logs/

# vLLM logları
journalctl --user -u bantz-vllm-watchdog.service -n 50
```

---

## 10. Güncelleme

```bash
cd /path/to/bantz
git pull origin dev
pip install -r requirements.txt

# Servisleri yeniden başlat
systemctl --user restart bantz.service
```

---

## Hızlı Başlangıç (TL;DR)

```bash
# 1. Klon + ortam
git clone https://github.com/miclaldogan/bantz.git && cd bantz
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-all.txt

# 2. .env oluştur
cp .env.example .env  # Düzenle: BANTZ_VLLM_URL, MIC_DEVICE vb.

# 3. vLLM başlat
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-3B-Instruct-AWQ \
    --quantization awq --port 8001 &

# 4. Servisleri kur
cp config/bantz.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now bantz.service

# 5. Doğrula
python scripts/health_check_vllm.py
python -c "from bantz.skills.sysinfo import run_health_check; print(run_health_check())"
```

Sorun yaşarsanız [Troubleshooting](#9-troubleshooting) bölümüne bakın.
