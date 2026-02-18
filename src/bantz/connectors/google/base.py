"""Base Google Connector — abstract interface for all Google service connectors.

Issue #1292: All Google connectors inherit from ``GoogleConnector``,
sharing the unified ``GoogleAuthManager`` for authentication and
exposing a standard ``get_tools()`` method for automatic tool registration.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from bantz.connectors.google.auth_manager import GoogleAuthManager

logger = logging.getLogger(__name__)

__all__ = ["GoogleConnector", "ToolSchema"]


class ToolSchema:
    """Lightweight descriptor for a tool exposed by a connector.

    Attributes
    ----------
    name : str
        Dot-qualified tool name (e.g. ``"google.tasks.list"``).
    description : str
        Human-readable description shown to the LLM planner.
    parameters : dict
        JSON-Schema ``object`` describing accepted parameters.
    handler : callable
        The async or sync function implementing the tool.
    risk : str
        Risk level: ``"low"``, ``"medium"``, or ``"high"``.
    confirm : bool
        Whether the tool requires user confirmation before execution.
    """

    __slots__ = ("name", "description", "parameters", "handler", "risk", "confirm")

    def __init__(
        self,
        *,
        name: str,
        description: str,
        parameters: dict,
        handler: Any,
        risk: str = "low",
        confirm: bool = False,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.risk = risk
        self.confirm = confirm


class GoogleConnector(ABC):
    """Abstract base class for Google service connectors.

    Subclasses must implement:
    - ``SERVICE_NAME`` class-level constant (e.g. ``"tasks"``).
    - ``get_tools()`` returning a list of ``ToolSchema`` instances.

    The base constructor authenticates via the unified auth manager
    and creates a ``service`` attribute for the Google API client.
    """

    SERVICE_NAME: str = ""

    def __init__(self, auth: GoogleAuthManager):
        if not self.SERVICE_NAME:
            raise NotImplementedError(
                "%s must define SERVICE_NAME" % type(self).__name__
            )
        self._auth = auth
        self._service: Any = None

    @property
    def service(self) -> Any:
        """Lazy-initialized Google API service object."""
        if self._service is None:
            self._service = self._auth.get_service(self.SERVICE_NAME)
        return self._service

    @abstractmethod
    def get_tools(self) -> list[ToolSchema]:
        """Return the tool descriptors this connector provides."""
        ...

    def _ok(self, **data: Any) -> dict[str, Any]:
        """Convenience: build a successful result dict."""
        return {"ok": True, **data}

    def _err(self, message: str, **data: Any) -> dict[str, Any]:
        """Convenience: build an error result dict."""
        return {"ok": False, "error": message, **data}
