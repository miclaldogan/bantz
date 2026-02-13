#!/usr/bin/env python3
"""
vLLM Health Check - Validate server status and performance
Usage: python scripts/health_check_vllm.py [--port PORT]
"""
import argparse
import sys
import time
from typing import Optional

import requests


def check_server_health(port: int = 8001, timeout: int = 5) -> dict:
    """Check vLLM server health and return status metrics."""
    result = {
        "port": port,
        "status": "unknown",
        "model_id": None,
        "response_time_ms": None,
        "error": None
    }
    
    url = f"http://localhost:{port}/v1/models"
    
    try:
        start = time.time()
        response = requests.get(url, timeout=timeout)
        elapsed_ms = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            if data.get("data") and len(data["data"]) > 0:
                result["status"] = "healthy"
                result["model_id"] = data["data"][0]["id"]
                result["response_time_ms"] = round(elapsed_ms, 1)
            else:
                result["status"] = "error"
                result["error"] = "No models found in response"
        else:
            result["status"] = "error"
            result["error"] = f"HTTP {response.status_code}"
            
    except requests.exceptions.ConnectionError:
        result["status"] = "offline"
        result["error"] = "Connection refused (server not running)"
    except requests.exceptions.Timeout:
        result["status"] = "timeout"
        result["error"] = f"Request timeout ({timeout}s)"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    
    return result


def print_health_report(result: dict, verbose: bool = False) -> bool:
    """Print formatted health report. Returns True if healthy."""
    port = result["port"]
    status = result["status"]
    
    # Status icon
    icons = {
        "healthy": "✅",
        "offline": "❌",
        "timeout": "⏱️",
        "error": "⚠️",
        "unknown": "❓"
    }
    icon = icons.get(status, "❓")
    
    print(f"\n{icon} vLLM Server Health Check (port {port})")
    print("=" * 50)
    
    if status == "healthy":
        print(f"Status:        {status.upper()}")
        print(f"Model ID:      {result['model_id']}")
        print(f"Response Time: {result['response_time_ms']} ms")
        print(f"Endpoint:      http://localhost:{port}/v1/completions")
        return True
    else:
        print(f"Status:  {status.upper()}")
        if result["error"]:
            print(f"Error:   {result['error']}")
        
        if status == "offline":
            print(f"\n💡 Tip: Start the server with:")
            print(f"   ./scripts/vllm/start_3b.sh   # For 3B model on port 8001")
            print(f"   ./scripts/vllm/start_7b.sh   # For 7B model on port 8002")
        
        return False


def main():
    parser = argparse.ArgumentParser(description="vLLM server health check")
    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Server port to check (default: 8001)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="Request timeout in seconds (default: 5)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Check both ports 8001 and 8002"
    )
    
    args = parser.parse_args()
    
    ports = [8001, 8002] if args.all else [args.port]
    all_healthy = True
    
    for port in ports:
        result = check_server_health(port, timeout=args.timeout)
        is_healthy = print_health_report(result, verbose=args.verbose)
        all_healthy = all_healthy and is_healthy
        
        if len(ports) > 1:
            print()  # Spacing between multi-port reports
    
    sys.exit(0 if all_healthy else 1)


if __name__ == "__main__":
    main()
