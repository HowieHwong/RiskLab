"""
Trajectory logger — records interaction traces for analysis.

Outputs are JSON-L files that can be consumed by risk detectors,
metric suites, and visualisation scripts.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from mas_risk_toolkit.evaluation.trajectory import Trajectory, TrajectoryStep


class TrajectoryLogger:
    """Append-only logger that builds a :class:`Trajectory` in-memory
    and can flush it to disk as JSON."""

    def __init__(
        self,
        experiment_id: str,
        output_dir: str = "logs",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.experiment_id = experiment_id
        self.output_dir = output_dir
        self.trajectory = Trajectory(
            experiment_id=experiment_id,
            metadata=metadata or {},
        )

    def log_step(
        self,
        round: int,
        speaker: str,
        observation: Any = None,
        message: Any = None,
        action: Any = None,
        local_utility: Optional[float] = None,
        system_state: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a single interaction step."""
        step = TrajectoryStep(
            round=round,
            speaker=speaker,
            observation=observation,
            message=message,
            action=action,
            local_utility=local_utility,
            system_state=system_state or {},
            metadata=metadata or {},
        )
        self.trajectory.add_step(step)

    def get_trajectory(self) -> Trajectory:
        """Return the in-memory trajectory object."""
        return self.trajectory

    def save(self, filename: Optional[str] = None) -> str:
        """Persist the trajectory to a JSON file.

        Returns the path to the saved file.
        """
        os.makedirs(self.output_dir, exist_ok=True)
        if filename is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.experiment_id}_{ts}.json"
        filepath = os.path.join(self.output_dir, filename)
        payload = {
            "experiment_id": self.experiment_id,
            "metadata": self.trajectory.metadata,
            "num_steps": len(self.trajectory),
            "trajectory": self.trajectory.to_list(),
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
        return filepath

    def reset(self) -> None:
        """Clear the current trajectory (start a new episode)."""
        self.trajectory = Trajectory(
            experiment_id=self.experiment_id,
            metadata=self.trajectory.metadata,
        )
