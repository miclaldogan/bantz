# _legacy

Bu klasör, artık aktif olarak kullanılmayan dosyaları içerir.
Silmeden önce referans için burada tutuluyorlar.

## İçerik

### `scripts/` — Eski & Deneysel Script'ler

| Dosya | Neden legacy? |
|:------|:-------------|
| `jarvis.sh` | Eski "Jarvis" marka adıyla başlatma script'i, yerini `python3 -m bantz` aldı |
| `terminal_jarvis.py` | vLLM'e dayanan eski terminal prototipi |
| `start_dual.sh` | Ollama + vLLM dual-server başlatıcı, vLLM devre dışı |
| `bench_*.py` | LLM kıyaslama araçları, anlık kullanım için değil |
| `demo_*.py` | Demo scriptleri, gerçek production akışının dışında |
| `vllm_*.py/sh` | vLLM backend araçları, Ollama-only moda geçildi |
| `tune_vllm.py` | vLLM fine-tuning, kullanım dışı |
| `trace_viewer.py` | Trace debug aracı |
| `replay_*.py` | Router replay tool'ları |
| `validate_hybrid_quality.*` | Hybrid kalite doğrulama |
| `generate_*.py` | Rapor üretici scriptler |
| `latency_report.py` | Gecikme raporu |
| `health_check_vllm.py` | vLLM sağlık kontrolü |

### `llm/` — vLLM Backend Modülleri

| Dosya | Neden legacy? |
|:------|:-------------|
| `vllm_openai_client.py` | vLLM OpenAI-compat client, Ollama'ya geçildi |
| `vllm_autotune.py` | vLLM otomatik parametre ayarı |
| `vllm_watchdog.py` / `vllm_watchdog_v0.py` | vLLM process watchdog |

### `vllm/` — vLLM Başlatma Script'leri

Ollama-only moda geçildiğinden bu script'ler artık kullanılmıyor:
`start_3b.sh`, `start_7b.sh`, `start_dual.sh`, `stop.sh`, `switch_model.sh`, vb.

### `docker/vllm/` — vLLM Docker Config

`docker-compose.yml` ile vLLM container'ı başlatmak için kullanılıyordu.
Şu an Ollama local çalıştırma ile değiştirildi.

---

## Geri Alma

Herhangi bir dosyayı geri almak için:

```bash
mv _legacy/scripts/bench_3b_models.py scripts/
```

> Bu dosyalar zorunda kalınmadıkça silinmemeli.
> Gelecekte bir referans veya vLLM dönüşü ihtimaline karşı korunuyor.
