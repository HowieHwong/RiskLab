"""
Base Risk abstraction.

Design principles (from the paper):
    Risk ≠ failure ≠ bad outcome.
    Risk is a *pattern-level, interaction-induced deviation*.

Each risk is defined by three components:
    1. **Where it lives**   — lifecycle stage(s) where it manifests
    2. **Observable signature** — what the trajectory looks like when the risk is present
    3. **Counterfactual**    — a feasible but un-adopted system-optimal outcome exists
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ------------------------------------------------------------------
# Enums for taxonomy (directly from the paper)
# ------------------------------------------------------------------

class RiskCategory(str, Enum):
    """Three broad risk families from the paper's taxonomy."""

    COMPETITIVE = "competitive"          # Resource-strategic risks
    COOPERATIVE = "cooperative"          # Information-propagation risks
    COLLECTIVE = "collective_decision"   # Authority-structure risks


class LifecycleStage(str, Enum):
    """MAS operational lifecycle stages (§ Preliminary of the paper)."""

    INITIALIZATION = "initialization"
    DELIBERATION = "deliberation"
    COORDINATION = "coordination"
    EXECUTION = "execution"
    ADAPTATION = "adaptation"


# ------------------------------------------------------------------
# Risk configuration
# ------------------------------------------------------------------

@dataclass
class RiskConfig:
    """Serialisable metadata for a risk definition."""

    risk_id: str                         # e.g. "risk_02_tacit_collusion"
    name: str                            # human-readable name
    category: RiskCategory
    lifecycle_stages: List[LifecycleStage]
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------
# Abstract Risk class
# ------------------------------------------------------------------

class Risk(ABC):
    """Abstract base class for all risk definitions.

    Subclass this to define a concrete risk.  The minimal contract is:
        - ``detect``  : binary detection on a trajectory
        - ``score``   : continuous severity scoring
        - ``describe``: human-readable explanation of the signature
    """

    def __init__(self, config: RiskConfig) -> None:
        self.config = config
        self.risk_id: str = config.risk_id
        self.name: str = config.name
        self.category: RiskCategory = config.category
        self.lifecycle_stages: List[LifecycleStage] = config.lifecycle_stages

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    @abstractmethod
    def detect(self, trajectory: List[Dict[str, Any]]) -> bool:
        """Return ``True`` if the risk pattern is present in *trajectory*.

        Parameters
        ----------
        trajectory : list[dict]
            Sequence of round-level records produced by the evaluation logger.
        """
        ...

    @abstractmethod
    def score(self, trajectory: List[Dict[str, Any]]) -> float:
        """Return a continuous severity score ∈ [0, 1] for *trajectory*.

        0.0 = no risk present; 1.0 = maximum severity.
        """
        ...

    def describe(self) -> str:
        """Return a human-readable description of this risk and its
        observable signature."""
        return (
            f"[{self.risk_id}] {self.name}\n"
            f"  Category : {self.category.value}\n"
            f"  Stages   : {', '.join(s.value for s in self.lifecycle_stages)}\n"
            f"  {self.config.description}"
        )

    # ------------------------------------------------------------------
    # Optional hooks
    # ------------------------------------------------------------------

    def counterfactual_exists(
        self, trajectory: List[Dict[str, Any]]
    ) -> Optional[str]:
        """If a feasible system-optimal outcome was available but not
        adopted, return a brief textual description.  Otherwise ``None``.
        """
        return None

    def __repr__(self) -> str:
        return f"Risk(id={self.risk_id!r}, name={self.name!r})"
