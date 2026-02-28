#!/usr/bin/env python3
"""
Run R2 (Tacit Collusion) experiments using the RiskLab framework.

Usage
-----
    # Navigate to the examples/R2 directory first
    cd examples/R2
    
    # Run a single condition (C1 / C2 / C3):
    python run_r2.py --condition C1

    # Run all three conditions:
    python run_r2.py --all

    # Customize seeds and output directory:
    python run_r2.py --all --seeds 3 --output results/
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


# ------------------------------------------------------------------
# Verbose round printer
# ------------------------------------------------------------------

def _make_round_printer(total_rounds: int):
    """Return a callback that pretty-prints each round to the terminal."""

    def _print_round(info: Dict[str, Any]) -> None:
        rnd = info.get("round", 0) + 1          # 0-indexed → 1-indexed
        prices = info.get("prices", {})
        speeches = info.get("speeches", {})
        winners = info.get("winners", [])
        market_price = info.get("market_price", 0)
        customers = info.get("customers_per_winner", 0)
        profits = info.get("round_profits", {})
        cum_profits = info.get("cumulative_profits", {})

        W = 68
        print(f"\n{'═' * W}")
        header = f"Round {rnd} / {total_rounds}"
        print(f"{'':>2}{header:^{W - 4}}")
        print(f"{'─' * W}")

        for aid in sorted(prices.keys()):
            p = prices[aid]
            s = speeches.get(aid, "")
            if len(s) > 38:
                s = s[:35] + "..."
            tag = ">>" if aid in winners else "  "
            print(f"  {tag} {aid:<12}  Price: {p:<5} \"{s}\"")

        print(f"{'─' * W}")
        winner_str = ", ".join(winners)
        print(f"  Market Price: {market_price}  |  Winner: {winner_str}  |  {customers} customers each")
        prof_parts = [f"{aid}: {profits.get(aid, 0):.0f}" for aid in sorted(prices.keys())]
        print(f"  Round Profit   {' | '.join(prof_parts)}")
        cum_parts = [f"{aid}: {cum_profits.get(aid, 0):.0f}" for aid in sorted(prices.keys())]
        print(f"  Cumul. Profit  {' | '.join(cum_parts)}")
        print(f"{'═' * W}")

    return _print_round


# Map condition codes → config file names
_CONDITIONS = {
    "C1": "r2_C1_basic.yaml",
    "C2": "r2_C2_strategy.yaml",
    "C3": "r2_C3_persona.yaml",
}

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "configs")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _run_condition(
    condition: str,
    num_seeds: int = 2,
    output_dir: str = "results/",
    verbose: bool = False,
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

    # Verbose callback
    round_callback = None
    if verbose:
        env = components["environment"]
        total = getattr(env, "max_rounds", 10)
        round_callback = _make_round_printer(total)

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
        on_round_callback=round_callback,
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
        choices=["C1", "C2", "C3"],
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
        default="results/",
        help="Output directory for results (default: results/).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print each round's prices, speeches and results.",
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
            results = _run_condition(cond, num_seeds=args.seeds, output_dir=args.output, verbose=args.verbose)
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
