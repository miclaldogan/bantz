# SPDX-License-Identifier: MIT
"""Issue #660: 'ara' regex must not capture calendar/gmail queries."""

from bantz.nlu.hybrid import RegexPatterns


def test_takvime_etkinlik_ara_not_browser_search():
    rp = RegexPatterns()
    result = rp.match("takvime etkinlik ara")
    assert result is None or result.intent != "browser_search"


def test_gmail_mesaj_ara_not_browser_search():
    rp = RegexPatterns()
    result = rp.match("gmail mesaj ara")
    assert result is None or result.intent != "browser_search"


def test_pure_web_search_still_works():
    rp = RegexPatterns()
    result = rp.match("python regex örnekleri ara")
    assert result is not None
    assert result.intent == "browser_search"
    assert result.confidence <= 0.85


def test_randevu_ara_not_browser():
    rp = RegexPatterns()
    result = rp.match("randevu ara")
    assert result is None or result.intent != "browser_search"
