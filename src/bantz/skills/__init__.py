"""
Bantz Skills Package.

Provides various skills for Bantz assistant including:
- daily: Basic daily tasks (browser, notifications, etc.)
- pc: PC control (apps, mouse, keyboard)
- news: Jarvis-style news briefing system
- summarizer: Page content extraction and LLM summarization
  - Enhanced with caching, progress callbacks, history, and length options
"""

from bantz.skills.daily import (
    open_btop,
    open_browser,
    open_path,
    open_url,
    google_search,
    notify,
)

from bantz.skills.news import (
    NewsItem,
    NewsSearchResult,
    NewsBriefing,
    MockNewsBriefing,
    extract_news_query,
    is_news_intent,
)

from bantz.skills.summarizer import (
    # Enums
    SummaryLength,
    ProgressStage,
    # Data Classes
    PageSummary,
    ExtractedPage,
    CacheEntry,
    # Core Classes
    SummaryCache,
    SummaryHistory,
    RateLimiter,
    PageSummarizer,
    MockPageSummarizer,
    # Helper Functions
    extract_question,
    parse_summary_length,
)

__all__ = [
    # Daily skills
    "open_btop",
    "open_browser",
    "open_path",
    "open_url",
    "google_search",
    "notify",
    # News skills
    "NewsItem",
    "NewsSearchResult",
    "NewsBriefing",
    "MockNewsBriefing",
    "extract_news_query",
    "is_news_intent",
    # Summarizer skills - Enums
    "SummaryLength",
    "ProgressStage",
    # Summarizer skills - Data Classes
    "PageSummary",
    "ExtractedPage",
    "CacheEntry",
    # Summarizer skills - Core Classes
    "SummaryCache",
    "SummaryHistory",
    "RateLimiter",
    "PageSummarizer",
    "MockPageSummarizer",
    # Summarizer skills - Helper Functions
    "extract_question",
    "parse_summary_length",
]
