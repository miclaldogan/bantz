"""Google Contacts Connector — People API integration.

Issue #1292: Provides search, get, and create operations for Google Contacts
via the unified ``GoogleAuthManager``.  Leverages the People API v1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from bantz.connectors.google.base import GoogleConnector, ToolSchema

logger = logging.getLogger(__name__)

__all__ = ["ContactsConnector", "Contact"]

# Fields to request from People API
_PERSON_FIELDS = (
    "names,emailAddresses,phoneNumbers,organizations,photos,"
    "biographies,birthdays,addresses"
)

_SEARCH_READ_MASK = "names,emailAddresses,phoneNumbers,organizations,photos"


@dataclass
class Contact:
    """A contact from Google People API."""

    resource_name: str = ""
    display_name: str = ""
    given_name: str = ""
    family_name: str = ""
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    organization: str = ""
    photo_url: str = ""
    birthday: str = ""
    address: str = ""
    notes: str = ""

    @property
    def primary_email(self) -> str:
        return self.emails[0] if self.emails else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_name": self.resource_name,
            "display_name": self.display_name,
            "given_name": self.given_name,
            "family_name": self.family_name,
            "emails": self.emails,
            "phones": self.phones,
            "organization": self.organization,
            "photo_url": self.photo_url,
            "birthday": self.birthday,
            "address": self.address,
            "notes": self.notes,
        }


def _parse_person(person: dict) -> Contact:
    """Parse a People API person resource into a ``Contact``."""
    names = person.get("names", [])
    emails = person.get("emailAddresses", [])
    phones = person.get("phoneNumbers", [])
    orgs = person.get("organizations", [])
    photos = person.get("photos", [])
    bdays = person.get("birthdays", [])
    addrs = person.get("addresses", [])
    bios = person.get("biographies", [])

    return Contact(
        resource_name=person.get("resourceName", ""),
        display_name=names[0].get("displayName", "") if names else "",
        given_name=names[0].get("givenName", "") if names else "",
        family_name=names[0].get("familyName", "") if names else "",
        emails=[e.get("value", "") for e in emails if e.get("value")],
        phones=[p.get("value", "") for p in phones if p.get("value")],
        organization=orgs[0].get("name", "") if orgs else "",
        photo_url=photos[0].get("url", "") if photos else "",
        birthday=_format_birthday(bdays[0].get("date", {})) if bdays else "",
        address=_format_address(addrs[0]) if addrs else "",
        notes=bios[0].get("value", "") if bios else "",
    )


def _format_birthday(date_obj: dict) -> str:
    """Format a Google date object to ``YYYY-MM-DD`` or ``MM-DD``."""
    year = date_obj.get("year")
    month = date_obj.get("month", 0)
    day = date_obj.get("day", 0)
    if year:
        return "%04d-%02d-%02d" % (year, month, day)
    if month and day:
        return "%02d-%02d" % (month, day)
    return ""


def _format_address(addr: dict) -> str:
    """Concatenate address parts into a single string."""
    return addr.get("formattedValue", "") or addr.get("streetAddress", "")


class ContactsConnector(GoogleConnector):
    """Google Contacts service connector.

    Provides:
    - ``search_contacts(query)`` — search by name, email, or phone
    - ``get_contact(resource_name)`` — fetch full contact details
    - ``create_contact(name, email, phone)`` — create a new contact
    """

    SERVICE_NAME = "contacts"

    async def search_contacts(
        self,
        query: str,
        *,
        max_results: int = 10,
    ) -> list[Contact]:
        """Search Google Contacts by name, email, or phone.

        Parameters
        ----------
        query : str
            Free-text search query.
        max_results : int
            Maximum number of contacts to return.

        Returns
        -------
        list[Contact]
            Matching contacts.
        """
        try:
            result = (
                self.service.people()
                .searchContacts(
                    query=query,
                    pageSize=min(max_results, 30),
                    readMask=_SEARCH_READ_MASK,
                )
                .execute()
            )
            results = result.get("results", [])
            return [
                _parse_person(r.get("person", {}))
                for r in results
                if r.get("person")
            ]
        except Exception as exc:
            logger.error("Contacts arama hatası: %s", exc)
            raise

    async def get_contact(self, resource_name: str) -> Optional[Contact]:
        """Fetch a single contact by ``resourceName``.

        Parameters
        ----------
        resource_name : str
            The People API resource name (e.g. ``"people/c123"``).

        Returns
        -------
        Contact or None
            The contact, or ``None`` if not found.
        """
        try:
            person = (
                self.service.people()
                .get(resourceName=resource_name, personFields=_PERSON_FIELDS)
                .execute()
            )
            return _parse_person(person)
        except Exception as exc:
            logger.error("Contact getirme hatası (%s): %s", resource_name, exc)
            return None

    async def create_contact(
        self,
        name: str,
        email: str,
        phone: Optional[str] = None,
    ) -> Optional[Contact]:
        """Create a new Google contact.

        Parameters
        ----------
        name : str
            Full display name.
        email : str
            Primary email address.
        phone : str, optional
            Phone number.

        Returns
        -------
        Contact or None
            The created contact, or ``None`` on failure.
        """
        body: dict[str, Any] = {
            "names": [{"givenName": name}],
            "emailAddresses": [{"value": email}],
        }
        if phone:
            body["phoneNumbers"] = [{"value": phone}]

        try:
            person = (
                self.service.people()
                .createContact(body=body)
                .execute()
            )
            contact = _parse_person(person)
            logger.info("Kişi oluşturuldu: %s (%s)", name, email)
            return contact
        except Exception as exc:
            logger.error("Kişi oluşturma hatası: %s", exc)
            return None

    # ── Tool handlers (sync wrappers) ───────────────────────────

    def _search_tool(self, query: str, **_kw: Any) -> dict:
        """Sync tool handler for contacts search."""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    contacts = pool.submit(
                        asyncio.run, self.search_contacts(query)
                    ).result()
            else:
                contacts = loop.run_until_complete(self.search_contacts(query))
        except RuntimeError:
            contacts = asyncio.run(self.search_contacts(query))
        except Exception as exc:
            return self._err("Kişi arama hatası: %s" % exc)

        return self._ok(
            contacts=[c.to_dict() for c in contacts],
            count=len(contacts),
        )

    def _get_tool(self, resource_name: str, **_kw: Any) -> dict:
        """Sync tool handler for contact get."""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    contact = pool.submit(
                        asyncio.run, self.get_contact(resource_name)
                    ).result()
            else:
                contact = loop.run_until_complete(self.get_contact(resource_name))
        except RuntimeError:
            contact = asyncio.run(self.get_contact(resource_name))
        except Exception as exc:
            return self._err("Kişi getirme hatası: %s" % exc)

        if contact is None:
            return self._err("Kişi bulunamadı: %s" % resource_name)
        return self._ok(contact=contact.to_dict())

    def _create_tool(
        self,
        name: str,
        email: str,
        phone: Optional[str] = None,
        **_kw: Any,
    ) -> dict:
        """Sync tool handler for contact creation."""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    contact = pool.submit(
                        asyncio.run, self.create_contact(name, email, phone)
                    ).result()
            else:
                contact = loop.run_until_complete(
                    self.create_contact(name, email, phone)
                )
        except RuntimeError:
            contact = asyncio.run(self.create_contact(name, email, phone))
        except Exception as exc:
            return self._err("Kişi oluşturma hatası: %s" % exc)

        if contact is None:
            return self._err("Kişi oluşturulamadı")
        return self._ok(contact=contact.to_dict())

    # ── ToolSchema registration ─────────────────────────────────

    def get_tools(self) -> list[ToolSchema]:
        """Return tool descriptors for the contacts connector."""
        return [
            ToolSchema(
                name="google.contacts.search",
                description="Google kişilerinde arama yap — isim, email veya telefon.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Arama sorgusu (isim, email veya telefon)",
                        },
                    },
                    "required": ["query"],
                },
                handler=self._search_tool,
                risk="low",
            ),
            ToolSchema(
                name="google.contacts.get",
                description="Google kişisinin detaylı bilgisini getir.",
                parameters={
                    "type": "object",
                    "properties": {
                        "resource_name": {
                            "type": "string",
                            "description": "Kişi resource name (ör. people/c123)",
                        },
                    },
                    "required": ["resource_name"],
                },
                handler=self._get_tool,
                risk="low",
            ),
            ToolSchema(
                name="google.contacts.create",
                description="Yeni Google kişisi oluştur.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Kişi adı",
                        },
                        "email": {
                            "type": "string",
                            "description": "E-posta adresi",
                        },
                        "phone": {
                            "type": "string",
                            "description": "Telefon numarası (opsiyonel)",
                        },
                    },
                    "required": ["name", "email"],
                },
                handler=self._create_tool,
                risk="medium",
                confirm=True,
            ),
        ]
