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

Gmail için (Issue #169):

- `~/.config/bantz/google/client_secret_gmail.json`
- `~/.config/bantz/google/gmail_token.json`

Env ile override edebilirsin:

```bash
export BANTZ_GOOGLE_CLIENT_SECRET="$HOME/.config/bantz/google/client_secret.json"
export BANTZ_GOOGLE_TOKEN_PATH="$HOME/.config/bantz/google/token.json"
export BANTZ_GOOGLE_CALENDAR_ID="primary"

## Önemli Notlar

- Calendar ve Gmail için **token dosyalarını ayrı tut**. Aksi halde birini yetkilendirirken diğerinin token'ını ezip "scope yetersiz" hatası alırsın.
- Tek bir `client_secret.json` ile hem Calendar hem Gmail çalışır. Gmail için ayrıca `client_secret_gmail.json` koymak zorunda değilsin.
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
export BANTZ_GMAIL_CLIENT_SECRET="$HOME/.config/bantz/google/client_secret_gmail.json"
export BANTZ_GMAIL_TOKEN_PATH="$HOME/.config/bantz/google/gmail_token.json"

# (Legacy/back-compat)
export BANTZ_GOOGLE_GMAIL_TOKEN_PATH="$HOME/.config/bantz/google/gmail_token.json"
```

Token üretmek için:

```bash
pip install -e ".[calendar]"
bantz google auth gmail --scope readonly

Eğer Gmail client secret dosyan `client_secret_gmail.json` değil de tek bir dosyaysa:

```bash
export BANTZ_GMAIL_CLIENT_SECRET="$HOME/.config/bantz/google/client_secret.json"
```

Eğer yanlışlıkla `~/.config/bantz/google/token.json` içinde Gmail scope'ları oluştuysa (Calendar token'ı yerine), hızlı düzeltme:

```bash
# Calendar token'ını yeniden üret (token.json calendar scope'ları ile yenilenir)
bantz google auth calendar

# Gmail token'ını ayrı dosyaya üret
export BANTZ_GMAIL_CLIENT_SECRET="$HOME/.config/bantz/google/client_secret.json"
bantz google auth gmail --scope readonly
```
```

Not: Gmail tool’ları repo içinde vLLM kadar “default” değildir; fakat OAuth altyapısı hazır ve aynı `client_secret.json` ile çalışır.
