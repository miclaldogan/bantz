from __future__ import annotations

import os
import time
import logging

from bantz.llm import create_fast_client, create_quality_client
from bantz.llm.base import LLMMessage
from bantz.llm.tiered import decide_tier, get_qos


def _env(name: str, default: str = "") -> str:
    v = str(os.environ.get(name, "")).strip()
    return v if v else default


def _print_env_banner() -> None:
    keys = [
        "BANTZ_VLLM_URL",
        "BANTZ_VLLM_MODEL",
        "BANTZ_TIERED_MODE",
        "BANTZ_LLM_TIER",
        "QUALITY_PROVIDER",
        "BANTZ_QUALITY_PROVIDER",
        "QUALITY_MODEL",
        "BANTZ_QUALITY_MODEL",
        "BANTZ_GEMINI_MODEL",
        "BANTZ_CLOUD_MODE",
        "BANTZ_LOCAL_ONLY",
        "BANTZ_CLOUD_REDACT",
        "BANTZ_CLOUD_MAX_CHARS",
        "BANTZ_LLM_METRICS",
        "BANTZ_TIERED_METRICS",
    ]
    print("\n=== env (selected) ===")
    for k in keys:
        v = os.environ.get(k)
        if v is None:
            continue
        if "KEY" in k or "TOKEN" in k:
            print(f"{k}=***")
        else:
            print(f"{k}={v}")


def _run_case(name: str, text: str) -> None:
    print(f"\n--- {name} ---")
    d = decide_tier(text)
    print(f"tier_decision use_quality={d.use_quality} reason={d.reason} c={d.complexity} w={d.writing} r={d.risk}")

    qos = get_qos(use_quality=bool(d.use_quality), profile="validate")
    print(f"qos timeout_s={qos.timeout_s} max_tokens={qos.max_tokens}")

    # For routing validation we explicitly show which client would be used.
    if d.use_quality:
        llm = create_quality_client(timeout=float(qos.timeout_s))
    else:
        llm = create_fast_client(timeout=float(qos.timeout_s))

    extra = ""
    if getattr(llm, "backend_name", "") == "vllm" and hasattr(llm, "base_url"):
        extra = f" base_url={getattr(llm, 'base_url', '')}"
    print(f"client backend={llm.backend_name} model={llm.model_name}{extra}")

    t0 = time.perf_counter()
    out = llm.chat(
        [LLMMessage(role="user", content=text)],
        temperature=0.2,
        max_tokens=int(qos.max_tokens),
    )
    dt_ms = int((time.perf_counter() - t0) * 1000)

    print(f"latency_ms={dt_ms}")
    print("reply:")
    print(out)


def main() -> int:
    # Ensure INFO logs show so metrics_logger lines are visible.
    logging.basicConfig(level=logging.INFO)

    # Recommended defaults for the demo run.
    os.environ.setdefault("BANTZ_TIERED_MODE", "1")
    os.environ.setdefault("BANTZ_LLM_TIER", "auto")
    os.environ.setdefault("BANTZ_LLM_METRICS", "1")
    os.environ.setdefault("BANTZ_TIERED_METRICS", "1")

    _print_env_banner()

    _run_case("1) smalltalk (should be fast)", "hey bantz nasılsın")
    _run_case(
        "2) mail (should be quality)",
        "Hocaya kibar bir mail taslağı yaz: projeyi 1 gün geç teslim edeceğim, özür dileyip yeni teslim tarihini teklif et.\nİmza: İ. Doğan",
    )
    _run_case(
        "3) roadmap (should be quality)",
        "Bu hafta için 4 adımlı bir çalışma roadmap'i çıkar: veri toplama, temizlik, model, rapor. Gün gün planla.",
    )

    print("\n--- 4) cloud kapalıyken fallback (should be fast even if provider=gemini) ---")
    old_cloud = os.environ.get("BANTZ_CLOUD_MODE")
    old_local_only = os.environ.get("BANTZ_LOCAL_ONLY")
    os.environ["BANTZ_CLOUD_MODE"] = "local"
    os.environ["BANTZ_LOCAL_ONLY"] = "1"
    try:
        _run_case(
            "4) mail with cloud disabled",
            "Hocaya mail taslağı yaz: yarın derse gelemeyeceğim, kısa ve resmi olsun.",
        )
    finally:
        if old_cloud is None:
            os.environ.pop("BANTZ_CLOUD_MODE", None)
        else:
            os.environ["BANTZ_CLOUD_MODE"] = old_cloud
        if old_local_only is None:
            os.environ.pop("BANTZ_LOCAL_ONLY", None)
        else:
            os.environ["BANTZ_LOCAL_ONLY"] = old_local_only

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
