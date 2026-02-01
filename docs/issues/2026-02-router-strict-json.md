# Issue: Router strict JSON + heuristics

**Type:** Reliability

## Problem
Router classification is sensitive to sampling and prompt length. When it produces non-JSON or extra text, downstream routing can fail and create poor UX.

## Goal
- Router classification should be stable:
  - `temperature=0.0`
  - small output budget (e.g., `max_tokens=64`)
  - minimal prompt
- Add deterministic heuristics to bias:
  - If no calendar markers -> `smalltalk` (confidence >= 0.8)
  - If calendar markers -> `calendar` (confidence >= 0.7)

## Acceptance Criteria
- “Selam” -> `smalltalk` with high confidence.
- Calendar queries (“bugün planım var mı?”, “yarın 10:00 toplantı ekle”) -> `calendar`.
- Parse failures never propagate to user-facing menus.

## Notes
Core should not depend on demo-only adapters.
