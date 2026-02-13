## Epic: LLM Tiering | P1 | Medium (3-4 days)

**Dependencies:** #178

**Update (2026-02-04):** Lokal multi-model (3B+8B / port 8002) hedefi şimdilik iptal. Kalite için **Gemini (cloud)** kullanılacak.

**Goal:** 3B local vLLM (fast) + Gemini (quality) ile sağlam bir tiered strateji.

**User Story:**
- "Router/planner işleri local 3B ile hızlı aksın"
- "Mail taslağı/uzun yazı/özet gibi işlerde Gemini kalite versin"
- "Cloud kapalıysa sistem düzgün fallback yapsın"

**Acceptance Criteria:**
- [ ] Tiered routing: fast (vLLM 3B) vs quality (Gemini) kavramları net
- [ ] Konfigürasyon env'leri dokümante:
  - BANTZ_CLOUD_MODE=cloud
  - QUALITY_PROVIDER=gemini
  - GEMINI_API_KEY=...
- [ ] Fallback davranışı: cloud disabled/unavailable -> fast tier
- [ ] Validation: validate_hybrid_quality.sh (veya benzeri) ile hızlı doğrulama
- [ ] Docs: docs/setup/vllm.md ve docs/gemini-hybrid-orchestrator.md güncel

**Out of scope (şimdilik):** 8002 portunda lokal 8B/7B paralel servis, GPU split, load balancing across two local models.

**Related:** PR #275 (docs/config strategy alignment)
