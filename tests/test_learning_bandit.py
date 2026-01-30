"""
Tests for ContextualBandit.
"""

import pytest

from bantz.learning.bandit import (
    ContextualBandit,
    ArmStats,
    create_contextual_bandit,
)


class TestArmStats:
    """Tests for ArmStats dataclass."""
    
    def test_create_arm(self):
        """Test creating an arm."""
        arm = ArmStats(arm_id="action1")
        
        assert arm.arm_id == "action1"
        assert arm.pulls == 0
        assert arm.total_reward == 0.0
    
    def test_mean_reward_no_pulls(self):
        """Test mean reward with no pulls."""
        arm = ArmStats(arm_id="test")
        
        assert arm.mean_reward == 0.0
    
    def test_mean_reward_with_pulls(self):
        """Test mean reward calculation."""
        arm = ArmStats(
            arm_id="test",
            pulls=10,
            total_reward=8.0,
        )
        
        assert arm.mean_reward == 0.8
    
    def test_contextual_reward(self):
        """Test contextual reward."""
        arm = ArmStats(
            arm_id="test",
            context_rewards={"hour:10": 5.0},
            context_counts={"hour:10": 5},
        )
        
        reward = arm.get_contextual_reward("hour:10")
        assert reward == 1.0
    
    def test_contextual_reward_fallback(self):
        """Test contextual reward falls back to overall."""
        arm = ArmStats(
            arm_id="test",
            pulls=10,
            total_reward=5.0,
        )
        
        reward = arm.get_contextual_reward("unknown")
        assert reward == 0.5
    
    def test_to_dict(self):
        """Test serialization."""
        arm = ArmStats(
            arm_id="action1",
            pulls=5,
            total_reward=3.0,
        )
        
        data = arm.to_dict()
        
        assert data["arm_id"] == "action1"
        assert data["pulls"] == 5
        assert data["total_reward"] == 3.0
    
    def test_from_dict(self):
        """Test deserialization."""
        data = {
            "arm_id": "action1",
            "pulls": 10,
            "total_reward": 7.0,
            "context_rewards": {},
            "context_counts": {},
        }
        
        arm = ArmStats.from_dict(data)
        
        assert arm.arm_id == "action1"
        assert arm.pulls == 10
        assert arm.mean_reward == 0.7


