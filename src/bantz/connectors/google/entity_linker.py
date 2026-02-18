"""Google Cross-Service Entity Linker — connects entities across Google services.

Issue #1292: Links Calendar attendees to Contacts, Tasks to Events,
and provides cross-service entity resolution.  Prepares entity
relationships for the graf bellek (EPIC 2) integration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = ["GoogleEntityLinker", "EntityLink"]


@dataclass
class EntityLink:
    """A link between two entities across Google services.

    Attributes
    ----------
    source_type : str
        Source entity type (e.g. ``"CalendarAttendee"``).
    source_id : str
        Source entity identifier (e.g. email address).
    edge_type : str
        Relationship type (e.g. ``"HAS_CONTACT_INFO"``).
    target_type : str
        Target entity type (e.g. ``"Contact"``).
    target_id : str
        Target entity identifier (e.g. resource name).
    metadata : dict
        Additional metadata about the link.
    """

    source_type: str
    source_id: str
    edge_type: str
    target_type: str
    target_id: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "edge_type": self.edge_type,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "metadata": self.metadata,
        }


class GoogleEntityLinker:
    """Cross-service entity linker for Google services.

    Connects entities found in one Google service to their counterparts
    in other services (e.g. Calendar attendee → Contact, Task → Event).

    Parameters
    ----------
    contacts_connector : ContactsConnector, optional
        For resolving email → contact lookups.
    tasks_connector : TasksConnector, optional
        For task-event matching.
    calendar_service : callable, optional
        A function that lists calendar events for a given date.
    """

    def __init__(
        self,
        *,
        contacts_connector: Any = None,
        tasks_connector: Any = None,
        calendar_list_events: Any = None,
    ):
        self._contacts = contacts_connector
        self._tasks = tasks_connector
        self._calendar_list_events = calendar_list_events
        self._links: list[EntityLink] = []

    @property
    def links(self) -> list[EntityLink]:
        """All discovered entity links."""
        return list(self._links)

    def clear_links(self) -> None:
        """Clear all discovered links."""
        self._links.clear()

    async def link_attendee_to_contact(
        self,
        attendee_email: str,
    ) -> Optional[dict]:
        """Find a Calendar attendee in Google Contacts.

        Parameters
        ----------
        attendee_email : str
            The email address of the calendar attendee.

        Returns
        -------
        dict or None
            Contact data if found, else ``None``.
        """
        if not self._contacts:
            logger.debug("Contacts connector yok — link atlanıyor")
            return None

        try:
            contacts = await self._contacts.search_contacts(attendee_email)
            if not contacts:
                return None

            contact = contacts[0]
            link = EntityLink(
                source_type="CalendarAttendee",
                source_id=attendee_email,
                edge_type="HAS_CONTACT_INFO",
                target_type="Contact",
                target_id=contact.resource_name,
                metadata={
                    "display_name": contact.display_name,
                    "phones": contact.phones,
                    "organization": contact.organization,
                },
            )
            self._links.append(link)
            logger.info(
                "Katılımcı→Kişi bağlantısı: %s → %s",
                attendee_email, contact.display_name,
            )
            return contact.to_dict()
        except Exception as exc:
            logger.warning(
                "Katılımcı→Kişi bağlantı hatası (%s): %s",
                attendee_email, exc,
            )
            return None

    async def link_attendees_to_contacts(
        self,
        attendee_emails: list[str],
    ) -> dict[str, Optional[dict]]:
        """Batch-link multiple calendar attendees to contacts.

        Returns
        -------
        dict[str, dict | None]
            Mapping of email → contact data (or ``None``).
        """
        results: dict[str, Optional[dict]] = {}
        for email in attendee_emails:
            results[email] = await self.link_attendee_to_contact(email)
        return results

    async def link_task_to_event(
        self,
        task_title: str,
        task_due: str,
        *,
        similarity_threshold: float = 0.6,
    ) -> Optional[dict]:
        """Match a Task to a Calendar event on the same day.

        Uses fuzzy title matching (``SequenceMatcher``) to find related
        events.

        Parameters
        ----------
        task_title : str
            The task title.
        task_due : str
            The task due date in ``YYYY-MM-DD`` or RFC 3339 format.
        similarity_threshold : float
            Minimum similarity ratio to consider a match (0.0–1.0).

        Returns
        -------
        dict or None
            Matching event data if found, else ``None``.
        """
        if not self._calendar_list_events:
            logger.debug("Calendar list_events yok — link atlanıyor")
            return None

        # Extract date portion
        date_str = task_due[:10] if len(task_due) >= 10 else task_due
        if not date_str:
            return None

        try:
            events = await self._calendar_list_events(date=date_str)
            if not events:
                return None

            best_match = None
            best_score = 0.0

            for event in events:
                event_title = ""
                if isinstance(event, dict):
                    event_title = event.get("summary", "") or event.get("title", "")
                    event_id = event.get("id", "")
                elif hasattr(event, "summary"):
                    event_title = getattr(event, "summary", "")
                    event_id = getattr(event, "id", "")
                else:
                    continue

                score = SequenceMatcher(
                    None,
                    task_title.lower(),
                    event_title.lower(),
                ).ratio()

                if score > best_score and score >= similarity_threshold:
                    best_score = score
                    best_match = event
                    best_match_id = event_id

            if best_match is not None:
                match_title = (
                    best_match.get("summary", "")
                    if isinstance(best_match, dict)
                    else getattr(best_match, "summary", "")
                )
                link = EntityLink(
                    source_type="Task",
                    source_id=task_title,
                    edge_type="RELATED_TO",
                    target_type="CalendarEvent",
                    target_id=best_match_id,
                    metadata={
                        "similarity": round(best_score, 3),
                        "event_title": match_title,
                        "date": date_str,
                    },
                )
                self._links.append(link)
                logger.info(
                    "Görev→Etkinlik bağlantısı: '%s' → '%s' (sim=%.2f)",
                    task_title, match_title, best_score,
                )
                if isinstance(best_match, dict):
                    return best_match
                return {"id": best_match_id, "summary": match_title}
        except Exception as exc:
            logger.warning(
                "Görev→Etkinlik bağlantı hatası ('%s'): %s",
                task_title, exc,
            )

        return None

    async def resolve_event_attendees(
        self,
        event: dict,
    ) -> dict:
        """Enrich a calendar event with contact info for all attendees.

        Parameters
        ----------
        event : dict
            A calendar event dict with an ``attendees`` field.

        Returns
        -------
        dict
            The event dict with an added ``attendee_contacts`` field.
        """
        attendees = event.get("attendees", [])
        emails = [
            a.get("email", "")
            for a in attendees
            if a.get("email")
        ]

        if not emails:
            event["attendee_contacts"] = []
            return event

        contacts = await self.link_attendees_to_contacts(emails)
        event["attendee_contacts"] = [
            {
                "email": email,
                "contact": contact_data,
                "resolved": contact_data is not None,
            }
            for email, contact_data in contacts.items()
        ]
        return event

    def get_links_summary(self) -> dict[str, Any]:
        """Return a summary of all discovered entity links."""
        by_type: dict[str, int] = {}
        for link in self._links:
            key = "%s→%s" % (link.source_type, link.target_type)
            by_type[key] = by_type.get(key, 0) + 1

        return {
            "total_links": len(self._links),
            "by_type": by_type,
            "links": [link.to_dict() for link in self._links],
        }
