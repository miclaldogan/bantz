"""Tests for Issue #1320: Pre-compiled regex patterns.

Verifies that hoisting re.compile() calls to module/class level
preserves the original matching behaviour.
"""

from __future__ import annotations

import re

# ── slots.py module-level regex ───────────────────────────────────────────


class TestSlotsModuleLevelRegex:
    """Verify the five module-level regex constants in slots.py."""

    def test_url_pattern_matches_http(self):
        from bantz.nlu.slots import _URL_PATTERN_RE

        m = _URL_PATTERN_RE.search("git clone https://github.com/user/repo merhaba")
        assert m is not None
        assert m.group(1) == "https://github.com/user/repo"

    def test_url_pattern_matches_http_unsecured(self):
        from bantz.nlu.slots import _URL_PATTERN_RE

        m = _URL_PATTERN_RE.search("bak http://example.com/page?q=1")
        assert m is not None
        assert m.group(1) == "http://example.com/page?q=1"

    def test_domain_pattern_matches(self):
        from bantz.nlu.slots import _DOMAIN_PATTERN_RE

        m = _DOMAIN_PATTERN_RE.search("github.com'a gir")
        assert m is not None
        assert m.group(1) == "github"
        assert m.group(2) == "com"

    def test_domain_pattern_ai_suffix(self):
        from bantz.nlu.slots import _DOMAIN_PATTERN_RE

        m = _DOMAIN_PATTERN_RE.search("openai.ai sitesine bak")
        assert m is not None
        assert m.group(2) == "ai"

    def test_search_pattern_turkish(self):
        from bantz.nlu.slots import _SEARCH_PATTERN_RE

        m = _SEARCH_PATTERN_RE.search("youtube'da python dersleri ara")
        assert m is not None
        assert m.group(1).lower() == "youtube"
        assert "python" in m.group(2).lower()

    def test_reverse_pattern_turkish(self):
        from bantz.nlu.slots import _REVERSE_PATTERN_RE

        m = _REVERSE_PATTERN_RE.search("python dersleri ara youtube'da")
        assert m is not None
        assert "python" in m.group(1).lower()

    def test_simple_search_pattern(self):
        from bantz.nlu.slots import _SIMPLE_SEARCH_RE

        m = _SIMPLE_SEARCH_RE.search("hava durumu ara")
        assert m is not None
        assert "hava" in m.group(1).lower()


# ── slots.py extract_url / extract_query end-to-end ──────────────────────


class TestExtractUrlEndToEnd:
    """extract_url() still works after regex hoisting."""

    def test_full_url(self):
        from bantz.nlu.slots import extract_url

        result = extract_url("https://github.com/miclaldogan/bantz adresine git")
        assert result is not None
        assert result.url == "https://github.com/miclaldogan/bantz"
        assert result.is_full_url is True

    def test_domain_url(self):
        from bantz.nlu.slots import extract_url

        result = extract_url("github.com'a bak")
        assert result is not None
        assert result.site_name == "github"

    def test_no_url(self):
        from bantz.nlu.slots import extract_url

        result = extract_url("bugün hava nasıl")
        assert result is None


class TestExtractQueryEndToEnd:
    """extract_query() still works after regex hoisting."""

    def test_site_query(self):
        from bantz.nlu.slots import extract_query

        result = extract_query("youtube'da python dersleri ara")
        assert result is not None
        assert "python" in result.query.lower()

    def test_simple_query(self):
        from bantz.nlu.slots import extract_query

        result = extract_query("hava durumu ara")
        assert result is not None
        assert "hava" in result.query.lower()

    def test_no_query(self):
        from bantz.nlu.slots import extract_query

        result = extract_query("merhaba nasılsın")
        assert result is None


# ── llm_router.py class-level regex ──────────────────────────────────────


class TestLLMRouterClassLevelRegex:
    """Verify the four class-level regex constants on JarvisLLMOrchestrator."""

    def test_type_prefix_re(self):
        from bantz.brain.llm_router import JarvisLLMOrchestrator as J

        assert J._TYPE_PREFIX_RE.sub("", "str: hello") == "hello"
        assert J._TYPE_PREFIX_RE.sub("", "email: foo@bar.com") == "foo@bar.com"
        assert J._TYPE_PREFIX_RE.sub("", "null: ") == ""

    def test_placeholder_re(self):
        from bantz.brain.llm_router import JarvisLLMOrchestrator as J

        assert J._PLACEHOLDER_RE.match("<YYYY-MM-DD veya null>")
        assert not J._PLACEHOLDER_RE.match("normal text")

    def test_valid_time_re(self):
        from bantz.brain.llm_router import JarvisLLMOrchestrator as J

        assert J._VALID_TIME_RE.match("14:30")
        assert not J._VALID_TIME_RE.match("2pm")

    def test_valid_date_re(self):
        from bantz.brain.llm_router import JarvisLLMOrchestrator as J

        assert J._VALID_DATE_RE.match("2025-01-15")
        assert not J._VALID_DATE_RE.match("15/01/2025")

    def test_junk_values(self):
        from bantz.brain.llm_router import JarvisLLMOrchestrator as J

        assert "null" in J._JUNK_VALUES
        assert "pm" in J._JUNK_VALUES
        assert "hello" not in J._JUNK_VALUES

    def test_instruction_fragments(self):
        from bantz.brain.llm_router import JarvisLLMOrchestrator as J

        assert "belirtilmedi" in J._INSTRUCTION_FRAGMENTS
        assert isinstance(J._INSTRUCTION_FRAGMENTS, tuple)


# ── Compile-once guarantee ───────────────────────────────────────────────


class TestCompileOnceGuarantee:
    """Ensure regex objects are the same object across calls (not recompiled)."""

    def test_slots_url_pattern_is_singleton(self):
        from bantz.nlu import slots

        assert slots._URL_PATTERN_RE is slots._URL_PATTERN_RE  # trivially True
        # The real check: it's a compiled pattern, not a string
        assert isinstance(slots._URL_PATTERN_RE, re.Pattern)

    def test_router_type_prefix_is_compiled(self):
        from bantz.brain.llm_router import JarvisLLMOrchestrator as J

        assert isinstance(J._TYPE_PREFIX_RE, re.Pattern)
        assert isinstance(J._VALID_TIME_RE, re.Pattern)
