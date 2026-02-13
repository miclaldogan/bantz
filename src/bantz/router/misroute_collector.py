"""Router Misroute Collection.

Issue #238: Collect router misroutes/fallbacks for dataset improvement.

This module provides:
- JSONL logging of misroutes with PII redaction
- Replay tool for testing router accuracy
- Dataset management utilities
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, List, Literal, Optional

from bantz.security.masking import DataMasker


# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_DATASET_PATH = os.getenv(
    "BANTZ_MISROUTE_DATASET",
    str(Path.home() / ".cache" / "bantz" / "datasets" / "router_misroutes.jsonl"),
)


# ============================================================================
# DATA TYPES
# ============================================================================

MisrouteReason = Literal[
    "wrong_route",      # Router chose wrong domain
    "wrong_intent",     # Router chose wrong intent within domain
    "missing_slot",     # Critical slot not extracted
    "wrong_slot",       # Slot value incorrect
    "fallback",         # Router returned fallback/unknown
    "low_confidence",   # Confidence below threshold
    "user_correction",  # User explicitly corrected
    "other",            # Other misroute reason
]


@dataclass
class MisrouteRecord:
    """Record of a router misroute."""
    
    # Input
    user_text: str
    
    # Router output
    router_route: str
    router_intent: str
    router_slots: dict = field(default_factory=dict)
    router_confidence: float = 0.0
    router_raw_output: str = ""
    
    # Expected (if known from user correction)
    expected_route: Optional[str] = None
    expected_intent: Optional[str] = None
    expected_slots: Optional[dict] = None
    
    # Metadata
    reason: MisrouteReason = "other"
    fallback_reason: Optional[str] = None
    notes: str = ""
    
    # Timestamps
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    session_id: str = ""
    
    # Version tracking
    model_name: str = ""
    model_version: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "MisrouteRecord":
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ============================================================================
# PII MASKER
# ============================================================================

# Singleton masker for PII redaction
_masker: Optional[DataMasker] = None


def get_masker() -> DataMasker:
    """Get or create the PII masker."""
    global _masker
    if _masker is None:
        _masker = DataMasker()
    return _masker


def redact_pii(text: str) -> str:
    """Redact PII from text using the masker."""
    return get_masker().mask(text)


def redact_record(record: MisrouteRecord) -> MisrouteRecord:
    """Redact PII from all text fields in a record."""
    return MisrouteRecord(
        user_text=redact_pii(record.user_text),
        router_route=record.router_route,
        router_intent=record.router_intent,
        router_slots={k: redact_pii(str(v)) if isinstance(v, str) else v 
                      for k, v in record.router_slots.items()},
        router_confidence=record.router_confidence,
        router_raw_output=redact_pii(record.router_raw_output),
        expected_route=record.expected_route,
        expected_intent=record.expected_intent,
        expected_slots={k: redact_pii(str(v)) if isinstance(v, str) else v 
                        for k, v in (record.expected_slots or {}).items()},
        reason=record.reason,
        fallback_reason=record.fallback_reason,
        notes=redact_pii(record.notes),
        timestamp=record.timestamp,
        session_id=record.session_id,
        model_name=record.model_name,
        model_version=record.model_version,
    )


# ============================================================================
# DATASET WRITER
# ============================================================================

class MisrouteDataset:
    """JSONL dataset for router misroutes."""
    
    def __init__(
        self,
        path: str = DEFAULT_DATASET_PATH,
        redact: bool = True,
    ):
        """Initialize dataset.
        
        Args:
            path: Path to JSONL file
            redact: Whether to redact PII before writing
        """
        self.path = Path(path)
        self.redact = redact
        self._ensure_dir()
    
    def _ensure_dir(self) -> None:
        """Ensure parent directory exists."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
    
    def append(self, record: MisrouteRecord) -> None:
        """Append a record to the dataset.
        
        Args:
            record: Record to append (will be PII-redacted if self.redact)
        """
        if self.redact:
            record = redact_record(record)
        
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
    
    def read_all(self) -> List[MisrouteRecord]:
        """Read all records from dataset.
        
        Returns:
            List of all records
        """
        records = []
        if not self.path.exists():
            return records
        
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        records.append(MisrouteRecord.from_dict(data))
                    except json.JSONDecodeError:
                        continue
        
        return records
    
    def iter_records(self) -> Iterator[MisrouteRecord]:
        """Iterate over records without loading all into memory.
        
        Yields:
            MisrouteRecord for each line
        """
        if not self.path.exists():
            return
        
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        yield MisrouteRecord.from_dict(data)
                    except json.JSONDecodeError:
                        continue
    
    def count(self) -> int:
        """Count records in dataset."""
        if not self.path.exists():
            return 0
        
        count = 0
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
    
    def clear(self) -> int:
        """Clear all records. Returns number of records removed."""
        count = self.count()
        if self.path.exists():
            self.path.unlink()
        return count
    
    def export_json(self, output_path: str) -> int:
        """Export to JSON array format.
        
        Args:
            output_path: Path to output JSON file
            
        Returns:
            Number of records exported
        """
        records = self.read_all()
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in records], f, ensure_ascii=False, indent=2)
        return len(records)


