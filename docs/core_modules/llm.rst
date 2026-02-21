=================
LLM Configuration
=================

RiskLab supports multiple LLM providers through a unified configuration
system.

Provider Setup
--------------

Configure providers in ``llm_config.yaml`` at the project root:

.. code-block:: yaml

   default_model: "gpt-4o"
   default_temperature: 0.7
   default_max_tokens: 2048
   providers:
     openai:
       api_key: "${OPENAI_API_KEY}"
       api_base: "https://api.openai.com/v1"
     anthropic:
       api_key: "${ANTHROPIC_API_KEY}"
     custom_provider:
       api_key: "sk-..."
       api_base: "https://my-proxy.example.com/v1"
       api_type: openai             # OpenAI-compatible API format

API Key Resolution
~~~~~~~~~~~~~~~~~~

Keys are resolved in order:

1. ``${ENV_VAR}`` — reads from environment variables
2. Literal string — used directly
3. Convention — if omitted, checks ``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY``

Provider Auto-Detection
~~~~~~~~~~~~~~~~~~~~~~~

When no provider is specified for a model, the client infers it:

- ``gpt-*``, ``o1-*``, ``o3-*`` → OpenAI
- ``claude-*`` → Anthropic
- ``"provider/model"`` syntax → explicit provider

Using the Client
----------------

.. code-block:: python

   from risklab.llm import LLMConfig, LLMClient

   # Load from YAML file
   config = LLMConfig.from_file("llm_config.yaml")

   # Or from environment variables only
   config = LLMConfig.from_env()

   # Create client and call
   client = LLMClient(config)
   response = client.chat(
       model="gpt-4o",
       messages=[
           {"role": "system", "content": "You are a helpful assistant."},
           {"role": "user", "content": "Hello!"},
       ],
       temperature=0.7,
   )

Per-Agent Models
~~~~~~~~~~~~~~~~

Each agent can use a different model. Specify it in the experiment config:

.. code-block:: yaml

   agents:
     - agent_id: agent_0
       model: gpt-4o
     - agent_id: agent_1
       model: claude-sonnet-4-20250514
     - agent_id: agent_2
       model: custom_provider/my-model   # explicit provider routing
