"""Intent Handler Protocol and Registry (Issue #420).

Provides a clean dispatch mechanism for Router._dispatch() by extracting
intent handlers into separate modules. The Router can look up handlers
from the registry instead of maintaining a 900-line if/elif chain.

Usage in Router._dispatch():
    handler = get_handler(intent)
    if handler:
        return handler(intent=intent, slots=slots, ctx=ctx, router=self, in_queue=in_queue)
"""

from __future__ import annotations

from typing import Callable, Optional, Protocol

from bantz.router.context import ConversationContext
from bantz.router.types import RouterResult


class IntentHandler(Protocol):
    """Protocol for intent handler callables."""

    def __call__(
        self,
        *,
        intent: str,
        slots: dict,
        ctx: ConversationContext,
        router: object,
        in_queue: bool,
    ) -> RouterResult: ...


# ── Handler Registry ──────────────────────────────────────────────────────
_REGISTRY: dict[str, IntentHandler] = {}


def register_handler(intent: str, handler: IntentHandler) -> None:
    """Register a handler function for a specific intent."""
    _REGISTRY[intent] = handler


def register_handlers(intents: list[str], handler: IntentHandler) -> None:
    """Register the same handler for multiple intents."""
    for intent in intents:
        _REGISTRY[intent] = handler


def get_handler(intent: str) -> Optional[IntentHandler]:
    """Look up the registered handler for an intent."""
    return _REGISTRY.get(intent)


def registered_intents() -> list[str]:
    """Return all registered intent names (for testing/debugging)."""
    return sorted(_REGISTRY.keys())
