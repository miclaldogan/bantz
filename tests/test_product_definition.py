"""
Tests for Issue #30: V2-0 Product Definition + Done Criteria

These tests validate:
1. Documentation files exist and have required content
2. Timing requirements are correctly defined
3. README links are valid
4. Acceptance criteria are measurable
"""

import os
import re
from pathlib import Path

import pytest

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
SRC_DIR = PROJECT_ROOT / "src"


class TestDocumentationExists:
    """Test that required documentation files exist."""
    
    def test_docs_roadmap_v2_exists(self):
        """docs/jarvis-roadmap-v2.md dosyası var."""
        roadmap_path = DOCS_DIR / "jarvis-roadmap-v2.md"
        assert roadmap_path.exists(), f"Missing: {roadmap_path}"
    
    def test_docs_acceptance_tests_exists(self):
        """docs/acceptance-tests.md dosyası var."""
        acceptance_path = DOCS_DIR / "acceptance-tests.md"
        assert acceptance_path.exists(), f"Missing: {acceptance_path}"
    
    def test_timing_module_exists(self):
        """src/bantz/core/timing.py dosyası var."""
        timing_path = SRC_DIR / "bantz" / "core" / "timing.py"
        assert timing_path.exists(), f"Missing: {timing_path}"


class TestRoadmapContent:
    """Test roadmap document content."""
    
    @pytest.fixture
    def roadmap_content(self):
        """Load roadmap content."""
        roadmap_path = DOCS_DIR / "jarvis-roadmap-v2.md"
        return roadmap_path.read_text(encoding="utf-8")
    
    def test_docs_phase0_done_criteria(self, roadmap_content):
        """Faz 0 bölümü mevcut."""
        assert "Faz 0" in roadmap_content or "Phase 0" in roadmap_content
        assert "Done" in roadmap_content or "done" in roadmap_content
    
    def test_roadmap_has_issue_links(self, roadmap_content):
        """Issue linkleri mevcut."""
        # Check for GitHub issue links
        issue_pattern = r"https://github\.com/miclaldogan/bantz/issues/\d+"
        matches = re.findall(issue_pattern, roadmap_content)
        assert len(matches) >= 5, f"Expected at least 5 issue links, found {len(matches)}"
    
    def test_roadmap_has_timing_section(self, roadmap_content):
        """Timing requirements bölümü mevcut."""
        assert "TimingRequirements" in roadmap_content or "timing" in roadmap_content.lower()
    
    def test_roadmap_has_architecture_diagram(self, roadmap_content):
        """Architecture diagram mevcut."""
        # Look for ASCII art diagram markers
        assert "┌" in roadmap_content or "Architecture" in roadmap_content


class TestAcceptanceTestsContent:
    """Test acceptance tests document content."""
    
    @pytest.fixture
    def acceptance_content(self):
        """Load acceptance tests content."""
        acceptance_path = DOCS_DIR / "acceptance-tests.md"
        return acceptance_path.read_text(encoding="utf-8")
    
    def test_has_scenario_1(self, acceptance_content):
        """Senaryo 1 mevcut."""
        assert "Senaryo 1" in acceptance_content or "Scenario 1" in acceptance_content
    
    def test_has_scenario_2(self, acceptance_content):
        """Senaryo 2 mevcut."""
        assert "Senaryo 2" in acceptance_content or "Scenario 2" in acceptance_content
    
    def test_has_scenario_3(self, acceptance_content):
        """Senaryo 3 mevcut."""
        assert "Senaryo 3" in acceptance_content or "Scenario 3" in acceptance_content
    
    def test_acceptance_criteria_measurable(self, acceptance_content):
        """Kriterler ölçülebilir metrikler içerir."""
        # Should have numeric thresholds
        assert "0.2" in acceptance_content or "200" in acceptance_content  # ACK time
        assert "30" in acceptance_content  # Summary time
        assert ">=" in acceptance_content or "≥" in acceptance_content  # Source count


