"""
Task evaluator — judges whether a task was completed successfully.

Separates *task-level* evaluation from *risk-level* evaluation:
    - Task evaluator → "Did the agents solve the problem?"
    - Risk detector  → "Did emergent interaction risks appear?"

The evaluator consumes a TaskConfig + Trajectory and returns a
TaskEvaluationResult.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from risklab.evaluation.trajectory import Trajectory
from risklab.tasks import TaskConfig


@dataclass
class TaskEvaluationResult:
    """Result of evaluating task completion."""

    task_id: str
    success: bool
    score: float  # 0.0 = total failure, 1.0 = perfect completion
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "score": self.score,
            "details": self.details,
        }


class TaskEvaluator(ABC):
    """Abstract base class for task evaluators.

    Subclass this to implement task-specific evaluation logic.
    """

    @abstractmethod
    def evaluate(
        self,
        task: TaskConfig,
        trajectory: Trajectory,
    ) -> TaskEvaluationResult:
        """Evaluate task completion.

        Parameters
        ----------
        task : TaskConfig
            The task specification (includes success criteria, ground truth).
        trajectory : Trajectory
            The full interaction trajectory to evaluate.

        Returns
        -------
        TaskEvaluationResult
        """
        ...


class RuleBasedTaskEvaluator(TaskEvaluator):
    """A configurable evaluator that uses success_criteria rules from TaskConfig.

    Supported criteria types:
        - ``"task_completed"``     : checks if a completion flag is in the last step
        - ``"round_budget"``       : checks if the task finished within N rounds
        - ``"output_match"``       : checks if the final output matches ground truth
        - ``"numeric_threshold"``  : checks if a numeric value in the trajectory
                                     meets a threshold

    This evaluator is extensible: subclass and override ``_evaluate_criterion``
    to add custom criteria types.
    """

    def evaluate(
        self,
        task: TaskConfig,
        trajectory: Trajectory,
    ) -> TaskEvaluationResult:
        criteria = task.success_criteria
        if not criteria:
            return TaskEvaluationResult(
                task_id=task.task_id,
                success=True,
                score=1.0,
                details={"note": "No success criteria specified."},
            )

        results = {}
        all_passed = True

        for key, value in criteria.items():
            passed = self._evaluate_criterion(key, value, task, trajectory)
            results[key] = passed
            if not passed:
                all_passed = False

        score = sum(results.values()) / max(len(results), 1)
        return TaskEvaluationResult(
            task_id=task.task_id,
            success=all_passed,
            score=score,
            details={"criteria_results": results},
        )

    def _evaluate_criterion(
        self,
        key: str,
        value: Any,
        task: TaskConfig,
        trajectory: Trajectory,
    ) -> bool:
        """Evaluate a single criterion.  Override to add custom types."""

        if key == "task_completed":
            # Check if any step has metadata indicating completion
            for step in reversed(trajectory.steps):
                if step.metadata.get("task_completed"):
                    return True
            return False

        if key == "round_budget":
            return trajectory.num_rounds <= value

        if key == "output_match":
            # Compare last step's action/message to ground truth
            if not trajectory.steps:
                return False
            last = trajectory.steps[-1]
            gt = task.ground_truth or {}
            expected = gt.get("expected_output")
            if expected is None:
                return True
            actual = last.action or last.message
            return str(actual).strip() == str(expected).strip()

        if key == "numeric_threshold":
            # value should be {"metric": "some_key", "op": "<=", "threshold": 5}
            if isinstance(value, dict):
                metric_key = value.get("metric", "")
                op = value.get("op", "<=")
                threshold = value.get("threshold", 0)
                # Search trajectory for the metric
                for step in reversed(trajectory.steps):
                    actual = step.system_state.get(metric_key)
                    if actual is not None:
                        return self._compare(actual, op, threshold)
            return False

        # Unknown criterion — skip (subclasses can override)
        return True

    @staticmethod
    def _compare(actual: float, op: str, threshold: float) -> bool:
        ops = {
            "<=": actual <= threshold,
            "<": actual < threshold,
            ">=": actual >= threshold,
            ">": actual > threshold,
            "==": actual == threshold,
        }
        return ops.get(op, False)
