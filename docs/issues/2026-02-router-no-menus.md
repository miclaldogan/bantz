# Issue: Router fallback must not show menus

**Type:** Bug / UX

## Problem
In some flows (especially small-context local models), router/classifier output may be `unknown` or fail to parse, leading to a user-facing choice menu (e.g., “Takvim mi sohbet mi? 1/2/0”). This is acceptable as debug UX, but not in normal product behavior.

## Goal
- No user-facing “choose 1/2/0” menu in normal flows.
- On router parse failure or `unknown`, default to safe smalltalk fallback.

## Acceptance Criteria
- Greeting like “Selam nasılsın?” produces a normal smalltalk response, never a menu.
- Router parse failure does not surface a menu; it logs a reason token and falls back to smalltalk.
- Debug menus remain available behind a debug flag.

## Notes
This should be handled in core (BrainLoop), not only in the demo script.
