"""
Configuration loader — builds experiment components from YAML configs.

This module provides utilities to load a complete experiment from a YAML
file, including resolving external LLM configuration files.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from mas_risk_toolkit.agents.base import Agent, AgentConfig
from mas_risk_toolkit.agents.llm_agent import LLMAgent
from mas_risk_toolkit.environments.base import Environment
from mas_risk_toolkit.llm import LLMConfig, LLMClient
from mas_risk_toolkit.protocols.base import InteractionProtocol
from mas_risk_toolkit.tasks import TaskConfig
from mas_risk_toolkit.topology import CommunicationTopology, InformationFlowConfig, build_topology_from_config


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
        config = AgentConfig(**agent_dict)

        # Build per-agent LLMConfig if the agent has provider overrides
        agent_llm_config = llm_config
        if any([config.provider, config.api_key, config.api_base]):
            # Clone global config and apply agent-specific overrides
            agent_llm_config = LLMConfig.from_dict(llm_config.to_dict())
            # If provider override is specified, ensure it exists
            provider_name = config.provider or agent_llm_config.detect_provider(config.model)
            if provider_name not in agent_llm_config.providers:
                from mas_risk_toolkit.llm import ProviderConfig
                agent_llm_config.providers[provider_name] = ProviderConfig(name=provider_name)
            # Apply per-agent overrides
            if config.api_key:
                agent_llm_config.providers[provider_name].api_key = config.api_key
            if config.api_base:
                agent_llm_config.providers[provider_name].api_base = config.api_base

        agent = LLMAgent(
            config=config,
            llm_config=agent_llm_config,
            llm_client=llm_client if agent_llm_config == llm_config else LLMClient(agent_llm_config),
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
