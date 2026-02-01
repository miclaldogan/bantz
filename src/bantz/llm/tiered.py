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


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "y", "on", "enable", "enabled"}


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


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

    # Multi-step / planning cues
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

    if _contains_any(
        t,
        [
            "mail",
            "e-posta",
            "email",
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
            "özetle",
            "özet çıkar",
            "uzun özet",
            "haber",
            "araştır",
            "kaynak",
            "blog",
            "linkedin",
            "cv",
            "cover letter",
            "pdf",
            "doküman",
            "döküman",
            "yönerge",
            "rubrik",
            "ödev",
            "classroom",
        ],
    ):
        score += 4

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
) -> TierDecision:
    """Decide whether to escalate to the quality model.

    Behavior is env-configurable:
    - BANTZ_TIERED_MODE=1 enables auto decisions (otherwise always fast unless forced)
    - BANTZ_LLM_TIER=fast|quality|auto forces tier
    """
    debug = _env_flag("BANTZ_TIERED_DEBUG", default=False)
    metrics = _env_flag("BANTZ_TIERED_METRICS", default=False) or _env_flag(
        "BANTZ_LLM_METRICS", default=False
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

    forced = str(os.getenv("BANTZ_LLM_TIER", "")).strip().lower()
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

    if not _env_flag("BANTZ_TIERED_MODE", default=False):
        # Tiering disabled: default to fast.
        d = TierDecision(False, "tiering_disabled", 0, 0, 0)
        if debug:
            logger.info("[tiered] disabled -> fast")
        emit(d)
        return d

    complexity = score_complexity(text)
    writing = score_writing_need(text)
    risk = score_risk(text, tool_names=tool_names, requires_confirmation=requires_confirmation)

    min_complexity = _env_int("BANTZ_TIERED_MIN_COMPLEXITY", 4)
    min_writing = _env_int("BANTZ_TIERED_MIN_WRITING", 4)

    # Extra force keywords (comma-separated)
    force_kw_raw = str(os.getenv("BANTZ_TIERED_FORCE_QUALITY_KEYWORDS", "")).strip()
    if force_kw_raw:
        kws = [x.strip() for x in force_kw_raw.split(",") if x.strip()]
        if kws and _contains_any(text, kws):
            d = TierDecision(True, "forced_by_keyword", complexity, writing, risk)
            if debug:
                logger.info(
                    "[tiered] quality (%s) c=%s w=%s r=%s",
                    d.reason,
                    d.complexity,
                    d.writing,
                    d.risk,
                )
            emit(d)
            return d

    if complexity >= min_complexity or writing >= min_writing:
        d = TierDecision(True, "auto_escalate", complexity, writing, risk)
        if debug:
            logger.info(
                "[tiered] quality (%s) c=%s w=%s r=%s",
                d.reason,
                d.complexity,
                d.writing,
                d.risk,
            )
        emit(d)
        return d

    # Risky actions: keep execution control on fast, but allow quality drafts elsewhere.
    if risk >= 4 and writing >= 2:
        d = TierDecision(True, "risky_draft", complexity, writing, risk)
        if debug:
            logger.info(
                "[tiered] quality (%s) c=%s w=%s r=%s",
                d.reason,
                d.complexity,
                d.writing,
                d.risk,
            )
        emit(d)
        return d

    d = TierDecision(False, "fast_ok", complexity, writing, risk)
    if debug:
        logger.info(
            "[tiered] fast (%s) c=%s w=%s r=%s",
            d.reason,
            d.complexity,
            d.writing,
            d.risk,
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
