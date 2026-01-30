# SPDX-License-Identifier: MIT
"""
LLM-based NLU (Natural Language Understanding) module.

This module provides intelligent intent classification that goes beyond
simple regex patterns. It uses a hybrid approach:

1. Fast regex path for common, unambiguous commands
2. LLM fallback for natural language variations
3. Slot extraction for entities (time, URL, app names)
4. Clarification handling for ambiguous inputs

Usage:
    from bantz.nlu import HybridNLU, IntentResult
    
    nlu = HybridNLU()
    result = nlu.parse("youtube'a gidebilir misin")
    # IntentResult(intent='browser_open', slots={'site': 'youtube'}, confidence=0.95)
    
    # Or use the bridge for legacy compatibility:
    from bantz.nlu import parse_intent_hybrid
    parsed = parse_intent_hybrid("youtube aç")
    # Parsed(intent='browser_open', slots={'site': 'youtube'})
"""

from bantz.nlu.types import (
    # Core types
    IntentResult,
    Slot,
    SlotType,
    ClarificationRequest,
    ClarificationOption,
    NLUContext,
    # Enums
    ConfidenceLevel,
    IntentCategory,
    # Stats
    NLUStats,
)

from bantz.nlu.classifier import (
    LLMIntentClassifier,
    ClassifierConfig,
)

from bantz.nlu.slots import (
    SlotExtractor,
    TimeSlot,
    URLSlot,
    AppSlot,
    QuerySlot,
)

from bantz.nlu.clarification import (
    ClarificationManager,
    ClarificationConfig,
)

from bantz.nlu.hybrid import (
    HybridNLU,
    HybridConfig,
    quick_parse,
    get_nlu,
    parse,
)

from bantz.nlu.bridge import (
    parse_intent_hybrid,
    parse_intent_adaptive,
    parse_with_context,
    parse_enhanced,
    parse_with_clarification,
    resolve_clarification,
    enable_hybrid_nlu,
    is_hybrid_enabled,
    get_nlu_stats,
    compare_parsers,
)

__all__ = [
    # Types
    "IntentResult",
    "Slot",
    "SlotType",
    "ClarificationRequest",
    "ClarificationOption",
    "NLUContext",
    "ConfidenceLevel",
    "IntentCategory",
    "NLUStats",
    # Classifier
    "LLMIntentClassifier",
    "ClassifierConfig",
    # Slots
    "SlotExtractor",
    "TimeSlot",
    "URLSlot",
    "AppSlot",
    "QuerySlot",
    # Clarification
    "ClarificationManager",
    "ClarificationConfig",
    # Hybrid
    "HybridNLU",
    "HybridConfig",
    "quick_parse",
    "get_nlu",
    "parse",
    # Bridge (legacy compatibility)
    "parse_intent_hybrid",
    "parse_intent_adaptive",
    "parse_with_context",
    "parse_enhanced",
    "parse_with_clarification",
    "resolve_clarification",
    "enable_hybrid_nlu",
    "is_hybrid_enabled",
    "get_nlu_stats",
    "compare_parsers",
]
