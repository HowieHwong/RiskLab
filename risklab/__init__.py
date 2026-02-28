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
- mcp_integration : Model Context Protocol support for external tools
- skills        : Agent Skills support for modular capabilities
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

# MCP and Skills (optional dependencies)
try:
    from risklab.agents.enhanced_llm_agent import EnhancedLLMAgent
    from risklab.mcp_integration import MCPClient, MCPServerConfig, load_mcp_config
    from risklab.skills import Skill, SkillRegistry, load_skills_config
    MCP_AVAILABLE = True
    SKILLS_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    SKILLS_AVAILABLE = False
    EnhancedLLMAgent = None  # type: ignore
    MCPClient = None  # type: ignore
    MCPServerConfig = None  # type: ignore
    load_mcp_config = None  # type: ignore
    Skill = None  # type: ignore
    SkillRegistry = None  # type: ignore
    load_skills_config = None  # type: ignore

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

# Conditionally add MCP and Skills to __all__
if MCP_AVAILABLE and SKILLS_AVAILABLE:
    __all__.extend([
        "EnhancedLLMAgent",
        "MCPClient",
        "MCPServerConfig",
        "load_mcp_config",
        "Skill",
        "SkillRegistry",
        "load_skills_config",
    ])
