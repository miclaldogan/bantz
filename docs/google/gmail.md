# Gmail

Durum: temel OAuth altyapısı hazır; Gmail API tool’ları bu repo içinde **opsiyonel**.

## OAuth

Aynı `client_secret.json` kullanılır.

Gmail token için ayrı dosya önerilir:

```bash
export BANTZ_GOOGLE_GMAIL_TOKEN_PATH="$HOME/.config/bantz/google/gmail_token.json"
```

Not: Gmail scope’ları Calendar’dan farklıdır; ilk kullanımda yeniden consent gerekir.

## Token üretme (CLI)

```bash
pip install -e ".[calendar]"
bantz google auth gmail --scope readonly
```
