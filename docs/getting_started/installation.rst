============
Installation
============

Requirements
------------

- Python >= 3.9
- ``pyyaml >= 6.0``

Optional (for LLM providers and tool integration):

- ``openai >= 1.0``
- ``anthropic >= 0.20``
- ``mcp >= 1.0.0``

Install from Source
-------------------

.. code-block:: bash

   git clone https://github.com/your-org/RiskLab.git
   cd RiskLab
   pip install -e .

Install with all optional dependencies:

.. code-block:: bash

   pip install -e ".[all]"

   # Or install individually:
   pip install -e ".[openai]"       # OpenAI support
   pip install -e ".[anthropic]"    # Anthropic support
   pip install -e ".[mcp]"          # MCP tool integration

LLM Configuration
-----------------

Copy the example config and fill in your API keys:

.. code-block:: bash

   cp "llm_config example.yaml" llm_config.yaml

Edit ``llm_config.yaml``:

.. code-block:: yaml

   default_model: "gpt-4o"
   default_temperature: 0.7
   default_max_tokens: 2048
   providers:
     openai:
       api_key: "${OPENAI_API_KEY}"    # env var or literal key
       api_base: "https://api.openai.com/v1"
     anthropic:
       api_key: "${ANTHROPIC_API_KEY}"

API keys can be provided as:

1. **Environment variable** — ``${OPENAI_API_KEY}``
2. **Literal string** — the key value directly
3. **Convention** — if omitted, RiskLab checks standard env vars automatically

Load and use LLM config in Python:

.. code-block:: python

   from risklab.llm import LLMConfig, LLMClient

   config = LLMConfig.from_file("llm_config.yaml")   # from YAML
   config = LLMConfig.from_env()                      # from env vars only

   client = LLMClient(config)
   response = client.chat(
       model="gpt-4o",
       messages=[{"role": "user", "content": "Hello!"}],
   )

Provider auto-detection: ``gpt-*`` / ``o1-*`` → OpenAI,
``claude-*`` → Anthropic, ``"provider/model"`` → explicit.

Verify Installation
-------------------

.. code-block:: bash

   python -c "import risklab; print(risklab.__version__)"
