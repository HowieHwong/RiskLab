"""
Task definitions.

A Task encapsulates the *what* of an experiment — the problem that agents
must solve together.  It is separate from:
    - Environment (the *world* with resources, constraints, dynamics)
    - Protocol    (the *how* of communication)
    - Topology    (the *who-talks-to-whom* graph)

A Task specifies:
    - description     : what the agents should accomplish
    - success_criteria: how to judge task completion (used by TaskEvaluator)
    - constraints     : rules the agents must respect
    - expected_output : format / schema of the desired result
    - ground_truth    : optional reference answer (for automatic scoring)
    - inputs          : what to feed into the pipeline (inline list or file)

Inputs
------
For **acyclic** (non-cyclic) flows the pipeline runs once per input item.
Inputs can come from three sources (checked in priority order):

1. ``inputs``      – inline list of dicts, each dict is one input item
2. ``input_file``  – path to an external JSON file
   ``input_key``   – key inside that JSON whose value is the input list
3. If neither is provided, ``load_inputs()`` returns a single empty dict
   so the pipeline runs exactly once.

For **cyclic** flows the input list is ignored — the flow loops on its own
until a stop condition fires.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskType(str, Enum):
    """High-level task categories."""
    RESOURCE_ALLOCATION = "resource_allocation"
    MARKET_TRADING = "market_trading"
    PIPELINE_PRODUCTION = "pipeline_production"
    COLLECTIVE_DECISION = "collective_decision"
    NEGOTIATION = "negotiation"
    INFORMATION_RELAY = "information_relay"
    CUSTOM = "custom"


@dataclass
class TaskConfig:
    """Serialisable, fully-specified task definition.

    This is the object that goes into the YAML config and is consumed
    by the ExperimentRunner and TaskEvaluator.

    Examples
    --------
    Cyclic task (market game — inputs not needed, loop until stop):

    >>> task = TaskConfig(
    ...     task_id="market_price_competition",
    ...     task_type=TaskType.MARKET_TRADING,
    ...     description="Three sellers compete in a homogeneous-goods market ...",
    ...     success_criteria={"type": "price_convergence", "threshold": 15},
    ...     constraints={"marginal_cost": 10, "price_range": [10, 100]},
    ...     parameters={"num_rounds": 10},
    ... )

    Acyclic task with inline inputs:

    >>> task = TaskConfig(
    ...     task_id="ad_pipeline_relay",
    ...     task_type=TaskType.PIPELINE_PRODUCTION,
    ...     description="Convert product reports into advertising copy.",
    ...     inputs=[
    ...         {"text": "Product A is a next-gen AI chip …", "id": "report_1"},
    ...         {"text": "Product B is a quantum sensor …",  "id": "report_2"},
    ...     ],
    ... )

    Acyclic task with external JSON file:

    >>> task = TaskConfig(
    ...     task_id="translation_relay",
    ...     task_type=TaskType.PIPELINE_PRODUCTION,
    ...     description="Translate and localise documents.",
    ...     input_file="data/documents.json",
    ...     input_key="documents",
    ... )
    """

    task_id: str
    task_type: TaskType = TaskType.CUSTOM
    description: str = ""
    success_criteria: Dict[str, Any] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)
    expected_output: Optional[str] = None
    ground_truth: Optional[Dict[str, Any]] = None
    parameters: Dict[str, Any] = field(default_factory=dict)

    # ---- Input specification (for acyclic / one-shot pipelines) ----------
    inputs: Optional[List[Dict[str, Any]]] = None
    input_file: Optional[str] = None
    input_key: Optional[str] = None

    # ------------------------------------------------------------------
    # Input loading
    # ------------------------------------------------------------------

    def load_inputs(self, base_dir: str = ".") -> List[Dict[str, Any]]:
        """Return the list of input items for this task.

        Resolution order:
            1. ``self.inputs``   — inline list (highest priority)
            2. ``self.input_file`` + optional ``self.input_key``
            3. Falls back to ``[{}]`` (single empty input ⇒ pipeline runs once)

        Parameters
        ----------
        base_dir : str
            Directory relative to which ``input_file`` is resolved.
            Typically the experiment config's directory.

        Returns
        -------
        list[dict]
            Each dict is one input item that will be injected into the first
            stage of an acyclic pipeline.
        """
        # 1. Inline inputs
        if self.inputs is not None:
            return list(self.inputs)

        # 2. External file
        if self.input_file is not None:
            path = (
                self.input_file
                if os.path.isabs(self.input_file)
                else os.path.join(base_dir, self.input_file)
            )
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if self.input_key is not None:
                data = data[self.input_key]

            if isinstance(data, list):
                return data
            # Single object → wrap in list
            return [data]

        # 3. Fallback — one empty input so the pipeline runs once
        return [{}]

    @property
    def num_inputs(self) -> int:
        """Number of input items (0 means 'use load_inputs fallback')."""
        if self.inputs is not None:
            return len(self.inputs)
        return 0

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "description": self.description,
            "success_criteria": self.success_criteria,
            "constraints": self.constraints,
            "expected_output": self.expected_output,
            "ground_truth": self.ground_truth,
            "parameters": self.parameters,
        }
        if self.inputs is not None:
            d["inputs"] = self.inputs
        if self.input_file is not None:
            d["input_file"] = self.input_file
        if self.input_key is not None:
            d["input_key"] = self.input_key
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskConfig":
        """Build from a YAML-parsed dict."""
        data = dict(data)
        if "task_type" in data:
            data["task_type"] = TaskType(data["task_type"])
        return cls(**data)

    def to_prompt_section(self) -> str:
        """Render the task as a text block suitable for injection into
        an agent's system prompt."""
        lines = [f"## Task: {self.task_id}"]
        if self.description:
            lines.append(self.description)
        if self.constraints:
            lines.append("### Constraints")
            for k, v in self.constraints.items():
                lines.append(f"  - {k}: {v}")
        if self.expected_output:
            lines.append(f"### Expected output format: {self.expected_output}")
        return "\n".join(lines)
