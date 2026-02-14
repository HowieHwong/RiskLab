#!/usr/bin/env python3
"""
Run R11 (Majority Sway and Conformity Cascades) experiments using the RiskLab framework.

Usage
-----
    # Navigate to the examples/R11 directory first
    cd examples/R11

    # Run Scenario 1 - News Verification (Experiment I):
    python run_r11.py --scenario 1 --seeds 10

    # Run Scenario 2 - Remediation Debate (Experiment II):
    python run_r11.py --scenario 2 --condition e1 --seeds 4

    # Run all conditions for Scenario 2:
    python run_r11.py --scenario 2 --condition all --seeds 4

Scenarios:
    1 (news): Fast agents (majority) vs Deep agents (minority) debate news veracity
    2 (debate): Analytics (majority) vs Engineers (minority) debate remediation plan

Experiment Conditions (for Scenario 2):
    E1: majority=Analytics(7), moderator_initial=Bedrock
    E2: majority=Engineer(7), moderator_initial=Bedrock
    E3: majority=Analytics(7), moderator_initial=Scalpel
    E4: majority=Engineer(7), moderator_initial=Scalpel
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
from risklab.risks.majority_sway import MajoritySwayRisk


_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "configs")
_NEWS_CONFIG_FILE = "r11_news_verification.yaml"
_DEBATE_CONFIG_FILE = "r11_remediation_debate.yaml"


# ------------------------------------------------------------------
# Config preprocessing for debate conditions
# ------------------------------------------------------------------

def _apply_debate_condition(
    config: Dict[str, Any],
    condition: str,
) -> Dict[str, Any]:
    """Apply experiment condition (e1/e2/e3/e4) to the debate config.

    E1: majority=Analytics(7), moderator_initial=Bedrock
    E2: majority=Engineer(7), moderator_initial=Bedrock
    E3: majority=Analytics(7), moderator_initial=Scalpel
    E4: majority=Engineer(7), moderator_initial=Scalpel
    """
    # Get the prompt templates
    prompts = config.get("moderator_prompts", {})

    # Determine moderator prompt based on condition
    if condition in ("e1", "e2"):
        moderator_prompt = prompts.get("initial_bedrock", "")
    else:  # e3, e4
        moderator_prompt = prompts.get("initial_scalpel", "")

    # Find and update moderator's prompt
    agents = config.get("agents", [])
    for agent in agents:
        if agent.get("agent_id") == "moderator":
            agent["system_prompt"] = moderator_prompt
            break

    # For E2 and E4, swap the majority (Engineer becomes majority with 7 agents)
    if condition in ("e2", "e4"):
        config = _swap_majority(config)

    return config


def _swap_majority(config: Dict[str, Any]) -> Dict[str, Any]:
    """Swap Analytics and Engineer agent counts (7 <-> 3).

    For E2/E4 conditions, Engineer agents become the majority.
    """
    env_params = config.get("environment", {}).get("parameters", {})

    # Swap the agent lists
    analytics = env_params.get("analytics_agents", [])
    engineers = env_params.get("engineer_agents", [])

    # Create new agent IDs with swapped counts
    # Engineers become majority (7), Analytics become minority (3)
    new_engineers = [f"engineer_{i}" for i in range(1, 8)]  # 7 engineers
    new_analytics = [f"analytics_{i}" for i in range(1, 4)]  # 3 analytics

    env_params["analytics_agents"] = new_analytics
    env_params["engineer_agents"] = new_engineers

    # Update topology
    _update_topology_for_swap(config, new_analytics, new_engineers)

    # Update agents list
    _update_agents_for_swap(config, new_analytics, new_engineers)

    return config


def _update_topology_for_swap(
    config: Dict[str, Any],
    analytics_ids: List[str],
    engineer_ids: List[str],
) -> None:
    """Update topology edges and flow for swapped agent counts."""
    topology = config.get("topology", {})

    # Update agents list
    all_agents = analytics_ids + engineer_ids + ["moderator"]
    topology["agents"] = all_agents

    # Rebuild edges
    edges = []
    # Analytics broadcast to engineers
    for a in analytics_ids:
        for e in engineer_ids:
            edges.append([a, e])
    # Engineers broadcast to analytics
    for e in engineer_ids:
        for a in analytics_ids:
            edges.append([e, a])
    # All agents send to moderator
    for agent in analytics_ids + engineer_ids:
        edges.append([agent, "moderator"])
    # Moderator broadcasts back to all
    for agent in analytics_ids + engineer_ids:
        edges.append(["moderator", agent])

    topology["edges"] = edges

    # Update flow
    flow = topology.get("flow", {})
    flow["entry_nodes"] = analytics_ids + engineer_ids
    flow["flow_order"] = [analytics_ids + engineer_ids, "moderator"]

    topology["flow"] = flow


def _update_agents_for_swap(
    config: Dict[str, Any],
    analytics_ids: List[str],
    engineer_ids: List[str],
) -> None:
    """Update agents list for swapped agent counts."""
    agents = config.get("agents", [])

    # Find template prompts
    analytics_prompt = None
    engineer_prompt = None
    moderator_config = None

    for agent in agents:
        if agent.get("agent_id", "").startswith("analytics_"):
            analytics_prompt = agent.get("system_prompt")
        elif agent.get("agent_id", "").startswith("engineer_"):
            engineer_prompt = agent.get("system_prompt")
        elif agent.get("agent_id") == "moderator":
            moderator_config = agent

    # Rebuild agents list
    new_agents = []

    # Add analytics agents (minority in E2/E4)
    for aid in analytics_ids:
        new_agents.append({
            "agent_id": aid,
            "role": "data_analytics",
            "model": "gpt-4o",
            "objective": "advocate_bedrock",
            "temperature": 0.7,
            "max_tokens": 1024,
            "system_prompt": analytics_prompt,
        })

    # Add engineer agents (majority in E2/E4)
    for eid in engineer_ids:
        new_agents.append({
            "agent_id": eid,
            "role": "system_engineer",
            "model": "gpt-4o",
            "objective": "advocate_scalpel",
            "temperature": 0.7,
            "max_tokens": 1024,
            "system_prompt": engineer_prompt,
        })

    # Add moderator
    if moderator_config:
        new_agents.append(moderator_config)

    config["agents"] = new_agents


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

def _run_news_experiment(
    num_seeds: int = 10,
    output_dir: str = "results/",
) -> List[Dict[str, Any]]:
    """Run R11 News Verification experiment (Experiment I)."""
    config_path = os.path.join(_CONFIG_DIR, _NEWS_CONFIG_FILE)

    if not os.path.isfile(config_path):
        print(f"  ✗ Config not found: {config_path}")
        return []

    print(f"\n{'='*70}")
    print(f"  R11  Majority Sway — News Verification")
    print(f"  Config    : {_NEWS_CONFIG_FILE}")
    print(f"  Seeds     : {num_seeds}")
    print(f"  Max Rounds: 5 per seed")
    print(f"  Ground Truth: FAKE")
    print(f"{'='*70}")

    all_results: List[Dict[str, Any]] = []

    for seed in range(num_seeds):
        print(f"\n── Experiment {seed + 1}/{num_seeds} (Seed {seed}) ─────────────────────")

        try:
            # Reload config fresh for each seed
            raw_config = load_experiment_config(config_path)

            # Build experiment components
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

            # Annotate with metadata
            for r in results:
                r["seed"] = seed
                r["scenario"] = 1

                # Get detailed metrics from risk detector
                for risk in runner.risks:
                    if isinstance(risk, MajoritySwayRisk):
                        trajectory = runner.logger.get_trajectory()
                        traj_list = trajectory.to_list()
                        detailed = risk.compute_detailed_metrics(traj_list)
                        r["detailed_metrics"] = detailed
                        r["outcome"] = risk.classify_outcome(traj_list)

                _print_news_result(seed, r)

            all_results.extend(results)

        except Exception as e:
            print(f"  ✗ Experiment {seed} failed: {e}")
            import traceback
            traceback.print_exc()
            all_results.append({
                "seed": seed,
                "scenario": 1,
                "error": str(e),
                "risk_results": {},
            })

    # Print aggregate summary
    _print_news_aggregate(all_results)

    # Save results
    os.makedirs(output_dir, exist_ok=True)
    agg_path = os.path.join(output_dir, "r11_news_results.json")
    with open(agg_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Results saved to: {agg_path}")

    return all_results


def _run_debate_experiment(
    condition: str = "e1",
    num_seeds: int = 4,
    output_dir: str = "results/",
) -> List[Dict[str, Any]]:
    """Run R11 Remediation Debate experiment (Experiment II)."""
    config_path = os.path.join(_CONFIG_DIR, _DEBATE_CONFIG_FILE)

    if not os.path.isfile(config_path):
        print(f"  ✗ Config not found: {config_path}")
        return []

    # Determine majority and initial stance based on condition
    condition_info = {
        "e1": ("Analytics(7)", "Bedrock"),
        "e2": ("Engineer(7)", "Bedrock"),
        "e3": ("Analytics(7)", "Scalpel"),
        "e4": ("Engineer(7)", "Scalpel"),
    }
    majority, initial = condition_info.get(condition, ("Analytics(7)", "Bedrock"))

    print(f"\n{'='*70}")
    print(f"  R11  Majority Sway — Remediation Debate")
    print(f"  Config    : {_DEBATE_CONFIG_FILE}")
    print(f"  Condition : {condition.upper()}")
    print(f"  Majority  : {majority}")
    print(f"  Initial   : {initial}")
    print(f"  Seeds     : {num_seeds}")
    print(f"  Max Rounds: 5 per seed")
    print(f"  Ground Truth: SCALPEL")
    print(f"{'='*70}")

    all_results: List[Dict[str, Any]] = []

    for seed in range(num_seeds):
        print(f"\n── Experiment {seed + 1}/{num_seeds} (Seed {seed}) ─────────────────────")

        try:
            # Reload config fresh for each seed
            raw_config = load_experiment_config(config_path)

            # Apply condition to config
            raw_config = _apply_debate_condition(raw_config, condition)

            # Build experiment components
            components = build_experiment_from_config(
                raw_config,
                base_dir=_PROJECT_ROOT,
            )
            components["output_dir"] = output_dir

            # Construct runner
            runner = ExperimentRunner(
                experiment_id=f"{components['experiment_id']}_{condition}_seed{seed}",
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
                r["condition"] = condition
                r["scenario"] = 2

                # Get detailed metrics from risk detector
                for risk in runner.risks:
                    if isinstance(risk, MajoritySwayRisk):
                        trajectory = runner.logger.get_trajectory()
                        traj_list = trajectory.to_list()
                        detailed = risk.compute_detailed_metrics(traj_list)
                        r["detailed_metrics"] = detailed
                        r["outcome"] = risk.classify_outcome(traj_list)

                _print_debate_result(seed, condition, r)

            all_results.extend(results)

        except Exception as e:
            print(f"  ✗ Experiment {seed} failed: {e}")
            import traceback
            traceback.print_exc()
            all_results.append({
                "seed": seed,
                "condition": condition,
                "scenario": 2,
                "error": str(e),
                "risk_results": {},
            })

    # Print aggregate summary
    _print_debate_aggregate(all_results, condition)

    # Save results
    os.makedirs(output_dir, exist_ok=True)
    agg_path = os.path.join(output_dir, f"r11_debate_{condition}_results.json")
    with open(agg_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Results saved to: {agg_path}")

    return all_results


def _print_news_result(seed: int, result: Dict[str, Any]) -> None:
    """Print result for one news experiment."""
    detailed = result.get("detailed_metrics", {})
    outcome = result.get("outcome", "unknown")

    final_decision = detailed.get("final_decision", "unknown")
    ground_truth = detailed.get("ground_truth", "fake")
    error_rate = detailed.get("error_rate", 0.0)
    correct = final_decision == ground_truth

    emoji = "✓" if correct else "✗"
    outcome_str = outcome.upper().replace("_", " ")

    print(
        f"  {emoji} [Seed {seed}] {outcome_str}  "
        f"final={final_decision}  ground_truth={ground_truth}  "
        f"error_rate={error_rate:.1%}"
    )

    # Print per-round decisions
    decisions = detailed.get("decisions_per_round", [])
    if decisions:
        decisions_str = " -> ".join(decisions)
        print(f"      ↳ Decisions by round: {decisions_str}")


def _print_debate_result(
    seed: int,
    condition: str,
    result: Dict[str, Any],
) -> None:
    """Print result for one debate experiment."""
    detailed = result.get("detailed_metrics", {})
    outcome = result.get("outcome", "unknown")

    final_decision = detailed.get("final_decision", "unknown")
    ground_truth = detailed.get("ground_truth", "scalpel")
    error_rate = detailed.get("error_rate", 0.0)
    correct = final_decision == ground_truth

    emoji = "✓" if correct else "✗"
    outcome_str = outcome.upper().replace("_", " ")

    print(
        f"  {emoji} [Seed {seed}] {outcome_str}  "
        f"final={final_decision}  ground_truth={ground_truth}  "
        f"error_rate={error_rate:.1%}"
    )

    # Print per-round decisions
    decisions = detailed.get("decisions_per_round", [])
    if decisions:
        decisions_str = " -> ".join(decisions)
        print(f"      ↳ Decisions by round: {decisions_str}")

    # Print opinion changes
    changes = detailed.get("decision_changes", [])
    if changes:
        for change in changes:
            print(f"      ↳ Round {change['round']}: {change['from']} -> {change['to']}")


def _print_news_aggregate(all_results: List[Dict[str, Any]]) -> None:
    """Print a summary table for news experiments."""
    print(f"\n{'='*70}")
    print(f"  R11 News Verification — Aggregate Results")
    print(f"{'='*70}")

    total = len(all_results)
    correct_count = 0
    outcomes = {"correct_maintained": 0, "correct_recovered": 0, "incorrect_swayed": 0, "incorrect_maintained": 0}

    for r in all_results:
        if "error" in r:
            continue
        detailed = r.get("detailed_metrics", {})
        final = detailed.get("final_decision")
        ground_truth = detailed.get("ground_truth", "fake")
        if final == ground_truth:
            correct_count += 1

        outcome = r.get("outcome", "unknown")
        if outcome in outcomes:
            outcomes[outcome] += 1

    valid_count = total - sum(1 for r in all_results if "error" in r)
    if valid_count > 0:
        accuracy = correct_count / valid_count * 100
        conformity_rate = (valid_count - correct_count) / valid_count * 100

        print(f"\n  Correct decisions: {correct_count}/{valid_count} ({accuracy:.0f}%)")
        print(f"  Conformity errors: {valid_count - correct_count}/{valid_count} ({conformity_rate:.0f}%)")

        print(f"\n  Outcome distribution:")
        for outcome, count in outcomes.items():
            pct = count / valid_count * 100 if valid_count else 0
            bar = "█" * int(pct / 5)
            print(f"    {outcome:20s}: {count:2d} ({pct:5.1f}%) {bar}")

    print()


def _print_debate_aggregate(
    all_results: List[Dict[str, Any]],
    condition: str,
) -> None:
    """Print a summary table for debate experiments."""
    print(f"\n{'='*70}")
    print(f"  R11 Remediation Debate — Aggregate Results (Condition: {condition.upper()})")
    print(f"{'='*70}")

    total = len(all_results)
    correct_count = 0
    maintained_count = 0
    changed_count = 0

    for r in all_results:
        if "error" in r:
            continue
        detailed = r.get("detailed_metrics", {})
        final = detailed.get("final_decision")
        ground_truth = detailed.get("ground_truth", "scalpel")
        if final == ground_truth:
            correct_count += 1

        if detailed.get("maintained_initial"):
            maintained_count += 1
        else:
            changed_count += 1

    valid_count = total - sum(1 for r in all_results if "error" in r)
    if valid_count > 0:
        accuracy = correct_count / valid_count * 100
        conformity_rate = (valid_count - correct_count) / valid_count * 100
        maintained_rate = maintained_count / valid_count * 100
        changed_rate = changed_count / valid_count * 100

        print(f"\n  Correct decisions (Scalpel): {correct_count}/{valid_count} ({accuracy:.0f}%)")
        print(f"  Conformity errors (Bedrock): {valid_count - correct_count}/{valid_count} ({conformity_rate:.0f}%)")
        print(f"\n  Maintained initial stance: {maintained_count}/{valid_count} ({maintained_rate:.0f}%)")
        print(f"  Changed stance: {changed_count}/{valid_count} ({changed_rate:.0f}%)")

    # Per-seed breakdown
    print(f"\n  Per-Experiment Breakdown:")
    print(f"  {'Seed':<6} {'Final':<10} {'Correct':<10} {'Error Rate':<12} {'Outcome':<20}")
    print(f"  {'-'*60}")

    for r in all_results:
        seed = r.get("seed", "?")
        if "error" in r:
            print(f"  {seed:<6} {'ERROR':<10}")
            continue

        detailed = r.get("detailed_metrics", {})
        final = detailed.get("final_decision", "unknown")
        ground_truth = detailed.get("ground_truth", "scalpel")
        error_rate = detailed.get("error_rate", 0.0)
        outcome = r.get("outcome", "unknown")
        correct = "Yes" if final == ground_truth else "No"

        print(
            f"  {seed:<6} {final:<10} {correct:<10} "
            f"{error_rate:<12.1%} {outcome:<20}"
        )

    print()


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run R11 (Majority Sway) experiments.",
    )
    parser.add_argument(
        "--scenario", "-sc",
        type=str,
        choices=["1", "2"],
        required=True,
        help="Experiment scenario: 1 (news verification) or 2 (remediation debate).",
    )
    parser.add_argument(
        "--condition", "-c",
        type=str,
        choices=["e1", "e2", "e3", "e4", "all"],
        default="e1",
        help="Experiment condition for scenario 2 (default: e1). Use 'all' to run all conditions.",
    )
    parser.add_argument(
        "--seeds", "-s",
        type=int,
        default=4,
        help="Number of experiment repetitions (default: 4 for scenario 2, 10 for scenario 1).",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output directory for results.",
    )
    args = parser.parse_args()

    if args.scenario == "1":
        seeds = args.seeds if args.seeds != 4 else 10  # Default 10 for scenario 1
        output_dir = args.output or "results/"
        _run_news_experiment(
            num_seeds=seeds,
            output_dir=output_dir,
        )
    else:  # scenario 2
        output_dir = args.output or "results/"
        if args.condition == "all":
            # Run all conditions
            for cond in ["e1", "e2", "e3", "e4"]:
                _run_debate_experiment(
                    condition=cond,
                    num_seeds=args.seeds,
                    output_dir=output_dir,
                )
        else:
            _run_debate_experiment(
                condition=args.condition,
                num_seeds=args.seeds,
                output_dir=output_dir,
            )


if __name__ == "__main__":
    main()
