"""
Tests for InterruptHandler (Issue #35 - Voice-2).

Tests:
- InterruptAction enum
- Handle interrupt stops TTS
- Handle interrupt pauses job
- Resume paused job
- Acknowledgment phrase
"""

import pytest
import asyncio
from unittest.mock import Mock, MagicMock, AsyncMock, patch


class TestInterruptAction:
    """Tests for InterruptAction enum."""
    
    def test_interrupt_actions_exist(self):
        """Test that all required actions exist."""
        from bantz.voice.interrupt_handler import InterruptAction
        
        assert hasattr(InterruptAction, 'PAUSE_AND_LISTEN')
        assert hasattr(InterruptAction, 'CANCEL_AND_LISTEN')
        assert hasattr(InterruptAction, 'IGNORE')
    
    def test_interrupt_actions_unique(self):
        """Test action values are unique."""
        from bantz.voice.interrupt_handler import InterruptAction
        
        values = [a.value for a in InterruptAction]
        assert len(values) == len(set(values))


class TestInterruptResult:
    """Tests for InterruptResult dataclass."""
    
    def test_result_creation(self):
        """Test InterruptResult can be created."""
        from bantz.voice.interrupt_handler import InterruptResult, InterruptAction
        
        result = InterruptResult(
            action=InterruptAction.PAUSE_AND_LISTEN,
            paused_job_id="job-123"
        )
        
        assert result.action == InterruptAction.PAUSE_AND_LISTEN
        assert result.paused_job_id == "job-123"
        assert result.new_command is None
        assert result.error is None


class TestInterruptHandler:
    """Tests for InterruptHandler class."""
    
    @pytest.fixture
    def handler(self):
        """Create InterruptHandler for testing."""
        from bantz.voice.interrupt_handler import InterruptHandler
        
        mock_job_manager = Mock()
        mock_job_manager.pause_job.return_value = True
        mock_job_manager.resume_job.return_value = True
        mock_job_manager.cancel_job.return_value = True
        
        mock_tts = Mock()
        mock_tts.stop = AsyncMock()
        mock_tts.speak = AsyncMock()
        
        with patch('bantz.voice.interrupt_handler.get_event_bus') as mock_bus:
            mock_bus.return_value = Mock()
            return InterruptHandler(
                job_manager=mock_job_manager,
                tts_controller=mock_tts,
                acknowledgment="Efendim"
            )
    
    def test_handler_acknowledgment(self, handler):
        """Test handler has correct acknowledgment."""
        assert handler._acknowledgment == "Efendim"
    
    def test_is_resume_command_devam(self, handler):
        """Test 'devam et' is recognized as resume command."""
        assert handler.is_resume_command("devam et") == True
        assert handler.is_resume_command("devam") == True
        assert handler.is_resume_command("continue") == True
        assert handler.is_resume_command("resume") == True
    
    def test_is_resume_command_other(self, handler):
        """Test other commands are not resume commands."""
        assert handler.is_resume_command("iptal") == False
        assert handler.is_resume_command("bekle") == False
    
    @pytest.mark.asyncio
    async def test_handle_interrupt_pauses_job(self, handler):
        """Test handle_interrupt pauses the current job."""
        from bantz.voice.interrupt_handler import InterruptAction
        
        result = await handler.handle_interrupt("job-123")
        
        assert result.action == InterruptAction.PAUSE_AND_LISTEN
        assert result.paused_job_id == "job-123"
        handler._job_manager.pause_job.assert_called_once_with("job-123")
    
    @pytest.mark.asyncio
    async def test_handle_interrupt_stops_tts(self, handler):
        """Test handle_interrupt stops TTS."""
        await handler.handle_interrupt("job-123")
        
        handler._tts_controller.stop.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_interrupt_says_acknowledgment(self, handler):
        """Test handle_interrupt says acknowledgment."""
        await handler.handle_interrupt("job-123")
        
        handler._tts_controller.speak.assert_called_once_with("Efendim")
    
    @pytest.mark.asyncio
    async def test_resume_paused_job(self, handler):
        """Test resume_paused_job works."""
        # First pause
        await handler.handle_interrupt("job-123")
        
        # Then resume
        success = await handler.resume_paused_job("job-123")
        
        assert success == True
        handler._job_manager.resume_job.assert_called_once_with("job-123")
    
    def test_get_paused_jobs(self, handler):
        """Test get_paused_jobs returns list."""
        paused = handler.get_paused_jobs()
        
        assert isinstance(paused, list)


class TestInterruptHandlerFactory:
    """Tests for create_interrupt_handler factory."""
    
    def test_factory_creates_handler(self):
        """Test factory function creates InterruptHandler."""
        from bantz.voice.interrupt_handler import create_interrupt_handler, InterruptHandler
        
        with patch('bantz.voice.interrupt_handler.get_event_bus') as mock_bus:
            mock_bus.return_value = Mock()
            handler = create_interrupt_handler(
                acknowledgment="Evet efendim"
            )
            
            assert isinstance(handler, InterruptHandler)
            assert handler._acknowledgment == "Evet efendim"
