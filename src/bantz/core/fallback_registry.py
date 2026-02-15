"""Fallback Registry — per-service fallback strategies for graceful degradation.

Issue #1298: Graceful Degradation — Circuit Breaker + Health Monitor + Fallback.

When a service is unhealthy, the FallbackRegistry determines the appropriate
fallback strategy: use cached data, fall back to a simpler model, degrade
functionality, or notify the user.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class FallbackStrategy(str, Enum):
    """Supported fallback strategies."""

    CACHE = "cache_fallback"          # Serve from cached data
    SQLITE = "sqlite_fallback"       # Fall back to SQLite from graph DB
    MODEL_DOWNGRADE = "model_downgrade"  # Use smaller/local model
    GRACEFUL_ERROR = "graceful_error"    # Return user-friendly error
    NONE = "none"                    # No fallback — propagate the error


@dataclass
class FallbackConfig:
    """Configuration for a single service's fallback."""

    service: str
    strategy: FallbackStrategy
    message_tr: str            # Turkish message for the user
    message_en: str = ""       # English fallback (optional)
    max_cache_age_s: int = 0   # Max staleness for cache fallback (seconds)
    fallback_model: str = ""   # Alternative model for model_downgrade
    fallback_fn: Optional[Callable[..., Any]] = None  # Custom fallback callable

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "service": self.service,
            "strategy": self.strategy.value,
            "message_tr": self.message_tr,
        }
        if self.max_cache_age_s:
            d["max_cache_age_s"] = self.max_cache_age_s
        if self.fallback_model:
            d["fallback_model"] = self.fallback_model
        return d


@dataclass
class FallbackResult:
    """Result of executing a fallback."""

    service: str
    strategy: FallbackStrategy
    success: bool
    data: Any = None
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service": self.service,
            "strategy": self.strategy.value,
            "success": self.success,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


# ── Built-in Fallback Handlers ──────────────────────────────────

def _cache_fallback(service: str, cache_dir: Path, max_age: int) -> FallbackResult:
    """Try to serve from a cached response file."""
    cache_file = cache_dir / f"{service}_cache.json"
    try:
        if not cache_file.exists():
            return FallbackResult(
                service=service,
                strategy=FallbackStrategy.CACHE,
                success=False,
                message="Önbellek dosyası bulunamadı",
            )

        stat = cache_file.stat()
        age_s = time.time() - stat.st_mtime
        if max_age > 0 and age_s > max_age:
            return FallbackResult(
                service=service,
                strategy=FallbackStrategy.CACHE,
                success=False,
                message=f"Önbellek çok eski ({age_s:.0f}s > {max_age}s)",
            )

        with open(cache_file) as f:
            data = json.load(f)

        return FallbackResult(
            service=service,
            strategy=FallbackStrategy.CACHE,
            success=True,
            data=data,
            message=f"Önbellekten yanıt verildi ({age_s:.0f}s eski)",
        )
    except Exception as exc:
        return FallbackResult(
            service=service,
            strategy=FallbackStrategy.CACHE,
            success=False,
            message=str(exc),
        )


def _sqlite_fallback(service: str) -> FallbackResult:
    """Fall back from graph DB (Neo4j) to SQLite."""
    try:
        import sqlite3

        db_path = Path.home() / ".bantz" / "bantz.db"
        if not db_path.exists():
            return FallbackResult(
                service=service,
                strategy=FallbackStrategy.SQLITE,
                success=False,
                message="SQLite veritabanı bulunamadı",
            )

        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.execute("SELECT 1")
        conn.close()

        return FallbackResult(
            service=service,
            strategy=FallbackStrategy.SQLITE,
            success=True,
            message="SQLite veritabanına yönlendirildi",
        )
    except Exception as exc:
        return FallbackResult(
            service=service,
            strategy=FallbackStrategy.SQLITE,
            success=False,
            message=str(exc),
        )


def _model_downgrade(
    service: str,
    fallback_model: str,
) -> FallbackResult:
    """Attempt to use a smaller/alternative LLM model."""
    if not fallback_model:
        return FallbackResult(
            service=service,
            strategy=FallbackStrategy.MODEL_DOWNGRADE,
            success=False,
            message="Yedek model tanımlı değil",
        )

    return FallbackResult(
        service=service,
        strategy=FallbackStrategy.MODEL_DOWNGRADE,
        success=True,
        data={"model": fallback_model},
        message=f"Model değiştirildi: {fallback_model}",
    )


# ── Fallback Registry ───────────────────────────────────────────

