"""
Configuration loader — builds experiment components from YAML configs.

This module provides utilities to load a complete experiment from a YAML
file, including resolving external LLM configuration files.

Supported factories:
    - ``load_llm_config``         — LLM provider configuration
    - ``build_agents_from_config``— agent instances from YAML
    - ``build_environment_from_config`` — environment from YAML
    - ``build_protocol_from_config``    — protocol from YAML
    - ``build_risks_from_config``       — risk detectors from YAML
    - ``build_experiment_from_config``  — full experiment assembly
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from risklab.agents.base import Agent, AgentConfig
from risklab.agents.llm_agent import LLMAgent
from risklab.environments.base import Environment, EnvironmentConfig
from risklab.llm import LLMConfig, LLMClient
from risklab.protocols.base import InteractionProtocol
from risklab.risks.base import Risk, RiskConfig, RiskCategory, LifecycleStage
from risklab.risks.registry import RiskRegistry
from risklab.tasks import TaskConfig, TaskType
from risklab.topology import CommunicationTopology, InformationFlowConfig, build_topology_from_config


def load_llm_config(
    config: Dict[str, Any],
    base_dir: Optional[str] = None,
) -> Optional[LLMConfig]:
    """Load LLM configuration from experiment config.

    Supports three modes:
    1. ``llm_config_path: "path/to/llm_config.yaml"`` — load from external file
    2. ``llm: {...}`` — inline LLM config in the experiment YAML
    3. Neither — use environment variables only (``LLMConfig.from_env()``)

    Parameters
    ----------
    config : dict
        The full experiment configuration dictionary.
    base_dir : str, optional
        Base directory for resolving relative ``llm_config_path``.
        If ``None``, uses the current working directory.

    Returns
    -------
    LLMConfig | None
        The loaded LLM config, or ``None`` if no config was specified
        (in which case the caller should use ``from_env()``).
    """
    base_dir = base_dir or os.getcwd()

    # Mode 1: external file reference
    llm_config_path = config.get("llm_config_path")
    if llm_config_path:
        if not os.path.isabs(llm_config_path):
            llm_config_path = os.path.join(base_dir, llm_config_path)
        return LLMConfig.from_file(llm_config_path)

    # Mode 2: inline llm: section
    llm_dict = config.get("llm")
    if llm_dict:
        return LLMConfig.from_dict(llm_dict)

    # Mode 3: no config → use env vars
    return None


def build_agents_from_config(
    agent_configs: List[Dict[str, Any]],
    llm_config: Optional[LLMConfig] = None,
    task: Optional[TaskConfig] = None,
) -> List[Agent]:
    """Build agent instances from YAML configuration.

    Parameters
    ----------
    agent_configs : list[dict]
        List of agent configuration dictionaries.
    llm_config : LLMConfig, optional
        Global LLM configuration.  If ``None``, uses ``from_env()``.
    task : TaskConfig, optional
        Task specification (injected into agent's system prompt).

    Returns
    -------
    list[Agent]
        Instantiated agent objects.
    """
    llm_config = llm_config or LLMConfig.from_env()
    llm_client = LLMClient(llm_config)

    task_prompt = task.to_prompt_section() if task else ""

    agents: List[Agent] = []
    for agent_dict in agent_configs:
        # Pop the agent type before constructing AgentConfig (which
        # does not have a ``type`` field).
        agent_dict = dict(agent_dict)  # shallow copy to avoid mutating input
        agent_type = agent_dict.pop("type", None)

        config = AgentConfig(**agent_dict)

        # Build per-agent LLMConfig if the agent has provider overrides
        agent_llm_config = llm_config
        if any([config.provider, config.api_key, config.api_base]):
            # Clone global config and apply agent-specific overrides
            agent_llm_config = LLMConfig.from_dict(llm_config.to_dict())
            # If provider override is specified, ensure it exists
            provider_name = config.provider or agent_llm_config.detect_provider(config.model)
            if provider_name not in agent_llm_config.providers:
                from risklab.llm import ProviderConfig
                agent_llm_config.providers[provider_name] = ProviderConfig(name=provider_name)
            # Apply per-agent overrides
            if config.api_key:
                agent_llm_config.providers[provider_name].api_key = config.api_key
            if config.api_base:
                agent_llm_config.providers[provider_name].api_base = config.api_base

        effective_client = (
            llm_client
            if agent_llm_config == llm_config
            else LLMClient(agent_llm_config)
        )

        if agent_type:
            # Use AgentRegistry to look up the registered class
            from risklab.agents.registry import AgentRegistry
            agent_cls = AgentRegistry.get(agent_type)
            agent = agent_cls(
                config=config,
                llm_config=agent_llm_config,
                llm_client=effective_client,
                task_prompt=task_prompt,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
        else:
            # Default: generic LLMAgent
            agent = LLMAgent(
                config=config,
                llm_config=agent_llm_config,
                llm_client=effective_client,
                task_prompt=task_prompt,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )

        agents.append(agent)

    return agents


def load_experiment_config(config_path: str) -> Dict[str, Any]:
    """Load a YAML experiment configuration file.

    Parameters
    ----------
    config_path : str
        Path to the experiment YAML file.

    Returns
    -------
    dict
        Parsed experiment configuration.

    Raises
    ------
    ImportError
        If PyYAML is not installed.
    FileNotFoundError
        If the config file does not exist.
    """
    try:
        import yaml
    except ImportError:
        raise ImportError(
            "PyYAML is required to load YAML config files. "
            "Install it with: pip install pyyaml"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config or {}


# ======================================================================
# Environment factory
# ======================================================================

# Registry of environment name → class (avoids circular imports)
_ENVIRONMENT_REGISTRY: Dict[str, type] = {}


def register_environment(name: str, cls: type) -> None:
    """Register an environment class for config-driven construction."""
    _ENVIRONMENT_REGISTRY[name] = cls


def _ensure_environments_registered() -> None:
    """Lazy-import concrete environments to populate the registry."""
    if _ENVIRONMENT_REGISTRY:
        return
    from risklab.environments.competitive.homogeneous_goods_market import (
        HomogeneousGoodsMarket,
    )
    register_environment("homogeneous_goods_market", HomogeneousGoodsMarket)

    # from risklab.environments.cooperative.ad_pipeline import (
    #     AdPipelineEnvironment,
    # )
    # register_environment("ad_pipeline", AdPipelineEnvironment)

    from risklab.environments.cooperative.grid_exploration import (
        GridExplorationEnvironment,
    )
    register_environment("grid_exploration", GridExplorationEnvironment)

    from risklab.environments.cooperative.cultural_negotiation import (
        CulturalNegotiationEnvironment,
    )
    register_environment("cultural_negotiation", CulturalNegotiationEnvironment)

    from risklab.environments.collective.trading_pipeline import (
        TradingPipelineEnvironment,
    )
    register_environment("trading_pipeline", TradingPipelineEnvironment)


def build_environment_from_config(
    env_config: Dict[str, Any],
    agent_ids: Optional[List[str]] = None,
) -> Environment:
    """Build an environment instance from a YAML config dict.

    Parameters
    ----------
    env_config : dict
        The ``environment:`` section of the experiment YAML.
    agent_ids : list[str], optional
        Agent identifiers to inject into environment parameters.

    Returns
    -------
    Environment
    """
    _ensure_environments_registered()

    name = env_config["name"]
    if name not in _ENVIRONMENT_REGISTRY:
        available = ", ".join(sorted(_ENVIRONMENT_REGISTRY)) or "(none)"
        raise KeyError(
            f"Unknown environment '{name}'. Available: {available}"
        )

    params = dict(env_config.get("parameters", {}))
    if agent_ids:
        params["agent_ids"] = agent_ids

    config = EnvironmentConfig(
        name=name,
        env_type=env_config.get("type", "competitive"),
        max_rounds=env_config.get("max_rounds", 10),
        num_agents=env_config.get("num_agents", len(agent_ids or [])),
        parameters=params,
    )

    env_cls = _ENVIRONMENT_REGISTRY[name]
    return env_cls(config)


# ======================================================================
# Protocol factory
# ======================================================================

def build_protocol_from_config(
    protocol_config: Dict[str, Any],
    agent_ids: List[str],
    topology: Optional[CommunicationTopology] = None,
    flow: Optional[InformationFlowConfig] = None,
) -> InteractionProtocol:
    """Build a protocol from a YAML config dict.

    Parameters
    ----------
    protocol_config : dict
        The ``protocol:`` section of the experiment YAML.
    agent_ids : list[str]
        Participating agent identifiers.
    topology : CommunicationTopology, optional
    flow : InformationFlowConfig, optional

    Returns
    -------
    InteractionProtocol
    """
    protocol_type = protocol_config.get("type", "market_turn_based")

    if protocol_type == "market_turn_based":
        from risklab.protocols.market import MarketTurnBased
        return MarketTurnBased(
            agent_ids=agent_ids,
            simultaneous=protocol_config.get("simultaneous", True),
            topology=topology,
            flow=flow,
        )
    elif protocol_type == "sequential":
        from risklab.protocols.sequential import SequentialHandoff
        return SequentialHandoff(
            agent_ids=agent_ids,
            topology=topology,
            flow=flow,
        )
    elif protocol_type == "broadcast":
        from risklab.protocols.broadcast import BroadcastDeliberation
        return BroadcastDeliberation(
            agent_ids=agent_ids,
            topology=topology,
            flow=flow,
        )
    else:
        raise ValueError(f"Unknown protocol type: {protocol_type!r}")


# ======================================================================
# Risk factory
# ======================================================================

def build_risks_from_config(
    risk_configs: List[Dict[str, Any]],
) -> List[Risk]:
    """Build risk detector instances from YAML config.

    Parameters
    ----------
    risk_configs : list[dict]
        The ``risks:`` section of the experiment YAML.

    Returns
    -------
    list[Risk]
    """
    # Ensure risk modules are importable (triggers @register decorators)
    try:
        import risklab.risks.tacit_collusion  # noqa: F401
    except ImportError:
        pass
    try:
        import risklab.risks.rigidity  # noqa: F401
    except ImportError:
        pass
    try:
        import risklab.risks.strategic_misreporting  # noqa: F401
    except ImportError:
        pass
    try:
        import risklab.risks.normative_deadlock  # noqa: F401
    except ImportError:
        pass

    risks: List[Risk] = []
    for rc in risk_configs:
        name = rc["name"]
        params = rc.get("parameters", {})

        risk_cls = RiskRegistry.get(name)

        # Instantiate once to recover class defaults (category/stages/risk_id)
        # when YAML does not provide explicit overrides.
        default_risk = risk_cls()
        default_config = default_risk.config

        # Respect explicit YAML category if valid; otherwise keep class default.
        category = default_config.category
        if "category" in rc:
            try:
                category = RiskCategory(rc["category"])
            except ValueError:
                category = default_config.category

        # Build config while preserving class-defined identifiers and lifecycle
        # metadata by default.
        risk_config = RiskConfig(
            risk_id=default_config.risk_id,
            name=default_config.name,
            category=category,
            lifecycle_stages=default_config.lifecycle_stages,
            description=default_config.description,
            parameters=params,
        )

        try:
            risk = risk_cls(config=risk_config)
        except TypeError:
            # Some risks may accept config as positional arg
            risk = risk_cls(risk_config)

        risks.append(risk)

    return risks


# ======================================================================
# Task factory
# ======================================================================

def build_task_from_config(
    task_config: Dict[str, Any],
) -> TaskConfig:
    """Build a TaskConfig from a YAML config dict.

    Parameters
    ----------
    task_config : dict
        The ``task:`` section of the experiment YAML.

    Returns
    -------
    TaskConfig
    """
    task_type_str = task_config.get("task_type", "custom")
    try:
        task_type = TaskType(task_type_str)
    except ValueError:
        task_type = TaskType.CUSTOM

    return TaskConfig(
        task_id=task_config.get("task_id", "unnamed_task"),
        task_type=task_type,
        description=task_config.get("description", ""),
        success_criteria=task_config.get("success_criteria", {}),
        constraints=task_config.get("constraints", {}),
        parameters=task_config.get("parameters", {}),
        inputs=task_config.get("inputs"),
        input_file=task_config.get("input_file"),
        input_key=task_config.get("input_key"),
    )


# ======================================================================
# Full experiment assembly
# ======================================================================

def build_experiment_from_config(
    config: Dict[str, Any],
    base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Build all experiment components from a parsed YAML config.

    Parameters
    ----------
    config : dict
        Full experiment config (as returned by ``load_experiment_config``).
    base_dir : str, optional
        Base directory for resolving relative paths.

    Returns
    -------
    dict
        Dictionary with keys: ``experiment_id``, ``environment``,
        ``protocol``, ``agents``, ``task``, ``topology``, ``flow``,
        ``risks``, ``output_dir``.
    """
    base_dir = base_dir or os.getcwd()

    # Experiment metadata
    exp_meta = config.get("experiment", {})
    experiment_id = exp_meta.get("id", "unnamed_experiment")

    # LLM config
    llm_config = load_llm_config(config, base_dir=base_dir)
    if llm_config is None:
        llm_config = LLMConfig.from_env()

    # Task
    task = None
    if "task" in config:
        task = build_task_from_config(config["task"])

    # Topology & flow
    topology = None
    flow = None
    if "topology" in config:
        topology, flow = build_topology_from_config(config["topology"])

    # Agent IDs (from topology or agents section)
    agent_ids = []
    if topology:
        agent_ids = topology.agent_ids
    elif "agents" in config:
        agent_ids = [a["agent_id"] for a in config["agents"]]

    # Environment
    environment = None
    if "environment" in config:
        environment = build_environment_from_config(
            config["environment"],
            agent_ids=agent_ids,
        )

    # Protocol
    protocol = None
    if "protocol" in config:
        protocol = build_protocol_from_config(
            config["protocol"],
            agent_ids=agent_ids,
            topology=topology,
            flow=flow,
        )

    # Agents
    agents = []
    if "agents" in config:
        agents = build_agents_from_config(
            config["agents"],
            llm_config=llm_config,
            task=task,
        )

    # Risks
    risks = []
    if "risks" in config:
        risks = build_risks_from_config(config["risks"])

    return {
        "experiment_id": experiment_id,
        "environment": environment,
        "protocol": protocol,
        "agents": agents,
        "task": task,
        "topology": topology,
        "flow": flow,
        "risks": risks,
        "output_dir": config.get("output_dir", "results"),
    }
