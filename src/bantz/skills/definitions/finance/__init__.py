"""Finance Tracker skill — expense parsing and budget analysis.

Issue #1299: Future Capabilities — Phase G+

Status: PLANNED — skeleton only.
Dependencies: Ingest Store (EPIC 1), Gmail Enhanced (EPIC 5).
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ExpenseCategory(str, Enum):
    """Expense categories."""

    FOOD = "food"
    TRANSPORT = "transport"
    ENTERTAINMENT = "entertainment"
    BILLS = "bills"
    SHOPPING = "shopping"
    HEALTH = "health"
    EDUCATION = "education"
    SUBSCRIPTION = "subscription"
    OTHER = "other"


@dataclass
class Expense:
    """Parsed expense record."""

    amount: float
    currency: str = "TRY"
    category: ExpenseCategory = ExpenseCategory.OTHER
    description: str = ""
    merchant: str = ""
    date: datetime = field(default_factory=datetime.now)
    source: str = "manual"  # gmail | manual

    def to_dict(self) -> Dict[str, Any]:
        return {
            "amount": self.amount,
            "currency": self.currency,
            "category": self.category.value,
            "description": self.description,
            "merchant": self.merchant,
            "date": self.date.isoformat(),
            "source": self.source,
        }


@dataclass
class BudgetAlert:
    """Budget threshold alert."""

    category: str
    budget: float
    spent: float
    remaining: float
    exceeded: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "budget": self.budget,
            "spent": self.spent,
            "remaining": self.remaining,
            "exceeded": self.exceeded,
        }


class FinanceTracker(ABC):
    """Abstract base for finance tracking.

    Concrete implementation will be activated when
    Ingest Store and Gmail Enhanced EPICs are complete.
    """

    @abstractmethod
    def parse_expenses(
        self,
        period: str = "this_month",
        source: str = "gmail",
    ) -> List[Expense]:
        """Parse expenses from bank emails or manual input."""
        ...

    @abstractmethod
    def monthly_summary(
        self,
        month: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate monthly expense summary with category breakdown."""
        ...

    @abstractmethod
    def check_budget(
        self,
        category: Optional[str] = None,
    ) -> List[BudgetAlert]:
        """Check budget limits and return alerts."""
        ...

    @abstractmethod
    def categorize(
        self,
        description: str,
        amount: float,
    ) -> ExpenseCategory:
        """Categorize an expense using LLM."""
        ...


# ── Bank Email Regex Patterns (Turkish banks) ───────────────────

BANK_PATTERNS = {
    "garanti": re.compile(
        r"(\d+[.,]\d{2})\s*(?:TL|TRY).*?(?:harcama|ödeme)",
        re.IGNORECASE,
    ),
    "is_bankasi": re.compile(
        r"(\d+[.,]\d{2})\s*(?:TL|TRY).*?(?:işlem|tahsilat)",
        re.IGNORECASE,
    ),
    "akbank": re.compile(
        r"(\d+[.,]\d{2})\s*(?:TL|TRY)",
        re.IGNORECASE,
    ),
}


class PlaceholderFinanceTracker(FinanceTracker):
    """Placeholder implementation — returns stub data.

    Will be replaced with real implementation when dependencies
    (Ingest Store, Gmail Enhanced) are available.
    """

    def parse_expenses(
        self,
        period: str = "this_month",
        source: str = "gmail",
    ) -> List[Expense]:
        logger.info("[Finance] parse_expenses called — stub mode")
        return []

    def monthly_summary(
        self,
        month: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "status": "planned",
            "message": "Finance tracking is not yet active. "
            "Will be activated after Ingest Store EPIC is complete.",
        }

    def check_budget(
        self,
        category: Optional[str] = None,
    ) -> List[BudgetAlert]:
        return []

    def categorize(
        self,
        description: str,
        amount: float,
    ) -> ExpenseCategory:
        return ExpenseCategory.OTHER