# Default fallback configurations for Bantz services
_DEFAULT_CONFIGS: Dict[str, FallbackConfig] = {
    "ollama": FallbackConfig(
        service="ollama",
        strategy=FallbackStrategy.MODEL_DOWNGRADE,
        message_tr="LLM servisi yanıt vermiyor, daha küçük model deneniyor.",
        max_cache_age_s=0,
        fallback_model="qwen2.5-coder:3b",
    ),
    "google": FallbackConfig(
        service="google",
        strategy=FallbackStrategy.CACHE,
        message_tr="Google API erişilemiyor, önbellekteki veriler kullanılıyor.",
        max_cache_age_s=3600,  # 1 hour
    ),
    "neo4j": FallbackConfig(
        service="neo4j",
        strategy=FallbackStrategy.SQLITE,
        message_tr="Graf veritabanı erişilemiyor, SQLite'a geri dönülüyor.",
    ),
    "weather": FallbackConfig(
        service="weather",
        strategy=FallbackStrategy.CACHE,
        message_tr="Hava durumu servisi yanıt vermiyor, son bilinen veriler kullanılıyor.",
        max_cache_age_s=7200,  # 2 hours
    ),
    "spotify": FallbackConfig(
        service="spotify",
        strategy=FallbackStrategy.GRACEFUL_ERROR,
        message_tr="Spotify erişilemiyor, müzik kontrol edilemiyor.",
    ),
}


class FallbackRegistry:
    """Registry of fallback strategies for graceful degradation.

    When a service goes down (circuit breaker open, health check fail),
    the registry determines how to handle the failure gracefully instead
    of propagating errors to the user.

    Usage:
        registry = FallbackRegistry()
        result = registry.execute_fallback("ollama")
        if result.success:
            use(result.data)
        else:
            show_error(result.message)
    """

    def __init__(
        self,
        *,
        configs: Dict[str, FallbackConfig] | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._configs: Dict[str, FallbackConfig] = (
            configs if configs is not None
            else dict(_DEFAULT_CONFIGS)
        )
        self._cache_dir = cache_dir or Path.home() / ".bantz" / "cache"
        self._history: list[FallbackResult] = []

    def register(self, config: FallbackConfig) -> None:
        """Register or update a fallback configuration."""
        self._configs[config.service] = config

    def unregister(self, service: str) -> None:
        """Remove a fallback configuration."""
        self._configs.pop(service, None)

    def get_config(self, service: str) -> Optional[FallbackConfig]:
        """Get fallback configuration for a service."""
        return self._configs.get(service)

    def list_services(self) -> list[str]:
        """List all services with fallback configurations."""
        return list(self._configs.keys())

    def execute_fallback(self, service: str) -> FallbackResult:
        """Execute the registered fallback for a service.

        Returns a ``FallbackResult`` indicating whether the fallback
        succeeded and any recovered data.
        """
        config = self._configs.get(service)
        if config is None:
            result = FallbackResult(
                service=service,
                strategy=FallbackStrategy.NONE,
                success=False,
                message=f"'{service}' için fallback tanımlı değil",
            )
            self._history.append(result)
            return result

        logger.info(
            "[FallbackRegistry] Executing %s for '%s'",
            config.strategy.value,
            service,
        )

        # Dispatch by strategy
        strategy = config.strategy

        if strategy == FallbackStrategy.CACHE:
            result = _cache_fallback(
                service,
                self._cache_dir,
                config.max_cache_age_s,
            )
        elif strategy == FallbackStrategy.SQLITE:
            result = _sqlite_fallback(service)
        elif strategy == FallbackStrategy.MODEL_DOWNGRADE:
            result = _model_downgrade(service, config.fallback_model)
        elif strategy == FallbackStrategy.GRACEFUL_ERROR:
            result = FallbackResult(
                service=service,
                strategy=FallbackStrategy.GRACEFUL_ERROR,
                success=True,
                message=config.message_tr,
            )
        else:  # NONE
            result = FallbackResult(
                service=service,
                strategy=FallbackStrategy.NONE,
                success=False,
                message="Fallback stratejisi yok",
            )

        # Custom handler override
        if config.fallback_fn is not None:
            try:
                custom_data = config.fallback_fn(service)
                result = FallbackResult(
                    service=service,
                    strategy=strategy,
                    success=True,
                    data=custom_data,
                    message="Özel fallback çalıştırıldı",
                )
            except Exception as exc:
                result = FallbackResult(
                    service=service,
                    strategy=strategy,
                    success=False,
                    message=f"Özel fallback başarısız: {exc}",
                )

        self._history.append(result)
        return result

    @property
    def history(self) -> list[FallbackResult]:
        """Get the history of fallback executions."""
        return list(self._history)

    def clear_history(self) -> None:
        """Clear fallback execution history."""
        self._history.clear()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize all configurations."""
        return {
            name: config.to_dict()
            for name, config in self._configs.items()
        }


# ── Singleton ────────────────────────────────────────────────────

_fallback_registry: Optional[FallbackRegistry] = None


def get_fallback_registry(**kwargs: Any) -> FallbackRegistry:
    """Get or create singleton FallbackRegistry."""
    global _fallback_registry
    if _fallback_registry is None:
        _fallback_registry = FallbackRegistry(**kwargs)
    return _fallback_registry


def reset_fallback_registry() -> None:
    """Reset singleton (for tests)."""
    global _fallback_registry
    _fallback_registry = None
