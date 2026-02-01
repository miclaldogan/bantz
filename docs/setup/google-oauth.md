# Google OAuth Setup (Calendar + Gmail)

Bantz Google entegrasyonları OAuth2 ile çalışır.

## Gerekenler

- Google Cloud Project
- OAuth consent screen
- OAuth client (Desktop app önerilir)
- İndirilen `client_secret.json`

## Dosya Konumları (Varsayılan)

Bantz şu dosyaları bekler:

- `~/.config/bantz/google/client_secret.json`
- `~/.config/bantz/google/token.json` (Calendar için)

Env ile override edebilirsin:

```bash
export BANTZ_GOOGLE_CLIENT_SECRET="$HOME/.config/bantz/google/client_secret.json"
export BANTZ_GOOGLE_TOKEN_PATH="$HOME/.config/bantz/google/token.json"
export BANTZ_GOOGLE_CALENDAR_ID="primary"
```

## Takvim Token’ı Üretme

İlk çalıştırmada OAuth flow açılır ve token dosyası yazılır.

Hızlı smoke test:
Önerilen (CLI):

```bash
pip install -e ".[calendar]"

# Konfig / path kontrol
bantz google env

# Token üret (read-only)
bantz google auth calendar

# Write gerekiyorsa:
bantz google auth calendar --write

# Smoke: event listele
bantz google calendar list --max-results 10
```

Alternatif (script smoke test):

```bash
pip install -e ".[calendar]"
python scripts/smoke_calendar_list_events.py
```

## Gmail Token (Ayrı)

Gmail için ayrı token dosyası kullanmak istersen:

```bash
export BANTZ_GOOGLE_GMAIL_TOKEN_PATH="$HOME/.config/bantz/google/gmail_token.json"
```

Token üretmek için:

```bash
pip install -e ".[calendar]"
bantz google auth gmail --scope readonly
```

Not: Gmail tool’ları repo içinde vLLM kadar “default” değildir; fakat OAuth altyapısı hazır ve aynı `client_secret.json` ile çalışır.