# ============================================================================
# LOGGING UTILITIES
# ============================================================================

# Global dataset instance
_dataset: Optional[MisrouteDataset] = None


def get_dataset() -> MisrouteDataset:
    """Get or create the global dataset instance."""
    global _dataset
    if _dataset is None:
        _dataset = MisrouteDataset()
    return _dataset


def log_misroute(
    user_text: str,
    router_route: str,
    router_intent: str = "",
    router_slots: Optional[dict] = None,
    router_confidence: float = 0.0,
    router_raw_output: str = "",
    expected_route: Optional[str] = None,
    expected_intent: Optional[str] = None,
    expected_slots: Optional[dict] = None,
    reason: MisrouteReason = "other",
    fallback_reason: Optional[str] = None,
    notes: str = "",
    session_id: str = "",
    model_name: str = "",
    model_version: str = "",
) -> MisrouteRecord:
    """Log a misroute to the dataset.
    
    This is the main entry point for logging misroutes.
    
    Args:
        user_text: Original user input
        router_route: Route chosen by router
        router_intent: Intent chosen by router
        router_slots: Slots extracted by router
        router_confidence: Router confidence score
        router_raw_output: Raw router output (for debugging)
        expected_route: Correct route (if known)
        expected_intent: Correct intent (if known)
        expected_slots: Correct slots (if known)
        reason: Type of misroute
        fallback_reason: Reason for fallback (if applicable)
        notes: Additional notes
        session_id: Session identifier
        model_name: Model used
        model_version: Model version
        
    Returns:
        The logged record
    """
    record = MisrouteRecord(
        user_text=user_text,
        router_route=router_route,
        router_intent=router_intent,
        router_slots=router_slots or {},
        router_confidence=router_confidence,
        router_raw_output=router_raw_output,
        expected_route=expected_route,
        expected_intent=expected_intent,
        expected_slots=expected_slots,
        reason=reason,
        fallback_reason=fallback_reason,
        notes=notes,
        session_id=session_id,
        model_name=model_name,
        model_version=model_version,
    )
    
    get_dataset().append(record)
    return record


def log_fallback(
    user_text: str,
    fallback_reason: str,
    router_raw_output: str = "",
    session_id: str = "",
    model_name: str = "",
) -> MisrouteRecord:
    """Convenience function for logging fallback events.
    
    Args:
        user_text: Original user input
        fallback_reason: Why fallback was triggered
        router_raw_output: Raw output (if any)
        session_id: Session identifier
        model_name: Model used
        
    Returns:
        The logged record
    """
    return log_misroute(
        user_text=user_text,
        router_route="unknown",
        router_intent="fallback",
        reason="fallback",
        fallback_reason=fallback_reason,
        router_raw_output=router_raw_output,
        session_id=session_id,
        model_name=model_name,
    )


