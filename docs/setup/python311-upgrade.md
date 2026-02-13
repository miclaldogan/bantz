# Python 3.11+ Upgrade Guide

## Neden 3.11+?

1. **Google API uyarıları** — Google libs Python 3.10 EOL uyarısı veriyor
2. **Performans** — Python 3.11 ortalama %25 daha hızlı (CPython speedup)
3. **Dil özellikleri** — `ExceptionGroup`, `tomllib`, `StrEnum` built-in
4. **Gelecek uyumluluk** — Büyük kütüphaneler 3.10 desteğini bırakıyor

## Kurulum (pyenv ile)

```bash
# pyenv kur (yoksa)
curl https://pyenv.run | bash

# Shell'e ekle (~/.bashrc veya ~/.zshrc)
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"

# Python 3.11 kur
pyenv install 3.11.11
pyenv local 3.11.11

# Doğrula
python --version  # Python 3.11.11
```

## Kurulum (uv ile — önerilen)

```bash
# uv kur
curl -LsSf https://astral.sh/uv/install.sh | sh

# Proje ortamı oluştur
cd /path/to/bantz
uv venv --python 3.11
source .venv/bin/activate

# Bağımlılıkları kur
uv pip install -r requirements-all.txt

# Doğrula
python --version
```

## Kurulum (apt ile — Ubuntu 22.04+)

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# Sanal ortam
python3.11 -m venv .venv
source .venv/bin/activate

pip install -r requirements-all.txt
```

## Doğrulama

```bash
# Versiyon kontrolü
python -c "import sys; assert sys.version_info >= (3, 11), f'Need 3.11+, got {sys.version}'; print(f'✓ Python {sys.version}')"

# Google API uyarı kontrolü
python -c "import warnings; warnings.filterwarnings('error'); import google.auth; print('✓ Google API: no warnings')" 2>/dev/null || echo "Google API not installed (OK if not using cloud)"

# Pip install temiz kurulum
pip install -e . 2>&1 | tail -1
```

## Notlar

- `pyproject.toml` artık `requires-python = ">=3.11"` içerir
- Mevcut `.venv` 3.10 ise silip yeniden oluşturun
- CI (varsa) Python 3.11'de çalışmalıdır
