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
    - ``resolve_round_horizon``         — one source of truth for episode length
"""

from __future__ import annotations

import os
import re
import warnings
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
                llm_params=config.llm_params,
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
# Episode length
# ======================================================================

# A YAML declares its episode length in up to three places, and the agent
# prompts usually repeat it in prose.  Nothing kept them in sync, so changing
# the horizon meant editing four sites and silently corrupting the run if you
# missed one (agents believing the game ends at round 10 play the end-game
# defection at round 10 regardless of the real horizon).
_ROUND_SITES = (
    "environment.max_rounds",
    "task.parameters.num_rounds",
    "topology.flow.stop_conditions[*].value",
)

#: Placeholders substituted into prompts / descriptions.  Plain ``str.replace``
#: is used rather than ``str.format`` because prompts routinely contain literal
#: braces (JSON examples, f-string-looking templates) that would blow up.
_ROUND_PLACEHOLDERS = ("{num_rounds}", "{total_rounds}", "{max_rounds}")

_PROMPT_KEYS = ("system_prompt", "prompt", "task_prompt", "persona")


def _fill_rounds(text: str, horizon: int) -> str:
    """Replace every round placeholder in *text* with *horizon*."""
    for token in _ROUND_PLACEHOLDERS:
        text = text.replace(token, str(horizon))
    return text


def fill_prompt_placeholder(config: Dict[str, Any], token: str, value: Any) -> int:
    """Substitute *token* with *value* in every prompt the agents actually read.

    :func:`resolve_round_horizon` does this for the episode length.  An
    experiment with a second quantity that must appear identically in the
    config and in the prose — a budget ceiling, a production cost — needs the
    same substitution over the same set of sites, and copying the list of
    prompt keys into the caller is how the two drift apart: the config says 90
    and the prompt still says 120, silently.

    *config* is modified in place.  Returns the number of sites changed, so a
    caller can fail loudly when it expected to rewrite a prompt and did not.
    """
    replacement = str(value)
    changed = 0
    for agent_cfg in config.get("agents") or []:
        if not isinstance(agent_cfg, dict):
            continue
        for key in _PROMPT_KEYS:
            text = agent_cfg.get(key)
            if isinstance(text, str) and token in text:
                agent_cfg[key] = text.replace(token, replacement)
                changed += 1
    task_cfg = config.get("task")
    if isinstance(task_cfg, dict):
        text = task_cfg.get("description")
        if isinstance(text, str) and token in text:
            task_cfg["description"] = text.replace(token, replacement)
            changed += 1
    return changed


def _stop_condition_entries(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every ``{type: max_rounds, value: N}`` entry in the flow config."""
    flow = (config.get("topology") or {}).get("flow") or {}
    return [
        sc
        for sc in (flow.get("stop_conditions") or [])
        if isinstance(sc, dict) and sc.get("type") == "max_rounds"
    ]


