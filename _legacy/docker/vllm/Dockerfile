# syntax=docker/dockerfile:1

# Multi-stage to keep runtime smaller.
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04 AS builder

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
     python3 python3-venv python3-pip \
     ca-certificates git \
  && rm -rf /var/lib/apt/lists/*

# Create a venv so we can copy it into the final image.
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# vLLM pinned per Issue #190 acceptance criteria.
RUN pip install --no-cache-dir -U pip \
  && pip install --no-cache-dir "vllm==0.6.0" \
  && pip install --no-cache-dir "uvicorn[standard]" "fastapi" "pydantic" \
  && pip install --no-cache-dir "requests"


FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04 AS runtime

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
     python3 \
     ca-certificates \
     curl \
  && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Hugging Face cache location (mount as volume in compose).
ENV HF_HOME=/data/hf
ENV TRANSFORMERS_CACHE=/data/hf

# Default to OpenAI-compatible server.
ENTRYPOINT ["python3", "-m", "vllm.entrypoints.openai.api_server"]
