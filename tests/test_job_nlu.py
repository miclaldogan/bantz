"""
Tests for NLU Job Control intents (Issue #31 - V2-1).

Tests the job control pattern matching in NLU.
"""

import pytest

from bantz.router.nlu import parse_intent


class TestJobPauseIntent:
    """Test job_pause intent recognition."""
    
    def test_bekle_pause(self):
        """'bekle' → job_pause"""
        assert parse_intent("bekle").intent == "job_pause"
    
    def test_dur_pause(self):
        """'dur' → job_pause"""
        assert parse_intent("dur").intent == "job_pause"
    
    def test_bir_saniye_pause(self):
        """'bir saniye' → job_pause"""
        assert parse_intent("bir saniye").intent == "job_pause"
    
    def test_durakla_pause(self):
        """'durakla' → job_pause"""
        assert parse_intent("durakla").intent == "job_pause"
    
    def test_pause_english(self):
        """'pause' → job_pause"""
        assert parse_intent("pause").intent == "job_pause"



class TestJobResumeIntent:
    """Test job_resume intent recognition."""
    
    def test_devam_et_resume(self):
        """'devam et' → job_resume"""
        assert parse_intent("devam et").intent == "job_resume"
    
    def test_devam_resume(self):
        """'devam' → job_resume"""
        assert parse_intent("devam").intent == "job_resume"
    
    def test_surdur_resume(self):
        """'sürdür' → job_resume"""
        assert parse_intent("sürdür").intent == "job_resume"
    
    def test_continue_english(self):
        """'continue' → job_resume"""
        assert parse_intent("continue").intent == "job_resume"


class TestJobCancelIntent:
    """Test job_cancel intent recognition."""
    
    def test_iptal_cancel(self):
        """'iptal' → job_cancel"""
        assert parse_intent("iptal").intent == "job_cancel"
    
    def test_vazgec_cancel(self):
        """'vazgeç' → job_cancel"""
        assert parse_intent("vazgeç").intent == "job_cancel"
    
    def test_cancel_english(self):
        """'cancel' → job_cancel"""
        assert parse_intent("cancel").intent == "job_cancel"
    
    def test_birak_cancel(self):
        """'bırak' → job_cancel"""
        assert parse_intent("bırak").intent == "job_cancel"
    
    def test_bosver_cancel(self):
        """'boşver' → job_cancel"""
        assert parse_intent("boşver").intent == "job_cancel"


class TestJobStatusIntent:
    """Test job_status intent recognition."""
    
    def test_ne_yapiyorsun_status(self):
        """'ne yapıyorsun' → job_status"""
        assert parse_intent("ne yapıyorsun").intent == "job_status"
    
    def test_durum_status(self):
        """'durum' → job_status"""
        assert parse_intent("durum").intent == "job_status"
    
    def test_neredesin_status(self):
        """'neredesin' → job_status"""
        assert parse_intent("neredesin").intent == "job_status"
    
    def test_status_english(self):
        """'status' → job_status"""
        assert parse_intent("status").intent == "job_status"


class TestJobControlCaseSensitivity:
    """Test case insensitivity."""
    
    def test_bekle_upper_case(self):
        """'BEKLE' → job_pause (case insensitive)"""
        assert parse_intent("BEKLE").intent == "job_pause"
    
    def test_devam_mixed_case(self):
        """'DeVaM Et' → job_resume (case insensitive)"""
        assert parse_intent("DeVaM Et").intent == "job_resume"
    
    def test_iptal_upper(self):
        """'IPTAL' → job_cancel (case insensitive)"""
        assert parse_intent("IPTAL").intent == "job_cancel"


class TestJobControlPriority:
    """Test that job control has high priority (matches before other intents)."""
    
    def test_dur_over_other_intents(self):
        """'dur' specifically matches job_pause."""
        result = parse_intent("dur")
        assert result.intent == "job_pause"
    
    def test_iptal_over_other_intents(self):
        """'iptal' specifically matches job_cancel."""
        result = parse_intent("iptal")
        assert result.intent == "job_cancel"
