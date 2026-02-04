# GitHub Issue Templates (Repo-tracked)

Bu klasör, GitHub issue metinlerini repo içinde sürümlü tutmak için var.

Amaç:
- Issue body değişiklikleri PR review sürecinden geçsin
- “Issue metni güncel mi?” sorusu tek bir yerden kontrol edilsin

## Apply / Sync

`gh` yüklüyse aşağıdaki script ile issue metinlerini GitHub’a uygulayabilirsin:

```bash
./scripts/sync_github_issues.sh
```

Notlar:
- Script idempotent olacak şekilde tasarlanmıştır; tekrar çalıştırmak güvenlidir.
- `gh auth login` yapılmış olmalı.
