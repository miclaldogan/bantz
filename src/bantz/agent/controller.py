"""Agent Controller - Üst düzey agent akış kontrolü.

Issue #22: Multi-Step Task Execution - Agent Framework

JarvisPanel ile entegre, async execution destekli agent controller.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from bantz.agent.core import Agent, AgentState, Step, Task
from bantz.agent.planner import Planner
from bantz.agent.tools import ToolRegistry
from bantz.agent.builtin_tools import build_default_registry

if TYPE_CHECKING:
    from bantz.ui.jarvis_panel import JarvisPanelController


# ─────────────────────────────────────────────────────────────────
# Step Status Icons - Iron Man Style
# ─────────────────────────────────────────────────────────────────

class StepStatusIcon(Enum):
    """Visual icons for step status."""
    PENDING = "○"       # Bekliyor
    IN_PROGRESS = "⏳"  # Çalışıyor
    COMPLETED = "✓"     # Tamamlandı
    FAILED = "✗"        # Başarısız
    SKIPPED = "⊘"       # Atlandı


STEP_STATUS_COLORS = {
    "pending": "#888888",      # Gri
    "running": "#FFD700",      # Altın sarısı (spinner)
    "completed": "#00FF7F",    # Yeşil
    "failed": "#FF4444",       # Kırmızı
    "skipped": "#666666",      # Koyu gri
}


def get_step_icon(status: str) -> str:
    """Get icon for step status."""
    icons = {
        "pending": "○",
        "running": "⏳",
        "completed": "✓",
        "failed": "✗",
        "skipped": "⊘",
    }
    return icons.get(status, "○")


# ─────────────────────────────────────────────────────────────────
# Plan Display Data
# ─────────────────────────────────────────────────────────────────

@dataclass
class PlanStepDisplay:
    """Single step for panel display."""
    index: int
    description: str
    status: str
    icon: str
    color: str
    tool: str
    elapsed_time: Optional[float] = None


@dataclass
class PlanDisplay:
    """Full plan for panel display."""
    id: str
    title: str
    description: str
    steps: List[PlanStepDisplay]
    current_step: int
    total_steps: int
    status: str  # planning, executing, completed, failed
    progress_percent: float
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


# ─────────────────────────────────────────────────────────────────
# Agent Controller
# ─────────────────────────────────────────────────────────────────

class ControllerState(Enum):
    """Controller state."""
    IDLE = "idle"
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ControllerContext:
    """Execution context passed between steps."""
    results: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    step_times: Dict[int, float] = field(default_factory=dict)


class AgentController:
    """Üst düzey agent akış kontrolü.
    
    Features:
    - Panel entegrasyonu (plan gösterimi)
    - Async execution support
    - Confirmation flow
    - Cancel/Skip controls
    - Step-by-step progress updates
    - TTS feedback integration
    """
    
    def __init__(
        self,
        agent: Optional[Agent] = None,
        panel: Optional["JarvisPanelController"] = None,
        on_speak: Optional[Callable[[str], None]] = None,
        on_step_update: Optional[Callable[[PlanDisplay], None]] = None,
        auto_confirm: bool = False,
    ):
        """Initialize controller.
        
        Args:
            agent: Agent instance (uses default if None)
            panel: JarvisPanelController for UI
            on_speak: TTS callback
            on_step_update: Step update callback
            auto_confirm: Auto-confirm plans without waiting
        """
        if agent is None:
            tools = build_default_registry()
            planner = Planner()
            agent = Agent(planner, tools)
        
        self.agent = agent
        self.panel = panel
        self.on_speak = on_speak
        self.on_step_update = on_step_update
        self.auto_confirm = auto_confirm
        
        # State
        self._state = ControllerState.IDLE
        self._current_task: Optional[Task] = None
        self._context = ControllerContext()
        self._cancelled = False
        self._skip_current = False
        self._paused = False
        
        # Confirmation
        self._confirmation_event: Optional[asyncio.Event] = None
        self._confirmed: bool = False
    
    @property
    def state(self) -> ControllerState:
        return self._state
    
    @property
    def current_task(self) -> Optional[Task]:
        return self._current_task
    
    @property
    def is_running(self) -> bool:
        return self._state in (ControllerState.EXECUTING, ControllerState.PLANNING)
    
    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────
    
    async def handle_request(
        self,
        request: str,
        *,
        runner: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        """Handle a complex multi-step request.
        
        Args:
            request: Natural language request
            runner: Step execution runner
            
        Returns:
            Execution result with summary
        """
        self._reset()
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        
        try:
            # 1. Planning
            self._state = ControllerState.PLANNING
            await self._speak("Anladım efendim. Planı hazırlıyorum...")
            
            task = self.agent.plan(request, task_id=task_id)
            self._current_task = task
            
            # Show plan
            plan_display = self._build_plan_display()
            await self._show_plan(plan_display)
            await self._speak(f"{len(task.steps)} adımlık bir plan hazırladım.")
            
            # 2. Confirmation
            if not self.auto_confirm:
                self._state = ControllerState.AWAITING_CONFIRMATION
                await self._speak("Onayınızı bekliyorum efendim.")
                
                confirmed = await self._wait_for_confirmation()
                if not confirmed:
                    self._state = ControllerState.CANCELLED
                    await self._speak("Tamam efendim, iptal ediyorum.")
                    return {"status": "cancelled", "reason": "user_cancelled"}
            
            # 3. Execution
            self._state = ControllerState.EXECUTING
            await self._speak("Başlıyorum efendim.")
            
            result = await self._execute_plan(runner)
            
            # 4. Summary
            if result["status"] == "completed":
                self._state = ControllerState.COMPLETED
                await self._speak(f"Tamamlandı efendim. {result.get('summary', '')}")
            else:
                self._state = ControllerState.FAILED
                await self._speak(f"Bir sorun oluştu efendim. {result.get('error', '')}")
            
            return result
            
        except Exception as e:
            self._state = ControllerState.FAILED
            await self._speak(f"Hata oluştu efendim: {str(e)}")
            return {"status": "error", "error": str(e)}
    
    def confirm(self) -> None:
        """Confirm the current plan."""
        self._confirmed = True
        if self._confirmation_event:
            self._confirmation_event.set()
    
    def cancel(self) -> None:
        """Cancel current execution."""
        self._cancelled = True
        self._confirmed = False
        if self._confirmation_event:
            self._confirmation_event.set()
    
    def skip_current_step(self) -> None:
        """Skip the currently running step."""
        self._skip_current = True
    
    def pause(self) -> None:
        """Pause execution."""
        self._paused = True
        self._state = ControllerState.PAUSED
    
    def resume(self) -> None:
        """Resume execution."""
        self._paused = False
        if self._current_task:
            self._state = ControllerState.EXECUTING
    
    # ─────────────────────────────────────────────────────────────
    # Synchronous API (for non-async contexts)
    # ─────────────────────────────────────────────────────────────
    
    def handle_request_sync(
        self,
        request: str,
        *,
        runner: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        """Synchronous version of handle_request."""
        try:
            loop = asyncio.get_running_loop()
            # Already in async context - use create_task
            return asyncio.ensure_future(self.handle_request(request, runner=runner))
        except RuntimeError:
            # No running loop - run synchronously
            return asyncio.run(self.handle_request(request, runner=runner))
    
    def plan_only(self, request: str) -> Optional[Task]:
        """Plan a request without executing (sync)."""
        try:
            task_id = f"task_{uuid.uuid4().hex[:8]}"
            task = self.agent.plan(request, task_id=task_id)
            self._current_task = task
            return task
        except Exception:
            return None
    
    # ─────────────────────────────────────────────────────────────
    # Internal Methods
    # ─────────────────────────────────────────────────────────────
    
    def _reset(self) -> None:
        """Reset controller state."""
        self._state = ControllerState.IDLE
        self._current_task = None
        self._context = ControllerContext()
        self._cancelled = False
        self._skip_current = False
        self._paused = False
        self._confirmed = False
        self._confirmation_event = None
    
    async def _speak(self, text: str) -> None:
        """Speak via TTS callback."""
        if self.on_speak:
            try:
                if asyncio.iscoroutinefunction(self.on_speak):
                    await self.on_speak(text)
                else:
                    self.on_speak(text)
            except Exception:
                pass
    
    async def _show_plan(self, plan_display: PlanDisplay) -> None:
        """Show plan in panel."""
        if self.panel:
            try:
                self.panel.show_plan(plan_display)
            except Exception:
                pass
        
        if self.on_step_update:
            try:
                if asyncio.iscoroutinefunction(self.on_step_update):
                    await self.on_step_update(plan_display)
                else:
                    self.on_step_update(plan_display)
            except Exception:
                pass
    
    async def _wait_for_confirmation(self, timeout: float = 30.0) -> bool:
        """Wait for user confirmation."""
        self._confirmation_event = asyncio.Event()
        self._confirmed = False
        
        try:
            await asyncio.wait_for(self._confirmation_event.wait(), timeout=timeout)
            return self._confirmed
        except asyncio.TimeoutError:
            return False
    
    async def _execute_plan(
        self,
        runner: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ) -> Dict[str, Any]:
        """Execute the current task's steps."""
        if not self._current_task:
            return {"status": "error", "error": "no_task"}
        
        task = self._current_task
        results: Dict[str, Any] = {}
        errors: List[str] = []
        
        for i, step in enumerate(task.steps):
            # Check for cancellation
            if self._cancelled:
                for remaining in task.steps[i:]:
                    remaining.status = "skipped"
                break
            
            # Check for pause
            while self._paused:
                await asyncio.sleep(0.1)
                if self._cancelled:
                    break
            
            # Skip if requested
            if self._skip_current:
                step.status = "skipped"
                self._skip_current = False
                task.current_step = i + 1
                await self._update_display()
                continue
            
            # Execute step
            step.status = "running"
            task.current_step = i
            step_start = time.time()
            await self._update_display()
            
            try:
                if runner:
                    result = runner(step.action, step.params)
                    if asyncio.iscoroutine(result):
                        result = await result
                    
                    step.result = result if isinstance(result, dict) else {"data": result}
                    step.status = "completed"
                    results[step.action] = step.result
                else:
                    # No runner - mark as completed (dry run)
                    step.status = "completed"
                    step.result = {"dry_run": True}
                
                # Speak progress
                await self._speak(f"{step.description} tamamlandı.")
                
            except Exception as e:
                step.status = "failed"
                step.error = str(e)
                errors.append(f"Step {i+1}: {e}")
                
                # Check if critical
                if self._is_critical_step(step):
                    break
            
            self._context.step_times[i] = time.time() - step_start
            task.current_step = i + 1
            await self._update_display()
        
        # Final status
        completed_count = sum(1 for s in task.steps if s.status == "completed")
        failed_count = sum(1 for s in task.steps if s.status == "failed")
        
        if self._cancelled:
            status = "cancelled"
        elif failed_count > 0:
            status = "partial" if completed_count > 0 else "failed"
        else:
            status = "completed"
        
        return {
            "status": status,
            "task_id": task.id,
            "completed": completed_count,
            "failed": failed_count,
            "total": len(task.steps),
            "results": results,
            "errors": errors,
            "summary": self._generate_summary(task),
        }
    
    async def _update_display(self) -> None:
        """Update panel display."""
        if self._current_task:
            plan_display = self._build_plan_display()
            await self._show_plan(plan_display)
    
    def _build_plan_display(self) -> PlanDisplay:
        """Build plan display from current task."""
        task = self._current_task
        if not task:
            return PlanDisplay(
                id="",
                title="",
                description="",
                steps=[],
                current_step=0,
                total_steps=0,
                status="idle",
                progress_percent=0,
            )
        
        steps = []
        for i, step in enumerate(task.steps):
            elapsed = self._context.step_times.get(i)
            steps.append(PlanStepDisplay(
                index=i + 1,
                description=step.description,
                status=step.status,
                icon=get_step_icon(step.status),
                color=STEP_STATUS_COLORS.get(step.status, "#888888"),
                tool=step.action,
                elapsed_time=elapsed,
            ))
        
        completed = sum(1 for s in task.steps if s.status == "completed")
        progress = (completed / len(task.steps) * 100) if task.steps else 0
        
        return PlanDisplay(
            id=task.id,
            title="GÖREV PLANI",
            description=task.original_request,
            steps=steps,
            current_step=task.current_step,
            total_steps=len(task.steps),
            status=self._state.value,
            progress_percent=progress,
            started_at=self._context.start_time,
        )
    
    def _generate_summary(self, task: Task) -> str:
        """Generate execution summary."""
        completed = sum(1 for s in task.steps if s.status == "completed")
        total = len(task.steps)
        
        parts = [f"{completed}/{total} adım tamamlandı."]
        
        for step in task.steps:
            if step.status == "completed" and step.result:
                # Extract key info from result
                if isinstance(step.result, dict):
                    info = step.result.get("summary", step.result.get("data", ""))
                    if info and isinstance(info, str) and len(info) < 100:
                        parts.append(f"{step.description}: {info}")
        
        return " ".join(parts)
    
    def _is_critical_step(self, step: Step) -> bool:
        """Check if step failure should stop execution."""
        critical_tools = ["payment", "delete", "send_email", "file_delete"]
        return step.action in critical_tools


