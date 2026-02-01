# Issue: Tiered LLM demo (3B router + Gemini quality)

**Type:** Feature / Demo

## Goal
Demonstrate tiered behavior:
- Fast local 3B is always used for routing + tool selection.
- Gemini (quality tier) is used for writing-heavy tasks (email drafts, long explanations, summaries).

## Acceptance Criteria
- A demo scenario exists where the user asks for an email draft and the system uses the quality provider.
- Calendar tool answers remain fast and do not unnecessarily escalate to Gemini.

## Notes
This is primarily to reduce confusion: in a calendar demo, Gemini may not trigger naturally.
