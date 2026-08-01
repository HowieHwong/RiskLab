"""
LLM configuration & provider management.

Handles API key resolution, provider detection, and provides a unified
client interface for calling different LLM backends.

Design
------
- **API keys** are resolved in priority order:
    1. ``${ENV_VAR}`` syntax in YAML  →  reads the named environment variable
    2. Convention-based env var (e.g. ``OPENAI_API_KEY`` for the ``openai`` provider)
    3. Literal string in the config (least recommended — avoid committing secrets)
- **Provider detection** maps a model name (e.g. ``"gpt-4o"``) to its provider
  automatically, or the user can be explicit with ``"provider/model"`` syntax.
- **LLMClient** provides a thin ``chat()`` method that dispatches to the correct
  provider.  Currently supports OpenAI-compatible APIs and Anthropic.

YAML schema
-----------
.. code-block:: yaml

    llm:
      default_model: "gpt-4o"
      default_temperature: 0.7
      default_max_tokens: 2048
      providers:
        openai:
          api_key: "${OPENAI_API_KEY}"
          api_base: "https://api.openai.com/v1"
        anthropic:
          api_key: "${ANTHROPIC_API_KEY}"
        local:
          api_key: "token-abc123"
          api_base: "http://localhost:8000/v1"
          api_type: "openai"          # openai-compatible server
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ======================================================================
# Constants
# ======================================================================

# Convention-based env var names for known providers
_DEFAULT_ENV_KEYS: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "google": "GOOGLE_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "together": "TOGETHER_API_KEY",
}

# Default API base URLs
_DEFAULT_API_BASES: Dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "deepseek": "https://api.deepseek.com/v1",
}

# Well-known model prefix → provider mapping (for auto-detection)
_MODEL_PREFIX_TO_PROVIDER: List[tuple] = [
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("text-", "openai"),
    ("claude-", "anthropic"),
    ("deepseek-", "deepseek"),
    ("gemini-", "google"),
    ("glm-", "zhipu"),
    ("mistral-", "mistral"),
    ("mixtral-", "mistral"),
]

_ENV_VAR_PATTERN = re.compile(r"^\$\{(\w+)\}$")


# ======================================================================
# API type enum
# ======================================================================

class APIType(str, Enum):
    """Supported API protocol types."""
    OPENAI = "openai"         # OpenAI chat completions (and compatible)
    ANTHROPIC = "anthropic"   # Anthropic messages API
    CUSTOM = "custom"


# ======================================================================
# Provider config
# ======================================================================

@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider.

    Parameters
    ----------
    name : str
        Provider identifier (``"openai"``, ``"anthropic"``, ``"local"``, …).
    api_key : str | None
        API key.  Supports ``${ENV_VAR}`` syntax to reference environment
        variables.  If ``None``, falls back to the convention-based env var.
    api_base : str | None
        Base URL of the API.  ``None`` → use the provider's default.
    api_type : str
        API protocol (``"openai"`` or ``"anthropic"``).  Most self-hosted
        servers are OpenAI-compatible.
    default_model : str | None
        Default model for this provider (overrides global default).
    extra_headers : dict
        Extra HTTP headers sent with every request.
    parameters : dict
        Provider-specific extra parameters (org id, project id, …).
    """

    name: str
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    api_type: str = "openai"
    default_model: Optional[str] = None
    extra_headers: Dict[str, str] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------

    def resolve_api_key(self) -> Optional[str]:
        """Resolve the API key in priority order.

        1. ``${ENV_VAR}`` reference  →  read the named env var
        2. Literal non-empty string  →  use as-is
        3. Convention-based env var   →  e.g. ``OPENAI_API_KEY`` for ``openai``
        4. ``None``
        """
        if self.api_key is not None:
            m = _ENV_VAR_PATTERN.match(self.api_key)
            if m:
                return os.environ.get(m.group(1))
            if self.api_key:
                return self.api_key

        # Fallback: convention-based env var
        env_key = _DEFAULT_ENV_KEYS.get(self.name)
        if env_key:
            return os.environ.get(env_key)

        return None

    def resolve_api_base(self) -> Optional[str]:
        """Return the effective API base URL."""
        if self.api_base:
            m = _ENV_VAR_PATTERN.match(self.api_base)
            if m:
                return os.environ.get(m.group(1))
            return self.api_base
        env_base = os.environ.get(f"{self.name.upper()}_BASE_URL")
        if env_base:
            return env_base
        return _DEFAULT_API_BASES.get(self.name)

    def resolve_api_type(self) -> APIType:
        """Return the effective API type."""
        try:
            return APIType(self.api_type)
        except ValueError:
            return APIType.OPENAI  # default fallback


# ======================================================================
# Global LLM config
# ======================================================================

