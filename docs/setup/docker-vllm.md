# Docker vLLM (GPU)

Issue #190 adds a minimal Docker setup to run vLLM (OpenAI-compatible server) with NVIDIA GPU passthrough.

## Prereqs

- Docker Engine
- Docker Compose plugin (`docker compose`)
- NVIDIA Container Toolkit

## Start 3B + 7B

From repo root:

```bash
docker compose up -d
```

Health checks:

```bash
curl http://127.0.0.1:8001/v1/models
curl http://127.0.0.1:8002/v1/models
```

## Config

Override models via env vars:

```bash
export BANTZ_VLLM_3B_MODEL="Qwen/Qwen2.5-3B-Instruct-AWQ"
export BANTZ_VLLM_7B_MODEL="Qwen/Qwen2.5-7B-Instruct-AWQ"
```

## Notes

- Hugging Face cache is persisted as a named volume (`vllm_hf_cache`).
- Logs are mounted to `./artifacts/logs`.
- The image is built from `docker/vllm/Dockerfile` (multi-stage) and pins `vllm==0.6.0`.
