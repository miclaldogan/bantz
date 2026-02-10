# SPDX-License-Identifier: MIT
"""
NLU Bridge - Integration between new NLU and existing router.

This module provides a bridge between the new hybrid NLU system and
the existing router infrastructure. It:

1. Provides drop-in replacement for parse_intent
2. Maintains backwards compatibility with Parsed format
3. Adds optional enhanced features (clarification, context)
4. Enables gradual migration

Usage:
    # Drop-in replacement
    from bantz.nlu.bridge import parse_intent_hybrid as parse_intent
    
    # Or use enhanced version
    from bantz.nlu.bridge import parse_with_context
"""

from __future__ import annotations

import os
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass

from bantz.router.nlu import Parsed, parse_intent as legacy_parse_intent
from bantz.nlu.types import IntentResult, NLUContext
from bantz.nlu.hybrid import HybridNLU, HybridConfig


# ============================================================================
# Global NLU Instance  (canonical singleton — Issue #651)
# ============================================================================

_nlu_instance: Optional[HybridNLU] = None

# Hybrid NLU varsayılan AÇIK.  Env-var ile kapatılabilir:
#   BANTZ_HYBRID_NLU=0  → legacy regex-only parse_intent
_use_hybrid: bool = os.getenv("BANTZ_HYBRID_NLU", "1") not in ("0", "false", "False", "no")


def get_nlu() -> HybridNLU:
    """Get the canonical global NLU instance.

    This is the **single** HybridNLU singleton for the entire process.
    ``hybrid.py:get_nlu()`` delegates here so that every call-site
    — regardless of which module it imports from — shares the same
    instance and therefore the same session context.
    """
    global _nlu_instance
    if _nlu_instance is None:
        config = HybridConfig(
            llm_enabled=True,
            clarification_enabled=True,
            slot_extraction_enabled=True,
        )
        _nlu_instance = HybridNLU(config=config)
    return _nlu_instance


def set_nlu(nlu: HybridNLU):
    """Set the global NLU instance."""
    global _nlu_instance
    _nlu_instance = nlu


def reset_nlu_instance():
    """Reset the global NLU singleton (for testing only)."""
    global _nlu_instance
    _nlu_instance = None


def enable_hybrid_nlu(enabled: bool = True):
    """Enable or disable hybrid NLU at runtime.

    The default is read once from ``BANTZ_HYBRID_NLU`` env-var (default
    ``"1"`` = enabled).  This function allows runtime overrides.
    """
    global _use_hybrid
    _use_hybrid = enabled


def is_hybrid_enabled() -> bool:
    """Check if hybrid NLU is enabled."""
    return _use_hybrid


# ============================================================================
# Bridge Functions
# ============================================================================


def parse_intent_hybrid(
    text: str,
    *,
    session_id: Optional[str] = None,
    context: Optional[NLUContext] = None,
    fallback_to_legacy: bool = True,
) -> Parsed:
    """Parse intent using hybrid NLU with legacy Parsed output.
    
    This is a drop-in replacement for parse_intent that uses the new
    hybrid NLU system internally.
    
    Args:
        text: User input text
        session_id: Optional session ID for context tracking
        context: Optional NLU context
        fallback_to_legacy: Fall back to legacy parser if hybrid fails
    
    Returns:
        Parsed object (legacy format)
    """
    try:
        nlu = get_nlu()
        result = nlu.parse(text, context=context, session_id=session_id)
        
        # Convert to legacy Parsed format
        return result.to_parsed()
        
    except Exception as e:
        if fallback_to_legacy:
            # Fall back to legacy parser
            return legacy_parse_intent(text)
        raise


def parse_with_context(
    text: str,
    *,
    session_id: Optional[str] = None,
    focused_app: Optional[str] = None,
    current_url: Optional[str] = None,
) -> Tuple[Parsed, IntentResult]:
    """Parse with context, returning both legacy and new formats.
    
    Useful during migration period when both formats are needed.
    
    Args:
        text: User input text
        session_id: Session ID
        focused_app: Currently focused application
        current_url: Current browser URL
    
    Returns:
        Tuple of (Parsed, IntentResult)
    """
    # Build context
    context = NLUContext(
        focused_app=focused_app,
        current_url=current_url,
        session_id=session_id,
    )
    
    nlu = get_nlu()
    result = nlu.parse(text, context=context, session_id=session_id)
    
    return result.to_parsed(), result


def parse_enhanced(
    text: str,
    *,
    session_id: Optional[str] = None,
    context: Optional[NLUContext] = None,
) -> IntentResult:
    """Parse with full IntentResult output.
    
    Use this for new code that wants all the enhanced features
    (clarification, alternatives, confidence, etc.)
    
    Args:
        text: User input text
        session_id: Session ID
        context: NLU context
    
    Returns:
        IntentResult
    """
    nlu = get_nlu()
    return nlu.parse(text, context=context, session_id=session_id)


