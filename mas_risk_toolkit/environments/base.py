"""
Base Environment abstraction.

Design rationale:
    Risk is NOT an agent property alone — it is a product of
    Agent × Environment × Protocol.

An environment encapsulates:
    - State       : shared or partial global state
    - Constraints : resource caps, queue rules, deadlines
    - Transition  : how joint actions change the state
    - Failure     : conditions that mark system-level failure
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class EnvironmentConfig:
    """Serialisable configuration for an environment instance."""

    name: str
    env_type: str  # "competitive" | "cooperative" | "collective"
    max_rounds: int = 10
    num_agents: int = 2
    parameters: Dict[str, Any] = field(default_factory=dict)


class Environment(ABC):
    """Abstract base class for all environments.

    The API follows the standard ``reset → step → … → done`` loop.
    Each ``step`` receives a *joint action* (dict keyed by agent_id)
    and returns observations, rewards, done flag, and info.
    """

    def __init__(self, config: EnvironmentConfig) -> None:
        self.config = config
        self.name: str = config.name
        self.env_type: str = config.env_type
        self.max_rounds: int = config.max_rounds
        self.current_round: int = 0
        self.state: Dict[str, Any] = {}
        self.done: bool = False

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    @abstractmethod
    def reset(self) -> Dict[str, Any]:
        """Reset to an initial state and return the initial observations.

        Returns
        -------
        observations : dict
            Mapping ``{agent_id: observation}`` for each agent.
        """
        ...

    @abstractmethod
    def step(
        self,
        joint_action: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, float], bool, Dict[str, Any]]:
        """Advance the environment by one round given joint actions.

        Parameters
        ----------
        joint_action : dict
            ``{agent_id: action}`` for each participating agent.

        Returns
        -------
        observations : dict[str, Any]
            Per-agent observations for the new state.
        rewards : dict[str, float]
            Per-agent reward signals.
        done : bool
            Whether the episode has ended.
        info : dict[str, Any]
            Auxiliary information (e.g. system-level metrics).
        """
        ...

    @abstractmethod
    def get_observation(self, agent_id: str) -> Dict[str, Any]:
        """Return the (possibly filtered) observation for a given agent.

        This enables **information asymmetry**: different agents may see
        different slices of the global state.
        """
        ...

    # ------------------------------------------------------------------
    # Optional hooks for subclasses
    # ------------------------------------------------------------------

    def check_failure(self) -> Optional[str]:
        """Return a failure reason string if a system-level failure has
        occurred, or ``None`` if the system is healthy."""
        return None

    def get_system_state(self) -> Dict[str, Any]:
        """Return the full system state (for logging / evaluation)."""
        return dict(self.state)

    def __repr__(self) -> str:
        return (
            f"Environment(name={self.name!r}, type={self.env_type!r}, "
            f"round={self.current_round}/{self.max_rounds})"
        )
