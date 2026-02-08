"""Agent abstractions and role management."""

from risklab.agents.base import Agent, AgentConfig
from risklab.agents.registry import AgentRegistry
from risklab.agents.llm_agent import LLMAgent

__all__ = ["Agent", "AgentConfig", "AgentRegistry", "LLMAgent"]
