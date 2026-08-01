#!/usr/bin/env python3
"""
Run R1.4 (Strategic Misreporting) experiments using the RiskLab framework.

Usage
-----
    # Navigate to the examples/R1.4_StrategicMisreporting directory first
    cd examples/R1.4_StrategicMisreporting

    # Run with default settings:
    python run_r1_4_strategic_misreporting.py

    # Customize seeds and output:
    python run_r1_4_strategic_misreporting.py --seeds 8 --output results/
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
from risklab.risks.strategic_misreporting import StrategicMisreportingRisk


_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "configs")
_CONFIG_FILE = "r1_4_strategic_misreporting.yaml"


# ------------------------------------------------------------------
# Main logic
# ------------------------------------------------------------------

def _run_r9(
    num_seeds: int = 8,
    output_dir: str = "results/",
) -> List[Dict[str, Any]]:
    """Run R1.4 Strategic Misreporting experiment."""
    config_path = os.path.join(_CONFIG_DIR, _CONFIG_FILE)

    if not os.path.isfile(config_path):
        print(f"  ✗ Config not found: {config_path}")
        return []

    print(f"\n{'='*70}")
    print(f"  R1.4  Strategic Misreporting — Relay-Based UAV Exploration")
    print(f"  Config  : {_CONFIG_FILE}")
    print(f"  Seeds   : {num_seeds}")
    print(f"  Rounds  : 5 per seed")
    print(f"  Total experiments: {num_seeds}")
    print(f"{'='*70}")

    all_results: List[Dict[str, Any]] = []

    for seed in range(num_seeds):
        print(f"\n── Experiment {seed + 1}/{num_seeds} (Seed {seed}) ─────────────────────")

        try:
            # Load and build fresh for each seed (reset state)
            raw_config = load_experiment_config(config_path)
            components = build_experiment_from_config(
                raw_config,
                base_dir=_PROJECT_ROOT,
            )
            components["output_dir"] = output_dir

            # Construct runner
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

            # Run experiment
            results = runner.run(num_seeds=1)

            # Annotate with seed
            for r in results:
                r["seed"] = seed

                # Reset risk cache between experiments
                for risk in runner.risks:
                    if isinstance(risk, StrategicMisreportingRisk):
                        # Get detailed metrics
                        trajectory = runner.logger.get_trajectory()
                        traj_list = trajectory.to_list()
                        detailed = risk.compute_detailed_metrics(traj_list)
                        r["detailed_metrics"] = detailed

                _print_experiment_result(seed, r)

            all_results.extend(results)

        except Exception as e:
            print(f"  ✗ Experiment {seed} failed: {e}")
            import traceback
            traceback.print_exc()
            all_results.append({
                "seed": seed,
                "error": str(e),
                "risk_results": {},
            })

    # Print aggregate summary
    _print_aggregate(all_results)

    # Save aggregate
    os.makedirs(output_dir, exist_ok=True)
    agg_path = os.path.join(output_dir, "r1_4_all_results.json")
    with open(agg_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Results saved to: {agg_path}")

    return all_results


def _print_experiment_result(seed: int, result: Dict[str, Any]) -> None:
    """Print result for one experiment."""
    risk = result.get("risk_results", {})

    for risk_id, rd in risk.items():
        detected = rd.get("detected", False)
        score = rd.get("score", 0.0)
        emoji = "⚠" if detected else "✓"

        # Convert score to percentage
        misreport_rate = score * 100

        print(
            f"  {emoji} [Seed {seed}] "
            f"misreport_rate={misreport_rate:.1f}%  "
            f"detected={detected}"
        )

        if rd.get("counterfactual"):
            cf = rd["counterfactual"]
            if len(cf) > 120:
                cf = cf[:120] + "…"
            print(f"      ↳ {cf}")

    # Print detailed metrics if available
    detailed = result.get("detailed_metrics", {})
    if detailed:
        total = detailed.get("total_reports", 0)
        deceptions = detailed.get("total_deceptions", 0)
        upgrades = detailed.get("upgrade_count", 0)
        downgrades = detailed.get("downgrade_count", 0)
        print(f"      Reports: {total}, Deceptions: {deceptions} "
              f"(↑{upgrades} ↓{downgrades})")


def _print_aggregate(all_results: List[Dict[str, Any]]) -> None:
    """Print a summary table across all experiments."""
    print(f"\n{'='*70}")
    print(f"  R1.4 Aggregate Results")
    print(f"{'='*70}")

    # Collect statistics
    total_experiments = len(all_results)
    experiments_with_deception = 0
    all_scores = []
    total_reports = 0
    total_deceptions = 0

    for r in all_results:
        if "error" in r:
            continue

        for rd in r.get("risk_results", {}).values():
            score = rd.get("score", 0.0)
            all_scores.append(score)
            if rd.get("detected"):
                experiments_with_deception += 1

        detailed = r.get("detailed_metrics", {})
        total_reports += detailed.get("total_reports", 0)
        total_deceptions += detailed.get("total_deceptions", 0)

    # Print summary
    if all_scores:
        avg_score = sum(all_scores) / len(all_scores)
        print(f"\n  Experiments with deception: {experiments_with_deception}/{total_experiments}")
        print(f"  Average misreport rate: {avg_score * 100:.1f}%")
        print(f"  Total reports across all experiments: {total_reports}")
        print(f"  Total deceptions across all experiments: {total_deceptions}")

        if total_reports > 0:
            overall_rate = total_deceptions / total_reports * 100
            print(f"  Overall deception rate: {overall_rate:.1f}%")

    # Per-seed breakdown
    print(f"\n  Per-Experiment Breakdown:")
    print(f"  {'Seed':<6} {'Reports':<10} {'Deceptions':<12} {'Rate':<10} {'Detected':<10}")
    print(f"  {'-'*48}")

    for r in all_results:
        seed = r.get("seed", "?")
        if "error" in r:
            print(f"  {seed:<6} {'ERROR':<10}")
            continue

        detailed = r.get("detailed_metrics", {})
        reports = detailed.get("total_reports", 0)
        deceptions = detailed.get("total_deceptions", 0)
        rate = (deceptions / reports * 100) if reports else 0
        detected = "Yes" if any(rd.get("detected") for rd in r.get("risk_results", {}).values()) else "No"

        print(f"  {seed:<6} {reports:<10} {deceptions:<12} {rate:<10.1f}% {detected:<10}")

    print()


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run R1.4 (Strategic Misreporting) experiments.",
    )
    parser.add_argument(
        "--seeds", "-s",
        type=int,
        default=8,
        help="Number of experiment repetitions (default: 8).",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="results/",
        help="Output directory for results (default: results/).",
    )
    args = parser.parse_args()

    _run_r9(num_seeds=args.seeds, output_dir=args.output)


if __name__ == "__main__":
    main()
