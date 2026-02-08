"""Router Intent Handlers Package (Issue #420).

Auto-registers all handler modules on import.
"""

from __future__ import annotations

_registered = False


def ensure_registered() -> None:
    """Register all handler modules (idempotent)."""
    global _registered
    if _registered:
        return
    _registered = True

    from bantz.router.handlers import browser, panel, pc, daily, scheduler, coding
    browser.register_all()
    panel.register_all()
    pc.register_all()
    daily.register_all()
    scheduler.register_all()
    coding.register_all()
