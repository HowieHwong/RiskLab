#!/usr/bin/env python3
"""
Run R6 (Semantic Drift) experiments using the RiskLab framework.

Usage
-----
    # Run with default 2 seeds:
    python -m risklab.experiments.run_r6

    # Customize seeds and output:
    python -m risklab.experiments.run_r6 --seeds 3 --output results/r6
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
from risklab.risks.semantic_drift import SemanticDriftRisk


_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "configs")
_CONFIG_FILE = "r6_semantic_drift.yaml"


# ------------------------------------------------------------------
# Product names for display
# ------------------------------------------------------------------
_PRODUCT_NAMES = [
    "Stellar X1 (Smartphone)",
    "PulseFit Pro (Fitness Tracker)",
    "Aero-4K (Consumer Drone)",
    "MorningBrew AI (Smart Coffee)",
    "TerraVolt Explorer (Power Station)",
]


# ------------------------------------------------------------------
# Main logic
# ------------------------------------------------------------------

def _run_r6(
    num_seeds: int = 2,
    output_dir: str = "results/r6",
) -> List[Dict[str, Any]]:
    """Run R6 Semantic Drift experiment across all 5 product inputs."""
    config_path = os.path.join(_CONFIG_DIR, _CONFIG_FILE)

    if not os.path.isfile(config_path):
        print(f"  ✗ Config not found: {config_path}")
        return []

    print(f"\n{'='*70}")
    print(f"  R6  Semantic Drift – Ad-Copy Pipeline Experiment")
    print(f"  Config  : {_CONFIG_FILE}")
    print(f"  Seeds   : {num_seeds}")
    print(f"  Products: {len(_PRODUCT_NAMES)}")
    print(f"  Total runs: {len(_PRODUCT_NAMES)} × {num_seeds} = "
          f"{len(_PRODUCT_NAMES) * num_seeds}")
    print(f"{'='*70}")

    all_results: List[Dict[str, Any]] = []

    for seed in range(num_seeds):
        print(f"\n── Seed {seed} ─────────────────────────────────")

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

        # Run acyclic pipeline (once per product input)
        results = runner.run(num_seeds=1)

        # Annotate with product names and print per-product results
        for r in results:
            idx = r.get("input_index", 0)
            product = _PRODUCT_NAMES[idx] if idx < len(_PRODUCT_NAMES) else f"Input {idx}"
            r["product_name"] = product
            r["seed"] = seed

            # Reset risk cache between products
            for risk in runner.risks:
                if isinstance(risk, SemanticDriftRisk):
                    risk.reset_cache()

            _print_product_result(seed, product, r)

        all_results.extend(results)

    # Print aggregate summary
    _print_aggregate(all_results)

    # Save aggregate
    os.makedirs(output_dir, exist_ok=True)
    agg_path = os.path.join(output_dir, "r6_all_results.json")
    with open(agg_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Results saved to: {agg_path}")

    return all_results


def _print_product_result(
    seed: int, product: str, result: Dict[str, Any]
) -> None:
    """Print result for one product × seed."""
    risk = result.get("risk_results", {})
    for risk_id, rd in risk.items():
        detected = rd.get("detected", False)
        score = rd.get("score", 0.0)
        emoji = "⚠" if detected else "✓"
        # Convert normalised score back to 1-10 for readability
        raw_score = round(score * 9 + 1, 1)
        print(
            f"  {emoji} [{product}] "
            f"drift_score={raw_score:.1f}/10  "
            f"(normalised={score:.4f})  "
            f"detected={detected}"
        )
        if rd.get("counterfactual"):
            cf = rd["counterfactual"]
            if len(cf) > 100:
                cf = cf[:100] + "…"
            print(f"      ↳ {cf}")


def _print_aggregate(all_results: List[Dict[str, Any]]) -> None:
    """Print a summary table across all products and seeds."""
    print(f"\n{'='*70}")
    print(f"  R6 Aggregate Results")
    print(f"{'='*70}")

    # Group by product
    by_product: Dict[str, List[float]] = {}
    for r in all_results:
        name = r.get("product_name", "Unknown")
        for rd in r.get("risk_results", {}).values():
            score = rd.get("score", 0.0)
            raw_score = round(score * 9 + 1, 1)
            by_product.setdefault(name, []).append(raw_score)

    # Print per-product averages
    all_scores = []
    for product, scores in by_product.items():
        avg = sum(scores) / len(scores) if scores else 0.0
        all_scores.extend(scores)
        scores_str = ", ".join(f"{s:.1f}" for s in scores)
        print(f"  {product}: avg={avg:.2f}  scores=[{scores_str}]")

    if all_scores:
        overall = sum(all_scores) / len(all_scores)
        print(f"\n  Overall average drift score: {overall:.2f}/10")
        print(f"  Total experiments: {len(all_scores)}")

    print()


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run R6 (Semantic Drift) experiments.",
    )
    parser.add_argument(
        "--seeds", "-s",
        type=int,
        default=2,
        help="Number of seeds (repetitions) per product (default: 2).",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="results/r6",
        help="Output directory for results (default: results/r6).",
    )
    args = parser.parse_args()

    _run_r6(num_seeds=args.seeds, output_dir=args.output)


if __name__ == "__main__":
    main()
