# LLM Configuration Guide

This document explains how to configure LLM providers for MAS-Risk-Toolkit.

## Quick Start

### 1. Create `llm_config.yaml`

```bash
# Copy the template to your project root
cp llm_config.yaml my_llm_config.yaml

# Or start from scratch
cat > llm_config.yaml <<EOF
default_model: "gpt-4o"
default_temperature: 0.7
default_max_tokens: 2048

providers:
  openai:
    api_key: "\${OPENAI_API_KEY}"
EOF
```

### 2. Set Environment Variables

```bash
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 3. Reference in Experiment Config

```yaml
# experiments/configs/my_experiment.yaml
experiment:
  id: "my_experiment"
  
llm_config_path: "llm_config.yaml"  # or "../llm_config.yaml" if nested

# ... rest of your experiment config
```

## Configuration Options

### Three Ways to Configure

| Method | Config File | Experiment YAML | Best For |
|--------|-------------|-----------------|----------|
| **1. External File** (recommended) | `llm_config.yaml` | `llm_config_path: "llm_config.yaml"` | Sharing config across experiments, keeping secrets separate |
| **2. Inline** | - | `llm:` section in experiment YAML | Single experiments, quick prototyping |
| **3. Env Only** | - | (omit both) | CI/CD, minimal setup |

### Provider Configuration

Each provider supports:

- `api_key`: API key (supports `${ENV_VAR}` syntax)
- `api_base`: Base URL (optional, defaults provided for known providers)
- `api_type`: `"openai"` or `"anthropic"` (default: `"openai"`)
- `default_model`: Provider-specific default model
- `extra_headers`: Extra HTTP headers (dict)
- `parameters`: Provider-specific extra parameters (dict)

### Per-Agent Overrides

Agents can override LLM settings:

```yaml
agents:
  - agent_id: "seller_1"
    model: "gpt-4o"
    temperature: 0.9              # override global default
    
  - agent_id: "seller_2"
    model: "local/my-model"       # explicit provider
    api_base: "http://gpu:8000/v1"  # override provider base URL
```

## Security Best Practices

1. **Never commit `llm_config.yaml` with real API keys**
   - Add to `.gitignore` (already included in template)
   - Use `${ENV_VAR}` syntax or convention-based env vars

2. **Use separate configs for different environments**
   ```bash
   llm_config.dev.yaml      # development
   llm_config.prod.yaml     # production
   ```

3. **Share templates, not secrets**
   - Commit `llm_config.yaml.template` with placeholders
   - Users copy and fill in their own keys

## Troubleshooting

### "ModuleNotFoundError: No module named 'yaml'"

```bash
pip install pyyaml
```

### "FileNotFoundError: llm_config.yaml not found"

- Check the path is relative to the experiment config file's directory
- Use absolute path if needed: `llm_config_path: "/path/to/llm_config.yaml"`

### "Cannot auto-detect provider for model 'xyz'"

- Use explicit syntax: `model: "provider/model"`
- Or register the provider in `llm_config.yaml` with a `default_model`

## Python API

```python
from mas_risk_toolkit import LLMConfig, load_llm_config, build_agents_from_config

# Load from file
config = LLMConfig.from_file("llm_config.yaml")

# Load from experiment config
exp_config = {"llm_config_path": "llm_config.yaml"}
config = load_llm_config(exp_config, base_dir=".")

# Build agents
agents = build_agents_from_config(
    agent_configs=[...],
    llm_config=config,
    task=task_config,
)
```

## Example Configurations

### Multi-Provider Setup

```yaml
providers:
  openai:
    api_key: "${OPENAI_API_KEY}"
  anthropic:
    api_key: "${ANTHROPIC_API_KEY}"
  deepseek:
    api_key: "${DEEPSEEK_API_KEY}"
    api_base: "https://api.deepseek.com/v1"
  local:
    api_base: "http://localhost:8000/v1"
    api_key: "not-needed"
    api_type: "openai"
```

### OpenAI Organization

```yaml
providers:
  openai:
    api_key: "${OPENAI_API_KEY}"
    extra_headers:
      "OpenAI-Organization": "org-abc123"
```

### Custom Timeout

```yaml
providers:
  openai:
    api_key: "${OPENAI_API_KEY}"
    parameters:
      timeout: 120  # 2 minutes
```
