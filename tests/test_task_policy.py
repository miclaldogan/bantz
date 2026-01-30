"""
Tests for TaskListeningPolicy (Issue #35 - Voice-2).

Tests:
- Allowed intents during task
- Rejection message
- Intent classification
- Job control intent detection
"""

import pytest
from unittest.mock import Mock


class TestTaskListeningPolicy:
    """Tests for TaskListeningPolicy class."""
    
    @pytest.fixture
    def policy(self):
        """Create TaskListeningPolicy for testing."""
        from bantz.voice.task_policy import TaskListeningPolicy
        return TaskListeningPolicy()
    
    def test_policy_accepts_pause(self, policy):
        """Test policy accepts job_pause intent."""
        assert policy.should_accept("job_pause") == True
    
    def test_policy_accepts_resume(self, policy):
        """Test policy accepts job_resume intent."""
        assert policy.should_accept("job_resume") == True
    
    def test_policy_accepts_cancel(self, policy):
        """Test policy accepts job_cancel intent."""
        assert policy.should_accept("job_cancel") == True
    
    def test_policy_accepts_interrupt(self, policy):
        """Test policy accepts interrupt intent."""
        assert policy.should_accept("interrupt") == True
    
    def test_policy_accepts_status(self, policy):
        """Test policy accepts status intent."""
        assert policy.should_accept("status") == True
    
    def test_policy_rejects_other(self, policy):
        """Test policy rejects other intents."""
        assert policy.should_accept("search") == False
        assert policy.should_accept("open_app") == False
        assert policy.should_accept("navigate") == False
    
    def test_policy_rejection_message(self, policy):
        """Test rejection message is Turkish."""
        message = policy.get_rejection_message()
        
        assert "görev çalışıyor" in message
        assert len(message) > 10
    
    def test_is_job_control_intent(self, policy):
        """Test is_job_control_intent identifies job commands."""
        assert policy.is_job_control_intent("job_pause") == True
        assert policy.is_job_control_intent("job_resume") == True
        assert policy.is_job_control_intent("job_cancel") == True
        assert policy.is_job_control_intent("search") == False
    
    def test_get_intent_action(self, policy):
        """Test get_intent_action returns correct actions."""
        assert policy.get_intent_action("job_pause") == "pause"
        assert policy.get_intent_action("job_resume") == "resume"
        assert policy.get_intent_action("job_cancel") == "cancel"
        assert policy.get_intent_action("interrupt") == "interrupt"
        assert policy.get_intent_action("unknown") is None
    
    def test_add_allowed_intent(self, policy):
        """Test adding custom allowed intent."""
        assert policy.should_accept("custom_intent") == False
        
        policy.add_allowed_intent("custom_intent")
        
        assert policy.should_accept("custom_intent") == True
    
    def test_remove_allowed_intent(self, policy):
        """Test removing allowed intent."""
        assert policy.should_accept("status") == True
        
        policy.remove_allowed_intent("status")
        
        assert policy.should_accept("status") == False
    
    def test_get_allowed_intents(self, policy):
        """Test get_allowed_intents returns set."""
        intents = policy.get_allowed_intents()
        
        assert isinstance(intents, set)
        assert "job_pause" in intents
        assert "job_resume" in intents
    
    def test_custom_rejection_message(self):
        """Test custom rejection message."""
        from bantz.voice.task_policy import TaskListeningPolicy
        
        policy = TaskListeningPolicy(
            rejection_message="Custom rejection"
        )
        
        assert policy.get_rejection_message() == "Custom rejection"


class TestIntentKeywords:
    """Tests for intent keyword mapping."""
    
    def test_intent_keywords_defined(self):
        """Test INTENT_KEYWORDS is defined with expected intents."""
        from bantz.voice.task_policy import INTENT_KEYWORDS
        
        assert "job_pause" in INTENT_KEYWORDS
        assert "job_resume" in INTENT_KEYWORDS
        assert "job_cancel" in INTENT_KEYWORDS
    
    def test_pause_keywords(self):
        """Test pause keywords include Turkish."""
        from bantz.voice.task_policy import INTENT_KEYWORDS
        
        keywords = INTENT_KEYWORDS["job_pause"]
        
        assert "bekle" in keywords
        assert "dur" in keywords
        assert "pause" in keywords
    
    def test_resume_keywords(self):
        """Test resume keywords include Turkish."""
        from bantz.voice.task_policy import INTENT_KEYWORDS
        
        keywords = INTENT_KEYWORDS["job_resume"]
        
        assert "devam et" in keywords
        assert "devam" in keywords


class TestClassifyTaskCommand:
    """Tests for classify_task_command function."""
    
    def test_classify_bekle(self):
        """Test classifying 'bekle' as job_pause."""
        from bantz.voice.task_policy import classify_task_command
        
        assert classify_task_command("bekle") == "job_pause"
        assert classify_task_command("Bekle!") == "job_pause"
    
    def test_classify_devam(self):
        """Test classifying 'devam et' as job_resume."""
        from bantz.voice.task_policy import classify_task_command
        
        assert classify_task_command("devam et") == "job_resume"
        assert classify_task_command("devam") == "job_resume"
    
    def test_classify_iptal(self):
        """Test classifying 'iptal' as job_cancel."""
        from bantz.voice.task_policy import classify_task_command
        
        assert classify_task_command("iptal") == "job_cancel"
        assert classify_task_command("vazgeç") == "job_cancel"
    
    def test_classify_unknown(self):
        """Test classifying unknown command returns None."""
        from bantz.voice.task_policy import classify_task_command
        
        assert classify_task_command("random text") is None


class TestTaskPolicyFactory:
    """Tests for create_task_policy factory."""
    
    def test_factory_creates_policy(self):
        """Test factory function creates TaskListeningPolicy."""
        from bantz.voice.task_policy import create_task_policy, TaskListeningPolicy
        
        policy = create_task_policy()
        
        assert isinstance(policy, TaskListeningPolicy)
    
    def test_factory_with_custom_intents(self):
        """Test factory with custom allowed intents."""
        from bantz.voice.task_policy import create_task_policy
        
        policy = create_task_policy(
            allowed_intents=["custom1", "custom2"]
        )
        
        assert policy.should_accept("custom1") == True
        assert policy.should_accept("job_pause") == False
