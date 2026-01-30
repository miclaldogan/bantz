"""
Tests for templates module.
"""

import pytest

from bantz.automation.templates import (
    TaskTemplate,
    TemplateRegistry,
    BUILTIN_TEMPLATES,
    EMAIL_COMPOSE_SEND,
    RESEARCH_SUMMARIZE,
    FILE_ORGANIZE,
    SCHEDULE_MEETING,
    DAILY_STANDUP,
    create_template_registry,
)


class TestTaskTemplate:
    """Tests for TaskTemplate dataclass."""
    
    def test_create_template(self):
        """Test creating a template."""
        template = TaskTemplate(
            id="test",
            name="Test Template",
            description="A test template",
            trigger_patterns=[r"test pattern"],
            steps=[{"action": "test", "description": "Test"}],
        )
        
        assert template.id == "test"
        assert template.name == "Test Template"
        assert len(template.steps) == 1
    
    def test_matches_pattern(self):
        """Test pattern matching."""
        template = TaskTemplate(
            id="test",
            name="Test",
            description="Test",
            trigger_patterns=[r"send email to (?P<recipient>\S+)"],
            steps=[],
            required_params=["recipient"],
        )
        
        result = template.matches("send email to user@example.com")
        
        assert result is not None
        assert result.get("recipient") == "user@example.com"
    
    def test_matches_no_match(self):
        """Test no match."""
        template = TaskTemplate(
            id="test",
            name="Test",
            description="Test",
            trigger_patterns=[r"specific pattern"],
            steps=[],
        )
        
        result = template.matches("completely different text")
        
        assert result is None
    
    def test_instantiate(self):
        """Test instantiating template."""
        template = TaskTemplate(
            id="test",
            name="Test",
            description="Test",
            trigger_patterns=[],
            steps=[
                {"action": "send", "description": "Send to {recipient}"},
                {"action": "confirm", "description": "Confirm {subject}"},
            ],
            required_params=["recipient"],
            optional_params={"subject": "No subject"},
        )
        
        steps = template.instantiate({"recipient": "user@test.com"})
        
        assert len(steps) == 2
        assert "user@test.com" in steps[0]["description"]
        assert "No subject" in steps[1]["description"]
    
    def test_instantiate_missing_required(self):
        """Test instantiate with missing required param."""
        template = TaskTemplate(
            id="test",
            name="Test",
            description="Test",
            trigger_patterns=[],
            steps=[],
            required_params=["required_param"],
        )
        
        with pytest.raises(ValueError) as exc:
            template.instantiate({})
        
        assert "required_param" in str(exc.value)
    
    def test_instantiate_with_depends_on(self):
        """Test step dependencies preserved."""
        template = TaskTemplate(
            id="test",
            name="Test",
            description="Test",
            trigger_patterns=[],
            steps=[
                {"action": "a1", "description": "Step 1"},
                {"action": "a2", "description": "Step 2", "depends_on": ["step_1"]},
            ],
        )
        
        steps = template.instantiate({})
        
        assert steps[1].get("depends_on") == ["step_1"]
    
    def test_to_dict(self):
        """Test serialization."""
        template = TaskTemplate(
            id="test",
            name="Test",
            description="Test",
            trigger_patterns=[r"test"],
            steps=[{"action": "a", "description": "A"}],
            category="testing",
            priority=5,
        )
        
        d = template.to_dict()
        
        assert d["id"] == "test"
        assert d["name"] == "Test"
        assert d["category"] == "testing"
        assert d["priority"] == 5


