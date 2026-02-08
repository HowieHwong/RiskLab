"""
RiskLab
=======

A controlled multi-agent interaction framework for instantiating, probing,
and measuring emergent social risks in LLM-based agent collectives.

Core Layers
-----------
- agents        : Agent abstraction & roles
- environments  : Task + resource + rule environments
- protocols     : Interaction & communication structures
- topology      : Communication graph (adjacency matrix) & information flow
- tasks         : Task definitions
- risks         : Risk definitions & indicators
- evaluation    : Metrics, logging, task evaluation
- experiments   : Reproducible experiment configs & runner
"""

__version__ = "0.1.0"

from risklab.agents.base import Agent, AgentConfig
from risklab.agents.llm_agent import LLMAgent
from risklab.environments.base import Environment
from risklab.protocols.base import InteractionProtocol
from risklab.topology import CommunicationTopology, InformationFlowConfig
from risklab.tasks import TaskConfig
from risklab.llm import LLMConfig, LLMClient, ProviderConfig
from risklab.risks.base import Risk
from risklab.evaluation.logger import TrajectoryLogger
from risklab.evaluation.task_evaluator import TaskEvaluator
from risklab.experiments.runner import ExperimentRunner
from risklab.experiments.config_loader import (
    load_llm_config,
    build_agents_from_config,
    load_experiment_config,
)
from risklab.inspect_config import inspect_config

__all__ = [
    "Agent",
    "AgentConfig",
    "LLMAgent",
    "LLMConfig",
    "LLMClient",
    "ProviderConfig",
    "Environment",
    "InteractionProtocol",
    "CommunicationTopology",
    "InformationFlowConfig",
    "TaskConfig",
    "Risk",
    "TrajectoryLogger",
    "TaskEvaluator",
    "ExperimentRunner",
    "load_llm_config",
    "build_agents_from_config",
    "load_experiment_config",
    "inspect_config",
]
