"""
Base Agent abstraction.

Design rationale (maps to the paper's formal framework):
    Agent = Policy + Role + Local View + Incentives

Each agent is characterised by:
    - agent_id   : unique identifier
    - role       : functional role (planner, executor, seller, moderator, …)
    - model      : underlying LLM backend identifier
    - objective  : utility specification (agent-level u_i)
    - observation_space : controls information asymmetry (I_i)
    - action_space      : set of permissible actions
    - memory     : supports history-dependent behaviour
    - system_prompt : role-specific prompt text
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AgentConfig:
    """Serialisable configuration that fully specifies an agent."""

    agent_id: str
    role: str
    model: str = "gpt-4o"
    objective: str = "selfish"  # selfish | cooperative | system
    system_prompt: str = ""
    observation_filter: Optional[str] = None  # controls what part of state is visible
    action_space: Optional[List[str]] = None
    parameters: Dict[str, Any] = field(default_factory=dict)


class Agent(ABC):
    """Abstract base class for all agents in the toolkit.

    Subclass this to create concrete agents backed by different LLM APIs
    or rule-based policies.  The minimal contract is:
        - ``act``   : given an observation, return an action / message.
        - ``observe``: receive an observation from the environment.
        - ``reset``  : reset internal state for a new episode.
    """

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.agent_id: str = config.agent_id
        self.role: str = config.role
        self.model: str = config.model
        self.objective: str = config.objective
        self.system_prompt: str = config.system_prompt
        self.memory: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    @abstractmethod
    def act(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Given the current observation, produce an action / message.

        Parameters
        ----------
        observation : dict
            Filtered view of the global state (respects ``observation_filter``).

        Returns
        -------
        dict
            Must contain at least ``{"message": str, "action": Any}``.
        """
        ...

    def observe(self, observation: Dict[str, Any]) -> None:
        """Receive and optionally store an observation."""
        self.memory.append(observation)

    def reset(self) -> None:
        """Reset the agent's internal state for a new episode."""
        self.memory.clear()

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def get_history(self) -> List[Dict[str, Any]]:
        """Return the full memory / history of this agent."""
        return list(self.memory)

    def __repr__(self) -> str:
        return (
            f"Agent(id={self.agent_id!r}, role={self.role!r}, "
            f"model={self.model!r}, objective={self.objective!r})"
        )
