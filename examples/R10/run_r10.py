#!/usr/bin/env python3
"""
Run R10 (Normative Deadlock) experiments using the RiskLab framework.

Usage
-----
    # Navigate to the examples/R10 directory first
    cd examples/R10

    # Run with default settings (condition from config):
    python run_r10.py

    # Run E1 (no mediation) condition:
    python run_r10.py --condition e1

    # Run E2 (with mediation) condition:
    python run_r10.py --condition e2

    # Customize seeds and output:
    python run_r10.py --condition e2 --seeds 5 --output results/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

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
from risklab.risks.normative_deadlock import NormativeDeadlockRisk


_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "configs")
_CONFIG_FILE = "r10_normative_deadlock.yaml"


# ------------------------------------------------------------------
# Config preprocessing
# ------------------------------------------------------------------

def _apply_condition(
    config: Dict[str, Any],
    condition: str,
) -> Dict[str, Any]:
    """Apply experiment condition (e1/e2) to the config.

    Replaces the summary_agent's system_prompt with the appropriate
    prompt template based on the condition.
    """
    # Get the prompt templates
    prompts = config.get("summary_agent_prompts", {})
    prompt = prompts.get(condition)

    if not prompt:
        print(f"  Warning: No prompt found for condition '{condition}', using e1")
        prompt = prompts.get("e1", "")

    # Find and update summary_agent's prompt
    agents = config.get("agents", [])
    for agent in agents:
        if agent.get("agent_id") == "summary_agent":
            agent["system_prompt"] = prompt
            break

    return config


def _get_condition(config: Dict[str, Any], cli_condition: Optional[str]) -> str:
    """Determine the experiment condition.

    Priority: CLI argument > config file > default (e1)
    """
    if cli_condition:
        return cli_condition

    exp_config = config.get("experiment", {})
    return exp_config.get("condition", "e1")


# ------------------------------------------------------------------
# Main logic
# ------------------------------------------------------------------

def _run_r10(
    condition: Optional[str] = None,
    num_seeds: int = 3,
    output_dir: str = "results/",
) -> List[Dict[str, Any]]:
    """Run R10 Normative Deadlock experiment."""
    config_path = os.path.join(_CONFIG_DIR, _CONFIG_FILE)

    if not os.path.isfile(config_path):
        print(f"  ✗ Config not found: {config_path}")
        return []

    # Load raw config
    raw_config = load_experiment_config(config_path)

    # Determine condition
    effective_condition = _get_condition(raw_config, condition)

    print(f"\n{'='*70}")
    print(f"  R10  Normative Deadlock — Multi-Cultural Negotiation")
    print(f"  Config    : {_CONFIG_FILE}")
    print(f"  Condition : {effective_condition.upper()} ({'no mediation' if effective_condition == 'e1' else 'with mediation'})")
    print(f"  Seeds     : {num_seeds}")
    print(f"  Max Rounds: 10 per seed")
    print(f"{'='*70}")

    all_results: List[Dict[str, Any]] = []

    for seed in range(num_seeds):
        print(f"\n── Experiment {seed + 1}/{num_seeds} (Seed {seed}) ─────────────────────")

        try:
            # Reload config fresh for each seed
            raw_config = load_experiment_config(config_path)

            # Apply condition to config
            raw_config = _apply_condition(raw_config, effective_condition)

            # Build experiment components
            components = build_experiment_from_config(
                raw_config,
                base_dir=_PROJECT_ROOT,
            )
            components["output_dir"] = output_dir

            # Construct runner
            runner = ExperimentRunner(
                experiment_id=f"{components['experiment_id']}_{effective_condition}_seed{seed}",
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

            # Annotate with metadata
            for r in results:
                r["seed"] = seed
                r["condition"] = effective_condition

                # Get detailed metrics from risk detector
                for risk in runner.risks:
                    if isinstance(risk, NormativeDeadlockRisk):
                        trajectory = runner.logger.get_trajectory()
                        traj_list = trajectory.to_list()
                        detailed = risk.compute_detailed_metrics(traj_list)
                        r["detailed_metrics"] = detailed
                        r["outcome"] = risk.classify_outcome(traj_list)

                _print_experiment_result(seed, effective_condition, r)

            all_results.extend(results)

        except Exception as e:
            print(f"  ✗ Experiment {seed} failed: {e}")
            import traceback
            traceback.print_exc()
            all_results.append({
                "seed": seed,
                "condition": effective_condition,
                "error": str(e),
                "risk_results": {},
            })

    # Print aggregate summary
    _print_aggregate(all_results, effective_condition)

    # Save results
    os.makedirs(output_dir, exist_ok=True)
    agg_path = os.path.join(output_dir, f"r10_{effective_condition}_results.json")
    with open(agg_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Results saved to: {agg_path}")

    return all_results


def _print_experiment_result(
    seed: int,
    condition: str,
    result: Dict[str, Any],
) -> None:
    """Print result for one experiment."""
    detailed = result.get("detailed_metrics", {})
    outcome = result.get("outcome", "unknown")

    max_score = detailed.get("max_score", 0.0)
    final_score = detailed.get("final_score", 0.0)
    converged = detailed.get("converged", False)
    total_rounds = detailed.get("total_rounds", 0)

    emoji = "✓" if converged else "⚠"
    outcome_str = outcome.upper().replace("_", " ")

    print(
        f"  {emoji} [Seed {seed}] {outcome_str}  "
        f"max_score={max_score:.1f}  final={final_score:.1f}  "
        f"rounds={total_rounds}"
    )

    # Print per-round convergence scores
    scores = detailed.get("convergence_scores", [])
    if scores:
        scores_str = " -> ".join(f"{s:.1f}" for s in scores)
        print(f"      ↳ Scores by round: {scores_str}")

    # Print convergence round if achieved
    conv_round = detailed.get("convergence_round")
    if conv_round:
        print(f"      ↳ Convergence reached at round {conv_round}")

    # Print hard conflicts if any
    conflicts = detailed.get("hard_conflicts", [])
    if conflicts and not converged:
        print(f"      ↳ Unresolved conflicts: {len(conflicts)}")
        for c in conflicts[:2]:  # Show first 2
            if len(c) > 80:
                c = c[:80] + "..."
            print(f"        - {c}")


def _print_aggregate(
    all_results: List[Dict[str, Any]],
    condition: str,
) -> None:
    """Print a summary table across all experiments."""
    print(f"\n{'='*70}")
    print(f"  R10 Aggregate Results — Condition: {condition.upper()}")
    print(f"{'='*70}")

    # Collect statistics
    total_experiments = len(all_results)
    convergence_count = 0
    all_max_scores = []
    all_rounds = []
    outcomes = {"convergence": 0, "near_convergence": 0, "partial_progress": 0, "deadlock": 0}

    for r in all_results:
        if "error" in r:
            continue

        detailed = r.get("detailed_metrics", {})
        max_score = detailed.get("max_score", 0.0)
        all_max_scores.append(max_score)

        if detailed.get("converged"):
            convergence_count += 1
            conv_round = detailed.get("convergence_round", 0)
            if conv_round:
                all_rounds.append(conv_round)

        outcome = r.get("outcome", "deadlock")
        if outcome in outcomes:
            outcomes[outcome] += 1

    # Print summary
    valid_count = len(all_max_scores)
    if valid_count > 0:
        avg_max_score = sum(all_max_scores) / valid_count
        convergence_rate = convergence_count / valid_count * 100

        print(f"\n  Convergence rate: {convergence_count}/{valid_count} ({convergence_rate:.0f}%)")
        print(f"  Average max score: {avg_max_score:.2f}/10")

        if all_rounds:
            avg_rounds = sum(all_rounds) / len(all_rounds)
            print(f"  Average rounds to convergence: {avg_rounds:.1f}")

        print(f"\n  Outcome distribution:")
        for outcome, count in outcomes.items():
            pct = count / valid_count * 100 if valid_count else 0
            bar = "█" * int(pct / 5)
            print(f"    {outcome:18s}: {count:2d} ({pct:5.1f}%) {bar}")

    # Per-seed breakdown
    print(f"\n  Per-Experiment Breakdown:")
    print(f"  {'Seed':<6} {'MaxScore':<10} {'Final':<8} {'Rounds':<8} {'Outcome':<18} {'Converged':<10}")
    print(f"  {'-'*60}")

    for r in all_results:
        seed = r.get("seed", "?")
        if "error" in r:
            print(f"  {seed:<6} {'ERROR':<10}")
            continue

        detailed = r.get("detailed_metrics", {})
        max_score = detailed.get("max_score", 0.0)
        final_score = detailed.get("final_score", 0.0)
        total_rounds = detailed.get("total_rounds", 0)
        outcome = r.get("outcome", "unknown")
        converged = "Yes" if detailed.get("converged") else "No"

        print(
            f"  {seed:<6} {max_score:<10.1f} {final_score:<8.1f} "
            f"{total_rounds:<8} {outcome:<18} {converged:<10}"
        )

    print()


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run R10 (Normative Deadlock) experiments.",
    )
    parser.add_argument(
        "--condition", "-c",
        type=str,
        choices=["e1", "e2"],
        default=None,
        help="Experiment condition: e1 (no mediation) or e2 (with mediation). "
             "If not specified, uses value from config file.",
    )
    parser.add_argument(
        "--seeds", "-s",
        type=int,
        default=3,
        help="Number of experiment repetitions (default: 3).",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="results/",
        help="Output directory for results (default: results/).",
    )
    args = parser.parse_args()

    _run_r10(
        condition=args.condition,
        num_seeds=args.seeds,
        output_dir=args.output,
    )


if __name__ == "__main__":
    main()
