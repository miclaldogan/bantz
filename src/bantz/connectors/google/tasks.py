"""Google Tasks Connector — Tasks API integration.

Issue #1292: Provides list, create, complete, and delete operations
for Google Tasks via the unified ``GoogleAuthManager``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from bantz.connectors.google.base import GoogleConnector, ToolSchema

logger = logging.getLogger(__name__)

__all__ = ["TasksConnector", "Task", "TaskList"]


@dataclass
class TaskList:
    """A Google Tasks task list."""

    id: str = ""
    title: str = ""
    updated: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "updated": self.updated,
        }


@dataclass
class Task:
    """A Google Tasks task."""

    id: str = ""
    title: str = ""
    notes: str = ""
    status: str = ""  # "needsAction" or "completed"
    due: str = ""  # RFC 3339 date
    completed: str = ""
    parent: str = ""
    position: str = ""
    updated: str = ""
    links: list[dict[str, str]] = field(default_factory=list)

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "notes": self.notes,
            "status": self.status,
            "due": self.due,
            "completed": self.completed,
            "updated": self.updated,
            "is_completed": self.is_completed,
        }


def _parse_task(t: dict) -> Task:
    """Parse a Tasks API task resource into a ``Task``."""
    return Task(
        id=t.get("id", ""),
        title=t.get("title", ""),
        notes=t.get("notes", ""),
        status=t.get("status", ""),
        due=t.get("due", ""),
        completed=t.get("completed", ""),
        parent=t.get("parent", ""),
        position=t.get("position", ""),
        updated=t.get("updated", ""),
        links=t.get("links", []),
    )


class TasksConnector(GoogleConnector):
    """Google Tasks service connector.

    Provides:
    - ``list_task_lists()`` — list all task lists
    - ``list_tasks(task_list)`` — list tasks in a task list
    - ``create_task(title, due, notes, task_list)`` — create a new task
    - ``complete_task(task_id, task_list)`` — mark a task as completed
    - ``delete_task(task_id, task_list)`` — delete a task
    """

    SERVICE_NAME = "tasks"

    async def list_task_lists(self) -> list[TaskList]:
        """List all task lists for the user."""
        try:
            result = self.service.tasklists().list(maxResults=100).execute()
            items = result.get("items", [])
            return [
                TaskList(
                    id=item.get("id", ""),
                    title=item.get("title", ""),
                    updated=item.get("updated", ""),
                )
                for item in items
            ]
        except Exception as exc:
            logger.error("Görev listeleri alınamadı: %s", exc)
            raise

    async def list_tasks(
        self,
        task_list: str = "@default",
        *,
        show_completed: bool = False,
        max_results: int = 100,
    ) -> list[Task]:
        """List tasks in a task list.

        Parameters
        ----------
        task_list : str
            Task list ID or ``"@default"`` for the primary list.
        show_completed : bool
            Whether to include completed tasks.
        max_results : int
            Maximum number of tasks to return.
        """
        try:
            result = (
                self.service.tasks()
                .list(
                    tasklist=task_list,
                    showCompleted=show_completed,
                    maxResults=min(max_results, 100),
                )
                .execute()
            )
            items = result.get("items", [])
            return [_parse_task(t) for t in items]
        except Exception as exc:
            logger.error("Görevler alınamadı: %s", exc)
            raise

    async def create_task(
        self,
        title: str,
        *,
        due: Optional[str] = None,
        notes: Optional[str] = None,
        task_list: str = "@default",
    ) -> Task:
        """Create a new task.

        Parameters
        ----------
        title : str
            Task title.
        due : str, optional
            Due date in RFC 3339 format (e.g. ``"2025-01-15T00:00:00Z"``).
        notes : str, optional
            Additional notes.
        task_list : str
            Task list ID.
        """
        body: dict[str, Any] = {"title": title}
        if due:
            body["due"] = due
        if notes:
            body["notes"] = notes

        try:
            result = (
                self.service.tasks()
                .insert(tasklist=task_list, body=body)
                .execute()
            )
            task = _parse_task(result)
            logger.info("Görev oluşturuldu: %s", title)
            return task
        except Exception as exc:
            logger.error("Görev oluşturma hatası: %s", exc)
            raise

    async def complete_task(
        self,
        task_id: str,
        *,
        task_list: str = "@default",
    ) -> Task:
        """Mark a task as completed.

        Parameters
        ----------
        task_id : str
            The task ID.
        task_list : str
            Task list ID.
        """
        try:
            # First get the task
            task_data = (
                self.service.tasks()
                .get(tasklist=task_list, task=task_id)
                .execute()
            )
            task_data["status"] = "completed"
            result = (
                self.service.tasks()
                .update(tasklist=task_list, task=task_id, body=task_data)
                .execute()
            )
            task = _parse_task(result)
            logger.info("Görev tamamlandı: %s", task.title)
            return task
        except Exception as exc:
            logger.error("Görev tamamlama hatası: %s", exc)
            raise

    async def delete_task(
        self,
        task_id: str,
        *,
        task_list: str = "@default",
    ) -> bool:
        """Delete a task.

        Parameters
        ----------
        task_id : str
            The task ID.
        task_list : str
            Task list ID.

        Returns
        -------
        bool
            ``True`` if deleted successfully.
        """
        try:
            self.service.tasks().delete(
                tasklist=task_list, task=task_id
            ).execute()
            logger.info("Görev silindi: %s", task_id)
            return True
        except Exception as exc:
            logger.error("Görev silme hatası: %s", exc)
            raise

    # ── Tool handlers (sync wrappers) ───────────────────────────

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

    def _list_tasks_tool(
        self,
        task_list: str = "@default",
        show_completed: bool = False,
        **_kw: Any,
    ) -> dict:
        """Sync tool handler for listing tasks."""
        try:
            tasks = self._run_async(
                self.list_tasks(task_list, show_completed=show_completed)
            )
            return self._ok(
                tasks=[t.to_dict() for t in tasks],
                count=len(tasks),
            )
        except Exception as exc:
            return self._err("Görevler alınamadı: %s" % exc)

    def _create_task_tool(
        self,
        title: str,
        due: Optional[str] = None,
        notes: Optional[str] = None,
        task_list: str = "@default",
        **_kw: Any,
    ) -> dict:
        """Sync tool handler for creating a task."""
        try:
            task = self._run_async(
                self.create_task(title, due=due, notes=notes, task_list=task_list)
            )
            return self._ok(task=task.to_dict())
        except Exception as exc:
            return self._err("Görev oluşturma hatası: %s" % exc)

    def _complete_task_tool(
        self,
        task_id: str,
        task_list: str = "@default",
        **_kw: Any,
    ) -> dict:
        """Sync tool handler for completing a task."""
        try:
            task = self._run_async(
                self.complete_task(task_id, task_list=task_list)
            )
            return self._ok(task=task.to_dict())
        except Exception as exc:
            return self._err("Görev tamamlama hatası: %s" % exc)

    def _delete_task_tool(
        self,
        task_id: str,
        task_list: str = "@default",
        **_kw: Any,
    ) -> dict:
        """Sync tool handler for deleting a task."""
        try:
            self._run_async(
                self.delete_task(task_id, task_list=task_list)
            )
            return self._ok(message="Görev silindi")
        except Exception as exc:
            return self._err("Görev silme hatası: %s" % exc)

    # ── ToolSchema registration ─────────────────────────────────

    def get_tools(self) -> list[ToolSchema]:
        """Return tool descriptors for the tasks connector."""
        return [
            ToolSchema(
                name="google.tasks.list",
                description="Google Tasks görevlerini listele.",
                parameters={
                    "type": "object",
                    "properties": {
                        "task_list": {
                            "type": "string",
                            "description": "Görev listesi ID (varsayılan: @default)",
                        },
                        "show_completed": {
                            "type": "boolean",
                            "description": "Tamamlanan görevleri de göster",
                        },
                    },
                },
                handler=self._list_tasks_tool,
                risk="low",
            ),
            ToolSchema(
                name="google.tasks.create",
                description="Yeni Google Tasks görevi oluştur.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Görev başlığı",
                        },
                        "due": {
                            "type": "string",
                            "description": "Bitiş tarihi (YYYY-MM-DDT00:00:00Z)",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Ek notlar (opsiyonel)",
                        },
                        "task_list": {
                            "type": "string",
                            "description": "Görev listesi ID (varsayılan: @default)",
                        },
                    },
                    "required": ["title"],
                },
                handler=self._create_task_tool,
                risk="medium",
                confirm=True,
            ),
            ToolSchema(
                name="google.tasks.complete",
                description="Google Tasks görevini tamamlandı olarak işaretle.",
                parameters={
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Görev ID",
                        },
                        "task_list": {
                            "type": "string",
                            "description": "Görev listesi ID (varsayılan: @default)",
                        },
                    },
                    "required": ["task_id"],
                },
                handler=self._complete_task_tool,
                risk="medium",
                confirm=True,
            ),
            ToolSchema(
                name="google.tasks.delete",
                description="Google Tasks görevini sil.",
                parameters={
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "Görev ID",
                        },
                        "task_list": {
                            "type": "string",
                            "description": "Görev listesi ID (varsayılan: @default)",
                        },
                    },
                    "required": ["task_id"],
                },
                handler=self._delete_task_tool,
                risk="high",
                confirm=True,
            ),
        ]
