"""
Metric suite — unified interface for outcome, interaction, and risk metrics.

Three metric families (from the paper):
    1. **Outcome metrics**      — task completion, efficiency
    2. **Interaction metrics**   — agreement rate, entropy collapse, repetition
    3. **Risk indicators**       — collusion score, drift distance, monopolisation ratio
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from risklab.evaluation.trajectory import Trajectory


class MetricType(str, Enum):
    OUTCOME = "outcome"
    INTERACTION = "interaction"
    RISK = "risk"


@dataclass
class MetricResult:
    """Container for a single metric evaluation result."""

    name: str
    metric_type: MetricType
    value: float
    details: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.details is None:
            self.details = {}


class Metric(ABC):
    """Abstract base class for a single metric."""

    def __init__(self, name: str, metric_type: MetricType) -> None:
        self.name = name
        self.metric_type = metric_type

    @abstractmethod
    def compute(self, trajectory: Trajectory) -> MetricResult:
        """Compute the metric over a trajectory."""
        ...


class MetricSuite:
    """A collection of metrics that are evaluated together.

    Usage
    -----
    >>> suite = MetricSuite()
    >>> suite.add(MyOutcomeMetric())
    >>> suite.add(MyRiskMetric())
    >>> results = suite.evaluate(trajectory)
    """

    def __init__(self) -> None:
        self._metrics: List[Metric] = []

    def add(self, metric: Metric) -> "MetricSuite":
        """Add a metric to the suite (builder pattern)."""
        self._metrics.append(metric)
        return self

    def evaluate(self, trajectory: Trajectory) -> List[MetricResult]:
        """Evaluate all metrics on the given trajectory."""
        return [m.compute(trajectory) for m in self._metrics]

    def evaluate_as_dict(self, trajectory: Trajectory) -> Dict[str, float]:
        """Evaluate and return a flat ``{name: value}`` dictionary."""
        return {r.name: r.value for r in self.evaluate(trajectory)}

    def list_metrics(self) -> List[str]:
        return [m.name for m in self._metrics]
