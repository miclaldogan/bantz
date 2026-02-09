from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Iterable, Optional

from bantz.llm.base import LLMClientProtocol

from . import create_fast_client, create_quality_client


logger = logging.getLogger(__name__)
metrics_logger = logging.getLogger("bantz.llm.metrics")


@dataclass(frozen=True)
class TierDecision:
    use_quality: bool
    reason: str
    complexity: int
    writing: int
    risk: int


@dataclass(frozen=True)
class TierQoS:
    """QoS defaults to keep fast paths snappy and avoid long blocks.

    These are *call-level* defaults. Underlying client timeouts still apply.
    """

    timeout_s: float
    max_tokens: int


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "y", "on", "enable", "enabled"}

def _env_raw(name: str, legacy: str | None = None) -> str:
    raw = str(os.getenv(name, "")).strip()
    if raw:
        return raw
    if legacy:
        return str(os.getenv(legacy, "")).strip()
    return ""

def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def get_qos(
    *,
    use_quality: bool,
    profile: str = "default",
) -> TierQoS:
    """Return tier-specific QoS settings.

    Env override precedence:
      1) Profile-specific: BANTZ_QOS_<PROFILE>_<FAST|QUALITY>_{TIMEOUT_S|MAX_TOKENS}
      2) Generic:          BANTZ_QOS_<FAST|QUALITY>_{TIMEOUT_S|MAX_TOKENS}
      3) Built-in defaults
    """

    tier = "QUALITY" if use_quality else "FAST"
    profile_key = (profile or "default").strip().upper().replace("-", "_")

    default_timeout = 90.0 if use_quality else 20.0
    default_max_tokens = 512 if use_quality else 256

    timeout_s = _env_float(
        f"BANTZ_QOS_{profile_key}_{tier}_TIMEOUT_S",
        _env_float(f"BANTZ_QOS_{tier}_TIMEOUT_S", default_timeout),
    )
    max_tokens = _env_int(
        f"BANTZ_QOS_{profile_key}_{tier}_MAX_TOKENS",
        _env_int(f"BANTZ_QOS_{tier}_MAX_TOKENS", default_max_tokens),
    )

    # Guardrails
    timeout_s = max(0.5, float(timeout_s))
    max_tokens = max(1, int(max_tokens))

    return TierQoS(timeout_s=timeout_s, max_tokens=max_tokens)


def _contains_any(text: str, phrases: Iterable[str]) -> bool:
    t = (text or "").lower()
    for p in phrases:
        p = (p or "").strip().lower()
        if not p:
            continue
        if p in t:
            return True
    return False


def score_complexity(text: str) -> int:
    """Heuristic complexity score (0-5)."""
    t = (text or "").strip().lower()
    if not t:
        return 0

    score = 0

    # Length-based: long prompts tend to require more planning.
    n = len(t)
    if n >= 450:
        score += 3
    elif n >= 220:
        score += 2
    elif n >= 120:
        score += 1

    # Issue #573: merged into a single keyword group to prevent double-counting.
    # "roadmap", "adım adım" etc. were in two lists, each adding +2 → false escalation.
    if _contains_any(
        t,
        [
            "adım adım",
            "roadmap",
            "plan",
            "planla",
            "gün gün",
            "haftalık",
            "strateji",
            "kıyasla",
            "tradeoff",
            "alternatif",
            "detaylı",
            "derinlemesine",
            "analiz",
            "gerekçelendir",
        ],
    ):
        score += 2

    # Strong signal BONUS: explicit N-step or weekly plan (only if not already matched above)
    strong_signals = [
        "3 adım", "4 adım", "5 adım",
        "haftalık plan",
    ]
    if _contains_any(t, strong_signals):
        score += 1  # bonus, not a full +2

    # Explicit "long" request
    if _contains_any(t, ["uzun", "kapsamlı", "çok detay", "tam rapor", "tümünü"]):
        score += 1

    return max(0, min(5, score))


def score_writing_need(text: str) -> int:
    """Heuristic writing/quality score (0-5)."""
    t = (text or "").strip().lower()
    if not t:
        return 0

    score = 0

    # Issue #573: Split write-intent keywords (high score) from read-intent.
    # "mail listele" is read-only → shouldn't escalate to quality.
    write_keywords = [
        "hocaya",
        "hoca",
        "okula",
        "öğretmen",
        "resmi",
        "yarı resmi",
        "taslak",
        "dilekçe",
        "metin",
        "yaz",
        "düzenle",
        "revize",
        "ton",
        "hitap",
        "kibar",
        "nazik",
        "ikna",
        "uzun özet",
        "blog",
        "linkedin",
        "cv",
        "cover letter",
        "doküman",
        "döküman",
        "yönerge",
        "rubrik",
        "ödev",
    ]

    # Read/info keywords: need quality only in combination with write verbs.
    read_keywords = [
        "mail",
        "e-posta",
        "email",
        "özetle",
        "özet çıkar",
        "haber",
        "araştır",
        "kaynak",
        "pdf",
        "classroom",
    ]

    # Read-only dampeners: if these appear alongside read_keywords, it's read intent.
    read_only_verbs = [
        "listele",
        "göster",
        "oku",
        "kontrol",
        "bak",
        "kaç tane",
        "sayısı",
        "var mı",
        "unread",
        "okunmamış",
    ]

    if _contains_any(t, write_keywords):
        score += 4
    elif _contains_any(t, read_keywords):
        # Only escalate if there's a write signal, not just read/list.
        if _contains_any(t, read_only_verbs):
            score += 1  # reading mail/news is fast-tier
        else:
            score += 3  # ambiguous context, moderate escalation

    # If the user is asking for a short ack/info, keep it low.
    if _contains_any(t, ["kısaca", "tek cümle", "özetle ama kısa", "tl;dr"]):
        score = max(0, score - 2)

    return max(0, min(5, score))


