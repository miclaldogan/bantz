# Component Integration Map — Personalization Altyapı (Issue #872)

> **Tarih**: 2026-02-11  
> **Durum**: Audit tamamlandı, bağlantı kararları verildi  
> **Toplam disconnected kod**: 11.543 satır (30 dosya)  
> **Aktif memory**: `brain/memory_lite.py` (284 satır)

---

## 1. Mevcut Durum Özeti

```
orchestrator_loop.py
  └── brain/memory_lite.py (284L) ✅ AKTİF
        ├── CompactSummary — rolling dialog özeti
        └── PIIFilter — PII maskeleme

  ╳── memory/ (21 dosya, 7923L) ❌ DISCONNECTED
  ╳── learning/ (9 dosya, 3620L) ❌ DISCONNECTED
```

### Aktif Pipeline
```
User Input → LLM Router → _force_tool_plan → _sanitize_tool_plan
           → _execute_tools_phase → Finalization Pipeline
           → memory_lite.update() (CompactSummary)
```

Memory/Learning modülleri bu pipeline'ın **hiçbir noktasında** çağrılmıyor.

---

## 2. Import Graph

### 2.1 Dışarıdan Import Edilen Modüller

| Kaynak (src/bantz/) | memory/ veya learning/ import? |
|---|---|
| brain/orchestrator_loop.py | ❌ Sadece `brain/memory_lite` |
| brain/prompt_engineering.py | ❌ Hiç |
| brain/finalization_pipeline.py | ❌ Hiç |
| brain/llm_router.py | ❌ Hiç |
| server.py | ❌ Hiç |
| api/ws.py | ❌ Hiç |

**Sonuç**: `memory/` ve `learning/` paketlerini runtime'da kullanan **sıfır** production dosya var.

### 2.2 Ters Bağımlılık (DÜZELTİLDİ)

```
ÖNCEKİ (kırılgan):
  memory/safety.py ──import──→ brain/memory_lite.PIIFilter

SONRAKI (Issue #872 fix):
  memory/safety.py ──lazy import──→ brain/memory_lite.PIIFilter
  (module-level import kaldırıldı, fonksiyon içi lazy import)
```

### 2.3 Paket-İçi Bağımlılıklar

#### memory/ iç graf
```
__init__.py ──→ (tüm alt modüller re-export)
context.py ──→ profile, personality, snippet, types
learning.py ──→ profile, personality, types, snippet_store
store.py ──→ types, models, migrations, ranking, sensitivity
preferences.py ──→ profile, types
retrieval.py ──→ ranking, types, snippet_store
safety.py ──→ brain/memory_lite (lazy, Issue #872)
snippet_manager.py ──→ snippet, snippet_store, types, write_policy
write_decision.py ──→ write_policy, sensitivity
```

#### learning/ iç graf
```
__init__.py ──→ (tüm alt modüller re-export)
behavioral.py ──→ profile (learning/profile)
preferences.py ──→ profile (learning/profile)
adaptive.py ──→ (bağımsız)
bandit.py ──→ (bağımsız)
temporal.py ──→ (bağımsız)
storage.py ──→ profile (learning/profile)
preference_integration.py ──→ (bağımsız, kendi dataclass'ları)
```

**memory/ ve learning/ birbirini import etmiyor.**

---

## 3. Duplicate UserProfile Analizi

### 3 Ayrı Tanım

| Konum | Satır | Odak | Temel Alanlar |
|---|---|---|---|
| `memory/profile.py` | 664 | **Fact-oriented** profil | name, language, timezone, communication_style, work_patterns, learned_facts, interests |
| `learning/profile.py` | 457 | **Behavioral/RL** profil | preferred_apps, command_sequences, time_patterns, exploration_tendency, app_affinity_scores |
| `memory/models.py` | 166 | **Key-value** storage modeli | Generic MemoryEntry, MemoryTag (SQLite CRUD için) |

### Örtüşen Alanlar
- `preferred_language` / `language`: Her iki UserProfile'da var
- `timezone`: Her ikisinde var
- `created_at` / `updated_at`: Her ikisinde var

