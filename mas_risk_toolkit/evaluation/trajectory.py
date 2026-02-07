"""
Trajectory data structures.

A Trajectory records the complete round-by-round history of an
experiment run.  It is the primary input to all Risk detectors
and metric computations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TrajectoryStep:
    """One round / turn in an interaction trajectory.

    This format is designed for easy serialisation to JSON and for
    direct consumption by Risk.detect() / Risk.score().
    """

    round: int
    speaker: str
    observation: Any = None
    message: Any = None
    action: Any = None
    local_utility: Optional[float] = None
    system_state: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "round": self.round,
            "speaker": self.speaker,
            "observation": self.observation,
            "message": self.message,
            "action": self.action,
            "local_utility": self.local_utility,
            "system_state": dict(self.system_state),
            "metadata": dict(self.metadata),
        }


@dataclass
class Trajectory:
    """A complete experiment trajectory — an ordered list of steps."""

    experiment_id: str
    steps: List[TrajectoryStep] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: TrajectoryStep) -> None:
        self.steps.append(step)

    def to_list(self) -> List[Dict[str, Any]]:
        """Serialise as a list of dicts (JSON-friendly)."""
        return [s.to_dict() for s in self.steps]

    @property
    def num_rounds(self) -> int:
        if not self.steps:
            return 0
        return max(s.round for s in self.steps) + 1

    @property
    def agents(self) -> List[str]:
        """Return the unique agent IDs that appear in this trajectory."""
        return sorted({s.speaker for s in self.steps})

    def filter_by_agent(self, agent_id: str) -> List[TrajectoryStep]:
        return [s for s in self.steps if s.speaker == agent_id]

    def filter_by_round(self, round_num: int) -> List[TrajectoryStep]:
        return [s for s in self.steps if s.round == round_num]

    def __len__(self) -> int:
        return len(self.steps)
