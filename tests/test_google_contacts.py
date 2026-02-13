"""Tests for Google Contacts integration (Issue #860)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from bantz.google.contacts import (
    GoogleContact,
    GoogleContactsClient,
    ContactSyncer,
    SyncResult,
    resolve_contact_email,
    PEOPLE_API_SCOPES,
    PERSON_FIELDS,
)


# ── GoogleContact ────────────────────────────────────────────────

class TestGoogleContact:

    def test_primary_email(self):
        c = GoogleContact(resource_name="people/1", emails=["a@b.com", "c@d.com"])
        assert c.primary_email == "a@b.com"

    def test_primary_email_empty(self):
        c = GoogleContact(resource_name="people/1")
        assert c.primary_email == ""

    def test_to_dict(self):
        c = GoogleContact(
            resource_name="people/1",
            display_name="Test",
            emails=["x@y.com"],
            phones=["+90555"],
        )
        d = c.to_dict()
        assert d["display_name"] == "Test"
        assert d["emails"] == ["x@y.com"]
        assert d["phones"] == ["+90555"]


# ── SyncResult ───────────────────────────────────────────────────

class TestSyncResult:

    def test_to_dict(self):
        r = SyncResult(added=3, updated=1, errors=0)
        d = r.to_dict()
        assert d["added"] == 3
        assert "timestamp" in d


# ── GoogleContactsClient ────────────────────────────────────────

class TestGoogleContactsClient:

    def _mock_service(self):
        service = MagicMock()
        return service

    def test_parse_person_full(self):
        person = {
            "resourceName": "people/c123",
            "names": [{"displayName": "Ali Veli", "givenName": "Ali", "familyName": "Veli"}],
            "emailAddresses": [{"value": "ali@test.com"}],
            "phoneNumbers": [{"value": "+905551234"}],
            "organizations": [{"name": "Acme"}],
            "photos": [{"url": "https://photo.url"}],
            "etag": "abc",
        }
        c = GoogleContactsClient._parse_person(person)
        assert c.display_name == "Ali Veli"
        assert c.given_name == "Ali"
        assert c.family_name == "Veli"
        assert c.emails == ["ali@test.com"]
        assert c.phones == ["+905551234"]
        assert c.organization == "Acme"
        assert c.photo_url == "https://photo.url"

    def test_parse_person_empty(self):
        c = GoogleContactsClient._parse_person({})
        assert c.display_name == ""
        assert c.emails == []

    @patch.object(GoogleContactsClient, "_get_service")
    def test_search(self, mock_get):
        service = self._mock_service()
        mock_get.return_value = service

        service.people.return_value.searchContacts.return_value.execute.return_value = {
            "results": [
                {"person": {"resourceName": "people/1", "names": [{"displayName": "test"}]}}
            ]
        }

        client = GoogleContactsClient(credentials=MagicMock())
        results = client.search("test")
        assert len(results) == 1
        assert results[0].display_name == "test"

    @patch.object(GoogleContactsClient, "_get_service")
    def test_search_error(self, mock_get):
        service = self._mock_service()
        mock_get.return_value = service
        service.people.return_value.searchContacts.return_value.execute.side_effect = Exception("API error")

        client = GoogleContactsClient(credentials=MagicMock())
        results = client.search("test")
        assert results == []

    @patch.object(GoogleContactsClient, "_get_service")
    def test_get_all_pagination(self, mock_get):
        service = self._mock_service()
        mock_get.return_value = service

        page1 = {
            "connections": [{"resourceName": "people/1", "names": [{"displayName": "A"}]}],
            "nextPageToken": "page2",
        }
        page2 = {
            "connections": [{"resourceName": "people/2", "names": [{"displayName": "B"}]}],
        }

        service.people.return_value.connections.return_value.list.return_value.execute.side_effect = [
            page1, page2
        ]

        client = GoogleContactsClient(credentials=MagicMock())
        contacts = client.get_all(page_size=1, max_pages=5)
        assert len(contacts) == 2

    @patch.object(GoogleContactsClient, "_get_service")
    def test_get_by_resource(self, mock_get):
        service = self._mock_service()
        mock_get.return_value = service
        service.people.return_value.get.return_value.execute.return_value = {
            "resourceName": "people/1",
            "names": [{"displayName": "Ali"}],
        }

        client = GoogleContactsClient(credentials=MagicMock())
        c = client.get_by_resource("people/1")
        assert c is not None
        assert c.display_name == "Ali"


# ── ContactSyncer ───────────────────────────────────────────────

class TestContactSyncer:

    @patch("bantz.google.contacts.contacts_resolve")
    @patch("bantz.google.contacts.contacts_upsert")
    def test_sync_from_google_adds(self, mock_upsert, mock_resolve):
        mock_resolve.return_value = {"ok": False}
        mock_upsert.return_value = {"ok": True}

        mock_client = MagicMock()
        mock_client.get_all.return_value = [
            GoogleContact(resource_name="p/1", display_name="A", emails=["a@b.com"]),
        ]

        syncer = ContactSyncer(client=mock_client)
        result = syncer.sync_from_google()
        assert result.added == 1
        assert result.updated == 0

    @patch("bantz.google.contacts.contacts_resolve")
    @patch("bantz.google.contacts.contacts_upsert")
    def test_sync_from_google_updates(self, mock_upsert, mock_resolve):
        mock_resolve.return_value = {"ok": True, "email": "old@b.com"}
        mock_upsert.return_value = {"ok": True}

        mock_client = MagicMock()
        mock_client.get_all.return_value = [
            GoogleContact(resource_name="p/1", display_name="A", emails=["new@b.com"]),
        ]

        syncer = ContactSyncer(client=mock_client)
        result = syncer.sync_from_google()
        assert result.updated == 1

    @patch("bantz.google.contacts.contacts_resolve")
    def test_sync_from_google_skip_no_email(self, mock_resolve):
        mock_client = MagicMock()
        mock_client.get_all.return_value = [
            GoogleContact(resource_name="p/1", display_name="NoEmail"),
        ]

        syncer = ContactSyncer(client=mock_client)
        result = syncer.sync_from_google()
        assert result.added == 0

    def test_sync_from_google_fetch_error(self):
        mock_client = MagicMock()
        mock_client.get_all.side_effect = Exception("fail")

        syncer = ContactSyncer(client=mock_client)
        result = syncer.sync_from_google()
        assert result.errors == 1


# ── resolve_contact_email ────────────────────────────────────────

class TestResolveContactEmail:

    @patch("bantz.google.contacts.contacts_resolve")
    def test_local_hit(self, mock_resolve):
        mock_resolve.return_value = {"ok": True, "email": "ali@x.com"}
        assert resolve_contact_email("Ali") == "ali@x.com"

    @patch("bantz.google.contacts.GoogleContactsClient")
    @patch("bantz.google.contacts.contacts_resolve")
    def test_google_fallback(self, mock_resolve, MockClient):
        mock_resolve.return_value = {"ok": False}

        mock_instance = MockClient.return_value
        mock_instance.search.return_value = [
            GoogleContact(resource_name="p/1", display_name="Ali", emails=["ali@g.com"]),
        ]

        with patch("bantz.google.contacts.contacts_upsert"):
            result = resolve_contact_email("Ali")
        assert result == "ali@g.com"

    @patch("bantz.google.contacts.GoogleContactsClient")
    @patch("bantz.google.contacts.contacts_resolve")
    def test_not_found(self, mock_resolve, MockClient):
        mock_resolve.return_value = {"ok": False}
        MockClient.return_value.search.return_value = []
        assert resolve_contact_email("Unknown") is None
