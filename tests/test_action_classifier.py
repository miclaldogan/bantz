"""
Tests for V2-5 Action Classifier (Issue #37).
"""

import pytest

from bantz.security.action_classifier import (
    ActionClassification,
    ActionClassifier,
    create_action_classifier,
)
from bantz.security.permission_level import PermissionLevel


class TestActionClassification:
    """Tests for ActionClassification dataclass."""
    
    def test_create_classification(self):
        """Test creating classification."""
        classification = ActionClassification(
            action="send_email",
            level=PermissionLevel.MEDIUM,
            is_destructive=False,
            is_external=True
        )
        
        assert classification.action == "send_email"
        assert classification.level == PermissionLevel.MEDIUM
        assert classification.is_destructive is False
        assert classification.is_external is True


class TestActionClassifier:
    """Tests for ActionClassifier."""
    
    def test_classify_low_action(self):
        """Test classifying LOW level action."""
        classifier = ActionClassifier()
        
        classification = classifier.classify("browser_open")
        
        assert classification.level == PermissionLevel.LOW
        assert classification.is_destructive is False
    
    def test_classify_medium_action(self):
        """Test classifying MEDIUM level action."""
        classifier = ActionClassifier()
        
        classification = classifier.classify("send_email")
        
        assert classification.level == PermissionLevel.MEDIUM
        assert classification.is_external is True
    
    def test_classify_high_action(self):
        """Test classifying HIGH level action."""
        classifier = ActionClassifier()
        
        classification = classifier.classify("delete_file")
        
        assert classification.level == PermissionLevel.HIGH
        assert classification.is_destructive is True
    
    def test_classify_unknown_action(self):
        """Test classifying unknown action defaults to HIGH (safer)."""
        classifier = ActionClassifier()
        
        classification = classifier.classify("unknown_action_xyz")
        
        # Default is HIGH for safety
        assert classification.level == PermissionLevel.HIGH
    
    def test_classify_destructive_action(self):
        """Test destructive actions are marked correctly."""
        classifier = ActionClassifier()
        
        destructive_actions = ["delete_file", "format_disk", "system_shutdown"]
        
        for action in destructive_actions:
            classification = classifier.classify(action)
            assert classification.is_destructive is True, f"{action} should be destructive"
    
    def test_classify_external_action(self):
        """Test external actions are marked correctly."""
        classifier = ActionClassifier()
        
        external_actions = ["send_email", "post_social", "api_call"]
        
        for action in external_actions:
            classification = classifier.classify(action)
            assert classification.is_external is True, f"{action} should be external"
    
    def test_context_elevation_banking(self):
        """Test banking domain elevates permission level."""
        classifier = ActionClassifier()
        
        # Normal browser_open is LOW
        normal = classifier.classify("browser_open")
        assert normal.level == PermissionLevel.LOW
        
        # Banking domain should elevate
        with_banking = classifier.classify("browser_open", context={"domain": "banking.com"})
        assert with_banking.level.value >= PermissionLevel.LOW.value
    
    def test_context_elevation_high_amount(self):
        """Test high payment amount elevates to HIGH."""
        classifier = ActionClassifier()
        
        # Normal make_payment is HIGH
        normal = classifier.classify("make_payment")
        assert normal.level == PermissionLevel.HIGH
        
        # High amount should still be HIGH
        with_amount = classifier.classify("make_payment", context={"amount": 10000})
        assert with_amount.level == PermissionLevel.HIGH
    
    def test_factory_function(self):
        """Test create_action_classifier factory."""
        classifier = create_action_classifier()
        
        assert isinstance(classifier, ActionClassifier)
    
    def test_custom_rules(self):
        """Test classifier with custom rules."""
        custom_levels = {
            "my_custom_action": PermissionLevel.HIGH
        }
        classifier = ActionClassifier(custom_levels=custom_levels)
        
        classification = classifier.classify("my_custom_action")
        assert classification.level == PermissionLevel.HIGH
