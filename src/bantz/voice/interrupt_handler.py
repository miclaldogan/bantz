"""
Interrupt Handler (Issue #35 - Voice-2).

Handles interrupts during task execution:
- Stops TTS playback
- Pauses current job
- Says "Efendim" (acknowledgment)
- Listens for new command
- Can resume paused job

Interrupt flow:
1. User says "Hey Bantz" during task
2. TTS is cut
3. Current job is paused
4. System says "Efendim"
5. User gives new command or says "devam et"
"""

from enum import Enum
from typing import Optional, Callable, Any
from dataclasses import dataclass
import asyncio

from bantz.core.events import EventBus, get_event_bus


class InterruptAction(Enum):
    """Actions that can be taken on interrupt."""
    PAUSE_AND_LISTEN = "pause_and_listen"      # Pause job, listen for command
    CANCEL_AND_LISTEN = "cancel_and_listen"    # Cancel job, listen for command
    IGNORE = "ignore"                          # Ignore interrupt


@dataclass
class InterruptResult:
    """Result of interrupt handling."""
    action: InterruptAction
    paused_job_id: Optional[str] = None
    new_command: Optional[str] = None
    error: Optional[str] = None


class InterruptHandler:
    """
    Handles interrupts during task execution.
    
    When user says wake word during a running task:
    1. TTS playback is immediately stopped
    2. Current job is paused (not cancelled)
    3. System acknowledges with "Efendim"
    4. System listens for new command
    
    Usage:
        handler = InterruptHandler(job_manager, tts_controller, event_bus)
        
        # When interrupt detected
        result = await handler.handle_interrupt(current_job_id)
        
        if result.new_command == "devam et":
            await handler.resume_paused_job(result.paused_job_id)
    """
    
    # Turkish acknowledgment phrase
    ACKNOWLEDGMENT = "Efendim"
    
    # Commands that resume paused job
    RESUME_COMMANDS = ["devam et", "devam", "continue", "resume"]
    
    def __init__(
        self,
        job_manager=None,  # Optional[JobManager]
        tts_controller=None,  # Optional TTS controller
        event_bus: Optional[EventBus] = None,
        acknowledgment: str = "Efendim"
    ):
        """
        Initialize InterruptHandler.
        
        Args:
            job_manager: JobManager for job control
            tts_controller: TTS controller for stopping speech
            event_bus: EventBus for publishing events
            acknowledgment: Phrase to say on interrupt
        """
        self._job_manager = job_manager
        self._tts_controller = tts_controller
        self._event_bus = event_bus or get_event_bus()
        self._acknowledgment = acknowledgment
        
        self._paused_jobs: dict[str, dict] = {}  # job_id -> job state
        
        # Callbacks
        self._on_interrupt: Optional[Callable[[str], None]] = None
        self._on_resume: Optional[Callable[[str], None]] = None
    
    async def handle_interrupt(
        self,
        current_job_id: Optional[str] = None
    ) -> InterruptResult:
        """
        Handle an interrupt request.
        
        Steps:
        1. Stop TTS
        2. Pause current job
        3. Say acknowledgment
        4. Return result for further handling
        
        Args:
            current_job_id: ID of currently running job
            
        Returns:
            InterruptResult with action taken and job state
        """
        try:
            # Step 1: Stop TTS
            await self._stop_tts()
            
            # Step 2: Pause current job
            paused_job_id = None
            if current_job_id:
                paused_job_id = await self._pause_job(current_job_id)
            
            # Step 3: Emit interrupt event
            self._emit_interrupt_event(current_job_id)
            
            # Step 4: Say acknowledgment
            await self._say_acknowledgment()
            
            # Notify callback
            if self._on_interrupt and current_job_id:
                self._on_interrupt(current_job_id)
            
            return InterruptResult(
                action=InterruptAction.PAUSE_AND_LISTEN,
                paused_job_id=paused_job_id
            )
            
        except Exception as e:
            return InterruptResult(
                action=InterruptAction.IGNORE,
                error=str(e)
            )
    
    async def resume_paused_job(self, job_id: str) -> bool:
        """
        Resume a previously paused job.
        
        Args:
            job_id: ID of job to resume
            
        Returns:
            True if resumed successfully
        """
        if not self._job_manager:
            return False
        
        try:
            # Check if job was paused by us
            if job_id not in self._paused_jobs:
                return False
            
            # Resume job
            success = self._job_manager.resume_job(job_id)
            
            if success:
                del self._paused_jobs[job_id]
                
                # Emit resume event
                if self._event_bus:
                    self._event_bus.publish(
                        "interrupt.resumed",
                        {"job_id": job_id},
                        source="interrupt_handler"
                    )
                
                # Notify callback
                if self._on_resume:
                    self._on_resume(job_id)
            
            return success
            
        except Exception:
            return False
    
    async def cancel_paused_job(self, job_id: str) -> bool:
        """
        Cancel a paused job instead of resuming.
        
        Args:
            job_id: ID of job to cancel
            
        Returns:
            True if cancelled successfully
        """
        if not self._job_manager:
            return False
        
        try:
            if job_id in self._paused_jobs:
                del self._paused_jobs[job_id]
            
            success = self._job_manager.cancel_job(job_id)
            
            if success and self._event_bus:
                self._event_bus.publish(
                    "interrupt.cancelled",
                    {"job_id": job_id},
                    source="interrupt_handler"
                )
            
            return success
            
        except Exception:
            return False
    
    def get_paused_jobs(self) -> list[str]:
        """Get list of job IDs paused by interrupt."""
        return list(self._paused_jobs.keys())
    
    def is_resume_command(self, command: str) -> bool:
        """Check if command is a resume command."""
        normalized = command.lower().strip()
        return normalized in self.RESUME_COMMANDS
    
    async def _stop_tts(self) -> None:
        """Stop TTS playback."""
        if self._tts_controller:
            try:
                # Try common TTS controller methods
                if hasattr(self._tts_controller, 'stop'):
                    await self._async_or_sync(self._tts_controller.stop)
                elif hasattr(self._tts_controller, 'cancel'):
                    await self._async_or_sync(self._tts_controller.cancel)
            except Exception:
                pass  # TTS stop is best-effort
    
    async def _pause_job(self, job_id: str) -> Optional[str]:
        """Pause a job and track it."""
        if not self._job_manager:
            return None
        
        try:
            success = self._job_manager.pause_job(job_id)
            if success:
                self._paused_jobs[job_id] = {"paused_at": asyncio.get_event_loop().time()}
                return job_id
        except Exception:
            pass
        
        return None
    
    async def _say_acknowledgment(self) -> None:
        """Say acknowledgment phrase."""
        if self._tts_controller:
            try:
                if hasattr(self._tts_controller, 'speak'):
                    await self._async_or_sync(
                        self._tts_controller.speak,
                        self._acknowledgment
                    )
                elif hasattr(self._tts_controller, 'say'):
                    await self._async_or_sync(
                        self._tts_controller.say,
                        self._acknowledgment
                    )
            except Exception:
                pass  # Acknowledgment is best-effort
    
    async def _async_or_sync(self, func, *args) -> Any:
        """Call function, handling both async and sync."""
        result = func(*args)
        if asyncio.iscoroutine(result):
            return await result
        return result
    
    def _emit_interrupt_event(self, job_id: Optional[str]) -> None:
        """Emit interrupt event."""
        if self._event_bus:
            self._event_bus.publish(
                "interrupt.triggered",
                {"job_id": job_id, "acknowledgment": self._acknowledgment},
                source="interrupt_handler"
            )
    
    def on_interrupt_callback(self, callback: Callable[[str], None]) -> None:
        """Register callback for interrupt events."""
        self._on_interrupt = callback
    
    def on_resume_callback(self, callback: Callable[[str], None]) -> None:
        """Register callback for resume events."""
        self._on_resume = callback


def create_interrupt_handler(
    job_manager=None,
    tts_controller=None,
    event_bus: Optional[EventBus] = None,
    acknowledgment: str = "Efendim"
) -> InterruptHandler:
    """
    Factory function to create InterruptHandler.
    
    Args:
        job_manager: Optional JobManager instance
        tts_controller: Optional TTS controller
        event_bus: Optional EventBus instance
        acknowledgment: Phrase to say on interrupt
    
    Returns:
        Configured InterruptHandler instance
    """
    return InterruptHandler(
        job_manager=job_manager,
        tts_controller=tts_controller,
        event_bus=event_bus,
        acknowledgment=acknowledgment
    )