class TestContextualBandit:
    """Tests for ContextualBandit class."""
    
    def test_create_bandit(self):
        """Test creating a bandit."""
        bandit = ContextualBandit()
        
        assert bandit.epsilon == ContextualBandit.DEFAULT_EPSILON
    
    def test_create_with_custom_epsilon(self):
        """Test creating with custom epsilon."""
        bandit = ContextualBandit(epsilon=0.2)
        
        assert bandit.epsilon == 0.2
    
    def test_add_arm(self):
        """Test adding an arm."""
        bandit = ContextualBandit()
        
        arm = bandit.add_arm("action1")
        
        assert arm is not None
        assert arm.arm_id == "action1"
        assert "action1" in bandit.arms
    
    def test_add_arm_duplicate(self):
        """Test adding duplicate arm."""
        bandit = ContextualBandit()
        
        arm1 = bandit.add_arm("action1")
        arm2 = bandit.add_arm("action1")
        
        assert arm1 is arm2
    
    def test_remove_arm(self):
        """Test removing an arm."""
        bandit = ContextualBandit()
        
        bandit.add_arm("action1")
        result = bandit.remove_arm("action1")
        
        assert result is True
        assert "action1" not in bandit.arms
    
    def test_remove_nonexistent_arm(self):
        """Test removing nonexistent arm."""
        bandit = ContextualBandit()
        
        result = bandit.remove_arm("unknown")
        
        assert result is False
    
    def test_select_arm_empty(self):
        """Test selecting from empty bandit."""
        bandit = ContextualBandit()
        
        selected = bandit.select_arm()
        
        assert selected is None
    
    def test_select_arm_single(self):
        """Test selecting from single arm."""
        bandit = ContextualBandit()
        bandit.add_arm("only_option")
        
        selected = bandit.select_arm()
        
        assert selected == "only_option"
    
    def test_select_arm_exploration(self):
        """Test exploration mode."""
        bandit = ContextualBandit(epsilon=1.0)  # Always explore
        
        bandit.add_arm("action1")
        bandit.add_arm("action2")
        
        # With epsilon=1.0, should randomly select
        selections = set()
        for _ in range(100):
            selections.add(bandit.select_arm())
        
        # Should have selected both at some point
        assert len(selections) == 2
    
    def test_select_arm_exploitation(self):
        """Test exploitation mode."""
        bandit = ContextualBandit(epsilon=0.0)  # Always exploit
        
        bandit.add_arm("bad")
        bandit.add_arm("good")
        
        # Make "good" have higher reward
        bandit.update_arm("good", 1.0)
        bandit.update_arm("good", 1.0)
        bandit.update_arm("bad", -1.0)
        
        # With epsilon=0, should always select best
        for _ in range(10):
            assert bandit.select_arm() == "good"
    
    def test_select_arm_with_available(self):
        """Test selecting from subset of arms."""
        bandit = ContextualBandit(epsilon=0.0)
        
        bandit.add_arm("a")
        bandit.add_arm("b")
        bandit.add_arm("c")
        
        bandit.update_arm("a", 1.0)  # Best overall
        bandit.update_arm("c", 0.5)
        
        # But only b and c available
        selected = bandit.select_arm(available_arms=["b", "c"])
        
        assert selected == "c"  # Best among available
    
    def test_update_arm(self):
        """Test updating an arm."""
        bandit = ContextualBandit()
        
        bandit.add_arm("action1")
        bandit.update_arm("action1", 1.0)
        
        arm = bandit.get_arm_stats("action1")
        
        assert arm.pulls == 1
        assert arm.total_reward == 1.0
    
    def test_update_arm_creates_if_missing(self):
        """Test update creates arm if missing."""
        bandit = ContextualBandit()
        
        bandit.update_arm("new_action", 0.5)
        
        assert "new_action" in bandit.arms
    
    def test_update_arm_contextual(self):
        """Test contextual update."""
        bandit = ContextualBandit()
        
        bandit.update_arm("action1", 1.0, context={"hour": 10})
        
        arm = bandit.get_arm_stats("action1")
        
        assert len(arm.context_rewards) > 0
    
    def test_epsilon_decay(self):
        """Test epsilon decays."""
        bandit = ContextualBandit(epsilon=0.5, decay_epsilon=True)
        
        initial = bandit.epsilon
        bandit.update_arm("action", 0.5)
        
        assert bandit.epsilon < initial
    
    def test_epsilon_no_decay(self):
        """Test epsilon doesn't decay when disabled."""
        bandit = ContextualBandit(epsilon=0.5, decay_epsilon=False)
        
        initial = bandit.epsilon
        bandit.update_arm("action", 0.5)
        
        assert bandit.epsilon == initial
    
    def test_get_best_arm(self):
        """Test getting best arm."""
        bandit = ContextualBandit()
        
        bandit.update_arm("a", 0.5)
        bandit.update_arm("b", 1.0)
        bandit.update_arm("c", 0.3)
        
        best = bandit.get_best_arm()
        
        assert best == "b"
    
    def test_get_best_arm_empty(self):
        """Test getting best arm when empty."""
        bandit = ContextualBandit()
        
        best = bandit.get_best_arm()
        
        assert best is None
    
    def test_get_rankings(self):
        """Test getting arm rankings."""
        bandit = ContextualBandit()
        
        bandit.update_arm("a", 0.5)
        bandit.update_arm("b", 1.0)
        bandit.update_arm("c", 0.3)
        
        rankings = bandit.get_rankings(limit=2)
        
        assert len(rankings) == 2
        assert rankings[0][0] == "b"
        assert rankings[1][0] == "a"
    
    def test_set_epsilon(self):
        """Test setting epsilon."""
        bandit = ContextualBandit()
        
        bandit.set_epsilon(0.3)
        
        assert bandit.epsilon == 0.3
    
    def test_set_epsilon_clamped(self):
        """Test epsilon is clamped."""
        bandit = ContextualBandit()
        
        bandit.set_epsilon(1.5)
        assert bandit.epsilon == 1.0
        
        bandit.set_epsilon(-0.5)
        assert bandit.epsilon == 0.0
    
    def test_reset(self):
        """Test reset."""
        bandit = ContextualBandit()
        
        bandit.add_arm("a")
        bandit.update_arm("a", 1.0)
        
        bandit.reset()
        
        assert len(bandit.arms) == 0
        assert bandit.epsilon == ContextualBandit.DEFAULT_EPSILON
    
    def test_to_dict(self):
        """Test serialization."""
        bandit = ContextualBandit(epsilon=0.3, decay_epsilon=False)  # Disable decay
        
        bandit.update_arm("action1", 0.5)
        
        data = bandit.to_dict()
        
        assert data["epsilon"] == 0.3
        assert "action1" in data["arms"]
    
    def test_from_dict(self):
        """Test deserialization."""
        bandit = ContextualBandit()
        
        data = {
            "epsilon": 0.4,
            "use_ucb": False,
            "decay_epsilon": True,
            "total_pulls": 10,
            "arms": {
                "action1": {
                    "arm_id": "action1",
                    "pulls": 5,
                    "total_reward": 3.0,
                    "context_rewards": {},
                    "context_counts": {},
                }
            },
        }
        
        bandit.from_dict(data)
        
        assert bandit.epsilon == 0.4
        assert "action1" in bandit.arms
        assert bandit.arms["action1"].pulls == 5


class TestUCB:
    """Tests for UCB selection."""
    
    def test_ucb_selects_unexplored(self):
        """Test UCB prefers unexplored arms."""
        bandit = ContextualBandit(use_ucb=True)
        
        bandit.add_arm("explored")
        bandit.add_arm("unexplored")
        
        # Pull explored arm
        bandit.update_arm("explored", 0.5)
        
        # UCB should select unexplored first
        selected = bandit.select_arm()
        
        assert selected == "unexplored"
    
    def test_ucb_balances_exploration(self):
        """Test UCB balances exploration and exploitation."""
        bandit = ContextualBandit(use_ucb=True)
        
        bandit.add_arm("good")
        bandit.add_arm("uncertain")
        
        # Good arm has high reward but many pulls
        for _ in range(20):
            bandit.update_arm("good", 0.8)
        
        # Uncertain has lower but fewer pulls
        bandit.update_arm("uncertain", 0.5)
        
        # UCB might select uncertain due to exploration bonus
        selections = []
        for _ in range(10):
            selections.append(bandit.select_arm())
        
        # Should have tried uncertain at least once
        assert "uncertain" in selections


class TestFactory:
    """Tests for factory function."""
    
    def test_create_contextual_bandit(self):
        """Test factory function."""
        bandit = create_contextual_bandit()
        
        assert bandit is not None
        assert isinstance(bandit, ContextualBandit)
    
    def test_create_with_options(self):
        """Test factory with options."""
        bandit = create_contextual_bandit(
            epsilon=0.3,
            use_ucb=True,
        )
        
        assert bandit.epsilon == 0.3
