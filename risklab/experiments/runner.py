"""
Experiment runner — orchestrates the full experiment loop.

One YAML config → one fully specified experiment
    = Environment + Topology + Protocol + Agents + Task + Risk(s) + Metrics

The runner coordinates:
    1. Build components from config
    2. Reset environment, protocol & agents
    3. Run the interaction loop (topology + protocol-driven)
    4. Collect trajectory
    5. Evaluate task completion
    6. Evaluate risks & metrics
    7. Save results
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from risklab.agents.base import Agent
from risklab.environments.base import Environment
from risklab.evaluation.logger import TrajectoryLogger
from risklab.evaluation.metrics import MetricSuite
from risklab.evaluation.task_evaluator import TaskEvaluator
from risklab.protocols.base import InteractionProtocol, Message
from risklab.risks.base import Risk
from risklab.tasks import TaskConfig
from risklab.topology import CommunicationTopology, InformationFlowConfig


class ExperimentRunner:
    """High-level runner that wires together all toolkit components.

    Parameters
    ----------
    experiment_id : str
        Unique identifier for this experiment run.
    environment : Environment
        The task environment.
    protocol : InteractionProtocol
        The interaction protocol (should already have topology/flow attached).
    agents : list[Agent]
        The agent instances participating in this experiment.
    task : TaskConfig, optional
        The task specification (what the agents should accomplish).
    topology : CommunicationTopology, optional
        Explicit topology reference (also accessible via ``protocol.topology``).
    flow : InformationFlowConfig, optional
        Information flow config (also accessible via ``protocol.flow``).
    risks : list[Risk], optional
        Risk detectors to evaluate after the run.
    task_evaluator : TaskEvaluator, optional
        Evaluator for task-level success / failure.
    metric_suite : MetricSuite, optional
        Additional metrics to compute.
    output_dir : str
        Directory for saving logs and results.
    """

    def __init__(
        self,
        experiment_id: str,
        environment: Environment,
        protocol: InteractionProtocol,
        agents: List[Agent],
        task: Optional[TaskConfig] = None,
        topology: Optional[CommunicationTopology] = None,
        flow: Optional[InformationFlowConfig] = None,
        risks: Optional[List[Risk]] = None,
        task_evaluator: Optional[TaskEvaluator] = None,
        metric_suite: Optional[MetricSuite] = None,
        output_dir: str = "results",
        on_round_callback: Optional[Any] = None,
    ) -> None:
        self.experiment_id = experiment_id
        self.environment = environment
        self.protocol = protocol
        self.agents = {a.agent_id: a for a in agents}
        self.task = task
        self.topology = topology or protocol.topology
        self.flow = flow or protocol.flow
        self.risks = risks or []
        self.task_evaluator = task_evaluator
        self.metric_suite = metric_suite or MetricSuite()
        self.output_dir = output_dir
        self.on_round_callback = on_round_callback

        self.logger = TrajectoryLogger(
            experiment_id=experiment_id,
            output_dir=os.path.join(output_dir, "trajectories"),
            metadata={
                "task": task.to_dict() if task else None,
                "topology": self.topology.to_dict() if self.topology else None,
                "flow": self.flow.to_dict() if self.flow else None,
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def is_cyclic(self) -> bool:
        """``True`` if the information flow forms a loop."""
        if self.flow is not None:
            return self.flow.cyclic
        return True  # default assumption: cyclic

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, num_seeds: int = 1) -> List[Dict[str, Any]]:
        """Execute the experiment for *num_seeds* independent runs.

        For **cyclic** flows each seed runs a single looping episode.
        For **acyclic** flows each seed runs the pipeline once per input
        item (from ``task.load_inputs()``).

        Returns
        -------
        all_results : list[dict]
            One result dict per seed, containing metrics and risk scores.
        """
        all_results: List[Dict[str, Any]] = []

        for seed in range(num_seeds):
            if self.is_cyclic:
                result = self._run_cyclic(seed)
                all_results.append(result)
            else:
                results = self._run_acyclic(seed)
                all_results.extend(results)

        # Persist aggregate results
        self._save_aggregate(all_results)
        return all_results

    # ------------------------------------------------------------------
    # Cyclic mode (default): loop until stop condition fires
    # ------------------------------------------------------------------

    def _run_cyclic(self, seed: int) -> Dict[str, Any]:
        """Run a cyclic (looping) episode — entry == exit, keeps going
        until a stop condition or environment termination."""
        return self._run_episode(seed, input_data=None, tag="cyclic")

    # ------------------------------------------------------------------
    # Acyclic mode: one-shot pipeline, once per input
    # ------------------------------------------------------------------

    def _run_acyclic(self, seed: int) -> List[Dict[str, Any]]:
        """Run the pipeline once per input item and collect results."""
        inputs = self.task.load_inputs() if self.task else [{}]
        results: List[Dict[str, Any]] = []
        for idx, input_data in enumerate(inputs):
            tag = f"acyclic_input{idx}"
            result = self._run_episode(seed, input_data=input_data, tag=tag)
            result["input_index"] = idx
            result["input_data"] = input_data
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Shared episode logic
    # ------------------------------------------------------------------

    def _run_episode(
        self,
        seed: int,
        input_data: Optional[Dict[str, Any]] = None,
        tag: str = "",
    ) -> Dict[str, Any]:
        """Run a single episode (shared by cyclic and acyclic modes).

        Parameters
        ----------
        seed : int
            Random seed index.
        input_data : dict, optional
            For acyclic flows, the input item to inject into the first
            stage's observation.  ``None`` for cyclic flows.
        tag : str
            Suffix for the trajectory filename.
        """
        # 1. Reset everything
        self.environment.reset()
        self.protocol.reset()
        self.logger.reset()
        for agent in self.agents.values():
            agent.reset()

        # For acyclic flows, inject input_data into environment state
        if input_data is not None:
            self.environment.state["_pipeline_input"] = input_data

        # 2. Interaction loop (topology + protocol-driven)
        while not self.environment.done:
            # Check flow-level stop conditions
            if self.protocol.should_stop():
                break

            speaker_id = self.protocol.get_next_speaker()
            if speaker_id is None:
                break

            agent = self.agents.get(speaker_id)
            if agent is None:
                self.protocol.advance()
                continue

            # Get observation for this agent
            observation = self.environment.get_observation(speaker_id)
            agent.observe(observation)

            # Agent acts
            action_result = agent.act(observation)

            # Determine listeners from topology / protocol
            listeners = self.protocol.get_listeners(speaker_id)

            # Route message through the protocol
            msg = Message(
                sender=speaker_id,
                receivers=listeners,
                content=action_result.get("message"),
                round=self.protocol.current_round,
                metadata={"action": action_result.get("action")},
            )
            self.protocol.route_message(msg)

            # Build joint action (single-agent step for protocol-driven loop)
            joint_action = {speaker_id: action_result}

            # Environment step
            observations, rewards, done, info = self.environment.step(
                joint_action
            )

            # Round callback (fires when a full round completes)
            if self.on_round_callback and info.get("round_complete", True) is not False:
                self.on_round_callback(info)

            # Log
            self.logger.log_step(
                round=self.protocol.current_round,
                speaker=speaker_id,
                observation=observation,
                message=action_result.get("message"),
                action=action_result.get("action"),
                local_utility=rewards.get(speaker_id),
                system_state=info,
                metadata={
                    "listeners": listeners,
                    "input_data": input_data,
                },
            )

            # Advance protocol
            self.protocol.advance()

            # Check termination
            if done:
                break

        # 3. Evaluate
        trajectory = self.logger.get_trajectory()

        # Task evaluation
        task_result = None
        if self.task and self.task_evaluator:
            task_result = self.task_evaluator.evaluate(self.task, trajectory)

        # Risk detection
        risk_results = {}
        for risk in self.risks:
            traj_list = trajectory.to_list()
            risk_results[risk.risk_id] = {
                "detected": risk.detect(traj_list),
                "score": risk.score(traj_list),
                "counterfactual": risk.counterfactual_exists(traj_list),
            }

        # Metrics
        metric_results = self.metric_suite.evaluate_as_dict(trajectory)

        # 4. Save trajectory
        filename = f"{self.experiment_id}_seed{seed}"
        if tag:
            filename += f"_{tag}"
        filename += ".json"
        self.logger.save(filename=filename)

        return {
            "experiment_id": self.experiment_id,
            "seed": seed,
            "tag": tag,
            "num_rounds": trajectory.num_rounds,
            "task_result": task_result.to_dict() if task_result else None,
            "risk_results": risk_results,
            "metric_results": metric_results,
            "failure": self.environment.check_failure(),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_aggregate(self, results: List[Dict[str, Any]]) -> str:
        os.makedirs(self.output_dir, exist_ok=True)
        filepath = os.path.join(
            self.output_dir, f"{self.experiment_id}_aggregate.json"
        )
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)
        return filepath
