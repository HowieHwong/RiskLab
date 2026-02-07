"""
MAS-Risk-Toolkit
================

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

from mas_risk_toolkit.agents.base import Agent, AgentConfig
from mas_risk_toolkit.agents.llm_agent import LLMAgent
from mas_risk_toolkit.environments.base import Environment
from mas_risk_toolkit.protocols.base import InteractionProtocol
from mas_risk_toolkit.topology import CommunicationTopology, InformationFlowConfig
from mas_risk_toolkit.tasks import TaskConfig
from mas_risk_toolkit.llm import LLMConfig, LLMClient, ProviderConfig
from mas_risk_toolkit.risks.base import Risk
from mas_risk_toolkit.evaluation.logger import TrajectoryLogger
from mas_risk_toolkit.evaluation.task_evaluator import TaskEvaluator
from mas_risk_toolkit.experiments.runner import ExperimentRunner
from mas_risk_toolkit.experiments.config_loader import (
    load_llm_config,
    build_agents_from_config,
    load_experiment_config,
)
from mas_risk_toolkit.inspect_config import inspect_config

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
