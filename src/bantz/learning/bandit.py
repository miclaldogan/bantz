"""
Contextual Bandit module.

Epsilon-greedy exploration/exploitation for action selection.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ArmStats:
    """Statistics for a bandit arm (action)."""
    
    arm_id: str
    """Identifier for this arm."""
    
    pulls: int = 0
    """Number of times this arm was pulled."""
    
    total_reward: float = 0.0
    """Total accumulated reward."""
    
    last_pulled: Optional[datetime] = None
    """When this arm was last pulled."""
    
    context_rewards: Dict[str, float] = field(default_factory=dict)
    """Rewards by context key."""
    
    context_counts: Dict[str, int] = field(default_factory=dict)
    """Pull counts by context key."""
    
    @property
    def mean_reward(self) -> float:
        """Average reward for this arm."""
        if self.pulls == 0:
            return 0.0
        return self.total_reward / self.pulls
    
    def get_contextual_reward(self, context_key: str) -> float:
        """Get mean reward for a specific context."""
        count = self.context_counts.get(context_key, 0)
        if count == 0:
            return self.mean_reward  # Fall back to overall
        return self.context_rewards.get(context_key, 0.0) / count
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "arm_id": self.arm_id,
            "pulls": self.pulls,
            "total_reward": self.total_reward,
            "last_pulled": self.last_pulled.isoformat() if self.last_pulled else None,
            "context_rewards": self.context_rewards,
            "context_counts": self.context_counts,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArmStats":
        """Create from dictionary."""
        return cls(
            arm_id=data["arm_id"],
            pulls=data.get("pulls", 0),
            total_reward=data.get("total_reward", 0.0),
            last_pulled=datetime.fromisoformat(data["last_pulled"]) if data.get("last_pulled") else None,
            context_rewards=data.get("context_rewards", {}),
            context_counts=data.get("context_counts", {}),
        )


class ContextualBandit:
    """
    Contextual multi-armed bandit with epsilon-greedy exploration.
    
    Uses context to make better action selections while balancing
    exploration (trying new things) and exploitation (using known good actions).
    """
    
    # Default exploration rate
    DEFAULT_EPSILON = 0.1
    
    # Epsilon decay rate
    EPSILON_DECAY = 0.99
    
    # Minimum epsilon
    MIN_EPSILON = 0.01
    
    # UCB exploration constant
    UCB_CONSTANT = 2.0
    
    def __init__(
        self,
        epsilon: float = DEFAULT_EPSILON,
        use_ucb: bool = False,
        decay_epsilon: bool = True,
    ):
        """
        Initialize the contextual bandit.
        
        Args:
            epsilon: Exploration probability (0.0 - 1.0).
            use_ucb: Whether to use UCB instead of epsilon-greedy.
            decay_epsilon: Whether to decay epsilon over time.
        """
        self._epsilon = epsilon
        self._use_ucb = use_ucb
        self._decay_epsilon = decay_epsilon
        self._arms: Dict[str, ArmStats] = {}
        self._total_pulls = 0
    
    @property
    def epsilon(self) -> float:
        """Current exploration rate."""
        return self._epsilon
    
    @property
    def arms(self) -> Dict[str, ArmStats]:
        """All arms."""
        return self._arms
    
    def add_arm(self, arm_id: str) -> ArmStats:
        """
        Add a new arm (action).
        
        Args:
            arm_id: Identifier for the arm.
            
        Returns:
            The new ArmStats.
        """
        if arm_id not in self._arms:
            self._arms[arm_id] = ArmStats(arm_id=arm_id)
        return self._arms[arm_id]
    
    def remove_arm(self, arm_id: str) -> bool:
        """
        Remove an arm.
        
        Args:
            arm_id: Arm to remove.
            
        Returns:
            Whether arm was removed.
        """
        if arm_id in self._arms:
            del self._arms[arm_id]
            return True
        return False
    
    def select_arm(
        self,
        available_arms: Optional[List[str]] = None,
        context: Dict = None,
    ) -> Optional[str]:
        """
        Select an arm using epsilon-greedy or UCB.
        
        Args:
            available_arms: Arms to choose from (or all if None).
            context: Current context for contextual selection.
            
        Returns:
            Selected arm ID or None if no arms.
        """
        context = context or {}
        
        # Get available arms
        if available_arms:
            arms = [self._arms.get(a) or self.add_arm(a) for a in available_arms]
        else:
            arms = list(self._arms.values())
        
        if not arms:
            return None
        
        # Get context key for contextual rewards
        context_key = self._get_context_key(context)
        
        if self._use_ucb:
            return self._select_ucb(arms, context_key)
        else:
            return self._select_epsilon_greedy(arms, context_key)
    
    def update_arm(
        self,
        arm_id: str,
        reward: float,
        context: Dict = None,
    ) -> None:
        """
        Update arm statistics after receiving reward.
        
        Args:
            arm_id: The arm that was pulled.
            reward: The reward received.
            context: Context when pulled.
        """
        context = context or {}
        
        # Ensure arm exists
        if arm_id not in self._arms:
            self.add_arm(arm_id)
        
        arm = self._arms[arm_id]
        
        # Update overall stats
        arm.pulls += 1
        arm.total_reward += reward
        arm.last_pulled = datetime.now()
        self._total_pulls += 1
        
        # Update contextual stats
        context_key = self._get_context_key(context)
        if context_key:
            arm.context_rewards[context_key] = arm.context_rewards.get(context_key, 0.0) + reward
            arm.context_counts[context_key] = arm.context_counts.get(context_key, 0) + 1
        
        # Decay epsilon
        if self._decay_epsilon:
            self._epsilon = max(self.MIN_EPSILON, self._epsilon * self.EPSILON_DECAY)
    
    def get_arm_stats(self, arm_id: str) -> Optional[ArmStats]:
        """
        Get statistics for an arm.
        
        Args:
            arm_id: Arm identifier.
            
        Returns:
            ArmStats or None.
        """
        return self._arms.get(arm_id)
    
    def get_best_arm(
        self,
        context: Dict = None,
        available_arms: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Get the best arm (pure exploitation).
        
        Args:
            context: Context for selection.
            available_arms: Arms to consider.
            
        Returns:
            Best arm ID or None.
        """
        context = context or {}
        context_key = self._get_context_key(context)
        
        if available_arms:
            arms = [self._arms.get(a) for a in available_arms if a in self._arms]
        else:
            arms = list(self._arms.values())
        
        if not arms:
            return None
        
        # Get arm with highest reward
        if context_key:
            best = max(arms, key=lambda a: a.get_contextual_reward(context_key))
        else:
            best = max(arms, key=lambda a: a.mean_reward)
        
        return best.arm_id
    
    def get_rankings(
        self,
        context: Dict = None,
        limit: int = 10,
    ) -> List[Tuple[str, float]]:
        """
        Get arm rankings.
        
        Args:
            context: Context for ranking.
            limit: Max arms to return.
            
        Returns:
            List of (arm_id, score) tuples.
        """
        context = context or {}
        context_key = self._get_context_key(context)
        
        if context_key:
            sorted_arms = sorted(
                self._arms.values(),
                key=lambda a: a.get_contextual_reward(context_key),
                reverse=True,
            )
        else:
            sorted_arms = sorted(
                self._arms.values(),
                key=lambda a: a.mean_reward,
                reverse=True,
            )
        
        return [(a.arm_id, a.mean_reward) for a in sorted_arms[:limit]]
    
    def set_epsilon(self, epsilon: float) -> None:
        """Set exploration rate."""
        self._epsilon = max(0.0, min(1.0, epsilon))
    
    def reset(self) -> None:
        """Reset all arm statistics."""
        self._arms.clear()
        self._total_pulls = 0
        self._epsilon = self.DEFAULT_EPSILON
    
    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary."""
        return {
            "epsilon": self._epsilon,
            "use_ucb": self._use_ucb,
            "decay_epsilon": self._decay_epsilon,
            "total_pulls": self._total_pulls,
            "arms": {k: v.to_dict() for k, v in self._arms.items()},
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load from dictionary."""
        self._epsilon = data.get("epsilon", self.DEFAULT_EPSILON)
        self._use_ucb = data.get("use_ucb", False)
        self._decay_epsilon = data.get("decay_epsilon", True)
        self._total_pulls = data.get("total_pulls", 0)
        
        arms_data = data.get("arms", {})
        self._arms = {k: ArmStats.from_dict(v) for k, v in arms_data.items()}
    
    def _select_epsilon_greedy(
        self,
        arms: List[ArmStats],
        context_key: str,
    ) -> str:
        """Epsilon-greedy selection."""
        # Exploration: random arm
        if random.random() < self._epsilon:
            return random.choice(arms).arm_id
        
        # Exploitation: best arm
        if context_key:
            best = max(arms, key=lambda a: a.get_contextual_reward(context_key))
        else:
            best = max(arms, key=lambda a: a.mean_reward)
        
        return best.arm_id
    
    def _select_ucb(
        self,
        arms: List[ArmStats],
        context_key: str,
    ) -> str:
        """UCB (Upper Confidence Bound) selection."""
        import math
        
        if self._total_pulls == 0:
            return random.choice(arms).arm_id
        
        best_arm = None
        best_ucb = float('-inf')
        
        for arm in arms:
            if arm.pulls == 0:
                # Unpulled arms get infinite priority
                return arm.arm_id
            
            # Get base value
            if context_key:
                value = arm.get_contextual_reward(context_key)
            else:
                value = arm.mean_reward
            
            # UCB bonus
            bonus = self.UCB_CONSTANT * math.sqrt(
                math.log(self._total_pulls) / arm.pulls
            )
            
            ucb = value + bonus
            
            if ucb > best_ucb:
                best_ucb = ucb
                best_arm = arm
        
        return best_arm.arm_id if best_arm else arms[0].arm_id
    
    def _get_context_key(self, context: Dict) -> str:
        """Generate context key for contextual lookups."""
        if not context:
            return ""
        
        # Create a simple key from sorted context items
        relevant_keys = ["hour", "day", "app", "intent"]
        parts = []
        
        for key in relevant_keys:
            if key in context:
                parts.append(f"{key}:{context[key]}")
        
        return "|".join(parts)


def create_contextual_bandit(
    epsilon: float = ContextualBandit.DEFAULT_EPSILON,
    use_ucb: bool = False,
    decay_epsilon: bool = True,
) -> ContextualBandit:
    """
    Factory function to create a contextual bandit.
    
    Args:
        epsilon: Exploration probability.
        use_ucb: Whether to use UCB.
        decay_epsilon: Whether to decay epsilon.
        
    Returns:
        Configured ContextualBandit instance.
    """
    return ContextualBandit(
        epsilon=epsilon,
        use_ucb=use_ucb,
        decay_epsilon=decay_epsilon,
    )
