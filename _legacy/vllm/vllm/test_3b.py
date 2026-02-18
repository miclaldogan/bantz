#!/usr/bin/env python3
"""Test vLLM 3B startup - bypass multiprocessing issues"""
import os
import sys

# Force fork method (avoid spawn import issues)
import multiprocessing
multiprocessing.set_start_method('fork', force=True)

# Disable torchvision if not needed
os.environ['VLLM_USE_V1'] = '0'
os.environ['VLLM_WORKER_MULTIPROC_METHOD'] = 'fork'

# Now run vLLM
from vllm.entrypoints.openai import api_server

if __name__ == "__main__":
    sys.argv = [
        'api_server.py',
        '--model', 'Qwen/Qwen2.5-3B-Instruct-AWQ',
        '--quantization', 'awq',
        '--port', '8001',
        '--dtype', 'half',
        '--max-model-len', '1024',
        '--gpu-memory-utilization', '0.60'
    ]
    api_server.main()
