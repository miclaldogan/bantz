"""Tests for Google Classroom tool handlers — Issue #1387.

Covers the sync tool handlers (_list_courses_tool, _list_coursework_tool,
_submission_status_tool) with mocked Google API responses.
Existing dataclass & get_tools tests live in test_issue_1292_google_suite.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_auth():
    """Minimal GoogleAuthManager mock."""
    auth = MagicMock()
    auth.get_service = MagicMock(return_value=MagicMock())
    return auth


@pytest.fixture
def connector(mock_auth):
    from bantz.connectors.google.classroom import ClassroomConnector
    return ClassroomConnector(mock_auth)


def _make_course(id_: str = "c1", name: str = "Matematik", state: str = "ACTIVE"):
    return {
        "id": id_,
        "name": name,
        "section": "",
        "descriptionHeading": "",
        "courseState": state,
        "enrollmentCode": "abc",
        "creationTime": "2025-01-01T00:00:00Z",
        "updateTime": "2025-01-01T00:00:00Z",
        "ownerId": "",
    }


def _make_coursework(id_: str = "cw1", title: str = "Odev 1"):
    return {
        "id": id_,
        "title": title,
        "description": "Aciklama",
        "workType": "ASSIGNMENT",
        "state": "PUBLISHED",
        "dueDate": {"year": 2025, "month": 6, "day": 15},
        "dueTime": {"hours": 23, "minutes": 59},
        "maxPoints": 100.0,
        "creationTime": "2025-01-01T00:00:00Z",
        "updateTime": "2025-01-01T00:00:00Z",
    }


def _make_submission(id_: str = "s1", state: str = "TURNED_IN"):
    return {
        "id": id_,
        "courseId": "c1",
        "courseWorkId": "cw1",
        "state": state,
        "assignedGrade": 85.0,
        "late": False,
        "updateTime": "2025-06-15T00:00:00Z",
    }


# ─────────────────────────────────────────────────────────────────
# list_courses tool handler
# ─────────────────────────────────────────────────────────────────


class TestListCoursesTool:
    def test_success(self, connector):
        mock_svc = connector.service
        mock_svc.courses().list().execute.return_value = {
            "courses": [_make_course(), _make_course("c2", "Fizik")]
        }

        result = connector._list_courses_tool(state="ACTIVE")
        assert result["ok"] is True
        assert result["count"] == 2
        assert result["courses"][0]["name"] == "Matematik"
        assert result["courses"][1]["name"] == "Fizik"

    def test_empty_result(self, connector):
        mock_svc = connector.service
        mock_svc.courses().list().execute.return_value = {"courses": []}

        result = connector._list_courses_tool()
        assert result["ok"] is True
        assert result["count"] == 0
        assert result["courses"] == []

    def test_api_error(self, connector):
        mock_svc = connector.service
        mock_svc.courses().list().execute.side_effect = Exception("API Error")

        result = connector._list_courses_tool()
        assert result["ok"] is False
        assert "Failed" in result["error"]


# ─────────────────────────────────────────────────────────────────
# list_coursework tool handler
# ─────────────────────────────────────────────────────────────────


class TestListCourseworkTool:
    def test_success(self, connector):
        mock_svc = connector.service
        mock_svc.courses().courseWork().list().execute.return_value = {
            "courseWork": [_make_coursework()]
        }

        result = connector._list_coursework_tool(course_id="c1")
        assert result["ok"] is True
        assert result["count"] == 1
        assert result["assignments"][0]["title"] == "Odev 1"
        assert result["assignments"][0]["due_display"] == "2025-06-15 23:59"

    def test_empty_result(self, connector):
        mock_svc = connector.service
        mock_svc.courses().courseWork().list().execute.return_value = {"courseWork": []}

        result = connector._list_coursework_tool(course_id="c1")
        assert result["ok"] is True
        assert result["count"] == 0

    def test_api_error(self, connector):
        mock_svc = connector.service
        mock_svc.courses().courseWork().list().execute.side_effect = Exception("Not found")

        result = connector._list_coursework_tool(course_id="bad_id")
        assert result["ok"] is False


# ─────────────────────────────────────────────────────────────────
# submission_status tool handler
# ─────────────────────────────────────────────────────────────────


class TestSubmissionStatusTool:
    def test_success(self, connector):
        mock_svc = connector.service
        mock_svc.courses().courseWork().studentSubmissions().list().execute.return_value = {
            "studentSubmissions": [_make_submission()]
        }

        result = connector._submission_status_tool(course_id="c1")
        assert result["ok"] is True
        assert result["count"] == 1
        assert result["submissions"][0]["is_submitted"] is True
        assert result["submissions"][0]["assigned_grade"] == 85.0

    def test_with_coursework_id(self, connector):
        mock_svc = connector.service
        mock_svc.courses().courseWork().studentSubmissions().list().execute.return_value = {
            "studentSubmissions": [_make_submission("s2", "NEW")]
        }

        result = connector._submission_status_tool(course_id="c1", coursework_id="cw1")
        assert result["ok"] is True
        assert result["submissions"][0]["is_submitted"] is False

    def test_api_error(self, connector):
        mock_svc = connector.service
        mock_svc.courses().courseWork().studentSubmissions().list().execute.side_effect = Exception("Auth")

        result = connector._submission_status_tool(course_id="c1")
        assert result["ok"] is False


# ─────────────────────────────────────────────────────────────────
# Metadata & Policy
# ─────────────────────────────────────────────────────────────────


class TestClassroomMetadata:
    def test_courses_is_safe(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk
        assert get_tool_risk("google.classroom.courses") == ToolRisk.SAFE

    def test_coursework_is_safe(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk
        assert get_tool_risk("google.classroom.coursework") == ToolRisk.SAFE

    def test_submissions_is_safe(self):
        from bantz.tools.metadata import get_tool_risk, ToolRisk
        assert get_tool_risk("google.classroom.submissions") == ToolRisk.SAFE
