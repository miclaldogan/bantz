"""
Planner module.

Creates task plans from goals using templates or LLM.
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Protocol

from bantz.automation.plan import TaskPlan, PlanStep, create_task_plan

if TYPE_CHECKING:
    from bantz.automation.templates import TemplateRegistry


class LLMClient(Protocol):
    """Protocol for LLM clients."""
    
    async def complete(self, prompt: str) -> str:
        """Complete a prompt."""
        ...


@dataclass
class PlanValidationResult:
    """Result of plan validation."""
    
    valid: bool
    """Whether the plan is valid."""
    
    issues: list[str]
    """List of validation issues."""
    
    warnings: list[str]
    """List of warnings (non-blocking)."""


class Planner:
    """
    Creates task plans from goals.
    
    Uses templates when available, falls back to LLM decomposition.
    """
    
    # Maximum steps in a plan
    MAX_STEPS = 20
    
    # Maximum goal length
    MAX_GOAL_LENGTH = 500
    
    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        template_registry: Optional["TemplateRegistry"] = None,
    ):
        """
        Initialize the planner.
        
        Args:
            llm_client: LLM client for plan generation.
            template_registry: Registry of task templates.
        """
        self._llm = llm_client
        self._templates = template_registry
    
    async def create_plan(
        self,
        goal: str,
        context: dict = None,
    ) -> TaskPlan:
        """
        Create a plan to achieve the goal.
        
        Args:
            goal: Goal to achieve.
            context: Additional context.
            
        Returns:
            TaskPlan with steps to achieve the goal.
        """
        context = context or {}
        
        # Validate goal
        if len(goal) > self.MAX_GOAL_LENGTH:
            goal = goal[:self.MAX_GOAL_LENGTH]
        
        # Try to find matching template
        if self._templates:
            match = self._templates.find_best_match(goal)
            if match:
                template, extracted_params = match
                # Merge extracted params with context
                params = {**extracted_params, **context}
                
                # Instantiate template
                steps = template.instantiate(params)
                plan = create_task_plan(goal, steps)
                plan.context = context
                plan.template_id = template.id
                return plan
        
        # Fall back to LLM-based planning
        if self._llm:
            return await self._create_plan_with_llm(goal, context)
        
        # No LLM available - create simple single-step plan
        return self._create_simple_plan(goal, context)
    
    async def _create_plan_with_llm(
        self,
        goal: str,
        context: dict,
    ) -> TaskPlan:
        """Create plan using LLM."""
        # Decompose goal into sub-tasks
        subtasks = await self.decompose_goal(goal)
        
        # Create plan with steps
        plan = create_task_plan(goal)
        plan.context = context
        
        for i, subtask in enumerate(subtasks):
            plan.add_step(
                action=self._infer_action(subtask),
                description=subtask,
            )
        
        return plan
    
    def _create_simple_plan(
        self,
        goal: str,
        context: dict,
    ) -> TaskPlan:
        """Create a simple single-step plan."""
        plan = create_task_plan(goal)
        plan.context = context
        
        plan.add_step(
            action="execute_goal",
            description=goal,
            parameters={"goal": goal, **context},
        )
        
        return plan
    
    async def decompose_goal(self, goal: str) -> list[str]:
        """
        Decompose a goal into sub-tasks.
        
        Args:
            goal: Goal to decompose.
            
        Returns:
            List of sub-task descriptions.
        """
        if not self._llm:
            return [goal]
        
        prompt = f"""Görevi alt görevlere ayır. Her satırda bir alt görev olsun.
Maksimum 5 alt görev.

Görev: {goal}

