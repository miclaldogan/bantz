"""Travel Assistant skill — flight/hotel/car booking management.

Issue #1299: Gelecek Yetenekler — Faz G+

Status: PLANNED — skeleton only.
Dependencies: Gmail Enhanced (EPIC 5), Graf Bellek (EPIC 2).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Booking:
    """Generic booking record."""

    booking_type: str  # flight | hotel | car
    provider: str = ""
    confirmation: str = ""
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": self.booking_type,
            "provider": self.provider,
        }
        if self.confirmation:
            d["confirmation"] = self.confirmation
        if self.start:
            d["start"] = self.start.isoformat()
        if self.end:
            d["end"] = self.end.isoformat()
        if self.details:
            d["details"] = self.details
        return d


@dataclass
class Trip:
    """Organized trip with bookings."""

    name: str
    destination: str = ""
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    bookings: List[Booking] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"name": self.name}
        if self.destination:
            d["destination"] = self.destination
        if self.start_date:
            d["start_date"] = self.start_date.isoformat()
        if self.end_date:
            d["end_date"] = self.end_date.isoformat()
        d["bookings"] = [b.to_dict() for b in self.bookings]
        return d


class TravelAssistant(ABC):
    """Abstract base for travel management.

    Concrete implementation depends on Gmail Enhanced and
    Graf Bellek EPICs.
    """

    @abstractmethod
    def parse_bookings(
        self,
        period: str = "upcoming",
    ) -> List[Booking]:
        """Parse booking information from emails."""
        ...

    @abstractmethod
    def create_itinerary(
        self,
        trip_name: str,
        bookings: List[Booking],
    ) -> Trip:
        """Create an organized trip itinerary."""
        ...

    @abstractmethod
    def set_reminders(
        self,
        trip: Trip,
        reminder_types: Optional[List[str]] = None,
    ) -> int:
        """Set proactive reminders for trip events.

        Returns count of reminders created.
        """
        ...


class PlaceholderTravelAssistant(TravelAssistant):
    """Placeholder — returns stub data."""

    def parse_bookings(
        self,
        period: str = "upcoming",
    ) -> List[Booking]:
        logger.info("[Travel] parse_bookings called — stub mode")
        return []

    def create_itinerary(
        self,
        trip_name: str,
        bookings: Optional[List[Booking]] = None,
    ) -> Trip:
        return Trip(name=trip_name)

    def set_reminders(
        self,
        trip: Trip,
        reminder_types: Optional[List[str]] = None,
    ) -> int:
        return 0
