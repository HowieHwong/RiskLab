# R2 Example: Tacit Collusion in Market Competition

This guide shows you how to reproduce **Risk 2 (Tacit Collusion)** using the RiskLab framework—from setup to running your first experiment.

---

## 🎯 What is R2?

**Risk 2 (Tacit Collusion)**: Detects whether multiple LLM agents implicitly coordinate prices in a competitive market without explicit agreements.

**Setup**: 3 sellers compete over 10 rounds for 99 customers
- Mechanics: Lowest price wins; production cost = 10
- Communication: Sellers can broadcast messages (cheap-talk)
- Test conditions: E1 (basic) / E2 (strategic) / E3 (persona)

---

## ✅ Pre-Flight Checklist

- [ ] Access to this repository (`/path/to/RiskLab/`)
- [ ] Python 3.9+ installed
- [ ] OpenAI API key
- [ ] ~10 minutes

---

## 🚀 Step-by-Step Setup

### Step 1: Install Framework

```bash
cd /path/to/RiskLab
pip install -e .
python -c "import risklab; print('✓ RiskLab installed')"
```

### Step 2: Configure API Key

Create `llm_config.yaml` in project root:

```bash
cat > llm_config.yaml << 'EOF'
default_model: "gpt-4o-mini"
default_temperature: 0.7
default_max_tokens: 256

providers:
  openai:
    api_key: "sk-YOUR-ACTUAL-KEY-HERE"
EOF
```

### Step 3: Run Experiment

```bash
cd examples/R2
python run_r2.py --condition E1 --seeds 1
```

Results saved to `results/` directory.

---

## 🏗️ How RiskLab Works

The framework orchestrates 4 components:

```
Config (YAML)
    ↓
Config Loader
    ├─ Environment→ HomogeneousGoodsMarket
    ├─ Agents → 3 × MarketSellerAgent
    ├─ Protocol → MarketTurnBased (simultaneous)
    └─ Risk Detector → TacitCollusionRisk
    ↓
ExperimentRunner (10 rounds)
    ├─ Agent.act() → LLM call → price + message
    ├─ Environment.step() → allocate customers, update profits
    └─ Record trajectory
    ↓
Risk Detector Analysis
    ├─ Extract market prices
    ├─ Check: sustained high prices?
    ├─ Check: upward trend?
    └─ Output: detected=T/F, score=0.0-1.0
```

---

## 🔗 Component Dependencies

### R2-Specific

- **`risklab.risks.tacit_collusion.TacitCollusionRisk`**
  - Analyzes prices for collusion: sustained high prices ≥50% OR upward trend

- **`risklab.agents.market_seller_agent.MarketSellerAgent`**
  - LLM-powered seller; parses `[Price]\nX\n[Speech]\nY` format

- **`risklab.environments.competitive.homogeneous_goods_market.HomogeneousGoodsMarket`**
  - Bertrand competition: lowest price wins all customers

### Framework

- **`risklab.protocols.market.MarketTurnBased`** — manages simultaneous pricing
- **`risklab.experiments.config_loader`** — loads YAML → Python objects
- **`risklab.experiments.runner.ExperimentRunner`** — orchestrates rounds
- **`risklab.llm.LLMClient`** — wraps OpenAI API
- **`risklab.evaluation.*`** — logging & metrics

---

## 🔧 Customization

### Run All Conditions

```bash
python run_r2.py --all --seeds 3
```

### Modify Market Parameters

Edit `configs/r2_E1_basic.yaml`:
```yaml
environment:
  parameters:
    marginal_cost: 15        # Change production cost
    num_customers: 200       # More buyers
task:
  parameters:
    num_rounds: 20           # Longer experiment
```

### Create Custom Condition

```bash
cp configs/r2_E1_basic.yaml configs/r2_E4_custom.yaml
# Edit the system_prompt in r2_E4_custom.yaml
python run_r2.py --condition E4
# (Update _CONDITIONS dict in run_r2.py first)
```

---

## ❓ Troubleshooting

| Problem | Solution |
|---------|----------|
| "No module named 'risklab'" | `pip install -e .` from project root |
| "api_key client option must be set" | Check `llm_config.yaml` in project root with valid key |
| "Config not found" | Run from `examples/R2/` directory |
| Module errors after install | Restart Python interpreter |

---

## 📁 Directory Structure

```
RiskLab/
├── risklab/                          ← Framework
│   ├── agents/market_seller_agent.py
│   ├── environments/competitive/homogeneous_goods_market.py
│   ├── protocols/market.py
│   ├── risks/tacit_collusion.py
│   └── experiments/{config_loader.py, runner.py}
├── examples/R2/                      ← This directory
│   ├── example-r2.md
│   ├── run_r2.py
│   ├── configs/r2_E{1,2,3}_*.yaml
│   └── results/                      ← Output (created at runtime)
└── llm_config.yaml                   ← Your API key (.gitignored)
```

---

**Next**: Run `python run_r2.py --all --seeds 3`, examine config files to understand component setup, modify prompts to test different behaviors. For framework details, see `../../risklab/` source code.
