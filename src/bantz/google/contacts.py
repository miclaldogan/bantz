"""Google People API integration for contact sync.

Provides:
- OAuth2 authentication reusing Bantz's existing Google auth infra
- Contact search: name → email, phone → name
- Two-way sync: Google Contacts ↔ local contacts.json
- Resolution helper for "Ahmet'e mail at" → auto email lookup
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PEOPLE_API_SCOPES = [
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/contacts",
]

# Fields to request from People API
PERSON_FIELDS = "names,emailAddresses,phoneNumbers,organizations,photos"

# Sync defaults
DEFAULT_SYNC_PAGE_SIZE = 100
MAX_SYNC_PAGES = 20


@dataclass
class GoogleContact:
    """A contact fetched from Google People API."""

    resource_name: str  # e.g. "people/c1234567890"
    display_name: str = ""
    given_name: str = ""
    family_name: str = ""
    emails: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    organization: str = ""
    photo_url: str = ""
    etag: str = ""

    @property
    def primary_email(self) -> str:
        return self.emails[0] if self.emails else ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_name": self.resource_name,
            "display_name": self.display_name,
            "given_name": self.given_name,
            "family_name": self.family_name,
            "emails": self.emails,
            "phones": self.phones,
            "organization": self.organization,
            "photo_url": self.photo_url,
        }


@dataclass
class SyncResult:
    """Result of a sync operation."""

    added: int = 0
    updated: int = 0
    deleted: int = 0
    errors: int = 0
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "added": self.added,
            "updated": self.updated,
            "deleted": self.deleted,
            "errors": self.errors,
            "duration_ms": round(self.duration_ms, 1),
            "timestamp": self.timestamp,
        }


def _build_service(credentials):
    """Build Google People API service from credentials."""
    try:
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Google API dependencies not installed. "
            "Install with: pip install google-api-python-client google-auth-oauthlib"
        ) from exc

    return build("people", "v1", credentials=credentials, cache_discovery=False)


class GoogleContactsClient:
    """Client for Google People API.

    Example::

        from bantz.google.contacts import GoogleContactsClient

        client = GoogleContactsClient()
        results = client.search("Ahmet")
        for contact in results:
            print(contact.display_name, contact.primary_email)
    """

    def __init__(self, credentials=None):
        """
        Args:
            credentials: Google OAuth credentials. If ``None``, fetched
                via ``bantz.google.auth.get_credentials``.
        """
        self._credentials = credentials
        self._service = None

    def _get_service(self):
        if self._service is None:
            if self._credentials is None:
                from bantz.google.auth import get_credentials

                self._credentials = get_credentials(
                    scopes=PEOPLE_API_SCOPES, interactive=False
                )
            self._service = _build_service(self._credentials)
        return self._service

    # ── search ───────────────────────────────────────────────────

    def search(self, query: str, max_results: int = 10) -> List[GoogleContact]:
        """Search contacts by name, email, or phone.

        Args:
            query: Search string (e.g. "Ahmet", "ahmet@gmail.com").
            max_results: Maximum results to return.

        Returns:
            List of matching GoogleContact objects.
        """
        service = self._get_service()
        try:
            response = (
                service.people()
                .searchContacts(
                    query=query,
                    readMask=PERSON_FIELDS,
                    pageSize=min(max_results, 30),
                )
                .execute()
            )
        except Exception as exc:
            logger.error("People API search failed: %s", exc)
            return []

        results = response.get("results", [])
        return [self._parse_person(r.get("person", {})) for r in results]

    def get_all(
        self, page_size: int = DEFAULT_SYNC_PAGE_SIZE, max_pages: int = MAX_SYNC_PAGES
    ) -> List[GoogleContact]:
        """Fetch all contacts (paginated).

        Returns:
            Full list of GoogleContact objects.
        """
        service = self._get_service()
        contacts: List[GoogleContact] = []
        page_token: Optional[str] = None

        for _ in range(max_pages):
            try:
                kwargs: Dict[str, Any] = {
                    "resourceName": "people/me",
                    "personFields": PERSON_FIELDS,
                    "pageSize": page_size,
                }
                if page_token:
                    kwargs["pageToken"] = page_token

                response = service.people().connections().list(**kwargs).execute()
            except Exception as exc:
                logger.error("People API list failed: %s", exc)
                break

            connections = response.get("connections", [])
            contacts.extend(self._parse_person(p) for p in connections)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return contacts

    def get_by_resource(self, resource_name: str) -> Optional[GoogleContact]:
        """Get a single contact by resource name."""
        service = self._get_service()
        try:
            person = (
                service.people()
                .get(resourceName=resource_name, personFields=PERSON_FIELDS)
                .execute()
            )
            return self._parse_person(person)
        except Exception as exc:
            logger.error("People API get failed for %s: %s", resource_name, exc)
            return None

    # ── parsing ──────────────────────────────────────────────────

    @staticmethod
    def _parse_person(person: Dict[str, Any]) -> GoogleContact:
        names = person.get("names", [])
        display_name = names[0].get("displayName", "") if names else ""
        given_name = names[0].get("givenName", "") if names else ""
        family_name = names[0].get("familyName", "") if names else ""

        emails = [
            e.get("value", "") for e in person.get("emailAddresses", []) if e.get("value")
        ]
        phones = [
            p.get("value", "") for p in person.get("phoneNumbers", []) if p.get("value")
        ]

        orgs = person.get("organizations", [])
        organization = orgs[0].get("name", "") if orgs else ""

        photos = person.get("photos", [])
        photo_url = photos[0].get("url", "") if photos else ""

        return GoogleContact(
            resource_name=person.get("resourceName", ""),
            display_name=display_name,
            given_name=given_name,
            family_name=family_name,
            emails=emails,
            phones=phones,
            organization=organization,
            photo_url=photo_url,
            etag=person.get("etag", ""),
        )


class ContactSyncer:
    """Two-way sync between Google Contacts and local contacts.json.

    Example::

        syncer = ContactSyncer()
        result = syncer.sync_from_google()
        print(f"Added {result.added}, updated {result.updated}")
    """

    def __init__(
        self,
        client: Optional[GoogleContactsClient] = None,
        contacts_path: Optional[str] = None,
    ):
        self._client = client or GoogleContactsClient()
        self._contacts_path = contacts_path

    def sync_from_google(self) -> SyncResult:
        """Pull contacts from Google → local store.

        Adds new contacts and updates existing ones (Google wins on conflict).
        """
        from bantz.contacts.store import contacts_upsert, contacts_resolve

        start = time.time()
        result = SyncResult()

        try:
            google_contacts = self._client.get_all()
        except Exception as exc:
            logger.error("Failed to fetch Google contacts: %s", exc)
            result.errors += 1
            result.duration_ms = (time.time() - start) * 1000
            return result

        for gc in google_contacts:
            if not gc.primary_email:
                continue

            try:
                existing = contacts_resolve(name=gc.display_name, path=self._contacts_path)
                if existing.get("ok"):
                    if existing.get("email") != gc.primary_email:
                        contacts_upsert(
                            name=gc.display_name,
                            email=gc.primary_email,
                            notes=gc.organization or None,
                            path=self._contacts_path,
                        )
                        result.updated += 1
                else:
                    contacts_upsert(
                        name=gc.display_name,
                        email=gc.primary_email,
                        notes=gc.organization or None,
                        path=self._contacts_path,
                    )
                    result.added += 1
            except Exception as exc:
                logger.warning("Sync error for %s: %s", gc.display_name, exc)
                result.errors += 1

        result.duration_ms = (time.time() - start) * 1000
        return result

    def sync_to_google(self) -> SyncResult:
        """Push local contacts → Google (creates new contacts for unknowns).

        Note: Only creates, does not update existing Google contacts.
        """
        from bantz.contacts.store import contacts_list

        start = time.time()
        result = SyncResult()

        try:
            local = contacts_list(path=self._contacts_path)
        except Exception as exc:
            logger.error("Failed to read local contacts: %s", exc)
            result.errors += 1
            result.duration_ms = (time.time() - start) * 1000
            return result

        for entry in local.get("contacts", []):
            name = entry.get("name", "")
            email = entry.get("email", "")

            if not name or not email:
                continue

            # Check if already in Google
            existing = self._client.search(email, max_results=1)
            if existing:
                continue

            try:
                self._create_google_contact(name, email, entry.get("notes"))
                result.added += 1
            except Exception as exc:
                logger.warning("Failed to create Google contact for %s: %s", name, exc)
                result.errors += 1

        result.duration_ms = (time.time() - start) * 1000
        return result

    def _create_google_contact(
        self, name: str, email: str, notes: Optional[str] = None
    ) -> None:
        """Create a new contact in Google People API."""
        service = self._client._get_service()

        body: Dict[str, Any] = {
            "names": [{"givenName": name}],
            "emailAddresses": [{"value": email}],
        }

        service.people().createContact(body=body).execute()


def resolve_contact_email(name: str, contacts_path: Optional[str] = None) -> Optional[str]:
    """Resolve a contact name to email, trying local first then Google.

    This is the convenience function for "Ahmet'e mail at" scenarios.

    Args:
        name: Contact name to look up.
        contacts_path: Optional path to contacts.json.

    Returns:
        Email address or None.
    """
    from bantz.contacts.store import contacts_resolve

    # Try local first
    local = contacts_resolve(name=name, path=contacts_path)
    if local.get("ok"):
        return local.get("email")

    # Try Google
    try:
        client = GoogleContactsClient()
        results = client.search(name, max_results=1)
        if results and results[0].primary_email:
            # Cache in local store for next time
            from bantz.contacts.store import contacts_upsert

            contacts_upsert(
                name=name,
                email=results[0].primary_email,
                path=contacts_path,
            )
            return results[0].primary_email
    except Exception as exc:
        logger.debug("Google contacts lookup failed for %r: %s", name, exc)

    return None
