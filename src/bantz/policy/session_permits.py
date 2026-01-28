from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InMemorySessionPermits:
    """Remember per-session confirmations.

    Intended for MED-risk actions where we confirm once per session.
    """

    _permits: dict[tuple[str, str], bool] = field(default_factory=dict)

    def is_confirmed(self, *, session_id: str, tool_name: str) -> bool:
        key = (str(session_id), str(tool_name))
        return bool(self._permits.get(key, False))

    def confirm(self, *, session_id: str, tool_name: str) -> None:
        key = (str(session_id), str(tool_name))
        self._permits[key] = True

    def revoke(self, *, session_id: str, tool_name: str) -> None:
        key = (str(session_id), str(tool_name))
        self._permits.pop(key, None)