### Karar: **İki Profil Birleştirilmeyecek**

**Gerekçe**:
1. `memory/profile.py::UserProfile` → **statik bilgiler** (isim, dil, iletişim tarzı, öğrenilen gerçekler)
2. `learning/profile.py::UserProfile` → **dinamik davranış** (app affinity, komut dizileri, RL exploration)
3. İki farklı konsepti tek class'a sıkıştırmak SRP ihlali olur

**Eylem Planı**:
- `learning/profile.py::UserProfile` → `BehavioralProfile` olarak rename edilecek (Issue #873'te)
- `memory/profile.py::UserProfile` canonical kalacak
- Örtüşen alanlar (`language`, `timezone`) → `UserProfile`'dan okunacak, `BehavioralProfile` bunları kaldıracak

---

## 4. Bileşen Bağlantı Kararları

### 4.1 Bağlanacak Bileşenler (Öncelikli)

| Bileşen | Wire Noktası | Nasıl | Öncelik | Issue |
|---|---|---|---|---|
| `memory/context.py::MemoryContextBuilder` | `orchestrator_loop.py` — session context build | `build_session_context()` içinde `MemoryContextBuilder.build()` çağrılacak | P1 | #873 |
| `learning/preference_integration.py::PreferenceIntegration` | `orchestrator_loop.py` — after turn | `process_turn()` sonunda `prefs.record_interaction()` çağrılacak | P1 | #874 |
| `memory/profile.py::UserProfile` | `prompt_engineering.py` — system prompt | Kullanıcı tercihlerini prompt'a injection | P2 | #875 |
| `memory/store.py::MemoryStore` | `orchestrator_loop.py` — init | `memory_lite` yanında long-term memory init | P2 | #876 |

### 4.2 Test-Only Kalacak Bileşenler (Şimdilik)

| Bileşen | Satır | Neden |
|---|---|---|
| `memory/personality.py` | 723 | Jarvis/Friday/Alfred presetleri — ileri aşama |
| `learning/bandit.py` | 425 | Epsilon-greedy bandit — ileri aşama |
| `learning/adaptive.py` | 491 | Adaptive response — ileri aşama |
| `learning/temporal.py` | 456 | Temporal patterns — ileri aşama |
| `memory/ranking.py` | 270 | BM25 ranking — MemoryStore aktif olduğunda otomatik gelecek |
| `memory/retrieval.py` | 231 | Multi-store retrieval — MemoryStore aktif olduğunda otomatik gelecek |

### 4.3 Utility/Altyapı (Hazır, Wire Beklemiyor)

| Bileşen | Satır | Durumu |
|---|---|---|
| `memory/safety.py` | 77 | ✅ Hazır (PIIFilter lazy import) |
| `memory/sensitivity.py` | 127 | ✅ Hazır (store.py tarafından kullanılıyor) |
| `memory/write_policy.py` | 327 | ✅ Hazır (snippet_manager kullanıyor) |
| `memory/write_decision.py` | 261 | ✅ Hazır (write_policy kullanıyor) |
| `memory/migrations.py` | 128 | ✅ Hazır (store.py tarafından kullanılıyor) |

---

## 5. Orchestrator Wire Noktaları

### 5.1 `orchestrator_loop.py` — Mevcut Memory Touchpoints

```python
# Init (satır ~380):
self.memory = CompactSummary(max_turns=...)  # ← memory_lite

# Session context (satır ~610):
session_context = state.session_context  # ← memory_lite.to_prompt_block()

# Dialog summary (satır ~665):
dialog_summary = self.memory.to_prompt_block()  # ← memory_lite

# Post-turn update (satır ~830):
self.memory.update(user_input, assistant_reply)  # ← memory_lite
```

### 5.2 Önerilen Wire Noktaları

```python
# Init'e eklenecek:
self.memory_context = MemoryContextBuilder(user_profile, personality)
self.preference_integration = PreferenceIntegration(user_id="default")

# Session context build'e eklenecek:
memory_context = self.memory_context.build(user_input, state)
session_context["personalization"] = memory_context

# Post-turn'e eklenecek:
self.preference_integration.record_interaction(
    user_input=user_input,
    tool_plan=output.tool_plan,
    success=any(r.get("success") for r in tool_results),
)
```

### 5.3 `finalization_pipeline.py` — Wire Noktaları

```python
# _build_prompt_via_builder (satır ~243):
# USER_PREFERENCES bloğu eklenecek:
if user_profile:
    blocks.append(f"USER_PREFERENCES: {user_profile.to_prompt_block()}")

# session_context fallback (satır ~340):
# Personalization context injection:
if memory_context:
    session_context["memory_snippets"] = memory_context.relevant_memories
```

---

## 6. Dead Code Raporu

### 🔴 Production'da Hiç Kullanılmayan (30 dosya)

**memory/** — 21 dosya, 7923 satır:
- `context.py` (523L), `learning.py` (735L), `personality.py` (723L)
- `preferences.py` (546L), `profile.py` (664L), `store.py` (915L)
- `types.py` (528L), `snippet_manager.py` (340L), `snippet_store.py` (465L)
- `snippet.py` (227L), `retrieval.py` (231L), `ranking.py` (270L)
- `persistent.py` (475L), `prompt.py` (61L), `models.py` (166L)
- `migrations.py` (128L), `sensitivity.py` (127L), `safety.py` (77L)
- `write_decision.py` (261L), `write_policy.py` (327L)
- `__init__.py` (134L)

**learning/** — 9 dosya, 3620 satır:
- `adaptive.py` (491L), `bandit.py` (425L), `behavioral.py` (452L)
- `preference_integration.py` (271L), `preferences.py` (478L)
- `profile.py` (457L), `storage.py` (507L), `temporal.py` (456L)
- `__init__.py` (83L)

### 🟢 Test Coverage
Tüm dosyaların test coverage'ı mevcut (`tests/` altında 18+ test dosyası).

---

## 7. Sonraki Adımlar (Roadmap)

| Issue | Başlık | Bağımlılık | Satır Etkisi |
|---|---|---|---|
| **#872** (bu issue) | Integration Audit + docs | Yok | Doküman + reverse dep fix |
| **#873** | MemoryContextBuilder wire | #872 | ~100-150L |
| **#874** | PreferenceIntegration wire | #872 | ~80-120L |
| **#875** | UserProfile prompt injection | #873 | ~60-80L |
| **#876** | MemoryStore long-term init | #873, #874 | ~100-150L |

### Kademeli Aktivasyon Stratejisi
```
Phase 1 (#872): Audit + ters bağımlılık fix ← ŞİMDİ
Phase 2 (#873): MemoryContextBuilder → orchestrator
Phase 3 (#874): PreferenceIntegration → orchestrator  
Phase 4 (#875): UserProfile → prompt_engineering
Phase 5 (#876): MemoryStore → orchestrator init
```

---

## 8. Mimari Not

### Neden memory_lite Tek Başına Yeterli Değil?

`memory_lite.CompactSummary` sadece **son N tur'un rolling özetini** tutar:
- Uzun vadeli tercih öğrenme yok
- Kullanıcı profili yok
- Kişilik/iletişim tarzı adaptasyonu yok
- Episodik bellek (geçmiş tool çağrıları) yok
- Patern çıkarma yok

`memory/` + `learning/` bu boşlukları dolduracak şekilde tasarlanmış ama **hiçbiri bağlanmamış**.

### Aktif vs Planlanan Memory Stack

```
ŞİMDİ:                          HEDEF:
┌──────────────┐                ┌──────────────────────────┐
│ CompactSummary│                │ CompactSummary (kısa)    │
│ (son N tur)   │                │ + MemoryStore (uzun)     │
└──────────────┘                │ + UserProfile (profil)   │
                                │ + PatternExtractor       │
                                │ + PreferenceIntegration  │
                                │ + MemoryContextBuilder   │
                                └──────────────────────────┘
```
