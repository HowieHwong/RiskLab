"""
Base class for cooperative / pipeline-based environments.

Adds sequential-handoff and information-relay helpers.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, List, Optional

from mas_risk_toolkit.environments.base import Environment, EnvironmentConfig


class CooperativeEnvironment(Environment):
    """Environments where agents collaborate through pipelines / relays.

    Subclasses define the pipeline topology, handoff rules, and
    how information is passed from one stage to the next.
    """

    def __init__(self, config: EnvironmentConfig) -> None:
        super().__init__(config)
        # Ordered list of agent IDs in the pipeline
        self.pipeline_order: List[str] = config.parameters.get(
            "pipeline_order", []
        )
        self.handoff_history: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Cooperative-specific interface
    # ------------------------------------------------------------------

    @abstractmethod
    def handoff(
        self,
        sender_id: str,
        receiver_id: str,
        payload: Any,
    ) -> Any:
        """Transfer information from *sender* to *receiver*.

        Subclasses may introduce noise, filtering, or summarisation.
        """
        ...

    def get_pipeline_state(self) -> List[Dict[str, Any]]:
        """Return the full handoff history for analysis."""
        return list(self.handoff_history)
