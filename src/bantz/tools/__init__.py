"""Tools module for BrainLoop."""

from __future__ import annotations

from .registry import register_web_tools
from .web_open import web_open
from .web_search import web_search

__all__ = ["web_search", "web_open", "register_web_tools"]