def log_user_correction(
    user_text: str,
    router_route: str,
    router_intent: str,
    expected_route: str,
    expected_intent: str = "",
    router_slots: Optional[dict] = None,
    expected_slots: Optional[dict] = None,
    session_id: str = "",
    model_name: str = "",
) -> MisrouteRecord:
    """Log when user explicitly corrects a routing decision.
    
    Args:
        user_text: Original user input
        router_route: Route chosen by router
        router_intent: Intent chosen by router
        expected_route: Correct route (from user)
        expected_intent: Correct intent (from user)
        router_slots: Slots extracted by router
        expected_slots: Correct slots
        session_id: Session identifier
        model_name: Model used
        
    Returns:
        The logged record
    """
    return log_misroute(
        user_text=user_text,
        router_route=router_route,
        router_intent=router_intent,
        router_slots=router_slots,
        expected_route=expected_route,
        expected_intent=expected_intent,
        expected_slots=expected_slots,
        reason="user_correction",
        session_id=session_id,
        model_name=model_name,
    )


# ============================================================================
# REPLAY TYPES
# ============================================================================

@dataclass
class ReplayResult:
    """Result of replaying a single record."""
    
    record: MisrouteRecord
    new_route: str
    new_intent: str
    new_slots: dict
    new_confidence: float
    
    # Comparison
    route_match: bool = False
    intent_match: bool = False
    improved: bool = False
    regression: bool = False
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "user_text": self.record.user_text,
            "original_route": self.record.router_route,
            "new_route": self.new_route,
            "expected_route": self.record.expected_route,
            "route_match": self.route_match,
            "improved": self.improved,
            "regression": self.regression,
        }


@dataclass
class ReplaySummary:
    """Summary of replay run."""
    
    total: int = 0
    improved: int = 0
    regressed: int = 0
    unchanged: int = 0
    route_accuracy: float = 0.0
    intent_accuracy: float = 0.0
    
    results: List[ReplayResult] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "total": self.total,
            "improved": self.improved,
            "regressed": self.regressed,
            "unchanged": self.unchanged,
            "improvement_rate": self.improved / self.total if self.total > 0 else 0,
            "regression_rate": self.regressed / self.total if self.total > 0 else 0,
            "route_accuracy": self.route_accuracy,
            "intent_accuracy": self.intent_accuracy,
        }
    
    def format_markdown(self) -> str:
        """Format as markdown report."""
        lines = [
            "# Router Replay Summary",
            "",
            f"**Total Records:** {self.total}",
            f"**Improved:** {self.improved} ({self.improved/self.total*100:.1f}%)" if self.total else "**Improved:** 0",
            f"**Regressed:** {self.regressed} ({self.regressed/self.total*100:.1f}%)" if self.total else "**Regressed:** 0",
            f"**Unchanged:** {self.unchanged} ({self.unchanged/self.total*100:.1f}%)" if self.total else "**Unchanged:** 0",
            "",
            "## Accuracy",
            f"- Route Accuracy: {self.route_accuracy*100:.1f}%",
            f"- Intent Accuracy: {self.intent_accuracy*100:.1f}%",
        ]
        
        # Show improvements
        improved_results = [r for r in self.results if r.improved]
        if improved_results:
            lines.extend([
                "",
                "## Improvements",
                "",
            ])
            for r in improved_results[:10]:
                lines.append(f"- `{r.record.user_text[:50]}...` : {r.record.router_route} → {r.new_route}")
        
        # Show regressions
        regressed_results = [r for r in self.results if r.regression]
        if regressed_results:
            lines.extend([
                "",
                "## Regressions",
                "",
            ])
            for r in regressed_results[:10]:
                lines.append(f"- `{r.record.user_text[:50]}...` : {r.record.router_route} → {r.new_route}")
        
        return "\n".join(lines)