def resolve_round_horizon(
    config: Dict[str, Any], num_rounds: Optional[int] = None
) -> Optional[int]:
    """Reconcile the episode length across the config and the prompts.

    Reads the horizon from (in priority order) the explicit *num_rounds*
    override, ``environment.max_rounds``, ``task.parameters.num_rounds``, or a
    ``max_rounds`` stop condition; writes it back to every site that declared
    one; and substitutes ``{num_rounds}`` (and its aliases) in agent prompts
    and the task description.

    *config* is modified in place.  Returns the horizon, or ``None`` when the
    config declares no episode length and none was supplied.

    Raises
    ------
    ValueError
        If *num_rounds* is not a positive integer.
    """
    if num_rounds is not None:
        num_rounds = int(num_rounds)
        if num_rounds < 1:
            raise ValueError(f"num_rounds must be >= 1, got {num_rounds}")

    env_cfg = config.get("environment")
    task_cfg = config.get("task")
    task_params = (task_cfg or {}).get("parameters") or {}
    stop_conditions = _stop_condition_entries(config)

    # --- What does the config currently claim? ---
    declared: Dict[str, int] = {}
    if isinstance(env_cfg, dict) and env_cfg.get("max_rounds") is not None:
        declared["environment.max_rounds"] = int(env_cfg["max_rounds"])
    if task_params.get("num_rounds") is not None:
        declared["task.parameters.num_rounds"] = int(task_params["num_rounds"])
    for i, sc in enumerate(stop_conditions):
        if sc.get("value") is not None:
            declared[f"topology.flow.stop_conditions[{i}].value"] = int(sc["value"])

    if num_rounds is None and len(set(declared.values())) > 1:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(declared.items()))
        warnings.warn(
            "Episode length is declared inconsistently and has been reconciled "
            f"to environment.max_rounds: {detail}",
            RuntimeWarning,
            stacklevel=2,
        )

    if num_rounds is not None:
        horizon = num_rounds
    elif "environment.max_rounds" in declared:
        horizon = declared["environment.max_rounds"]
    elif declared:
        horizon = next(iter(declared.values()))
    else:
        return None

    # --- Write it back everywhere ---
    if isinstance(env_cfg, dict):
        env_cfg["max_rounds"] = horizon
    if isinstance(task_cfg, dict) and (
        "task.parameters.num_rounds" in declared or num_rounds is not None
    ):
        task_cfg.setdefault("parameters", {})["num_rounds"] = horizon
    for sc in stop_conditions:
        sc["value"] = horizon

    # --- And in the prose the agents actually read ---
    for agent_cfg in config.get("agents") or []:
        if not isinstance(agent_cfg, dict):
            continue
        for key in _PROMPT_KEYS:
            value = agent_cfg.get(key)
            if isinstance(value, str):
                agent_cfg[key] = _fill_rounds(value, horizon)
    if isinstance(task_cfg, dict) and isinstance(task_cfg.get("description"), str):
        task_cfg["description"] = _fill_rounds(task_cfg["description"], horizon)

    return horizon


def find_hardcoded_rounds(config: Dict[str, Any], horizon: int) -> List[str]:
    """Prompt sites that still state a round count in prose, for linting.

    Returns human-readable locations of any ``"<n> rounds"`` mention whose
    number disagrees with *horizon* — the failure mode ``resolve_round_horizon``
    exists to prevent, for configs not yet migrated to ``{num_rounds}``.
    """
    pattern = re.compile(r"\b(\d+)\s+rounds?\b", re.IGNORECASE)
    offenders: List[str] = []
    for agent_cfg in config.get("agents") or []:
        if not isinstance(agent_cfg, dict):
            continue
        aid = agent_cfg.get("agent_id", "?")
        for key in _PROMPT_KEYS:
            value = agent_cfg.get(key)
            if not isinstance(value, str):
                continue
            for match in pattern.finditer(value):
                if int(match.group(1)) != horizon:
                    offenders.append(
                        f"agents[{aid}].{key}: {match.group(0)!r} != {horizon}"
                    )
    return offenders


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
    from risklab.environments.competitive.bilateral_bargaining import (
        BilateralBargaining,
    )
    from risklab.environments.competitive.subtask_selection import (
        SubtaskSelection,
    )
    register_environment("homogeneous_goods_market", HomogeneousGoodsMarket)
    register_environment("bilateral_bargaining", BilateralBargaining)
    register_environment("subtask_selection", SubtaskSelection)

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
    try:
        import risklab.risks.information_asymmetry_exploitation  # noqa: F401
    except ImportError:
        pass
    try:
        import risklab.risks.competitive_task_avoidance  # noqa: F401
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
    num_rounds: Optional[int] = None,
) -> Dict[str, Any]:
    """Build all experiment components from a parsed YAML config.

    Parameters
    ----------
    config : dict
        Full experiment config (as returned by ``load_experiment_config``).
    base_dir : str, optional
        Base directory for resolving relative paths.
    num_rounds : int, optional
        Override the episode length.  Applied to the environment, the task,
        the stop conditions *and* the agent prompts in one place — see
        ``resolve_round_horizon``.

    Returns
    -------
    dict
        Dictionary with keys: ``experiment_id``, ``environment``,
        ``protocol``, ``agents``, ``task``, ``topology``, ``flow``,
        ``risks``, ``num_rounds``, ``output_dir``.
    """
    base_dir = base_dir or os.getcwd()

    # Reconcile the episode length before anything reads it, so the
    # environment, the stop conditions and the prompts cannot disagree.
    horizon = resolve_round_horizon(config, num_rounds)

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
        "num_rounds": horizon,
        "output_dir": config.get("output_dir", "results"),
    }