# ─────────────────────────────────────────────────────────────────
# Mock Controller for Testing
# ─────────────────────────────────────────────────────────────────

class MockAgentController:
    """Mock controller for testing without LLM."""
    
    def __init__(self):
        self._state = ControllerState.IDLE
        self._plans: List[PlanDisplay] = []
        self._confirmed = False
        self._cancelled = False
    
    @property
    def state(self) -> ControllerState:
        return self._state
    
    @property
    def plans(self) -> List[PlanDisplay]:
        return self._plans
    
    def set_state(self, state: ControllerState) -> None:
        self._state = state
    
    def add_mock_plan(self, description: str, steps: List[str]) -> PlanDisplay:
        """Add a mock plan."""
        plan = PlanDisplay(
            id=f"mock_{len(self._plans)}",
            title="GÖREV PLANI",
            description=description,
            steps=[
                PlanStepDisplay(
                    index=i + 1,
                    description=step,
                    status="pending",
                    icon="○",
                    color="#888888",
                    tool="mock_tool",
                )
                for i, step in enumerate(steps)
            ],
            current_step=0,
            total_steps=len(steps),
            status="planning",
            progress_percent=0,
        )
        self._plans.append(plan)
        return plan
    
    def confirm(self) -> None:
        self._confirmed = True
    
    def cancel(self) -> None:
        self._cancelled = True
    
    def is_confirmed(self) -> bool:
        return self._confirmed
    
    def is_cancelled(self) -> bool:
        return self._cancelled