@dataclass
class LLMConfig:
    """Top-level LLM configuration (maps to the ``llm:`` section in YAML).

    Examples
    --------
    >>> cfg = LLMConfig.from_dict({
    ...     "default_model": "gpt-4o",
    ...     "providers": {
    ...         "openai": {"api_key": "${OPENAI_API_KEY}"},
    ...         "local":  {"api_base": "http://localhost:8000/v1",
    ...                    "api_key": "token-abc"},
    ...     },
    ... })
    """

    default_model: str = "gpt-4o"
    default_temperature: float = 0.7
    default_max_tokens: int = 2048
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Provider / model resolution
    # ------------------------------------------------------------------

    def get_provider(self, name: str) -> ProviderConfig:
        """Retrieve a provider config by name.

        Raises ``KeyError`` if the provider is not registered.
        """
        if name not in self.providers:
            available = ", ".join(sorted(self.providers)) or "(none)"
            raise KeyError(
                f"Unknown LLM provider '{name}'. "
                f"Registered providers: {available}"
            )
        return self.providers[name]

    def detect_provider(self, model: str) -> str:
        """Auto-detect the provider name for a given model string.

        Supports two formats:
            - ``"provider/model"`` → explicit provider
            - ``"gpt-4o"`` → matched via prefix table

        Raises ``ValueError`` if no provider can be determined.
        """
        # Explicit "provider/model" syntax
        if "/" in model:
            return model.split("/", 1)[0]

        # Prefix-based matching
        model_lower = model.lower()
        for prefix, provider in _MODEL_PREFIX_TO_PROVIDER:
            if model_lower.startswith(prefix):
                return provider

        # Check if the model name matches any provider's default_model
        for pname, pcfg in self.providers.items():
            if pcfg.default_model and pcfg.default_model == model:
                return pname

        raise ValueError(
            f"Cannot auto-detect provider for model '{model}'. "
            f"Use 'provider/model' syntax or register the provider explicitly."
        )

    def resolve_model(self, model: str) -> tuple:
        """Resolve a model string into ``(provider_name, model_name, ProviderConfig)``.

        Parameters
        ----------
        model : str
            Either ``"gpt-4o"`` (auto-detect) or ``"provider/model"`` (explicit).

        Returns
        -------
        tuple
            ``(provider_name, actual_model_name, ProviderConfig)``
        """
        if "/" in model:
            provider_name, model_name = model.split("/", 1)
        else:
            provider_name = self.detect_provider(model)
            model_name = model

        # Auto-create a minimal provider config if not explicitly defined
        if provider_name not in self.providers:
            self.providers[provider_name] = ProviderConfig(name=provider_name)

        provider = self.providers[provider_name]
        return provider_name, model_name, provider

    def get_api_key_for_model(self, model: str) -> Optional[str]:
        """Convenience: resolve the API key for a model string."""
        _, _, provider = self.resolve_model(model)
        return provider.resolve_api_key()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "default_model": self.default_model,
            "default_temperature": self.default_temperature,
            "default_max_tokens": self.default_max_tokens,
            "providers": {},
        }
        for name, pcfg in self.providers.items():
            pd: Dict[str, Any] = {}
            if pcfg.api_key is not None:
                pd["api_key"] = pcfg.api_key
            if pcfg.api_base is not None:
                pd["api_base"] = pcfg.api_base
            if pcfg.api_type != "openai":
                pd["api_type"] = pcfg.api_type
            if pcfg.default_model is not None:
                pd["default_model"] = pcfg.default_model
            if pcfg.extra_headers:
                pd["extra_headers"] = pcfg.extra_headers
            if pcfg.parameters:
                pd["parameters"] = pcfg.parameters
            d["providers"][name] = pd
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LLMConfig":
        """Build from a YAML-parsed dict (the value of ``llm:`` key)."""
        data = dict(data)
        raw_providers = data.pop("providers", {})
        providers: Dict[str, ProviderConfig] = {}
        for name, pcfg_dict in raw_providers.items():
            pcfg_dict = dict(pcfg_dict)
            providers[name] = ProviderConfig(name=name, **pcfg_dict)
        return cls(
            default_model=data.get("default_model", "gpt-4o"),
            default_temperature=data.get("default_temperature", 0.7),
            default_max_tokens=data.get("default_max_tokens", 2048),
            providers=providers,
        )

    @classmethod
    def from_file(cls, path: str) -> "LLMConfig":
        """Load LLM configuration from a YAML file.

        Parameters
        ----------
        path : str
            Path to the YAML config file (e.g. ``llm_config.yaml``).

        Returns
        -------
        LLMConfig

        Raises
        ------
        ImportError
            If PyYAML is not installed.
        FileNotFoundError
            If the file does not exist.
        """
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "PyYAML is required to load YAML config files. "
                "Install it with: pip install pyyaml"
            )

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return cls.from_dict(data)

    @classmethod
    def from_env(cls, default_model: str = "gpt-4o") -> "LLMConfig":
        """Create a minimal config that reads API keys purely from
        environment variables (zero YAML needed).

        This is the simplest way to get started::

            export OPENAI_API_KEY="sk-..."
            cfg = LLMConfig.from_env()
        """
        providers: Dict[str, ProviderConfig] = {}
        for pname, env_key in _DEFAULT_ENV_KEYS.items():
            if os.environ.get(env_key):
                providers[pname] = ProviderConfig(name=pname)
        return cls(default_model=default_model, providers=providers)