Alt görevler:
1."""
        
        try:
            response = await self._llm.complete(prompt)
            
            # Parse numbered list
            subtasks = []
            for line in response.split("\n"):
                line = line.strip()
                # Match lines like "1. task" or "- task"
                match = re.match(r"^(?:\d+[\.\)]\s*|[-•]\s*)?(.+)$", line)
                if match and match.group(1).strip():
                    subtasks.append(match.group(1).strip())
            
            return subtasks[:5] if subtasks else [goal]
            
        except Exception:
            return [goal]
    
    def _infer_action(self, description: str) -> str:
        """Infer action name from description."""
        desc_lower = description.lower()
        
        # Action mapping
        action_keywords = {
            "ara": "web_search",
            "search": "web_search",
            "bul": "web_search",
            "yaz": "compose_text",
            "write": "compose_text",
            "gönder": "send_message",
            "send": "send_message",
            "aç": "open_app",
            "open": "open_app",
            "oku": "read_content",
            "read": "read_content",
            "özetle": "summarize",
            "summarize": "summarize",
            "kaydet": "save_file",
            "save": "save_file",
            "kontrol": "verify",
            "check": "verify",
        }
        
        for keyword, action in action_keywords.items():
            if keyword in desc_lower:
                return action
        
        return "generic_action"
    
    def _extract_params_from_goal(
        self,
        goal: str,
        required_params: list[str],
    ) -> dict:
        """Extract parameters from goal text."""
        params = {}
        
        # Simple extraction patterns
        patterns = {
            "recipient": r"(?:kime|to|alıcı)[:\s]+([^\s,]+)",
            "subject": r"(?:konu|subject)[:\s]+([^,]+)",
            "topic": r"(?:hakkında|about|konusu)[:\s]+([^,]+)",
            "filename": r"(?:dosya|file)[:\s]+([^\s,]+)",
        }
        
        for param in required_params:
            if param in patterns:
                match = re.search(patterns[param], goal, re.IGNORECASE)
                if match:
                    params[param] = match.group(1).strip()
        
        return params
    
    def validate_plan(self, plan: TaskPlan) -> PlanValidationResult:
        """
        Validate a task plan.
        
        Args:
            plan: Plan to validate.
            
        Returns:
            Validation result with issues.
        """
        issues = []
        warnings = []
        
        # Check step count
        if len(plan.steps) == 0:
            issues.append("Plan has no steps")
        elif len(plan.steps) > self.MAX_STEPS:
            issues.append(f"Plan has too many steps ({len(plan.steps)} > {self.MAX_STEPS})")
        
        # Check for circular dependencies
        if self._has_circular_deps(plan):
            issues.append("Plan has circular dependencies")
        
        # Check for missing dependencies
        step_ids = {step.id for step in plan.steps}
        for step in plan.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    issues.append(f"Step {step.id} depends on unknown step {dep}")
        
        # Warnings
        if len(plan.steps) > 10:
            warnings.append("Plan has many steps - consider breaking into sub-plans")
        
        # Check for steps without description
        for step in plan.steps:
            if not step.description:
                warnings.append(f"Step {step.id} has no description")
        
        return PlanValidationResult(
            valid=len(issues) == 0,
            issues=issues,
            warnings=warnings,
        )
    
    def _has_circular_deps(self, plan: TaskPlan) -> bool:
        """Check for circular dependencies in plan."""
        # Build adjacency list
        deps = {step.id: set(step.depends_on) for step in plan.steps}
        
        # DFS for cycle detection
        visited = set()
        rec_stack = set()
        
        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            
            for neighbor in deps.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            
            rec_stack.remove(node)
            return False
        
        for step_id in deps:
            if step_id not in visited:
                if dfs(step_id):
                    return True
        
        return False
    
    async def revise_plan(
        self,
        plan: TaskPlan,
        feedback: str,
    ) -> TaskPlan:
        """
        Revise a plan based on feedback.
        
        Args:
            plan: Original plan.
            feedback: Feedback for revision.
            
        Returns:
            Revised plan.
        """
        if not self._llm:
            # Without LLM, just return original
            return plan
        
        # Get current plan summary
        current_steps = "\n".join(
            f"{i+1}. {step.description}"
            for i, step in enumerate(plan.steps)
        )
        
        prompt = f"""Mevcut plan:
{current_steps}

Geri bildirim: {feedback}

Planı revize et. Her satırda bir adım olsun:
1."""
        
        try:
            response = await self._llm.complete(prompt)
            
            # Parse new steps
            new_steps = []
            for line in response.split("\n"):
                line = line.strip()
                match = re.match(r"^(?:\d+[\.\)]\s*)?(.+)$", line)
                if match and match.group(1).strip():
                    new_steps.append({
                        "action": self._infer_action(match.group(1)),
                        "description": match.group(1).strip(),
                    })
            
            if new_steps:
                revised = create_task_plan(plan.goal, new_steps)
                revised.context = plan.context
                revised.template_id = plan.template_id
                return revised
            
        except Exception:
            pass
        
        return plan


def create_planner(
    llm_client: Optional[LLMClient] = None,
    template_registry: Optional["TemplateRegistry"] = None,
) -> Planner:
    """
    Factory function to create a planner.
    
    Args:
        llm_client: LLM client for plan generation.
        template_registry: Registry of task templates.
        
    Returns:
        Configured Planner instance.
    """
    return Planner(
        llm_client=llm_client,
        template_registry=template_registry,
    )
