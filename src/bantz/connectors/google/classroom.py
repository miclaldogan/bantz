"""Google Classroom Connector — Classroom API integration.

Issue #1292 / refs #840: Provides course listing, coursework listing,
and submission status operations for Google Classroom via the unified
``GoogleAuthManager``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from bantz.connectors.google.base import GoogleConnector, ToolSchema

logger = logging.getLogger(__name__)

__all__ = ["ClassroomConnector", "Course", "Assignment", "Submission"]


@dataclass
class Course:
    """A Google Classroom course."""

    id: str = ""
    name: str = ""
    section: str = ""
    description: str = ""
    state: str = ""  # ACTIVE, ARCHIVED, PROVISIONED, DECLINED, SUSPENDED
    enrollment_code: str = ""
    creation_time: str = ""
    update_time: str = ""
    teacher_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "section": self.section,
            "description": self.description,
            "state": self.state,
            "enrollment_code": self.enrollment_code,
            "creation_time": self.creation_time,
            "update_time": self.update_time,
            "teacher_name": self.teacher_name,
        }


@dataclass
class Assignment:
    """A Google Classroom course work item (assignment, quiz, etc.)."""

    id: str = ""
    course_id: str = ""
    title: str = ""
    description: str = ""
    work_type: str = ""  # ASSIGNMENT, SHORT_ANSWER_QUESTION, MULTIPLE_CHOICE_QUESTION
    state: str = ""  # PUBLISHED, DRAFT, DELETED
    due_date: str = ""
    due_time: str = ""
    max_points: float = 0.0
    creation_time: str = ""
    update_time: str = ""

    @property
    def due_display(self) -> str:
        """Human-readable due date string."""
        if self.due_date:
            return "%s %s" % (self.due_date, self.due_time) if self.due_time else self.due_date
        return "Tarih yok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "course_id": self.course_id,
            "title": self.title,
            "description": self.description,
            "work_type": self.work_type,
            "state": self.state,
            "due_display": self.due_display,
            "max_points": self.max_points,
            "creation_time": self.creation_time,
            "update_time": self.update_time,
        }


@dataclass
class Submission:
    """A student's submission for a course work item."""

    id: str = ""
    course_id: str = ""
    coursework_id: str = ""
    state: str = ""  # NEW, CREATED, TURNED_IN, RETURNED, RECLAIMED_BY_STUDENT
    assigned_grade: Optional[float] = None
    late: bool = False
    update_time: str = ""

    @property
    def is_submitted(self) -> bool:
        return self.state in ("TURNED_IN", "RETURNED")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "course_id": self.course_id,
            "coursework_id": self.coursework_id,
            "state": self.state,
            "is_submitted": self.is_submitted,
            "assigned_grade": self.assigned_grade,
            "late": self.late,
            "update_time": self.update_time,
        }


def _parse_due(due_date: dict | None, due_time: dict | None) -> tuple[str, str]:
    """Parse Classroom dueDate + dueTime into strings."""
    date_str = ""
    time_str = ""
    if due_date and isinstance(due_date, dict):
        y = due_date.get("year", 0)
        m = due_date.get("month", 0)
        d = due_date.get("day", 0)
        if y and m and d:
            date_str = "%04d-%02d-%02d" % (y, m, d)
    if due_time and isinstance(due_time, dict):
        h = due_time.get("hours", 0)
        mi = due_time.get("minutes", 0)
        time_str = "%02d:%02d" % (h, mi)
    return date_str, time_str


