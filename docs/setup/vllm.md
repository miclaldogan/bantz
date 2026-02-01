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

2) vLLM sunucusunu başlat:

- 3B (hız / router / tool seçim):

```bash
./scripts/vllm/start_3b.sh
```

- 7B (kalite / daha uzun cevaplar):

```bash
./scripts/vllm/start_7b.sh
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
./scripts/vllm/status.sh
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
