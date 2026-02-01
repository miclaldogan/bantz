# vLLM Setup (Bantz)

Bu repo **yalnızca vLLM** (OpenAI-compatible API) ile çalışır.

## Hızlı Başlangıç (Önerilen)

1) Python bağımlılıkları:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[llm]"
```

Not: Şu an bazı sistemlerde CUDA uyumluluğu nedeniyle **global Python** ile çalıştırmak daha stabil olabilir.
Bu durumda `.venv` zorunlu değil; önemli olan `python3 -c 'import vllm'` çalışması.

2) vLLM sunucusunu başlat:

- 3B (hız / router / tool seçim):

```bash
./scripts/vllm/start_3b.sh
```

- 7B (kalite / daha uzun cevaplar):

```bash
./scripts/vllm/start_7b.sh
```

### 3B + 7B aynı anda (tek GPU)

Tek GPU’da iki instance çalıştırmak istiyorsan:

```bash
./scripts/start_dual.sh
```

Alternatif (doğrudan):

```bash
./scripts/vllm/start_dual.sh
```

Bu scriptler “dual-friendly” KV/cache limitleriyle gelir (VRAM/KV-cache patlamasını azaltır).
Gerekirse env ile daha da kısabilirsin:

```bash
export BANTZ_VLLM_3B_GPU_UTIL=0.45
export BANTZ_VLLM_3B_MAX_MODEL_LEN=1024
export BANTZ_VLLM_7B_GPU_UTIL=0.55
export BANTZ_VLLM_7B_MAX_MODEL_LEN=1536
export BANTZ_VLLM_7B_CPU_OFFLOAD_GB=6
export BANTZ_VLLM_7B_SWAP_SPACE=6
```

3) Sunucu kontrol:

```bash
curl -s http://127.0.0.1:8001/v1/models
```

## Varsayılan Portlar

- 8001: 3B (hız)
- 8002: 7B (kalite)

Not: 6GB VRAM cihazlarda 3B ve 7B aynı anda çalışmayabilir.

## Yönetim Komutları

```bash
./scripts/vllm_status.sh
./scripts/vllm/test.sh 8001
./scripts/vllm/test.sh 8002
./scripts/vllm/stop.sh
```

## Sorun Giderme

- Port doluysa: `ss -ltnp | grep 8001` ve `pkill -f "vllm.entrypoints.openai.api_server"`
- CUDA/driver uyumsuzluğu: `nvidia-smi` hata veriyorsa reboot gerekebilir.

## Bantz tarafı (env)

Bantz, vLLM endpoint’ine şu env’lerle bağlanır:

```bash
export BANTZ_VLLM_URL="http://127.0.0.1:8001"
export BANTZ_VLLM_MODEL="Qwen/Qwen2.5-3B-Instruct-AWQ"
```

Kalite gereken işler (örn: sayfa özetleme) için 7B endpoint’i ayrı tanımlanabilir:

```bash
export BANTZ_VLLM_QUALITY_URL="http://127.0.0.1:8002"
export BANTZ_VLLM_QUALITY_MODEL="Qwen/Qwen2.5-7B-Instruct-AWQ"
```

İpucu: model id’yi makineden makineye farklı tutuyorsan `auto` kullanabilirsin:

```bash
export BANTZ_VLLM_MODEL=auto
export BANTZ_VLLM_QUALITY_MODEL=auto
```

## Tiered routing (3B → 7B eskalasyon)

Varsayılan davranış: Bantz çoğu yerde **3B (fast)** ile gider.
7B (quality) otomatik devreye girsin istiyorsan:

```bash
export BANTZ_TIERED_MODE=1
```

İsteğe göre zorlamak için:

```bash
export BANTZ_LLM_TIER=fast     # her zaman 3B
export BANTZ_LLM_TIER=quality  # her zaman 7B
export BANTZ_LLM_TIER=auto     # (varsayılan) heuristic
```

Heuristic eşikleri:

```bash
export BANTZ_TIERED_MIN_COMPLEXITY=4
export BANTZ_TIERED_MIN_WRITING=4
```

Kaliteye zorlayan keyword listesi (opsiyonel):

```bash
export BANTZ_TIERED_FORCE_QUALITY_KEYWORDS="mail,taslak,roadmap,detaylı"
```
