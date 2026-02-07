"""
Base class for competitive / resource-strategic environments.

Adds resource-management helpers on top of the generic Environment.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, List

from mas_risk_toolkit.environments.base import Environment, EnvironmentConfig


class CompetitiveEnvironment(Environment):
    """Environments where agents compete for shared, scarce resources.

    Subclasses should implement the resource allocation mechanism
    (``allocate``) and the concrete ``step`` / ``reset`` logic.
    """

    def __init__(self, config: EnvironmentConfig) -> None:
        super().__init__(config)
        self.resource_capacity: Dict[str, float] = config.parameters.get(
            "resource_capacity", {}
        )
        self.allocation_history: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Competitive-specific interface
    # ------------------------------------------------------------------

    @abstractmethod
    def allocate(
        self, requests: Dict[str, float]
    ) -> Dict[str, float]:
        """Given agent requests, return realised allocations.

        This is the allocation mechanism F in the paper's formalism.
        """
        ...

    def get_resource_utilisation(self) -> Dict[str, float]:
        """Return current utilisation ratios per resource type."""
        return dict(self.resource_capacity)
