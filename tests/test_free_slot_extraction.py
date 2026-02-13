# SPDX-License-Identifier: MIT
"""Tests for free slot request extraction (Issue #237)."""

from datetime import datetime

import pytest

from bantz.nlu.slots import extract_free_slot_request


class TestFreeSlotExtraction:
    """Test free slot request extraction."""
    
    def test_simple_query_uses_defaults(self):
        """Test 'uygun saat var mı' uses default 30m, today 09-18."""
        request = extract_free_slot_request("uygun saat var mı")
        
        assert request is not None
        assert request.duration_minutes == 30
        assert request.day == "bugün"
        assert request.window_start == "09:00"
        assert request.window_end == "18:00"
        assert request.needs_clarification is False
    
    def test_with_duration(self):
        """Test '1 saatlik boşluk' extracts 60 minutes."""
        request = extract_free_slot_request("yarın 1 saatlik boşluk var mı")
        
        assert request is not None
        assert request.duration_minutes == 60
        assert request.day == "yarın"
    
    def test_with_explicit_minutes(self):
        """Test '45 dakika' extracts duration."""
        request = extract_free_slot_request("bugün 45 dakika boş zaman var mı")
        
        assert request is not None
        assert request.duration_minutes == 45
        assert request.day == "bugün"
    
    def test_two_hour_duration(self):
        """Test '2 saatlik' extracts 120 minutes."""
        request = extract_free_slot_request("2 saatlik toplantı için uygun saat")
        
        assert request is not None
        assert request.duration_minutes == 120
    
    def test_with_day_of_week(self):
        """Test 'pazartesi' extracts day."""
        request = extract_free_slot_request("pazartesi boş zaman var mı")
        
        assert request is not None
        assert request.day == "pazartesi"
        assert request.duration_minutes == 30  # default
    
    def test_afternoon_window(self):
        """Test 'öğleden sonra' sets 13-18 window."""
        request = extract_free_slot_request("bugün öğleden sonra uygun saat")
        
        assert request is not None
        assert request.window_start == "13:00"
        assert request.window_end == "18:00"
    
    def test_morning_window(self):
        """Test 'sabah' sets 09-12 window."""
        request = extract_free_slot_request("yarın sabah boşluk var mı")
        
        assert request is not None
        assert request.window_start == "09:00"
        assert request.window_end == "12:00"
        assert request.day == "yarın"
    
    def test_evening_window(self):
        """Test 'akşam' sets 18-21 window."""
        request = extract_free_slot_request("akşam müsait zaman")
        
        assert request is not None
        assert request.window_start == "18:00"
        assert request.window_end == "21:00"
    
    def test_noon_window(self):
        """Test 'öğlen' sets 12-14 window."""
        request = extract_free_slot_request("öğlen boş saat var mı")
        
        assert request is not None
        assert request.window_start == "12:00"
        assert request.window_end == "14:00"
    
    def test_combined_duration_and_time(self):
        """Test '1 saatlik sabah boşluk'."""
        request = extract_free_slot_request("1 saatlik sabah toplantı için boşluk")
        
        assert request is not None
        assert request.duration_minutes == 60
        assert request.window_start == "09:00"
        assert request.window_end == "12:00"
    
    def test_non_free_slot_query_returns_none(self):
        """Test non-free-slot queries return None."""
        assert extract_free_slot_request("merhaba") is None
        assert extract_free_slot_request("yarın toplantı ekle") is None
        assert extract_free_slot_request("hava nasıl") is None
    
    def test_various_free_slot_patterns(self):
        """Test different ways to ask for free slots."""
        patterns = [
            "uygun saat var mı",
            "boş zaman ne zaman",
            "müsait saat",
            "ne zaman boş",
            "boşluk bul",
            "boşluk ara",
        ]
        
        for pattern in patterns:
            request = extract_free_slot_request(pattern)
            assert request is not None, f"Failed to extract from: {pattern}"
            assert request.duration_minutes == 30
            assert request.day == "bugün"
    
    def test_half_hour_duration(self):
        """Test 'yarım saat' extracts 30 minutes."""
        request = extract_free_slot_request("yarım saat boşluk")
        
        assert request is not None
        assert request.duration_minutes == 30
    
    def test_all_weekdays(self):
        """Test all Turkish weekday names."""
        weekdays = ["pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar"]
        
        for day in weekdays:
            request = extract_free_slot_request(f"{day} uygun saat var mı")
            assert request is not None
            assert request.day == day
    
    def test_raw_text_preserved(self):
        """Test raw input text is preserved."""
        text = "Yarın sabah 1 saatlik toplantı için uygun saat var mı"
        request = extract_free_slot_request(text)
        
        assert request is not None
        assert request.raw_text == text
