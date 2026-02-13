## Epic: vLLM Infrastructure | P0 | Large (updated for 3B-only)

**Update (2026-02-04):** Lokal 7B/8B (port 8002) planı şimdilik askıda. Strateji: **vLLM ile 3B (8001)** + kalite gereken yazım işleri için **Gemini (cloud)**.

**Problem:** vLLM kurulum/operasyon sorunları yaşıyoruz. Ollama yerine vLLM kullanacağız, hız kritik.

**User Story:**
- "vLLM 8001 portunda 3B model stabil çalışsın"
- "Server crash etmesin, auto-restart olsun"
- "Kurulum + troubleshooting dokümanı olsun"

**Acceptance Criteria:**
- [ ] vLLM 0.6.0+ kurulumu (pip ve/veya docker) dokümante
- [ ] CUDA / driver compatibility notları (Linux)
- [ ] Port config: **8001 (3B)**
- [ ] Health check endpoint: /v1/models
- [ ] Auto-restart / recovery: watchdog veya systemd ile
- [ ] Log klasörü + takip komutları (journalctl / artifacts/logs)
- [ ] Docs: step-by-step installation + runbook
- [ ] Tests: smoke test (curl/health_check script)

**Out of scope (şimdilik):** Lokal 8B/7B servisi, port 8002, GPU memory split.

**Related:** PR #275 (docs/config strategy alignment)

**Risk:** HIGH - production stability depends on this
