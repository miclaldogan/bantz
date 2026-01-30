# vLLM PoC Setup Guide

Issue: #132

## Amaç
GPU üzerinde vLLM server'ı çalıştır (OpenAI API uyumlu endpoint).

## Kurulum

### 1. vLLM kurulumu

```bash
# venv oluştur (önerilen)
python3 -m venv venv-vllm
source venv-vllm/bin/activate

# vLLM kur
pip install vllm

# Alternatif: requirements'a ekle
echo "vllm>=0.6.0" >> requirements-llm.txt
pip install -r requirements-llm.txt
```

### 2. GPU Doğrulama

```bash
nvidia-smi
# CUDA Version: 12.2+
# GPU Memory: 6GB+ (Qwen2.5-3B için yeterli)
```

### 3. Model İndir (İlk çalıştırmada otomatik)

```bash
# Hugging Face'den otomatik indirilir
# Model: Qwen/Qwen2.5-3B-Instruct (~6GB)
```

## Kullanım

### Terminal 1: vLLM Server Başlat

```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-3B-Instruct \
    --port 8000 \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.9
```

**Parametreler:**
- `--model`: HuggingFace model ID
- `--port`: HTTP port (default: 8000)
- `--max-model-len`: Max context length
- `--gpu-memory-utilization`: VRAM kullanım oranı (0.9 = %90)

### Terminal 2: Test Script

```bash
# Bantz workspace'de
python scripts/vllm_poc.py
```

## Test Senaryoları

### Test 1: Router JSON Output
- Router prompt ile JSON üretimi
- Latency ölçümü (hedef: <500ms)
- JSON validity check

### Test 2: Determinism
- Aynı prompt 10 kez
- temperature=0, seed=42
- Tüm yanıtlar identical olmalı

### Test 3: VRAM Usage
- `nvidia-smi` ile VRAM check
- Qwen2.5-3B: ~3-4GB kullanmalı

## Beklenen Sonuçlar

✅ **Success Criteria:**
- `/v1/chat/completions` endpoint yanıt veriyor
- Latency < 1000ms (3B model, RTX 4050)
- Deterministic output (temp=0, seed=42)
- JSON parsing başarılı
- VRAM kullanımı stabil

## Curl ile Manuel Test

```bash
# Model listesi
curl http://localhost:8000/v1/models

# Chat completion
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-3B-Instruct",
    "messages": [{"role": "user", "content": "Merhaba"}],
    "temperature": 0,
    "max_tokens": 100
  }'
```

## Sorun Giderme

### Problem: `nvidia-smi` bulunamadı
**Çözüm:** NVIDIA driver kurulumu gerekli

### Problem: CUDA version uyumsuz
**Çözüm:** vLLM CUDA 12.x gerektirir

### Problem: Model indirilmiyor
**Çözüm:** Hugging Face token gerekebilir
```bash
huggingface-cli login
```

### Problem: Out of memory
**Çözüm:** 
- Daha küçük model dene: `Qwen/Qwen2.5-1.5B-Instruct`
- `--gpu-memory-utilization 0.7` ile azalt

## Sonraki Adımlar

Bu PoC başarılı olduktan sonra:
1. ✅ Issue #132 tamamlandı
2. ➡️ Issue #133: Backend Abstraction
3. ➡️ Issue #134: Router Integration

## Model Alternatifleri

| Model | Size | VRAM | Use Case |
|-------|------|------|----------|
| Qwen2.5-1.5B-Instruct | 1.5B | ~2GB | Router (hızlı) |
| Qwen2.5-3B-Instruct | 3B | ~4GB | Router+Chat |
| Qwen2.5-7B-Instruct | 7B | ~8GB | Chat (kaliteli) |
| Llama-3.2-3B-Instruct | 3B | ~4GB | Alternatif |

## Performans Hedefleri

| Metric | Target | Measured |
|--------|--------|----------|
| First token latency | <500ms | TBD |
| Throughput | >50 tokens/s | TBD |
| VRAM usage | <5GB | TBD |
| Determinism | 100% | TBD |

## Notlar

- vLLM OpenAI API'sine tamamen uyumlu
- Streaming destekli (gelecekte kullanılabilir)
- Multi-GPU desteği var (şu an tek GPU)
- PagedAttention ile memory efficient