# ============================================================================
# REPLAY FUNCTION
# ============================================================================

RouterFunction = Callable[[str], dict]


def replay_dataset(
    router_fn: RouterFunction,
    dataset_path: str = DEFAULT_DATASET_PATH,
    limit: Optional[int] = None,
) -> ReplaySummary:
    """Replay dataset through a router function.
    
    Args:
        router_fn: Function that takes user_text and returns dict with
                   route, intent, slots, confidence keys
        dataset_path: Path to dataset JSONL
        limit: Optional limit on number of records to replay
        
    Returns:
        ReplaySummary with results
    """
    dataset = MisrouteDataset(path=dataset_path, redact=False)
    records = dataset.read_all()
    
    if limit:
        records = records[:limit]
    
    summary = ReplaySummary()
    summary.total = len(records)
    
    route_correct = 0
    intent_correct = 0
    
    for record in records:
        try:
            result = router_fn(record.user_text)
            
            new_route = result.get("route", "")
            new_intent = result.get("intent", "")
            new_slots = result.get("slots", {})
            new_confidence = result.get("confidence", 0.0)
            
            # Determine expected route/intent
            expected_route = record.expected_route or record.router_route
            expected_intent = record.expected_intent or record.router_intent
            
            # Check matches
            route_match = new_route == expected_route
            intent_match = new_intent == expected_intent if expected_intent else True
            
            if route_match:
                route_correct += 1
            if intent_match:
                intent_correct += 1
            
            # Determine improvement/regression
            was_correct = record.router_route == expected_route
            now_correct = route_match
            
            improved = not was_correct and now_correct
            regressed = was_correct and not now_correct
            
            replay_result = ReplayResult(
                record=record,
                new_route=new_route,
                new_intent=new_intent,
                new_slots=new_slots,
                new_confidence=new_confidence,
                route_match=route_match,
                intent_match=intent_match,
                improved=improved,
                regression=regressed,
            )
            
            summary.results.append(replay_result)
            
            if improved:
                summary.improved += 1
            elif regressed:
                summary.regressed += 1
            else:
                summary.unchanged += 1
                
        except Exception as e:
            # Log error but continue
            print(f"Error replaying record: {e}")
            continue
    
    # Calculate accuracies
    if summary.total > 0:
        summary.route_accuracy = route_correct / summary.total
        summary.intent_accuracy = intent_correct / summary.total
    
    return summary


# ============================================================================
# STATISTICS
# ============================================================================

def get_dataset_stats(dataset_path: str = DEFAULT_DATASET_PATH) -> dict:
    """Get statistics about the misroute dataset.
    
    Args:
        dataset_path: Path to dataset
        
    Returns:
        Dictionary with statistics
    """
    dataset = MisrouteDataset(path=dataset_path, redact=False)
    records = dataset.read_all()
    
    if not records:
        return {
            "total": 0,
            "by_reason": {},
            "by_route": {},
            "by_model": {},
        }
    
    # Count by reason
    by_reason: dict[str, int] = {}
    for r in records:
        by_reason[r.reason] = by_reason.get(r.reason, 0) + 1
    
    # Count by route
    by_route: dict[str, int] = {}
    for r in records:
        by_route[r.router_route] = by_route.get(r.router_route, 0) + 1
    
    # Count by model
    by_model: dict[str, int] = {}
    for r in records:
        model = r.model_name or "unknown"
        by_model[model] = by_model.get(model, 0) + 1
    
    # Time range
    timestamps = [r.timestamp for r in records if r.timestamp]
    
    return {
        "total": len(records),
        "by_reason": by_reason,
        "by_route": by_route,
        "by_model": by_model,
        "first_record": min(timestamps) if timestamps else None,
        "last_record": max(timestamps) if timestamps else None,
    }
