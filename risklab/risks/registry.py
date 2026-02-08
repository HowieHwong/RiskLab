"""
Risk registry — extensible lookup for all risk types.

Usage
-----
>>> from risklab.risks.registry import RiskRegistry
>>>
>>> @RiskRegistry.register("tacit_collusion")
... class TacitCollusion(Risk):
...     ...
>>>
>>> risk_cls = RiskRegistry.get("tacit_collusion")
"""

from __future__ import annotations

from typing import Dict, List, Type

from risklab.risks.base import Risk, RiskCategory


class RiskRegistry:
    """Global, extensible registry of risk implementations."""

    _registry: Dict[str, Type[Risk]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator to register a Risk subclass under *name*."""
        def decorator(risk_cls: Type[Risk]) -> Type[Risk]:
            if name in cls._registry:
                raise ValueError(f"Risk type '{name}' is already registered.")
            cls._registry[name] = risk_cls
            return risk_cls
        return decorator

    @classmethod
    def get(cls, name: str) -> Type[Risk]:
        """Retrieve a registered risk class by *name*."""
        if name not in cls._registry:
            available = ", ".join(sorted(cls._registry)) or "(none)"
            raise KeyError(
                f"Unknown risk type '{name}'. Available: {available}"
            )
        return cls._registry[name]

    @classmethod
    def list_registered(cls) -> List[str]:
        """Return a sorted list of all registered risk type names."""
        return sorted(cls._registry.keys())

    @classmethod
    def list_by_category(cls, category: RiskCategory) -> List[str]:
        """Return risk names that belong to *category*."""
        return sorted(
            name
            for name, rcls in cls._registry.items()
            # Access the category from the class-level default config if set,
            # otherwise skip (it will be set at instance time).
        )
