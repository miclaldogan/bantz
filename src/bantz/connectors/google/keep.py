"""Google Keep Connector — Keep API integration.

Issue #1292: Provides list, create, and search operations for Google Keep
notes.  Note: The Google Keep API (Enterprise) has limited availability —
it requires a Google Workspace account and is not available for consumer
accounts.  This connector degrades gracefully with a clear error message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from bantz.connectors.google.base import GoogleConnector, ToolSchema

logger = logging.getLogger(__name__)

__all__ = ["KeepConnector", "Note"]

# Keep API availability flag — set to False if the API returns 403
_KEEP_API_AVAILABLE: bool = True


@dataclass
class Note:
    """A Google Keep note."""

    name: str = ""  # Resource name e.g. "notes/abc123"
    title: str = ""
    body: str = ""
    create_time: str = ""
    update_time: str = ""
    trashed: bool = False
    labels: list[str] = field(default_factory=list)
    pinned: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "body": self.body,
            "create_time": self.create_time,
            "update_time": self.update_time,
            "trashed": self.trashed,
            "labels": self.labels,
            "pinned": self.pinned,
        }


def _parse_note(note: dict) -> Note:
    """Parse a Keep API note resource into a ``Note``."""
    body_content = ""
    body_obj = note.get("body", {})
    if isinstance(body_obj, dict):
        # Text note
        text_content = body_obj.get("text", {})
        if isinstance(text_content, dict):
            body_content = text_content.get("text", "")
        elif isinstance(text_content, str):
            body_content = text_content
        # List note — concatenate items
        list_content = body_obj.get("list", {})
        if isinstance(list_content, dict):
            items = list_content.get("listItems", [])
            lines = []
            for item in items:
                text_obj = item.get("text", {})
                text = text_obj.get("text", "") if isinstance(text_obj, dict) else str(text_obj)
                checked = item.get("checked", False)
                prefix = "☑" if checked else "☐"
                lines.append("%s %s" % (prefix, text))
            if lines:
                body_content = "\n".join(lines)

    return Note(
        name=note.get("name", ""),
        title=note.get("title", ""),
        body=body_content,
        create_time=note.get("createTime", ""),
        update_time=note.get("updateTime", ""),
        trashed=note.get("trashed", False),
    )


class KeepConnector(GoogleConnector):
    """Google Keep service connector.

    Provides:
    - ``list_notes(filter)`` — list notes, optionally filtered
    - ``create_note(title, body)`` — create a new note
    - ``search_notes(query)`` — search notes by content

    .. note::
       The Google Keep API is only available for Google Workspace
       (enterprise) accounts.  Consumer accounts will receive a clear
       error message explaining this limitation.
    """

    SERVICE_NAME = "keep"

    def _check_availability(self) -> Optional[str]:
        """Return an error message if Keep API is not available, else ``None``."""
        global _KEEP_API_AVAILABLE
        if not _KEEP_API_AVAILABLE:
            return (
                "Google Keep API bu hesap türü için kullanılamıyor. "
                "Keep API yalnızca Google Workspace (kurumsal) hesaplarda aktiftir."
            )
        return None

    async def list_notes(
        self,
        *,
        max_results: int = 50,
        filter_str: Optional[str] = None,
    ) -> list[Note]:
        """List Google Keep notes.

        Parameters
        ----------
        max_results : int
            Maximum number of notes to return.
        filter_str : str, optional
            Filter string (e.g. ``"trashed=false"``).
        """
        global _KEEP_API_AVAILABLE
        try:
            kwargs: dict[str, Any] = {"pageSize": min(max_results, 100)}
            if filter_str:
                kwargs["filter"] = filter_str

            result = self.service.notes().list(**kwargs).execute()
            items = result.get("notes", [])
            return [_parse_note(n) for n in items if not n.get("trashed")]
        except Exception as exc:
            error_str = str(exc)
            if "403" in error_str or "not enabled" in error_str.lower():
                _KEEP_API_AVAILABLE = False
                logger.warning("Keep API kullanılamıyor: %s", exc)
                raise RuntimeError(
                    "Google Keep API bu hesap için aktif değil. "
                    "Keep API yalnızca Google Workspace hesaplarında çalışır."
                ) from exc
            logger.error("Keep notları alınamadı: %s", exc)
            raise

    async def create_note(
        self,
        title: str,
        body: str,
    ) -> Note:
        """Create a new Google Keep note.

        Parameters
        ----------
        title : str
            Note title.
        body : str
            Note body text.
        """
        global _KEEP_API_AVAILABLE
        note_body: dict[str, Any] = {
            "title": title,
            "body": {
                "text": {
                    "text": body,
                },
            },
        }
        try:
            result = self.service.notes().create(body=note_body).execute()
            note = _parse_note(result)
            logger.info("Not oluşturuldu: %s", title)
            return note
        except Exception as exc:
            error_str = str(exc)
            if "403" in error_str or "not enabled" in error_str.lower():
                _KEEP_API_AVAILABLE = False
            logger.error("Not oluşturma hatası: %s", exc)
            raise

    async def search_notes(
        self,
        query: str,
        *,
        max_results: int = 20,
    ) -> list[Note]:
        """Search notes by title or body content.

        Parameters
        ----------
        query : str
            Search query (case-insensitive substring match).
        max_results : int
            Maximum number of results.

        Note: The Keep API does not support server-side full-text search,
        so we fetch all notes and filter client-side.
        """
        all_notes = await self.list_notes(max_results=200)
        query_lower = query.lower()
        matches = [
            n for n in all_notes
            if query_lower in n.title.lower() or query_lower in n.body.lower()
        ]
        return matches[:max_results]

    # ── Tool handlers ───────────────────────────────────────────

    def _run_async(self, coro: Any) -> Any:
        """Run an async coroutine from sync context."""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, coro).result()
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    def _list_notes_tool(self, **_kw: Any) -> dict:
        """Sync tool handler for listing notes."""
        avail_err = self._check_availability()
        if avail_err:
            return self._err(avail_err)
        try:
            notes = self._run_async(self.list_notes())
            return self._ok(
                notes=[n.to_dict() for n in notes],
                count=len(notes),
            )
        except Exception as exc:
            return self._err("Notlar alınamadı: %s" % exc)

    def _create_note_tool(self, title: str, body: str, **_kw: Any) -> dict:
        """Sync tool handler for creating a note."""
        avail_err = self._check_availability()
        if avail_err:
            return self._err(avail_err)
        try:
            note = self._run_async(self.create_note(title, body))
            return self._ok(note=note.to_dict())
        except Exception as exc:
            return self._err("Not oluşturma hatası: %s" % exc)

    def _search_notes_tool(self, query: str, **_kw: Any) -> dict:
        """Sync tool handler for searching notes."""
        avail_err = self._check_availability()
        if avail_err:
            return self._err(avail_err)
        try:
            notes = self._run_async(self.search_notes(query))
            return self._ok(
                notes=[n.to_dict() for n in notes],
                count=len(notes),
            )
        except Exception as exc:
            return self._err("Not arama hatası: %s" % exc)

    # ── ToolSchema registration ─────────────────────────────────

    def get_tools(self) -> list[ToolSchema]:
        """Return tool descriptors for the Keep connector."""
        return [
            ToolSchema(
                name="google.keep.list",
                description="Google Keep notlarını listele.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                handler=self._list_notes_tool,
                risk="low",
            ),
            ToolSchema(
                name="google.keep.create",
                description="Yeni Google Keep notu oluştur.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Not başlığı",
                        },
                        "body": {
                            "type": "string",
                            "description": "Not içeriği",
                        },
                    },
                    "required": ["title", "body"],
                },
                handler=self._create_note_tool,
                risk="medium",
                confirm=True,
            ),
            ToolSchema(
                name="google.keep.search",
                description="Google Keep notlarında ara.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Arama sorgusu",
                        },
                    },
                    "required": ["query"],
                },
                handler=self._search_notes_tool,
                risk="low",
            ),
        ]
