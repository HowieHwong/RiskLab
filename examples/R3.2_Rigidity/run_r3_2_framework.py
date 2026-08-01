#!/usr/bin/env python3
"""
Run R3.2 (Rigidity and Mistaken Commitments) experiments with YAML configs.

Four experimental conditions:
  C1  Rigidity: never sell TechCorp        (5 rounds, 4 market events)
  C2  Rigidity: never sell BioGen           (5 rounds, 4 market events)
  C3  Mistaken commitment: GNVT acquisition (4 rounds, 3 market events)
  C4  Mistaken commitment: LMLG contract    (4 rounds, 3 market events)

Usage
-----
    # Navigate to the examples/R3.2_Rigidity directory first
    cd examples/R3.2_Rigidity

    # Run all conditions:
    python run_r3_2_framework.py

    # Run specific conditions:
    python run_r3_2_framework.py --conditions C1 C3

    # Customize seeds and output directory:
    python run_r3_2_framework.py --seeds 3 --output results/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

# Ensure project root is importable
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from risklab.experiments.config_loader import (
    build_experiment_from_config,
    load_experiment_config,
)
from risklab.risks.rigidity import RigidityRisk


# ------------------------------------------------------------------
# Condition definitions
# ------------------------------------------------------------------

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "configs")

_CONDITIONS: Dict[str, Dict[str, Any]] = {
    "C1": {
        "yaml": "r3_2_C1.yaml",
        "label": "Rigidity — Never sell TC",
        "total_market_rounds": 4,
    },
    "C2": {
        "yaml": "r3_2_C2.yaml",
        "label": "Rigidity — Never sell BGI",
        "total_market_rounds": 4,
    },
    "C3": {
        "yaml": "r3_2_C3.yaml",
        "label": "Mistaken Commitment — GNVT acquisition",
        "total_market_rounds": 3,
    },
    "C4": {
        "yaml": "r3_2_C4.yaml",
        "label": "Mistaken Commitment — LMLG contract",
        "total_market_rounds": 3,
    },
}


# ------------------------------------------------------------------
# Main logic
# ------------------------------------------------------------------

def _run_r3_2_framework(
    num_seeds: int = 3,
    output_dir: str = "results/",
    conditions: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Run R3.2 experiments across selected conditions."""
    conditions = conditions or list(_CONDITIONS.keys())

    # Validate
    for c in conditions:
        if c not in _CONDITIONS:
            print(f"  ✗ Unknown condition: {c}")
            print(f"    Available: {', '.join(_CONDITIONS)}")
            return []

    total = len(conditions) * num_seeds
    print(f"\n{'='*70}")
    print(f"  R3.2  Rigidity & Mistaken Commitments  (framework YAML)")
    print(f"  Design: All agents receive user strategy directly")
    print(f"  Conditions : {', '.join(conditions)}")
    print(f"  Seeds      : {num_seeds}")
    print(f"  Total runs : {total}")
    print(f"{'='*70}")

    all_results: List[Dict[str, Any]] = []

    for cond_name in conditions:
        cond = _CONDITIONS[cond_name]
        config_path = os.path.join(_CONFIG_DIR, cond["yaml"])

        if not os.path.isfile(config_path):
            print(f"  ✗ Config not found: {config_path}")
            continue

        print(f"\n── {cond_name}: {cond['label']} ──")

        for seed in range(num_seeds):
            print(f"\n  Seed {seed}:")

            # Load and build fresh for each seed
            raw_config = load_experiment_config(config_path)
            components = build_experiment_from_config(
                raw_config,
                base_dir=_PROJECT_ROOT,
            )
            components["output_dir"] = output_dir

            from risklab.experiments.runner import ExperimentRunner

            runner = ExperimentRunner(
                experiment_id=f"{components['experiment_id']}_seed{seed}",
                environment=components["environment"],
                protocol=components["protocol"],
                agents=components["agents"],
                task=components.get("task"),
                topology=components.get("topology"),
                flow=components.get("flow"),
                risks=components.get("risks", []),
                output_dir=components["output_dir"],
            )

            # Run cyclic episode
            results = runner.run(num_seeds=1)

            for r in results:
                r["condition"] = cond_name
                r["condition_label"] = cond["label"]
                r["seed"] = seed
                r["total_market_rounds"] = cond["total_market_rounds"]

                _print_episode_result(cond_name, seed, r)

            all_results.extend(results)

    # Print aggregate summary
    _print_aggregate(all_results)

    # Save aggregate
    os.makedirs(output_dir, exist_ok=True)
    agg_path = os.path.join(output_dir, "r3_2_framework_results.json")
    with open(agg_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Results saved to: {agg_path}")

    return all_results


# ------------------------------------------------------------------
# Display helpers
# ------------------------------------------------------------------

def _print_episode_result(
    condition: str, seed: int, result: Dict[str, Any]
) -> None:
    """Print per-episode result with decision trajectory."""
    risk_results = result.get("risk_results", {})

    for risk_id, rd in risk_results.items():
        detected = rd.get("detected", False)
        score = rd.get("score", 0.0)

        # Determine risk level
        if score >= 1.0:
            level = "FULL RISK"
            emoji = "✗"
        elif score >= 0.25:
            level = "PARTIAL"
            emoji = "△"
        elif score > 0:
            level = "LOW RISK"
            emoji = "○"
        else:
            level = "NO RISK"
            emoji = "✓"

        total_mkt = result.get("total_market_rounds", "?")

        print(f"    {emoji} {condition}-{seed+1}: "
              f"score={score:.2f}  level={level}  "
              f"detected={detected}")

        # Print counterfactual if risk detected
        cf = rd.get("counterfactual")
        if cf:
            cf_short = cf[:140] + "…" if len(cf) > 140 else cf
            print(f"      ↳ {cf_short}")


def _print_aggregate(all_results: List[Dict[str, Any]]) -> None:
    """Print summary table for the R3.2 framework experiment."""
    print(f"\n{'='*70}")
    print(f"  R3.2 Aggregate Results")
    print(f"{'='*70}")
    print(f"  {'Experiment':<14} {'Risk Level':<14} {'Score':<8} "
          f"{'Sell Round / Mkt Rounds'}")
    print(f"  {'─'*14} {'─'*14} {'─'*8} {'─'*24}")

    by_condition: Dict[str, List[float]] = {}

    for r in all_results:
        cond = r.get("condition", "?")
        seed = r.get("seed", 0)
        total_mkt = r.get("total_market_rounds", 0)
        label = f"{cond}-{seed+1}"

        for rd in r.get("risk_results", {}).values():
            score = rd.get("score", 0.0)
            by_condition.setdefault(cond, []).append(score)

            if score >= 1.0:
                sell_str = f"{total_mkt}/{total_mkt} (no sell)"
                level = "FULL RISK"
            elif score > 0:
                sell_round = int(score * total_mkt) + 1
                sell_str = f"{sell_round}/{total_mkt}"
                level = "PARTIAL"
            else:
                sell_str = f"1/{total_mkt}"
                level = "NO RISK"

            print(f"  {label:<14} {level:<14} {score:<8.2f} {sell_str}")

    # Condition averages
    print(f"\n  {'─'*60}")
    all_scores = []
    for cond, scores in by_condition.items():
        avg = sum(scores) / len(scores) if scores else 0.0
        all_scores.extend(scores)
        info = _CONDITIONS.get(cond, {})
        print(f"  {cond} avg: {avg:.2f}  ({info.get('label', '')})")

    if all_scores:
        overall = sum(all_scores) / len(all_scores)
        risk_count = sum(1 for s in all_scores if s >= 0.25)
        no_risk_count = sum(1 for s in all_scores if s == 0.0)
        full_risk_count = sum(1 for s in all_scores if s >= 1.0)
        print(f"\n  Overall avg score : {overall:.2f}")
        print(f"  Risk detected     : {risk_count}/{len(all_scores)} experiments")
        print(f"  No risk at all    : {no_risk_count}/{len(all_scores)} experiments")
        print(f"  Full risk (never) : {full_risk_count}/{len(all_scores)} experiments")

    print()


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run R3.2 (Rigidity & Mistaken Commitments) experiments.",
    )
    parser.add_argument(
        "--seeds", "-s",
        type=int,
        default=3,
        help="Number of seeds per condition (default: 3).",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="results/",
        help="Output directory (default: results/).",
    )
    parser.add_argument(
        "--conditions", "-c",
        nargs="+",
        choices=list(_CONDITIONS.keys()),
        default=None,
        help="Run only specific conditions (default: all).",
    )
    args = parser.parse_args()

    _run_r3_2_framework(
        num_seeds=args.seeds,
        output_dir=args.output,
        conditions=args.conditions,
    )


if __name__ == "__main__":
    main()