# ======================================================================
# Unified LLM Client
# ======================================================================

class LLMClient:
    """Thin wrapper that dispatches ``chat()`` calls to the correct provider.

    Parameters
    ----------
    config : LLMConfig
        The global LLM configuration.

    Examples
    --------
    >>> client = LLMClient(LLMConfig.from_env())
    >>> reply = client.chat(
    ...     model="gpt-4o",
    ...     messages=[{"role": "user", "content": "Hello!"}],
    ... )
    >>> print(reply)
    """

    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self.config = config or LLMConfig.from_env()

    def chat(
        self,
        model: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """Send a chat completion request and return the assistant's reply.

        Parameters
        ----------
        model : str, optional
            Model identifier (``"gpt-4o"``, ``"claude-3-opus"``,
            ``"local/my-model"``).  Falls back to ``config.default_model``.
        messages : list[dict]
            OpenAI-style message list.
        temperature : float, optional
        max_tokens : int, optional
        **kwargs
            Extra arguments passed to the underlying API call.

        Returns
        -------
        str
            The text content of the assistant's reply.
        """
        model = model or self.config.default_model
        messages = messages or []
        temperature = temperature if temperature is not None else self.config.default_temperature
        max_tokens = max_tokens if max_tokens is not None else self.config.default_max_tokens

        provider_name, model_name, provider = self.config.resolve_model(model)
        api_type = provider.resolve_api_type()
        api_key = provider.resolve_api_key()
        api_base = provider.resolve_api_base()
        provider_kwargs = dict(provider.parameters)
        provider_kwargs.update(kwargs)

        if api_type in (APIType.OPENAI, APIType.CUSTOM):
            return self._call_openai_compatible(
                model_name=model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=api_key,
                api_base=api_base,
                extra_headers=provider.extra_headers,
                **provider_kwargs,
            )
        elif api_type == APIType.ANTHROPIC:
            return self._call_anthropic(
                model_name=model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=api_key,
                api_base=api_base,
                extra_headers=provider.extra_headers,
                **provider_kwargs,
            )
        else:
            raise ValueError(f"Unsupported API type: {api_type}")

    # ------------------------------------------------------------------
    # OpenAI-compatible backend
    # ------------------------------------------------------------------

    @staticmethod
    def _call_openai_compatible(
        model_name: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        api_key: Optional[str],
        api_base: Optional[str],
        extra_headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "The 'openai' package is required for OpenAI-compatible APIs. "
                "Install it with: pip install openai"
            )

        client_kwargs: Dict[str, Any] = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if api_base:
            client_kwargs["base_url"] = api_base
        if extra_headers:
            client_kwargs["default_headers"] = extra_headers

        client = OpenAI(**client_kwargs)
        token_limit_param = (
            {"max_completion_tokens": max_tokens}
            if model_name.startswith("gpt-5")
            else {"max_tokens": max_tokens}
        )
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=temperature,
            **token_limit_param,
            **kwargs,
        )
        return response.choices[0].message.content or ""

    # ------------------------------------------------------------------
    # Anthropic backend
    # ------------------------------------------------------------------

    @staticmethod
    def _call_anthropic(
        model_name: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        api_key: Optional[str],
        api_base: Optional[str],
        extra_headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> str:
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "The 'anthropic' package is required for Anthropic APIs. "
                "Install it with: pip install anthropic"
            )

        client_kwargs: Dict[str, Any] = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        if api_base:
            client_kwargs["base_url"] = api_base
        if extra_headers:
            client_kwargs["default_headers"] = extra_headers

        client = anthropic.Anthropic(**client_kwargs)

        # Anthropic requires separating the system message
        system_text = ""
        user_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_text += msg.get("content", "") + "\n"
            else:
                user_messages.append(msg)

        create_kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": user_messages or [{"role": "user", "content": ""}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system_text.strip():
            create_kwargs["system"] = system_text.strip()
        create_kwargs.update(kwargs)

        response = client.messages.create(**create_kwargs)
        # Anthropic returns content blocks
        return response.content[0].text if response.content else ""
