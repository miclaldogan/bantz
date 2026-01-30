"""
Verifier module.

Verifies execution results to ensure goals are achieved.
"""

from dataclasses import dataclass, field
from typing import Optional, Protocol

from bantz.automation.plan import TaskPlan, PlanStep
from bantz.automation.executor import ExecutionResult


class LLMClient(Protocol):
    """Protocol for LLM clients."""
    
    async def complete(self, prompt: str) -> str:
        """Complete a prompt."""
        ...


@dataclass
class VerificationResult:
    """Result of verification."""
    
    step_id: Optional[str] = None
    """Step ID (None for plan-level verification)."""
    
    verified: bool = False
    """Whether verification passed."""
    
    confidence: float = 0.0
    """Confidence score (0.0 - 1.0)."""
    
    evidence: Optional[str] = None
    """Evidence supporting the verification."""
    
    issues: list[str] = field(default_factory=list)
    """List of detected issues."""
    
    suggestions: list[str] = field(default_factory=list)
    """Suggestions for fixing issues."""
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "step_id": self.step_id,
            "verified": self.verified,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "issues": self.issues,
            "suggestions": self.suggestions,
        }


class Verifier:
    """
    Verifies execution results.
    
    Checks if steps and plans achieved their intended goals.
    """
    
    # Minimum confidence for automatic pass
    MIN_CONFIDENCE_THRESHOLD = 0.7
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        """
        Initialize the verifier.
        
        Args:
            llm_client: LLM client for semantic verification.
        """
        self._llm = llm_client
    
    async def verify_step(
        self,
        step: PlanStep,
        result: ExecutionResult,
    ) -> VerificationResult:
        """
        Verify a step's execution result.
        
        Args:
            step: The executed step.
            result: The execution result.
            
        Returns:
            Verification result.
        """
        # Basic verification without LLM
        if result.success:
            # Check if result is meaningful
            if result.result is not None:
                return VerificationResult(
                    step_id=step.id,
                    verified=True,
                    confidence=0.8,
                    evidence=f"Step completed successfully with result: {str(result.result)[:100]}",
                )
            else:
                return VerificationResult(
                    step_id=step.id,
                    verified=True,
                    confidence=0.6,
                    evidence="Step completed but returned no result",
                    issues=["No result returned - verify manually if needed"],
                )
        else:
            return VerificationResult(
                step_id=step.id,
                verified=False,
                confidence=0.9,
                evidence=f"Step failed with error: {result.error}",
                issues=[result.error or "Unknown error"],
                suggestions=["Retry the step", "Check input parameters"],
            )
    
    async def verify_step_with_llm(
        self,
        step: PlanStep,
        result: ExecutionResult,
    ) -> VerificationResult:
        """
        Verify step using LLM for semantic analysis.
        
        Args:
            step: The executed step.
            result: The execution result.
            
        Returns:
            Verification result.
        """
        if not self._llm:
            return await self.verify_step(step, result)
        
        prompt = self.get_verification_prompt(step, result)
        
        try:
            response = await self._llm.complete(prompt)
            
            # Parse LLM response
            verified = "evet" in response.lower() or "başarılı" in response.lower()
            confidence = 0.85 if verified else 0.75
            
            issues = []
            if not verified:
                # Extract issues from response
                for line in response.split("\n"):
                    if "sorun" in line.lower() or "hata" in line.lower():
                        issues.append(line.strip())
            
            return VerificationResult(
                step_id=step.id,
                verified=verified,
                confidence=confidence,
                evidence=response[:200],
                issues=issues,
            )
            
        except Exception as e:
            # Fall back to basic verification
            basic_result = await self.verify_step(step, result)
            basic_result.issues.append(f"LLM verification failed: {e}")
            return basic_result
    
    async def verify_plan(
        self,
        plan: TaskPlan,
        results: list[ExecutionResult],
    ) -> VerificationResult:
        """
        Verify entire plan execution.
        
        Args:
            plan: The executed plan.
            results: All execution results.
            
        Returns:
            Plan-level verification result.
        """
        # Count successes and failures
        successes = sum(1 for r in results if r.success)
        failures = sum(1 for r in results if not r.success)
        total = len(results)
        
        if total == 0:
            return VerificationResult(
                verified=False,
                confidence=0.0,
                issues=["No steps were executed"],
            )
        
        success_rate = successes / total
        
        # All steps succeeded
        if failures == 0:
            return VerificationResult(
                verified=True,
                confidence=0.9,
                evidence=f"All {total} steps completed successfully",
            )
        
        # Some failures
        issues = [
            f"{failures} of {total} steps failed",
        ]
        
        # Add specific failure details
        for result in results:
            if not result.success:
                issues.append(f"Step {result.step_id}: {result.error}")
        
        # Determine if overall plan succeeded
        # Consider partial success if > 70% steps passed
        verified = success_rate >= 0.7
        
        return VerificationResult(
            verified=verified,
            confidence=success_rate,
            evidence=f"Success rate: {success_rate:.1%}",
            issues=issues,
            suggestions=[
                "Review failed steps",
                "Consider retrying with modified parameters",
            ] if not verified else [],
        )
    
    def get_verification_prompt(
        self,
        step: PlanStep,
        result: ExecutionResult,
    ) -> str:
        """
        Generate verification prompt for LLM.
        
        Args:
            step: The executed step.
            result: The execution result.
            
        Returns:
            Prompt string.
        """
        prompt = f"""Aşağıdaki adımın başarıyla tamamlanıp tamamlanmadığını doğrula.

Adım: {step.description}
Eylem: {step.action}
Parametreler: {step.parameters}

Sonuç:
- Başarılı: {"Evet" if result.success else "Hayır"}
- Çıktı: {str(result.result)[:500] if result.result else "Yok"}
- Hata: {result.error or "Yok"}

Bu adım hedefine ulaştı mı? Neden?
"""
        return prompt
    
    async def quick_verify(
        self,
        step: PlanStep,
        result: ExecutionResult,
    ) -> bool:
        """
        Quick verification without detailed analysis.
        
        Args:
            step: The executed step.
            result: The execution result.
            
        Returns:
            True if verified, False otherwise.
        """
        # Simple success check
        if not result.success:
            return False
        
        # Check for meaningful result
        if result.result is None:
            return True  # No result expected
        
        # Check result is not empty
        if isinstance(result.result, (list, dict, str)):
            return bool(result.result)
        
        return True


def create_verifier(llm_client: Optional[LLMClient] = None) -> Verifier:
    """
    Factory function to create a verifier.
    
    Args:
        llm_client: LLM client for semantic verification.
        
    Returns:
        Configured Verifier instance.
    """
    return Verifier(llm_client=llm_client)