class TestTemplateRegistry:
    """Tests for TemplateRegistry class."""
    
    @pytest.fixture
    def registry(self):
        """Create empty registry."""
        return TemplateRegistry()
    
    @pytest.fixture
    def sample_template(self):
        """Create sample template."""
        return TaskTemplate(
            id="sample",
            name="Sample Template",
            description="A sample",
            trigger_patterns=[r"sample (?P<item>.+)"],
            steps=[{"action": "sample_action", "description": "Do {item}"}],
            required_params=["item"],
            category="test",
        )
    
    def test_register(self, registry, sample_template):
        """Test registering template."""
        registry.register(sample_template)
        
        assert len(registry) == 1
        assert "sample" in registry
    
    def test_unregister(self, registry, sample_template):
        """Test unregistering template."""
        registry.register(sample_template)
        
        result = registry.unregister("sample")
        
        assert result
        assert len(registry) == 0
    
    def test_unregister_not_found(self, registry):
        """Test unregistering non-existent template."""
        result = registry.unregister("nonexistent")
        
        assert not result
    
    def test_get(self, registry, sample_template):
        """Test getting template by ID."""
        registry.register(sample_template)
        
        template = registry.get("sample")
        
        assert template is not None
        assert template.id == "sample"
    
    def test_get_not_found(self, registry):
        """Test getting non-existent template."""
        template = registry.get("nonexistent")
        
        assert template is None
    
    def test_find_matching(self, registry, sample_template):
        """Test finding matching templates."""
        registry.register(sample_template)
        
        matches = registry.find_matching("sample something")
        
        assert len(matches) == 1
        template, params = matches[0]
        assert template.id == "sample"
        assert params.get("item") == "something"
    
    def test_find_matching_priority(self, registry):
        """Test matching sorted by priority."""
        low = TaskTemplate(
            id="low",
            name="Low Priority",
            description="",
            trigger_patterns=[r"test"],
            steps=[],
            priority=1,
        )
        high = TaskTemplate(
            id="high",
            name="High Priority",
            description="",
            trigger_patterns=[r"test"],
            steps=[],
            priority=10,
        )
        
        registry.register(low)
        registry.register(high)
        
        matches = registry.find_matching("test")
        
        assert matches[0][0].id == "high"
    
    def test_find_best_match(self, registry, sample_template):
        """Test finding best match."""
        registry.register(sample_template)
        
        result = registry.find_best_match("sample item")
        
        assert result is not None
        template, params = result
        assert template.id == "sample"
    
    def test_find_best_match_none(self, registry):
        """Test no best match."""
        result = registry.find_best_match("no match")
        
        assert result is None
    
    def test_instantiate(self, registry, sample_template):
        """Test instantiating via registry."""
        registry.register(sample_template)
        
        steps = registry.instantiate("sample", {"item": "test"})
        
        assert len(steps) == 1
        assert "test" in steps[0]["description"]
    
    def test_instantiate_not_found(self, registry):
        """Test instantiate with non-existent template."""
        with pytest.raises(KeyError):
            registry.instantiate("nonexistent", {})
    
    def test_list_templates(self, registry, sample_template):
        """Test listing all templates."""
        registry.register(sample_template)
        
        templates = registry.list_templates()
        
        assert len(templates) == 1
    
    def test_list_templates_by_category(self, registry, sample_template):
        """Test listing by category."""
        registry.register(sample_template)
        
        templates = registry.list_templates(category="test")
        assert len(templates) == 1
        
        templates = registry.list_templates(category="other")
        assert len(templates) == 0
    
    def test_list_categories(self, registry, sample_template):
        """Test listing categories."""
        registry.register(sample_template)
        
        categories = registry.list_categories()
        
        assert "test" in categories


class TestBuiltinTemplates:
    """Tests for builtin templates."""
    
    def test_builtin_templates_exist(self):
        """Test all builtin templates exist."""
        assert len(BUILTIN_TEMPLATES) >= 5
    
    def test_email_template(self):
        """Test email compose template."""
        assert EMAIL_COMPOSE_SEND.id == "email_compose_send"
        assert EMAIL_COMPOSE_SEND.category == "communication"
        assert len(EMAIL_COMPOSE_SEND.steps) >= 3
    
    def test_email_template_matches(self):
        """Test email template matching."""
        result = EMAIL_COMPOSE_SEND.matches("mail gönder user@test.com")
        assert result is not None
    
    def test_research_template(self):
        """Test research template."""
        assert RESEARCH_SUMMARIZE.id == "research_summarize"
        assert RESEARCH_SUMMARIZE.category == "research"
    
    def test_research_template_matches(self):
        """Test research template matching."""
        result = RESEARCH_SUMMARIZE.matches("machine learning hakkında araştır")
        assert result is not None
        assert "topic" in result
    
    def test_file_organize_template(self):
        """Test file organize template."""
        assert FILE_ORGANIZE.id == "file_organize"
        assert FILE_ORGANIZE.category == "files"
    
    def test_schedule_meeting_template(self):
        """Test schedule meeting template."""
        assert SCHEDULE_MEETING.id == "schedule_meeting"
        assert SCHEDULE_MEETING.category == "calendar"
    
    def test_daily_standup_template(self):
        """Test daily standup template."""
        assert DAILY_STANDUP.id == "daily_standup"
        assert DAILY_STANDUP.category == "productivity"


class TestCreateTemplateRegistry:
    """Tests for create_template_registry factory."""
    
    def test_create_with_builtins(self):
        """Test factory loads builtins."""
        registry = create_template_registry(load_builtins=True)
        
        assert len(registry) >= 5
        assert "email_compose_send" in registry
    
    def test_create_without_builtins(self):
        """Test factory without builtins."""
        registry = create_template_registry(load_builtins=False)
        
        assert len(registry) == 0
