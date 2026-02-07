"""
Agent registry — a central place to register and look up agent types.

Usage
-----
>>> from mas_risk_toolkit.agents.registry import AgentRegistry
>>>
>>> @AgentRegistry.register("openai")
... class OpenAIAgent(Agent):
...     ...
>>>
>>> agent_cls = AgentRegistry.get("openai")
"""

from __future__ import annotations

from typing import Dict, Type

from mas_risk_toolkit.agents.base import Agent


class AgentRegistry:
    """Global, extensible registry of agent implementations."""

    _registry: Dict[str, Type[Agent]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator to register an Agent subclass under *name*."""
        def decorator(agent_cls: Type[Agent]) -> Type[Agent]:
            if name in cls._registry:
                raise ValueError(f"Agent type '{name}' is already registered.")
            cls._registry[name] = agent_cls
            return agent_cls
        return decorator

    @classmethod
    def get(cls, name: str) -> Type[Agent]:
        """Retrieve a registered agent class by *name*."""
        if name not in cls._registry:
            available = ", ".join(sorted(cls._registry)) or "(none)"
            raise KeyError(
                f"Unknown agent type '{name}'. Available: {available}"
            )
        return cls._registry[name]

    @classmethod
    def list_registered(cls):
        """Return a sorted list of all registered agent type names."""
        return sorted(cls._registry.keys())
