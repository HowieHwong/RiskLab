"""Agent abstractions and role management."""

from mas_risk_toolkit.agents.base import Agent, AgentConfig
from mas_risk_toolkit.agents.registry import AgentRegistry
from mas_risk_toolkit.agents.llm_agent import LLMAgent

__all__ = ["Agent", "AgentConfig", "AgentRegistry", "LLMAgent"]
