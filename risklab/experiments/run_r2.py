#!/usr/bin/env python3
"""
Run R2 (Tacit Collusion) experiments using the RiskLab framework.

Usage
-----
    # Run a single condition (E1 / E2 / E3):
    python -m risklab.experiments.run_r2 --condition E1

    # Run all three conditions:
    python -m risklab.experiments.run_r2 --all

    # Customize seeds and output directory:
    python -m risklab.experiments.run_r2 --all --seeds 3 --output results/r2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

# Ensure the project root is importable
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from risklab.experiments.config_loader import (
    build_experiment_from_config,
    load_experiment_config,
)
from risklab.experiments.runner import ExperimentRunner


# Map condition codes → config file names
_CONDITIONS = {
    "E1": "r2_E1_basic.yaml",
    "E2": "r2_E2_strategy.yaml",
    "E3": "r2_E3_persona.yaml",
}

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "configs")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _run_condition(
    condition: str,
    num_seeds: int = 2,
    output_dir: str = "results/r2",
) -> List[Dict[str, Any]]:
    """Run a single condition and return results."""
    config_file = _CONDITIONS[condition]
    config_path = os.path.join(_CONFIG_DIR, config_file)

    if not os.path.isfile(config_path):
        print(f"  ✗ Config not found: {config_path}")
        return []

    print(f"\n{'='*60}")
    print(f"  Condition {condition}  ({config_file})")
    print(f"  Seeds: {num_seeds}")
    print(f"{'='*60}")

    # Load and build
    raw_config = load_experiment_config(config_path)
    components = build_experiment_from_config(
        raw_config,
        base_dir=_PROJECT_ROOT,
    )

    # Override output directory
    components["output_dir"] = output_dir

    # Construct runner
    runner = ExperimentRunner(
        experiment_id=components["experiment_id"],
        environment=components["environment"],
        protocol=components["protocol"],
        agents=components["agents"],
        task=components.get("task"),
        topology=components.get("topology"),
        flow=components.get("flow"),
        risks=components.get("risks", []),
        output_dir=components["output_dir"],
    )

    # Execute
    results = runner.run(num_seeds=num_seeds)

    # Summarise
    _print_summary(condition, results)
    return results


def _print_summary(condition: str, results: List[Dict[str, Any]]) -> None:
    """Print a human-readable summary for one condition."""
    print(f"\n  ── Condition {condition} summary ──")

    for r in results:
        seed = r.get("seed", "?")
        rounds = r.get("num_rounds", 0)
        risk = r.get("risk_results", {})

        print(f"  Seed {seed}: {rounds} rounds logged")

        for risk_id, rd in risk.items():
            detected = rd.get("detected", False)
            score = rd.get("score", 0.0)
            emoji = "⚠" if detected else "✓"
            print(
                f"    {emoji} {risk_id}: detected={detected}, "
                f"score={score:.4f}"
            )
            if rd.get("counterfactual"):
                print(f"      ↳ {rd['counterfactual']}")

    print()


def _print_aggregate(all_results: Dict[str, List[Dict]]) -> None:
    """Print a cross-condition comparison table."""
    print("\n" + "="*60)
    print("  Aggregate comparison across conditions")
    print("="*60)

    for condition, results in all_results.items():
        if not results:
            continue
        scores = []
        detected_count = 0
        for r in results:
            for rd in r.get("risk_results", {}).values():
                scores.append(rd.get("score", 0.0))
                if rd.get("detected"):
                    detected_count += 1

        avg_score = sum(scores) / len(scores) if scores else 0.0
        print(
            f"  {condition}: avg_score={avg_score:.4f}, "
            f"detected={detected_count}/{len(results)} seeds"
        )

    print()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run R2 (Tacit Collusion) experiments.",
    )
    parser.add_argument(
        "--condition", "-c",
        choices=["E1", "E2", "E3"],
        help="Run a specific condition.",
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Run all three conditions.",
    )
    parser.add_argument(
        "--seeds", "-s",
        type=int,
        default=2,
        help="Number of seeds per condition (default: 2).",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="results/r2",
        help="Output directory for results (default: results/r2).",
    )
    args = parser.parse_args()

    if not args.condition and not args.all:
        parser.print_help()
        print("\nError: specify --condition or --all.")
        sys.exit(1)

    conditions = list(_CONDITIONS.keys()) if args.all else [args.condition]

    all_results: Dict[str, List[Dict]] = {}
    for cond in conditions:
        try:
            results = _run_condition(cond, num_seeds=args.seeds, output_dir=args.output)
            all_results[cond] = results
        except Exception as e:
            print(f"  ✗ Condition {cond} failed: {e}")
            import traceback
            traceback.print_exc()
            all_results[cond] = []

    if len(all_results) > 1:
        _print_aggregate(all_results)

    # Save aggregate JSON
    os.makedirs(args.output, exist_ok=True)
    agg_path = os.path.join(args.output, "r2_aggregate_results.json")
    with open(agg_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"  Aggregate results saved to {agg_path}")


if __name__ == "__main__":
    main()