class ClassroomConnector(GoogleConnector):
    """Google Classroom service connector.

    Provides:
    - ``list_courses()`` — list all courses
    - ``list_coursework(course_id)`` — list assignments for a course
    - ``get_submission_status(course_id)`` — get submission statuses
    """

    SERVICE_NAME = "classroom"

    async def list_courses(
        self,
        *,
        state: str = "ACTIVE",
        max_results: int = 50,
    ) -> list[Course]:
        """List Google Classroom courses.

        Parameters
        ----------
        state : str
            Course state filter: ``"ACTIVE"``, ``"ARCHIVED"``, etc.
        max_results : int
            Maximum number of courses to return.
        """
        try:
            params: dict[str, Any] = {
                "pageSize": min(max_results, 100),
            }
            if state:
                params["courseStates"] = [state]

            result = self.service.courses().list(**params).execute()
            items = result.get("courses", [])

            courses = []
            for c in items:
                # Try to get teacher name from ownerId
                teacher_name = ""
                owner_id = c.get("ownerId", "")
                if owner_id:
                    try:
                        profile = (
                            self.service.userProfiles()
                            .get(userId=owner_id)
                            .execute()
                        )
                        name_obj = profile.get("name", {})
                        teacher_name = name_obj.get("fullName", "")
                    except Exception:
                        pass

                courses.append(Course(
                    id=c.get("id", ""),
                    name=c.get("name", ""),
                    section=c.get("section", ""),
                    description=c.get("descriptionHeading", ""),
                    state=c.get("courseState", ""),
                    enrollment_code=c.get("enrollmentCode", ""),
                    creation_time=c.get("creationTime", ""),
                    update_time=c.get("updateTime", ""),
                    teacher_name=teacher_name,
                ))
            return courses
        except Exception as exc:
            logger.error("Dersler alınamadı: %s", exc)
            raise

    async def list_coursework(
        self,
        course_id: str,
        *,
        max_results: int = 50,
    ) -> list[Assignment]:
        """List course work items (assignments, quizzes) for a course.

        Parameters
        ----------
        course_id : str
            The course ID.
        max_results : int
            Maximum number of items to return.
        """
        try:
            result = (
                self.service.courses()
                .courseWork()
                .list(courseId=course_id, pageSize=min(max_results, 100))
                .execute()
            )
            items = result.get("courseWork", [])

            assignments = []
            for cw in items:
                due_date, due_time = _parse_due(
                    cw.get("dueDate"), cw.get("dueTime")
                )
                assignments.append(Assignment(
                    id=cw.get("id", ""),
                    course_id=course_id,
                    title=cw.get("title", ""),
                    description=cw.get("description", ""),
                    work_type=cw.get("workType", ""),
                    state=cw.get("state", ""),
                    due_date=due_date,
                    due_time=due_time,
                    max_points=cw.get("maxPoints", 0.0),
                    creation_time=cw.get("creationTime", ""),
                    update_time=cw.get("updateTime", ""),
                ))
            return assignments
        except Exception as exc:
            logger.error("Ödevler alınamadı (ders %s): %s", course_id, exc)
            raise

    async def get_submission_status(
        self,
        course_id: str,
        *,
        coursework_id: Optional[str] = None,
    ) -> list[Submission]:
        """Get submission statuses for course work items.

        Parameters
        ----------
        course_id : str
            The course ID.
        coursework_id : str, optional
            Specific course work ID.  If ``None``, returns submissions
            for all course work items.
        """
        try:
            cw_id = coursework_id or "-"  # "-" means all coursework
            result = (
                self.service.courses()
                .courseWork()
                .studentSubmissions()
                .list(
                    courseId=course_id,
                    courseWorkId=cw_id,
                    userId="me",
                )
                .execute()
            )
            items = result.get("studentSubmissions", [])

            submissions = []
            for s in items:
                submissions.append(Submission(
                    id=s.get("id", ""),
                    course_id=s.get("courseId", ""),
                    coursework_id=s.get("courseWorkId", ""),
                    state=s.get("state", ""),
                    assigned_grade=s.get("assignedGrade"),
                    late=s.get("late", False),
                    update_time=s.get("updateTime", ""),
                ))
            return submissions
        except Exception as exc:
            logger.error(
                "Teslim durumları alınamadı (ders %s): %s", course_id, exc,
            )
            raise

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

    def _list_courses_tool(self, state: str = "ACTIVE", **_kw: Any) -> dict:
        """Sync tool handler for listing courses."""
        try:
            courses = self._run_async(self.list_courses(state=state))
            return self._ok(
                courses=[c.to_dict() for c in courses],
                count=len(courses),
            )
        except Exception as exc:
            return self._err("Dersler alınamadı: %s" % exc)

    def _list_coursework_tool(self, course_id: str, **_kw: Any) -> dict:
        """Sync tool handler for listing assignments."""
        try:
            assignments = self._run_async(self.list_coursework(course_id))
            return self._ok(
                assignments=[a.to_dict() for a in assignments],
                count=len(assignments),
            )
        except Exception as exc:
            return self._err("Ödevler alınamadı: %s" % exc)

    def _submission_status_tool(
        self,
        course_id: str,
        coursework_id: Optional[str] = None,
        **_kw: Any,
    ) -> dict:
        """Sync tool handler for getting submission statuses."""
        try:
            submissions = self._run_async(
                self.get_submission_status(course_id, coursework_id=coursework_id)
            )
            return self._ok(
                submissions=[s.to_dict() for s in submissions],
                count=len(submissions),
            )
        except Exception as exc:
            return self._err("Teslim durumları alınamadı: %s" % exc)

    # ── ToolSchema registration ─────────────────────────────────

    def get_tools(self) -> list[ToolSchema]:
        """Return tool descriptors for the Classroom connector."""
        return [
            ToolSchema(
                name="google.classroom.courses",
                description="Google Classroom derslerini listele.",
                parameters={
                    "type": "object",
                    "properties": {
                        "state": {
                            "type": "string",
                            "description": "Ders durumu filtresi (ACTIVE, ARCHIVED)",
                        },
                    },
                },
                handler=self._list_courses_tool,
                risk="low",
            ),
            ToolSchema(
                name="google.classroom.coursework",
                description="Google Classroom dersindeki ödevleri listele.",
                parameters={
                    "type": "object",
                    "properties": {
                        "course_id": {
                            "type": "string",
                            "description": "Ders ID",
                        },
                    },
                    "required": ["course_id"],
                },
                handler=self._list_coursework_tool,
                risk="low",
            ),
            ToolSchema(
                name="google.classroom.submissions",
                description="Google Classroom ödev teslim durumlarını getir.",
                parameters={
                    "type": "object",
                    "properties": {
                        "course_id": {
                            "type": "string",
                            "description": "Ders ID",
                        },
                        "coursework_id": {
                            "type": "string",
                            "description": "Ödev ID (opsiyonel, tüm ödevler için boş bırakın)",
                        },
                    },
                    "required": ["course_id"],
                },
                handler=self._submission_status_tool,
                risk="low",
            ),
        ]
