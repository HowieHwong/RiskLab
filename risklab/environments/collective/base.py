"""
Base class for collective decision-making environments.

Adds aggregation and voting helpers.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, List

from risklab.environments.base import Environment, EnvironmentConfig


class CollectiveEnvironment(Environment):
    """Environments where agents aggregate evidence / preferences to form
    a shared decision (e.g. deliberation, moderation, voting).

    Subclasses implement the aggregation rule and authority structure.
    """

    def __init__(self, config: EnvironmentConfig) -> None:
        super().__init__(config)
        self.votes: List[Dict[str, Any]] = []
        self.authority_map: Dict[str, float] = config.parameters.get(
            "authority_map", {}
        )

    # ------------------------------------------------------------------
    # Collective-specific interface
    # ------------------------------------------------------------------

    @abstractmethod
    def aggregate(
        self, judgments: Dict[str, Any]
    ) -> Any:
        """Aggregate individual agent judgments into a group decision.

        Parameters
        ----------
        judgments : dict
            ``{agent_id: judgment}`` for each participating agent.

        Returns
        -------
        decision : Any
            The collective decision (format depends on the task).
        """
        ...

    def get_authority(self, agent_id: str) -> float:
        """Return the authority weight for *agent_id* (default 1.0)."""
        return self.authority_map.get(agent_id, 1.0)