# ============================================================================
# Adaptive Parser
# ============================================================================


def parse_intent_adaptive(text: str) -> Parsed:
    """Parse intent with adaptive strategy.
    
    Uses hybrid NLU if enabled, otherwise falls back to legacy.
    This is the recommended function for gradual migration.
    
    Args:
        text: User input text
    
    Returns:
        Parsed object
    """
    if _use_hybrid:
        return parse_intent_hybrid(text, fallback_to_legacy=True)
    else:
        return legacy_parse_intent(text)


# ============================================================================
# Clarification Support
# ============================================================================


@dataclass
class ParseResultWithClarification:
    """Parse result that may include clarification request."""
    
    parsed: Parsed
    intent_result: IntentResult
    needs_clarification: bool
    clarification_question: Optional[str] = None
    clarification_options: list = None
    
    def __post_init__(self):
        if self.clarification_options is None:
            self.clarification_options = []


def parse_with_clarification(
    text: str,
    session_id: str,
) -> ParseResultWithClarification:
    """Parse with clarification support.
    
    Returns a result that indicates whether clarification is needed
    and provides the clarification question if so.
    
    Args:
        text: User input text
        session_id: Session ID for tracking state
    
    Returns:
        ParseResultWithClarification
    """
    nlu = get_nlu()
    result = nlu.parse(text, session_id=session_id)
    
    needs_clarification = result.needs_clarification
    question = None
    options = []
    
    if result.clarification:
        question = result.clarification.question
        options = [
            {"intent": opt.intent, "description": opt.description}
            for opt in result.clarification.options
        ]
    
    return ParseResultWithClarification(
        parsed=result.to_parsed(),
        intent_result=result,
        needs_clarification=needs_clarification,
        clarification_question=question,
        clarification_options=options,
    )


def resolve_clarification(
    response: str,
    session_id: str,
) -> Optional[Parsed]:
    """Resolve a pending clarification.
    
    Args:
        response: User's response to clarification
        session_id: Session ID
    
    Returns:
        Parsed result if resolved, None otherwise
    """
    nlu = get_nlu()
    
    if nlu._clarification:
        resolved = nlu._clarification.resolve_from_response(response, session_id)
        if resolved:
            return resolved.to_parsed()
    
    return None


# ============================================================================
# Stats and Debugging
# ============================================================================


def get_nlu_stats() -> Dict[str, Any]:
    """Get NLU statistics.
    
    Returns:
        Dictionary of stats
    """
    nlu = get_nlu()
    stats = nlu.get_stats()
    
    if stats:
        return stats.to_dict()
    
    return {}


def reset_nlu_stats():
    """Reset NLU statistics."""
    nlu = get_nlu()
    nlu.reset_stats()


def get_nlu_context(session_id: str) -> Optional[Dict[str, Any]]:
    """Get NLU context for a session.
    
    Args:
        session_id: Session ID
    
    Returns:
        Context dictionary or None
    """
    nlu = get_nlu()
    context = nlu.get_context(session_id)
    
    if context:
        return context.to_dict()
    
    return None


# ============================================================================
# Testing Utilities
# ============================================================================


def compare_parsers(text: str) -> Dict[str, Any]:
    """Compare legacy and hybrid parser results.
    
    Useful for testing and validation during migration.
    
    Args:
        text: Text to parse
    
    Returns:
        Comparison results
    """
    # Legacy result
    legacy = legacy_parse_intent(text)
    
    # Hybrid result
    nlu = get_nlu()
    hybrid = nlu.parse(text)
    
    # Compare
    intent_match = legacy.intent == hybrid.intent
    slots_match = dict(legacy.slots) == dict(hybrid.slots)
    
    return {
        "text": text,
        "legacy": {
            "intent": legacy.intent,
            "slots": dict(legacy.slots),
        },
        "hybrid": {
            "intent": hybrid.intent,
            "slots": dict(hybrid.slots),
            "confidence": hybrid.confidence,
            "source": hybrid.source,
        },
        "match": {
            "intent": intent_match,
            "slots": slots_match,
            "full": intent_match and slots_match,
        },
    }


def batch_compare(texts: list[str]) -> Dict[str, Any]:
    """Compare parsers on multiple texts.
    
    Args:
        texts: List of texts to compare
    
    Returns:
        Summary of comparisons
    """
    results = [compare_parsers(t) for t in texts]
    
    matches = sum(1 for r in results if r["match"]["full"])
    intent_matches = sum(1 for r in results if r["match"]["intent"])
    
    return {
        "total": len(texts),
        "full_matches": matches,
        "intent_matches": intent_matches,
        "match_rate": matches / len(texts) if texts else 0,
        "details": results,
    }