class TestReadmeLinks:
    """Test README contains valid links."""
    
    @pytest.fixture
    def readme_content(self):
        """Load README content."""
        readme_path = PROJECT_ROOT / "README.md"
        return readme_path.read_text(encoding="utf-8")
    
    def test_readme_has_v2_roadmap_link(self, readme_content):
        """README V2 roadmap linkini içerir."""
        assert "jarvis-roadmap-v2.md" in readme_content or "roadmap" in readme_content.lower()
    
    def test_readme_has_acceptance_tests_link(self, readme_content):
        """README acceptance tests linkini veya referansını içerir."""
        assert "acceptance-tests.md" in readme_content or "acceptance" in readme_content.lower() or "test" in readme_content.lower()
    
    def test_readme_links_valid(self, readme_content):
        """README'deki lokal dosya linkleri geçerli."""
        # Find markdown links to docs/
        link_pattern = r"\[([^\]]+)\]\((docs/[^)]+)\)"
        matches = re.findall(link_pattern, readme_content)
        
        for link_text, link_path in matches:
            full_path = PROJECT_ROOT / link_path
            assert full_path.exists(), f"Broken link: {link_text} -> {link_path}"


class TestTimingRequirements:
    """Test timing module functionality."""
    
    def test_timing_import(self):
        """TimingRequirements import edilebilir."""
        from bantz.core.timing import TimingRequirements, TIMING
        assert TIMING is not None
    
    def test_timing_ack_max_ms(self):
        """ACK_MAX_MS = 200."""
        from bantz.core.timing import TIMING
        assert TIMING.ACK_MAX_MS == 200
    
    def test_timing_first_source_range(self):
        """İlk kaynak bulma süresi 3-10 saniye."""
        from bantz.core.timing import TIMING
        assert TIMING.FIRST_SOURCE_MIN_S == 3
        assert TIMING.FIRST_SOURCE_MAX_S == 10
    
    def test_timing_summary_max_s(self):
        """Özet süresi max 30 saniye."""
        from bantz.core.timing import TIMING
        assert TIMING.SUMMARY_MAX_S == 30
    
    def test_timing_permission_required(self):
        """Permission prompt zorunlu."""
        from bantz.core.timing import TIMING
        assert TIMING.PERMISSION_PROMPT_REQUIRED is True
    
    def test_is_ack_fast_enough(self):
        """is_ack_fast_enough helper çalışır."""
        from bantz.core.timing import is_ack_fast_enough
        assert is_ack_fast_enough(100) is True
        assert is_ack_fast_enough(200) is True
        assert is_ack_fast_enough(201) is False
    
    def test_is_source_time_valid(self):
        """is_source_time_valid helper çalışır."""
        from bantz.core.timing import is_source_time_valid
        assert is_source_time_valid(2) is False   # Too fast
        assert is_source_time_valid(5) is True    # In range
        assert is_source_time_valid(11) is False  # Too slow
    
    def test_is_summary_fast_enough(self):
        """is_summary_fast_enough helper çalışır."""
        from bantz.core.timing import is_summary_fast_enough
        assert is_summary_fast_enough(20) is True
        assert is_summary_fast_enough(30) is True
        assert is_summary_fast_enough(31) is False
    
    def test_get_retry_delay(self):
        """get_retry_delay exponential backoff döner."""
        from bantz.core.timing import get_retry_delay, TIMING
        assert get_retry_delay(1) == TIMING.RETRY_DELAY_1_S  # 1.0
        assert get_retry_delay(2) == TIMING.RETRY_DELAY_2_S  # 3.0
        assert get_retry_delay(3) == TIMING.RETRY_DELAY_3_S  # 7.0
        assert get_retry_delay(4) == TIMING.RETRY_DELAY_3_S  # Clamped to last
    
    def test_timing_metric(self):
        """TimingMetric doğru çalışır."""
        from bantz.core.timing import measure_ack_timing
        
        # Fast enough
        metric = measure_ack_timing(150)
        assert metric.passed is True
        assert metric.value_ms == 150
        assert metric.threshold_ms == 200
        
        # Too slow
        metric = measure_ack_timing(250)
        assert metric.passed is False