def score_risk(
    text: str,
    *,
    tool_names: Optional[Iterable[str]] = None,
    requires_confirmation: bool = False,
) -> int:
    """Heuristic risk score (0-5).

    Note: Real enforcement is handled by the policy/confirmation firewall.
    This score is only for escalation decisions (e.g., draft text on 7B).
    """
    if requires_confirmation:
        return 4

    t = (text or "").strip().lower()
    risk = 0

    if tool_names:
        lowered = {str(x or "").strip().lower() for x in tool_names}
        if any("delete" in x or "sil" in x for x in lowered):
            risk = max(risk, 5)
        if any("update" in x or "modify" in x for x in lowered):
            risk = max(risk, 4)
        if any("create_event" in x or "create" in x for x in lowered):
            risk = max(risk, 3)

    if _contains_any(t, ["gönder", "sil", "paylaş", "iptal et", "sıfırla", "delete"]):
        risk = max(risk, 3)

    return max(0, min(5, risk))


def decide_tier(
    text: str,
    *,
    tool_names: Optional[Iterable[str]] = None,
    requires_confirmation: bool = False,
    route: str = "unknown",
) -> TierDecision:
    """Decide whether to escalate to the quality model.

    Behavior is env-configurable:
    - BANTZ_TIER_MODE=1 enables auto decisions (otherwise always fast unless forced)
      (legacy: BANTZ_TIERED_MODE)
    - BANTZ_TIER_FORCE=fast|quality|auto forces tier
      (legacy: BANTZ_LLM_TIER)
    """
    debug = _env_flag("BANTZ_TIER_DEBUG", default=False) or _env_flag(
        "BANTZ_TIERED_DEBUG", default=False
    )
    metrics = (
        _env_flag("BANTZ_TIER_METRICS", default=False)
        or _env_flag("BANTZ_TIERED_METRICS", default=False)
        or _env_flag("BANTZ_LLM_METRICS", default=False)
    )

    def emit(d: TierDecision) -> None:
        if not metrics:
            return
        tier = "quality" if d.use_quality else "fast"
        metrics_logger.info(
            "tier_decision tier=%s reason=%s complexity=%s writing=%s risk=%s",
            tier,
            d.reason,
            d.complexity,
            d.writing,
            d.risk,
        )

    forced = _env_raw("BANTZ_TIER_FORCE", "BANTZ_LLM_TIER").strip().lower()
    if forced in {"fast", "3b", "small"}:
        d = TierDecision(False, "forced_fast", 0, 0, 0)
        if debug:
            logger.info("[tiered] forced=fast")
        emit(d)
        return d
    if forced in {"quality", "7b", "large"}:
        d = TierDecision(True, "forced_quality", 5, 5, 0)
        if debug:
            logger.info("[tiered] forced=quality")
        emit(d)
        return d

    if not (
        _env_flag("BANTZ_TIER_MODE", default=False)
        or _env_flag("BANTZ_TIERED_MODE", default=False)
    ):
        # Tiering disabled: default to fast.
        d = TierDecision(False, "tiering_disabled", 0, 0, 0)
        if debug:
            logger.info("[tiered] disabled -> fast")
        emit(d)
        return d

    # Canonical tiering engine: quality_gating (Issue #598)
    from bantz.brain.quality_gating import evaluate_quality_gating, GatingDecision

    result = evaluate_quality_gating(
        text,
        tool_names=list(tool_names) if tool_names is not None else None,
        requires_confirmation=requires_confirmation,
        route=route,
    )

    use_quality = result.decision == GatingDecision.USE_QUALITY
    d = TierDecision(
        use_quality,
        str(result.reason),
        int(result.score.complexity),
        int(result.score.writing),
        int(result.score.risk),
    )
    emit(d)
    return d


def get_client_for_text(
    text: str,
    *,
    fast_timeout: float = 120.0,
    quality_timeout: float = 240.0,
) -> tuple[LLMClientProtocol, TierDecision]:
    """Return (client, decision) for a given user text."""
    decision = decide_tier(text)
    if decision.use_quality:
        return create_quality_client(timeout=quality_timeout), decision
    return create_fast_client(timeout=fast_timeout), decision


def get_client_and_qos_for_text(
    text: str,
    *,
    profile: str = "default",
    fast_client_timeout: float = 120.0,
    quality_client_timeout: float = 240.0,
) -> tuple[LLMClientProtocol, TierDecision, TierQoS]:
    """Return (client, decision, qos) for a given user text.

    - `qos` is intended for per-call defaults (e.g. chat max_tokens).
    - Client timeouts are still controlled via `*_client_timeout`.
    """

    decision = decide_tier(text)
    qos = get_qos(use_quality=bool(decision.use_quality), profile=profile)

    if decision.use_quality:
        return create_quality_client(timeout=quality_client_timeout), decision, qos
    return create_fast_client(timeout=fast_client_timeout), decision, qos
