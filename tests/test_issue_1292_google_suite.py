"""Tests for Issue #1292 — Google Suite Super-Connector.

Tests cover:
- GoogleAuthManager (unified token, scope management, migration)
- GoogleConnector base class
- ContactsConnector, TasksConnector, KeepConnector, ClassroomConnector
- GoogleEntityLinker (cross-service linking)
- Tool registration via register_all.py
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_token_dir(tmp_path: Path):
    """Create a temp directory for token files."""
    token_dir = tmp_path / "google"
    token_dir.mkdir()
    return token_dir


@pytest.fixture
def mock_credentials():
    """Create a mock Google OAuth Credentials object."""
    creds = MagicMock()
    creds.scopes = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/gmail.modify",
    ]
    creds.expired = False
    creds.valid = True
    creds.refresh_token = "fake-refresh-token"
    creds.to_json.return_value = json.dumps({
        "token": "fake-token",
        "refresh_token": "fake-refresh-token",
        "scopes": creds.scopes,
    })
    creds.has_scopes = MagicMock(return_value=True)
    return creds


@pytest.fixture
def mock_google_deps(mock_credentials):
    """Patch Google API imports."""
    mock_request = MagicMock()
    mock_creds_cls = MagicMock()
    mock_creds_cls.from_authorized_user_file.return_value = mock_credentials
    mock_flow = MagicMock()
    mock_build = MagicMock()

    with patch(
        "bantz.connectors.google.auth_manager._import_google_deps",
        return_value=(mock_request, mock_creds_cls, mock_flow, mock_build),
    ):
        yield {
            "Request": mock_request,
            "Credentials": mock_creds_cls,
            "InstalledAppFlow": mock_flow,
            "build": mock_build,
        }


@pytest.fixture
def auth_manager(tmp_token_dir, mock_google_deps, mock_credentials):
    """Create a GoogleAuthManager with temp paths and mocked deps."""
    from bantz.connectors.google.auth_manager import GoogleAuthManager

    token_path = str(tmp_token_dir / "google_unified_token.json")
    secret_path = str(tmp_token_dir / "client_secret.json")

    # Write a fake client secret
    (tmp_token_dir / "client_secret.json").write_text(
        json.dumps({"installed": {"client_id": "fake", "client_secret": "fake"}}),
        encoding="utf-8",
    )

    # Write a fake token
    Path(token_path).write_text(mock_credentials.to_json(), encoding="utf-8")

    mgr = GoogleAuthManager(
        token_path=token_path,
        client_secret_path=secret_path,
        interactive=False,
    )
    return mgr


# ═══════════════════════════════════════════════════════════════════
# GoogleAuthManager tests
# ═══════════════════════════════════════════════════════════════════


class TestGoogleAuthManager:
    """Tests for the unified GoogleAuthManager."""

    def test_scope_registry_contains_all_services(self):
        from bantz.connectors.google.auth_manager import SCOPE_REGISTRY

        expected_services = {"gmail", "calendar", "contacts", "tasks", "keep", "classroom"}
        assert set(SCOPE_REGISTRY.keys()) == expected_services

    def test_service_map_matches_scope_registry(self):
        from bantz.connectors.google.auth_manager import (SCOPE_REGISTRY,
                                                          SERVICE_MAP)

        assert set(SERVICE_MAP.keys()) == set(SCOPE_REGISTRY.keys())

    def test_ensure_scope_known_service(self, auth_manager):
        creds = auth_manager.ensure_scope("calendar")
        assert creds is not None

    def test_ensure_scope_unknown_service_raises(self, auth_manager):
        with pytest.raises(ValueError, match="Bilinmeyen Google servisi"):
            auth_manager.ensure_scope("nonexistent")

    def test_get_service_returns_cached(self, auth_manager, mock_google_deps):
        svc1 = auth_manager.get_service("calendar")
        svc2 = auth_manager.get_service("calendar")
        # build() should only be called once
        assert mock_google_deps["build"].call_count == 1
        assert svc1 is svc2

    def test_invalidate_cache_specific(self, auth_manager, mock_google_deps):
        auth_manager.get_service("calendar")
        auth_manager.invalidate_cache("calendar")
        auth_manager.get_service("calendar")
        assert mock_google_deps["build"].call_count == 2

    def test_invalidate_cache_all(self, auth_manager, mock_google_deps):
        auth_manager.get_service("calendar")
        auth_manager.invalidate_cache()
        auth_manager.get_service("calendar")
        assert mock_google_deps["build"].call_count == 2

    def test_current_scopes(self, auth_manager):
        scopes = auth_manager.current_scopes()
        assert isinstance(scopes, list)

    def test_connected_services(self, auth_manager):
        services = auth_manager.connected_services()
        assert isinstance(services, list)

    def test_effective_scopes_expands_implied(self, auth_manager):
        granted = ["https://www.googleapis.com/auth/gmail.modify"]
        effective = auth_manager._effective_scopes(granted)
        assert "https://www.googleapis.com/auth/gmail.readonly" in effective
        assert "https://www.googleapis.com/auth/gmail.send" in effective

    def test_effective_scopes_calendar(self, auth_manager):
        granted = ["https://www.googleapis.com/auth/calendar"]
        effective = auth_manager._effective_scopes(granted)
        assert "https://www.googleapis.com/auth/calendar.readonly" in effective
        assert "https://www.googleapis.com/auth/calendar.events" in effective

    def test_effective_scopes_empty(self, auth_manager):
        effective = auth_manager._effective_scopes(None)
        assert effective == set()

    def test_get_credentials_bridge(self, auth_manager):
        creds = auth_manager.get_credentials(
            scopes=["https://www.googleapis.com/auth/calendar"]
        )
        assert creds is not None

    def test_expand_scopes_non_interactive_raises(self, auth_manager):
        # Force credentials to None so a scope expansion is needed
        auth_manager._credentials = None
        auth_manager._load_credentials = MagicMock()  # prevent file load

        with pytest.raises(RuntimeError, match="yetkilendirmesi gerekli"):
            auth_manager._expand_scopes(["https://www.googleapis.com/auth/tasks"])

    def test_save_token_atomic(self, auth_manager, mock_credentials):
        auth_manager._credentials = mock_credentials
        auth_manager._save_token()
        assert auth_manager.token_path.exists()
        content = json.loads(auth_manager.token_path.read_text(encoding="utf-8"))
        assert "token" in content

    def test_migrate_legacy_no_files(self, auth_manager):
        result = auth_manager.migrate_legacy_tokens()
        # Both files likely don't exist at the temp path
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════
# Singleton tests
# ═══════════════════════════════════════════════════════════════════


class TestSingleton:
    """Tests for the auth manager singleton pattern."""

    def test_setup_and_get(self, tmp_token_dir, mock_google_deps):
        import bantz.connectors.google.auth_manager as mod
        from bantz.connectors.google.auth_manager import (get_auth_manager,
                                                          setup_auth_manager)

        # Save and restore singleton
        prev = mod._auth_manager
        try:
            mod._auth_manager = None

            mgr = setup_auth_manager(
                token_path=str(tmp_token_dir / "test_token.json"),
                client_secret_path=str(tmp_token_dir / "test_secret.json"),
                interactive=False,
            )
            assert mgr is not None
            assert get_auth_manager() is mgr
        finally:
            mod._auth_manager = prev


# ═══════════════════════════════════════════════════════════════════
# GoogleConnector base tests
# ═══════════════════════════════════════════════════════════════════


class TestGoogleConnectorBase:
    """Tests for the GoogleConnector abstract base class."""

    def test_service_name_required(self, auth_manager):
        from bantz.connectors.google.base import GoogleConnector

        class BadConnector(GoogleConnector):
            def get_tools(self):
                return []

        with pytest.raises(NotImplementedError, match="SERVICE_NAME"):
            BadConnector(auth_manager)

    def test_ok_helper(self, auth_manager):
        from bantz.connectors.google.contacts import ContactsConnector

        c = ContactsConnector(auth_manager)
        result = c._ok(foo="bar")
        assert result == {"ok": True, "foo": "bar"}

    def test_err_helper(self, auth_manager):
        from bantz.connectors.google.contacts import ContactsConnector

        c = ContactsConnector(auth_manager)
        result = c._err("something failed")
        assert result == {"ok": False, "error": "something failed"}


# ═══════════════════════════════════════════════════════════════════
# ContactsConnector tests
# ═══════════════════════════════════════════════════════════════════


class TestContactsConnector:
    """Tests for the Google Contacts connector."""

    def test_parse_person(self):
        from bantz.connectors.google.contacts import _parse_person

        person = {
            "resourceName": "people/c123",
            "names": [{"displayName": "Ali Yılmaz", "givenName": "Ali", "familyName": "Yılmaz"}],
            "emailAddresses": [{"value": "ali@example.com"}],
            "phoneNumbers": [{"value": "+905551234567"}],
            "organizations": [{"name": "Bantz Inc"}],
            "photos": [{"url": "https://photo.example.com/ali"}],
        }
        contact = _parse_person(person)
        assert contact.display_name == "Ali Yılmaz"
        assert contact.primary_email == "ali@example.com"
        assert contact.phones == ["+905551234567"]
        assert contact.organization == "Bantz Inc"

    def test_parse_person_empty(self):
        from bantz.connectors.google.contacts import _parse_person

        contact = _parse_person({})
        assert contact.display_name == ""
        assert contact.emails == []
        assert contact.resource_name == ""

    def test_contact_to_dict(self):
        from bantz.connectors.google.contacts import Contact

        c = Contact(display_name="Test", emails=["test@test.com"])
        d = c.to_dict()
        assert d["display_name"] == "Test"
        assert d["emails"] == ["test@test.com"]

    def test_get_tools_returns_three(self, auth_manager):
        from bantz.connectors.google.contacts import ContactsConnector

        c = ContactsConnector(auth_manager)
        tools = c.get_tools()
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert "google.contacts.search" in names
        assert "google.contacts.get" in names
        assert "google.contacts.create" in names

    def test_format_birthday_full(self):
        from bantz.connectors.google.contacts import _format_birthday

        assert _format_birthday({"year": 1990, "month": 5, "day": 15}) == "1990-05-15"

    def test_format_birthday_month_day(self):
        from bantz.connectors.google.contacts import _format_birthday

        assert _format_birthday({"month": 12, "day": 25}) == "12-25"

    def test_format_birthday_empty(self):
        from bantz.connectors.google.contacts import _format_birthday

        assert _format_birthday({}) == ""


# ═══════════════════════════════════════════════════════════════════
# TasksConnector tests
# ═══════════════════════════════════════════════════════════════════


class TestTasksConnector:
    """Tests for the Google Tasks connector."""

    def test_parse_task(self):
        from bantz.connectors.google.tasks import _parse_task

        t = _parse_task({
            "id": "task123",
            "title": "Rapor hazırla",
            "status": "needsAction",
            "due": "2025-01-15T00:00:00Z",
            "notes": "Acil",
        })
        assert t.id == "task123"
        assert t.title == "Rapor hazırla"
        assert not t.is_completed

    def test_task_completed(self):
        from bantz.connectors.google.tasks import Task

        t = Task(status="completed")
        assert t.is_completed

    def test_task_to_dict(self):
        from bantz.connectors.google.tasks import Task

        t = Task(id="t1", title="Test", status="needsAction")
        d = t.to_dict()
        assert d["id"] == "t1"
        assert d["is_completed"] is False

    def test_task_list_to_dict(self):
        from bantz.connectors.google.tasks import TaskList

        tl = TaskList(id="list1", title="My Tasks")
        d = tl.to_dict()
        assert d["id"] == "list1"
        assert d["title"] == "My Tasks"

    def test_get_tools_returns_four(self, auth_manager):
        from bantz.connectors.google.tasks import TasksConnector

        c = TasksConnector(auth_manager)
        tools = c.get_tools()
        assert len(tools) == 4
        names = {t.name for t in tools}
        assert "google.tasks.list" in names
        assert "google.tasks.create" in names
        assert "google.tasks.complete" in names
        assert "google.tasks.delete" in names


# ═══════════════════════════════════════════════════════════════════
# KeepConnector tests
# ═══════════════════════════════════════════════════════════════════


class TestKeepConnector:
    """Tests for the Google Keep connector."""

    def test_parse_note_text(self):
        from bantz.connectors.google.keep import _parse_note

        note = _parse_note({
            "name": "notes/abc123",
            "title": "Alışveriş Listesi",
            "body": {"text": {"text": "Süt, yumurta, ekmek"}},
        })
        assert note.name == "notes/abc123"
        assert note.title == "Alışveriş Listesi"
        assert note.body == "Süt, yumurta, ekmek"

    def test_parse_note_list(self):
        from bantz.connectors.google.keep import _parse_note

        note = _parse_note({
            "name": "notes/list1",
            "title": "Yapılacaklar",
            "body": {
                "list": {
                    "listItems": [
                        {"text": {"text": "Süt al"}, "checked": False},
                        {"text": {"text": "Yumurta al"}, "checked": True},
                    ]
                }
            },
        })
        assert "☐ Süt al" in note.body
        assert "☑ Yumurta al" in note.body

    def test_parse_note_empty(self):
        from bantz.connectors.google.keep import _parse_note

        note = _parse_note({})
        assert note.name == ""
        assert note.body == ""

    def test_note_to_dict(self):
        from bantz.connectors.google.keep import Note

        n = Note(name="notes/1", title="Test", body="Content")
        d = n.to_dict()
        assert d["name"] == "notes/1"
        assert d["title"] == "Test"

    def test_get_tools_returns_three(self, auth_manager):
        from bantz.connectors.google.keep import KeepConnector

        c = KeepConnector(auth_manager)
        tools = c.get_tools()
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert "google.keep.list" in names
        assert "google.keep.create" in names
        assert "google.keep.search" in names

    def test_check_availability_when_unavailable(self, auth_manager):
        import bantz.connectors.google.keep as keep_mod
        from bantz.connectors.google.keep import KeepConnector

        c = KeepConnector(auth_manager)
        # Simulate API unavailable
        prev = keep_mod._KEEP_API_AVAILABLE
        try:
            keep_mod._KEEP_API_AVAILABLE = False
            err = c._check_availability()
            assert err is not None
            assert "Workspace" in err
        finally:
            keep_mod._KEEP_API_AVAILABLE = prev


# ═══════════════════════════════════════════════════════════════════
# ClassroomConnector tests
# ═══════════════════════════════════════════════════════════════════


class TestClassroomConnector:
    """Tests for the Google Classroom connector."""

    def test_parse_due_full(self):
        from bantz.connectors.google.classroom import _parse_due

        date_str, time_str = _parse_due(
            {"year": 2025, "month": 3, "day": 15},
            {"hours": 23, "minutes": 59},
        )
        assert date_str == "2025-03-15"
        assert time_str == "23:59"

    def test_parse_due_no_time(self):
        from bantz.connectors.google.classroom import _parse_due

        date_str, time_str = _parse_due(
            {"year": 2025, "month": 1, "day": 1},
            None,
        )
        assert date_str == "2025-01-01"
        assert time_str == ""

    def test_parse_due_empty(self):
        from bantz.connectors.google.classroom import _parse_due

        date_str, time_str = _parse_due(None, None)
        assert date_str == ""
        assert time_str == ""

    def test_course_to_dict(self):
        from bantz.connectors.google.classroom import Course

        c = Course(id="c1", name="Matematik", state="ACTIVE")
        d = c.to_dict()
        assert d["id"] == "c1"
        assert d["name"] == "Matematik"

    def test_assignment_due_display(self):
        from bantz.connectors.google.classroom import Assignment

        a = Assignment(due_date="2025-03-15", due_time="23:59")
        assert a.due_display == "2025-03-15 23:59"

        a2 = Assignment(due_date="2025-03-15")
        assert a2.due_display == "2025-03-15"

        a3 = Assignment()
        assert a3.due_display == "Tarih yok"

    def test_submission_is_submitted(self):
        from bantz.connectors.google.classroom import Submission

        s = Submission(state="TURNED_IN")
        assert s.is_submitted

        s2 = Submission(state="NEW")
        assert not s2.is_submitted

    def test_get_tools_returns_three(self, auth_manager):
        from bantz.connectors.google.classroom import ClassroomConnector

        c = ClassroomConnector(auth_manager)
        tools = c.get_tools()
        assert len(tools) == 3
        names = {t.name for t in tools}
        assert "google.classroom.courses" in names
        assert "google.classroom.coursework" in names
        assert "google.classroom.submissions" in names


# ═══════════════════════════════════════════════════════════════════
# GoogleEntityLinker tests
# ═══════════════════════════════════════════════════════════════════


class TestGoogleEntityLinker:
    """Tests for cross-service entity linking."""

    def test_link_no_connectors(self):
        from bantz.connectors.google.entity_linker import GoogleEntityLinker

        linker = GoogleEntityLinker()
        assert linker.links == []

    @pytest.mark.asyncio
    async def test_link_attendee_to_contact(self):
        from bantz.connectors.google.contacts import Contact
        from bantz.connectors.google.entity_linker import GoogleEntityLinker

        mock_contacts = MagicMock()
        mock_contacts.search_contacts = AsyncMock(return_value=[
            Contact(
                resource_name="people/c123",
                display_name="Ali Yılmaz",
                emails=["ali@example.com"],
                phones=["+905551234567"],
            )
        ])

        linker = GoogleEntityLinker(contacts_connector=mock_contacts)
        result = await linker.link_attendee_to_contact("ali@example.com")

        assert result is not None
        assert result["display_name"] == "Ali Yılmaz"
        assert len(linker.links) == 1
        assert linker.links[0].edge_type == "HAS_CONTACT_INFO"

    @pytest.mark.asyncio
    async def test_link_attendee_not_found(self):
        from bantz.connectors.google.entity_linker import GoogleEntityLinker

        mock_contacts = MagicMock()
        mock_contacts.search_contacts = AsyncMock(return_value=[])

        linker = GoogleEntityLinker(contacts_connector=mock_contacts)
        result = await linker.link_attendee_to_contact("unknown@example.com")

        assert result is None
        assert len(linker.links) == 0

    @pytest.mark.asyncio
    async def test_link_attendee_no_connector(self):
        from bantz.connectors.google.entity_linker import GoogleEntityLinker

        linker = GoogleEntityLinker()
        result = await linker.link_attendee_to_contact("test@example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_link_task_to_event(self):
        from bantz.connectors.google.entity_linker import GoogleEntityLinker

        async def mock_list_events(date: str):
            return [
                {"id": "evt1", "summary": "Rapor toplantısı"},
                {"id": "evt2", "summary": "Öğle yemeği"},
            ]

        linker = GoogleEntityLinker(calendar_list_events=mock_list_events)
        result = await linker.link_task_to_event(
            "Rapor toplantısı notları", "2025-01-15T00:00:00Z",
        )

        # "Rapor toplantısı notları" vs "Rapor toplantısı" should match (high similarity)
        assert result is not None
        assert len(linker.links) == 1
        assert linker.links[0].edge_type == "RELATED_TO"

    @pytest.mark.asyncio
    async def test_link_task_no_match(self):
        from bantz.connectors.google.entity_linker import GoogleEntityLinker

        async def mock_list_events(date: str):
            return [{"id": "evt1", "summary": "Tamamen farklı bir konu"}]

        linker = GoogleEntityLinker(calendar_list_events=mock_list_events)
        result = await linker.link_task_to_event(
            "Alışveriş yap", "2025-01-15",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_batch_link_attendees(self):
        from bantz.connectors.google.contacts import Contact
        from bantz.connectors.google.entity_linker import GoogleEntityLinker

        mock_contacts = MagicMock()

        async def search_side_effect(query):
            if "ali" in query:
                return [Contact(resource_name="p/1", display_name="Ali")]
            return []

        mock_contacts.search_contacts = AsyncMock(side_effect=search_side_effect)

        linker = GoogleEntityLinker(contacts_connector=mock_contacts)
        results = await linker.link_attendees_to_contacts(
            ["ali@test.com", "unknown@test.com"]
        )

        assert results["ali@test.com"] is not None
        assert results["unknown@test.com"] is None

    @pytest.mark.asyncio
    async def test_resolve_event_attendees(self):
        from bantz.connectors.google.contacts import Contact
        from bantz.connectors.google.entity_linker import GoogleEntityLinker

        mock_contacts = MagicMock()
        mock_contacts.search_contacts = AsyncMock(return_value=[
            Contact(resource_name="p/1", display_name="Ali")
        ])

        linker = GoogleEntityLinker(contacts_connector=mock_contacts)
        event = {
            "id": "evt1",
            "attendees": [
                {"email": "ali@test.com"},
                {"email": "mehmet@test.com"},
            ],
        }

        enriched = await linker.resolve_event_attendees(event)
        assert "attendee_contacts" in enriched
        assert len(enriched["attendee_contacts"]) == 2

    def test_links_summary(self):
        from bantz.connectors.google.entity_linker import (EntityLink,
                                                           GoogleEntityLinker)

        linker = GoogleEntityLinker()
        linker._links = [
            EntityLink("A", "1", "LINK", "B", "2"),
            EntityLink("A", "3", "LINK", "B", "4"),
        ]
        summary = linker.get_links_summary()
        assert summary["total_links"] == 2
        assert "A→B" in summary["by_type"]

    def test_clear_links(self):
        from bantz.connectors.google.entity_linker import (EntityLink,
                                                           GoogleEntityLinker)

        linker = GoogleEntityLinker()
        linker._links = [EntityLink("A", "1", "LINK", "B", "2")]
        linker.clear_links()
        assert len(linker.links) == 0


# ═══════════════════════════════════════════════════════════════════
# ToolSchema tests
# ═══════════════════════════════════════════════════════════════════


class TestToolSchema:
    """Tests for the ToolSchema descriptor."""

    def test_tool_schema_fields(self):
        from bantz.connectors.google.base import ToolSchema

        ts = ToolSchema(
            name="test.tool",
            description="Test tool",
            parameters={"type": "object", "properties": {}},
            handler=lambda: None,
            risk="low",
            confirm=False,
        )
        assert ts.name == "test.tool"
        assert ts.risk == "low"
        assert ts.confirm is False

    def test_tool_schema_defaults(self):
        from bantz.connectors.google.base import ToolSchema

        ts = ToolSchema(
            name="t", description="d", parameters={}, handler=lambda: None,
        )
        assert ts.risk == "low"
        assert ts.confirm is False


# ═══════════════════════════════════════════════════════════════════
# Auth bridge tests (legacy → unified)
# ═══════════════════════════════════════════════════════════════════


class TestAuthBridge:
    """Test that legacy auth functions delegate to unified manager."""

    def test_google_auth_bridge(self, auth_manager, mock_google_deps):
        """When unified manager is available, get_credentials delegates."""
        import bantz.connectors.google.auth_manager as mod

        prev = mod._auth_manager
        try:
            mod._auth_manager = auth_manager

            from bantz.google.auth import get_credentials

            # This should use the unified manager
            creds = get_credentials(
                scopes=["https://www.googleapis.com/auth/calendar"],
            )
            assert creds is not None
        finally:
            mod._auth_manager = prev

    def test_gmail_auth_bridge(self, auth_manager, mock_google_deps):
        """When unified manager is available, get_gmail_credentials delegates."""
        import bantz.connectors.google.auth_manager as mod

        prev = mod._auth_manager
        try:
            mod._auth_manager = auth_manager

            from bantz.google.gmail_auth import get_gmail_credentials

            creds = get_gmail_credentials(
                scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            )
            assert creds is not None
        finally:
            mod._auth_manager = prev


# ═══════════════════════════════════════════════════════════════════
# EntityLink tests
# ═══════════════════════════════════════════════════════════════════


class TestEntityLink:
    """Tests for the EntityLink dataclass."""

    def test_to_dict(self):
        from bantz.connectors.google.entity_linker import EntityLink

        link = EntityLink(
            source_type="Task",
            source_id="t1",
            edge_type="RELATED_TO",
            target_type="Event",
            target_id="e1",
            metadata={"similarity": 0.85},
        )
        d = link.to_dict()
        assert d["source_type"] == "Task"
        assert d["edge_type"] == "RELATED_TO"
        assert d["metadata"]["similarity"] == 0.85


# ═══════════════════════════════════════════════════════════════════
# Config tests
# ═══════════════════════════════════════════════════════════════════


class TestUnifiedAuthConfig:
    """Tests for UnifiedAuthConfig and path resolution."""

    def test_default_config(self):
        from bantz.connectors.google.auth_manager import _get_unified_config

        cfg = _get_unified_config()
        assert str(cfg.token_path).endswith("google_unified_token.json")
        assert str(cfg.client_secret_path).endswith("client_secret.json")

    def test_custom_config(self, tmp_path):
        from bantz.connectors.google.auth_manager import _get_unified_config

        cfg = _get_unified_config(
            token_path=str(tmp_path / "my_token.json"),
            client_secret_path=str(tmp_path / "my_secret.json"),
        )
        assert cfg.token_path == (tmp_path / "my_token.json").resolve()

    def test_env_var_override(self, tmp_path, monkeypatch):
        from bantz.connectors.google.auth_manager import _get_unified_config

        monkeypatch.setenv("BANTZ_GOOGLE_UNIFIED_TOKEN_PATH", str(tmp_path / "env_token.json"))
        cfg = _get_unified_config()
        assert "env_token.json" in str(cfg.token_path)
