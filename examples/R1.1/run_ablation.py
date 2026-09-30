#!/usr/bin/env python3
"""
Risk 1.1 supplementary experiments — Q-Learning vs. LLM, with vs. without
natural-language communication.

Three conditions, one market, one risk definition::

    Experiment I    Q-Learning seller   no communication    (Reviewer 1)
    Experiment II   LLM seller          no communication    (Reviewer 2)
    Experiment III  LLM seller          communication       (current paper, C1)

Everything except the two manipulated factors — *agent type* and *communication
channel* — is held fixed: three symmetric sellers, marginal cost 10, 99
customers, lowest price takes the market, ties split it, 10 rounds, and the
same ``tacit_collusion`` detector with the same thresholds.  Experiment III
reuses ``r1_1_C1_basic.yaml`` unmodified, so previously reported C1 numbers stay
comparable; the only change is the number of repetitions.

Usage
-----
    cd examples/R1.1

    # Main table (the minimal version from the plan), 30 runs per condition
    python run_ablation.py --exp all --runs 30

    # Q-learning only; set --jobs to the physical core count (training is
    # CPU-bound, extra processes just timeshare)
    python run_ablation.py --exp I --runs 30 --jobs 2

    # Q-learning on the wide price grid, matching the LLMs' [10,100] reach
    python run_ablation.py --exp Iw --runs 30 --jobs 2

    # Cross-model version of the two LLM conditions
    python run_ablation.py --exp II,III --runs 30 --jobs 4 \
        --models gpt-4o-mini,deepseek-chat

    # Optional §8 probe: force seller_1 down to 11 in round 6 and watch the
    # other two sellers react
    python run_ablation.py --exp all --runs 10 --price-cut seller_1:6:11

Outputs (under ``--output``, default ``results/ablation``)
    r1_1_ablation_runs.json      one record per run
    r1_1_ablation_summary.json   aggregates + statistical comparisons
    r1_1_ablation_table.md       paste-ready main table
    raw/                         trajectories and per-run aggregates
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Ensure the project root is importable
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from risklab.experiments.config_loader import (  # noqa: E402
    build_experiment_from_config,
    load_experiment_config,
)
from risklab.experiments.qlearning_trainer import (  # noqa: E402
    QTrainingConfig,
    train_q_learning_sellers,
)
from risklab.experiments.runner import ExperimentRunner  # noqa: E402
from risklab.risks.tacit_collusion import TacitCollusionRisk  # noqa: E402

_CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs")

# ---------------------------------------------------------------------------
# Experiment table
# ---------------------------------------------------------------------------

EXPERIMENTS: Dict[str, Dict[str, Any]] = {
    "I": {
        "label": "Experiment I",
        "config": "r1_1_expI_qlearning.yaml",
        "agent_type": "Q-Learning",
        "communication": False,
        "kind": "qlearning",
    },
    "Iw": {
        # Same as I, on an action space spanning the LLM conditions' full
        # [10, 100] price range (non-uniform grid — see the config header).
        "label": "Experiment I (wide)",
        "config": "r1_1_expI_qlearning_wide.yaml",
        "agent_type": "Q-Learning",
        "communication": False,
        "kind": "qlearning",
    },
    "II": {
        "label": "Experiment II",
        "config": "r1_1_expII_llm_nocomm.yaml",
        "agent_type": "LLM",
        "communication": False,
        "kind": "llm",
    },
    "III": {
        "label": "Experiment III",
        "config": "r1_1_C1_basic.yaml",   # unchanged current-paper C1 baseline
        "agent_type": "LLM",
        "communication": True,
        "kind": "llm",
    },
    # Cross-model counterparts of II and III.  Same prompts, same market, same
    # detector — only the model line changes, supplied with --models.  These
    # test whether the monotone "+1" price ramp gpt-4o-mini produces is a
    # single-model artefact rather than a property of LLM market agents.
    "IIX": {
        "label": "Experiment II-X",
        "config": "r1_1_expII_xmodel_nocomm.yaml",
        "agent_type": "LLM (reasoning)",
        "communication": False,
        "kind": "llm",
    },
    "IIIX": {
        "label": "Experiment III-X",
        "config": "r1_1_expIII_xmodel_comm.yaml",
        "agent_type": "LLM (reasoning)",
        "communication": True,
        "kind": "llm",
    },
}

# "Iw" (wide grid) and the "X" (cross-model) conditions are opt-in via --exp
_EXP_ORDER = ["I", "II", "III"]

# (no-communication, communication) pairs that Comparison B is defined over.
# One pair per prompt/decoding regime, so a batch that runs only the
# reasoning-model conditions still gets its II-vs-III statistics.
_LLM_PAIRS = [("II", "III"), ("IIX", "IIIX")]


# ---------------------------------------------------------------------------
# Small statistics helpers (stdlib only)
# ---------------------------------------------------------------------------

def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: Sequence[float], ddof: int = 1) -> float:
    n = len(xs)
    if n <= ddof:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - ddof))


def _p_from_z(z: float) -> float:
    """Two-sided p-value of a standard normal deviate."""
    return math.erfc(abs(z) / math.sqrt(2.0))


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny, eps, max_iter = 1e-30, 3e-12, 300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log(1.0 - x)
    )
    front = math.exp(lbeta)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _p_from_t(t: float, df: float) -> float:
    """Two-sided p-value of a Student-t deviate (exact, no scipy needed)."""
    if df <= 0:
        return float("nan")
    return _betai(df / 2.0, 0.5, df / (df + t * t))


def _wilson_ci(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval for a proportion (well behaved for small n)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _two_proportion_test(k1: int, n1: int, k2: int, n2: int) -> Dict[str, Any]:
    """Pooled two-proportion z-test."""
    if n1 == 0 or n2 == 0:
        return {"z": None, "p_value": None}
    p1, p2 = k1 / n1, k2 / n2
    p_pool = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return {"p1": p1, "p2": p2, "diff": p2 - p1, "z": 0.0, "p_value": 1.0}
    z = (p2 - p1) / se
    return {
        "p1": p1,
        "p2": p2,
        "diff": p2 - p1,
        "z": z,
        "p_value": _p_from_z(z),
    }


def _fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact test p-value for the 2x2 table [[a,b],[c,d]]."""
    n = a + b + c + d
    if n == 0:
        return float("nan")
    row1, row2, col1 = a + b, c + d, a + c

    def prob(x: int) -> float:
        return (
            math.comb(row1, x) * math.comb(row2, col1 - x) / math.comb(n, col1)
        )

    lo, hi = max(0, col1 - row2), min(row1, col1)
    p_obs = prob(a)
    total = sum(
        prob(x) for x in range(lo, hi + 1) if prob(x) <= p_obs * (1 + 1e-9)
    )
    return min(1.0, total)


def _welch_t_test(xs: Sequence[float], ys: Sequence[float]) -> Dict[str, Any]:
    """Welch's unequal-variance t-test."""
    n1, n2 = len(xs), len(ys)
    if n1 < 2 or n2 < 2:
        return {"t": None, "df": None, "p_value": None}
    m1, m2 = _mean(xs), _mean(ys)
    v1, v2 = _std(xs) ** 2, _std(ys) ** 2
    se2 = v1 / n1 + v2 / n2
    if se2 == 0:
        return {
            "mean1": m1, "mean2": m2, "diff": m2 - m1,
            "t": 0.0, "df": float(n1 + n2 - 2), "p_value": 1.0,
        }
    t = (m2 - m1) / math.sqrt(se2)
    df = se2 ** 2 / (
        (v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1)
    )
    pooled_sd = math.sqrt((v1 * (n1 - 1) + v2 * (n2 - 1)) / (n1 + n2 - 2))
    return {
        "mean1": m1,
        "mean2": m2,
        "diff": m2 - m1,
        "t": t,
        "df": df,
        "p_value": _p_from_t(t, df),
        "cohens_d": (m2 - m1) / pooled_sd if pooled_sd else None,
    }


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

def _apply_overrides(raw: Dict[str, Any], spec: Dict[str, Any]) -> str:
    """Apply per-run overrides to a parsed config; return the run's id."""
    base_id = raw.get("experiment", {}).get("id", "experiment")
    model = spec.get("model")
    parts = [base_id]
    if model:
        parts.append(model.replace("/", "-"))
    parts.append(f"run{spec['run']:03d}")
    run_id = "_".join(parts)
    raw.setdefault("experiment", {})["id"] = run_id

    if model:
        for agent in raw.get("agents", []):
            agent["model"] = model

    # Reasoning tokens are billed against max_tokens, and a model that spends
    # its whole budget thinking returns an empty completion (which
    # MarketSellerAgent raises on).  The ceiling therefore has to be set per
    # model, not per condition, so it is an override rather than a YAML edit.
    max_tokens = spec.get("max_tokens")
    if max_tokens:
        for agent in raw.get("agents", []):
            agent["max_tokens"] = int(max_tokens)

    # Reasoning strength is a treatment, not a nuisance parameter: the YAML
    # pins `effort: high` for the cross-model conditions, and a batch that
    # lowers it is a different condition rather than a top-up of the same one.
    # OpenRouter ignores `effort` on models whose endpoints do not advertise
    # it (kimi-k2.6), where only `enabled: false` actually suppresses the
    # trace, so "off" is spelled out separately from the effort levels.
    reasoning = spec.get("reasoning")
    if reasoning:
        body = {"enabled": False} if reasoning == "off" else {
            "effort": reasoning, "exclude": False
        }
        for agent in raw.get("agents", []):
            extra = agent.setdefault("llm_params", {}).setdefault("extra_body", {})
            extra["reasoning"] = body

    price_cut = spec.get("price_cut")
    if price_cut:
        env_params = raw.setdefault("environment", {}).setdefault("parameters", {})
        env_params["forced_deviation"] = dict(price_cut)

    return run_id


def _run_single(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one independent run and return its summary record.

    Module-level (and only primitives in *spec*) so it can be dispatched to a
    process pool for the CPU-bound Q-learning condition.
    """
    exp_key = spec["exp"]
    meta = EXPERIMENTS[exp_key]
    config_path = os.path.join(_CONFIG_DIR, meta["config"])

    raw = load_experiment_config(config_path)
    run_id = _apply_overrides(raw, spec)

    components = build_experiment_from_config(
        raw, base_dir=_PROJECT_ROOT, num_rounds=spec.get("rounds")
    )
    environment = components["environment"]
    agents = components["agents"]

    round_callback = None
    if spec.get("verbose"):
        from run_r2 import _make_round_printer  # reuse the R2 pretty printer

        round_callback = _make_round_printer(getattr(environment, "max_rounds", 10))

    # --- Learning phase (Experiment I only) ---
    training_info: Optional[Dict[str, Any]] = None
    if meta["kind"] == "qlearning":
        ql = dict(raw.get("qlearning", {}))
        # NB: ``is not None`` — ``--train-rounds 0`` is a valid budget (the
        # zero-training floor arm) and must not be swallowed as falsy.
        if spec.get("train_rounds") is not None:
            ql["training_rounds"] = int(spec["train_rounds"])
        train_cfg = QTrainingConfig(
            training_rounds=int(ql.get("training_rounds", 5_000_000)),
            convergence_window=int(ql.get("convergence_window", 50_000)),
            price_tolerance=float(ql.get("price_tolerance", 0.25)),
            check_interval=int(ql.get("check_interval", 1_000)),
            stop_on_convergence=bool(ql.get("stop_on_convergence", False)),
            epsilon_final=float(ql.get("epsilon_final", 1e-3)),
            seed=int(spec["seed"]),
            price_log_bin=int(ql.get("price_log_bin", 10_000)),
            verbose=bool(spec.get("verbose")),
        )
        training_info = train_q_learning_sellers(
            environment, agents, train_cfg
        ).to_dict()

    # --- Evaluation episode (identical path for every condition) ---
    runner = ExperimentRunner(
        experiment_id=run_id,
        environment=environment,
        protocol=components["protocol"],
        agents=agents,
        task=components.get("task"),
        topology=components.get("topology"),
        flow=components.get("flow"),
        risks=components.get("risks", []),
        output_dir=spec["output_dir"],
        on_round_callback=round_callback,
    )
    results = runner.run(num_seeds=1)

    return _summarise_run(
        spec, meta, run_id, environment, components, results, training_info
    )


def _summarise_run(
    spec: Dict[str, Any],
    meta: Dict[str, Any],
    run_id: str,
    environment: Any,
    components: Dict[str, Any],
    results: List[Dict[str, Any]],
    training_info: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Turn one episode into a flat record for the comparison tables."""
    round_results = environment.get_round_results()

    # Reuse the detector that the experiment was configured with, so the
    # thresholds in the record are exactly the thresholds in the YAML.
    detector = next(
        (r for r in components.get("risks", [])
         if isinstance(r, TacitCollusionRisk)),
        None,
    ) or TacitCollusionRisk()
    metrics = detector.compute_detailed_metrics(round_results)

    result0 = results[0] if results else {}
    risk_results = result0.get("risk_results", {})
    detected = any(rr.get("detected") for rr in risk_results.values())
    score = max(
        (rr.get("score", 0.0) for rr in risk_results.values()), default=0.0
    )

    prices = metrics.get("market_prices", [])
    record: Dict[str, Any] = {
        "experiment": spec["exp"],
        "label": meta["label"],
        "agent_type": meta["agent_type"],
        "communication": meta["communication"],
        "model": (
            "q_learning" if meta["kind"] == "qlearning"
            else spec.get("model") or _config_model(components)
        ),
        "run": spec["run"],
        "seed": spec["seed"],
        "experiment_id": run_id,
        "num_rounds": len(prices),
        "market_prices": prices,
        "avg_price": metrics.get("avg_market_price", 0.0),
        "final_price": prices[-1] if prices else None,
        "max_price": max(prices) if prices else None,
        "min_price": min(prices) if prices else None,
        "price_slope": metrics.get("price_slope", 0.0),
        "pattern": metrics.get("pattern", "insufficient_data"),
        "avg_price_spread": metrics.get("avg_price_spread", 0.0),
        "risk_detected": bool(detected),
        "risk_score": float(score),
        "per_agent_prices": metrics.get("per_agent_prices", {}),
        "cumulative_profits": metrics.get("per_agent_cumulative_profits", {}),
        # Data-integrity counters.  `llm_errors` > 0 means some round used the
        # marginal-cost fallback instead of a real decision, which biases the
        # market price down; `llm_retries` rounds are clean but flag a model
        # whose generations sometimes fail to terminate.
        "llm_errors": sum(
            getattr(a, "llm_errors", 0) for a in components.get("agents") or []
        ),
        "llm_retries": sum(
            getattr(a, "llm_retries", 0) for a in components.get("agents") or []
        ),
    }
    if training_info is not None:
        record["training"] = training_info
    if spec.get("price_cut"):
        record["deviation"] = _deviation_analysis(
            round_results, spec["price_cut"]
        )
    return record


def _config_model(components: Dict[str, Any]) -> Optional[str]:
    """The model the agents were actually built with (from the YAML)."""
    agents = components.get("agents") or []
    models = {getattr(a, "model", None) for a in agents}
    if len(models) == 1:
        return models.pop()
    return "+".join(sorted(m for m in models if m))


def _deviation_analysis(
    round_results: List[Dict[str, Any]], price_cut: Dict[str, Any]
) -> Dict[str, Any]:
    """Did the other sellers follow a forced one-round price cut? (plan §8)"""
    target_round = int(price_cut["round"])          # 1-indexed
    deviator = str(price_cut["agent_id"])
    idx = target_round - 1
    if not (0 <= idx < len(round_results)):
        return {"applied": False, "reason": "forced round outside episode"}

    def others_mean(i: int) -> Optional[float]:
        if not (0 <= i < len(round_results)):
            return None
        others = [
            p for aid, p in round_results[i]["prices"].items() if aid != deviator
        ]
        return _mean(others) if others else None

    market = [r["market_price"] for r in round_results]
    before, after = others_mean(idx - 1), others_mean(idx + 1)
    pre_mean = _mean(market[:idx]) if idx > 0 else None
    post_mean = _mean(market[idx + 1:]) if idx + 1 < len(market) else None

    return {
        "applied": bool(round_results[idx].get("forced_deviation")),
        "deviator": deviator,
        "round": target_round,
        "forced_price": price_cut["price"],
        "submitted_price": (
            (round_results[idx].get("forced_deviation") or {}).get("submitted_price")
        ),
        "others_price_before": before,
        "others_price_after": after,
        "followed_cut": (
            bool(after < before) if (before is not None and after is not None)
            else None
        ),
        "market_price_pre_mean": pre_mean,
        "market_price_post_mean": post_mean,
        "recovered_to_pre_level": (
            bool(market[-1] >= pre_mean) if pre_mean is not None else None
        ),
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _aggregate(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate the per-run records of one condition."""
    n = len(records)
    if n == 0:
        return {"n_runs": 0}

    avg_prices = [r["avg_price"] for r in records]
    finals = [r["final_price"] for r in records if r["final_price"] is not None]
    maxes = [r["max_price"] for r in records if r["max_price"] is not None]
    mins = [r["min_price"] for r in records if r["min_price"] is not None]
    flags = [bool(r["risk_detected"]) for r in records]
    k = sum(flags)

    horizon = min((len(r["market_prices"]) for r in records), default=0)
    by_round = [
        _mean([r["market_prices"][t] for r in records]) for t in range(horizon)
    ]

    first = records[0]
    agg: Dict[str, Any] = {
        "experiment": first["experiment"],
        "label": first["label"],
        "agent_type": first["agent_type"],
        "communication": first["communication"],
        "model": first["model"],
        "n_runs": n,
        "avg_price_mean": _mean(avg_prices),
        "avg_price_std": _std(avg_prices),
        "avg_price_sem": _std(avg_prices) / math.sqrt(n) if n else 0.0,
        "final_price_mean": _mean(finals),
        "max_price_mean": _mean(maxes),
        "min_price_mean": _mean(mins),
        "highest_price_observed": max(maxes) if maxes else None,
        "lowest_price_observed": min(mins) if mins else None,
        "price_slope_mean": _mean([r["price_slope"] for r in records]),
        "risk_count": k,
        "risk_rate": k / n,
        "risk_rate_ci95": _wilson_ci(k, n),
        "risk_score_mean": _mean([r["risk_score"] for r in records]),
        "pattern_counts": dict(Counter(r["pattern"] for r in records)),
        "mean_price_by_round": by_round,
        "_avg_prices": avg_prices,
    }

    trainings = [r["training"] for r in records if r.get("training")]
    if trainings:
        agg["training"] = {
            "converged_runs": sum(1 for t in trainings if t["converged"]),
            "price_stable_runs": sum(
                1 for t in trainings if t.get("price_stable")
            ),
            "mean_price_drift": _mean(
                [t["price_drift"] for t in trainings
                 if t.get("price_drift") is not None]
            ),
            "mean_policy_churn": _mean(
                [t.get("final_policy_churn", 0.0) for t in trainings]
            ),
            "mean_rounds_trained": _mean([t["rounds_trained"] for t in trainings]),
            "mean_final_epsilon": _mean([t["final_epsilon"] for t in trainings]),
            "mean_train_price_last_window": _mean(
                [t["last_window_mean_price"] for t in trainings]
            ),
            "mean_wall_time_sec": _mean([t["wall_time_sec"] for t in trainings]),
        }

    deviations = [r["deviation"] for r in records if r.get("deviation")]
    if deviations:
        followed = [d["followed_cut"] for d in deviations if d["followed_cut"] is not None]
        recovered = [
            d["recovered_to_pre_level"] for d in deviations
            if d["recovered_to_pre_level"] is not None
        ]
        agg["deviation"] = {
            "n": len(deviations),
            "follow_rate": _mean([float(f) for f in followed]) if followed else None,
            "recovery_rate": _mean([float(x) for x in recovered]) if recovered else None,
            "others_price_before_mean": _mean(
                [d["others_price_before"] for d in deviations
                 if d["others_price_before"] is not None]
            ),
            "others_price_after_mean": _mean(
                [d["others_price_after"] for d in deviations
                 if d["others_price_after"] is not None]
            ),
            "market_price_pre_mean": _mean(
                [d["market_price_pre_mean"] for d in deviations
                 if d["market_price_pre_mean"] is not None]
            ),
            "market_price_post_mean": _mean(
                [d["market_price_post_mean"] for d in deviations
                 if d["market_price_post_mean"] is not None]
            ),
        }
    return agg


def _compare(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Compare two conditions on risk rate and average price."""
    return {
        "baseline": a["label"],
        "comparison": b["label"],
        "risk_rate": {
            "baseline": a["risk_rate"],
            "comparison": b["risk_rate"],
            **_two_proportion_test(
                a["risk_count"], a["n_runs"], b["risk_count"], b["n_runs"]
            ),
            "fisher_exact_p": _fisher_exact(
                a["risk_count"], a["n_runs"] - a["risk_count"],
                b["risk_count"], b["n_runs"] - b["risk_count"],
            ),
        },
        "avg_price": _welch_t_test(a["_avg_prices"], b["_avg_prices"]),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _fmt(value: Optional[float], digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _main_table_rows(aggs: List[Dict[str, Any]]) -> List[List[str]]:
    rows = []
    for a in aggs:
        rows.append([
            a["label"],
            a["agent_type"] + (f" ({a['model']})" if a["agent_type"] == "LLM" and a["model"] else ""),
            "Yes" if a["communication"] else "No",
            str(a["n_runs"]),
            f"{_fmt(a['avg_price_mean'])} ± {_fmt(a['avg_price_std'])}",
            _fmt(a["final_price_mean"]),
            _fmt(a["max_price_mean"]),
            _fmt(a["min_price_mean"]),
            f"{a['risk_count']}/{a['n_runs']} ({a['risk_rate']*100:.1f}%)",
        ])
    return rows


_HEADERS = [
    "Setting", "Agent", "Comm.", "Runs", "Avg. Price",
    "Final", "Max", "Min", "Risk Rate",
]


def _print_table(headers: List[str], rows: List[List[str]]) -> None:
    widths = [
        max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print("  " + line)
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print("  " + "  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))


def _markdown_table(headers: List[str], rows: List[List[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |"]
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def _print_comparison(title: str, question: str, cmp_result: Dict[str, Any]) -> None:
    rr = cmp_result["risk_rate"]
    ap = cmp_result["avg_price"]
    print(f"\n  {title}")
    print(f"    {question}")
    print(
        f"    Risk rate : {rr['baseline']*100:5.1f}%  →  {rr['comparison']*100:5.1f}%  "
        f"(Δ {rr['diff']*100:+.1f} pp, z={_fmt(rr.get('z'))}, "
        f"p={_fmt(rr.get('p_value'), 4)}, Fisher p={_fmt(rr.get('fisher_exact_p'), 4)})"
    )
    print(
        f"    Avg price : {_fmt(ap.get('mean1'))}  →  {_fmt(ap.get('mean2'))}  "
        f"(Δ {_fmt(ap.get('diff'))}, t={_fmt(ap.get('t'))}, "
        f"df={_fmt(ap.get('df'), 1)}, p={_fmt(ap.get('p_value'), 4)}, "
        f"d={_fmt(ap.get('cohens_d'))})"
    )


def _print_round_trajectories(aggs: List[Dict[str, Any]]) -> None:
    horizon = max((len(a["mean_price_by_round"]) for a in aggs), default=0)
    if not horizon:
        return
    headers = ["Setting"] + [f"R{t+1}" for t in range(horizon)]
    rows = []
    for a in aggs:
        cells = [_fmt(p, 1) for p in a["mean_price_by_round"]]
        cells += ["—"] * (horizon - len(cells))
        rows.append([a["label"]] + cells)
    print("\n  Mean market price per round")
    _print_table(headers, rows)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _dispatch(specs: List[Dict[str, Any]], jobs: int, use_processes: bool) -> List[Dict[str, Any]]:
    """Run every spec, sequentially or in parallel, preserving order."""
    total = len(specs)
    records: List[Optional[Dict[str, Any]]] = [None] * total

    if jobs <= 1:
        for i, spec in enumerate(specs):
            records[i] = _run_one_guarded(spec, i + 1, total)
        return [r for r in records if r]

    from concurrent.futures import (
        ProcessPoolExecutor, ThreadPoolExecutor, as_completed,
    )

    executor_cls = ProcessPoolExecutor if use_processes else ThreadPoolExecutor
    done = 0
    with executor_cls(max_workers=jobs) as pool:
        futures = {pool.submit(_run_single, spec): i for i, spec in enumerate(specs)}
        for future in as_completed(futures):
            i = futures[future]
            done += 1
            try:
                records[i] = future.result()
                _report_run(records[i], done, total)
            except Exception as exc:  # keep the batch alive
                print(f"  ✗ run {specs[i]['run']} of Experiment "
                      f"{specs[i]['exp']} failed: {exc}")
    return [r for r in records if r]


def _run_one_guarded(spec: Dict[str, Any], index: int, total: int) -> Optional[Dict[str, Any]]:
    try:
        record = _run_single(spec)
        _report_run(record, index, total)
        return record
    except Exception as exc:
        print(f"  ✗ run {spec['run']} of Experiment {spec['exp']} failed: {exc}")
        if spec.get("verbose"):
            import traceback
            traceback.print_exc()
        return None


def _report_run(record: Dict[str, Any], index: int, total: int) -> None:
    flag = "⚠ risk" if record["risk_detected"] else "✓ clean"
    extra = ""
    if record.get("training"):
        t = record["training"]
        extra = (
            f"  [trained {t['rounds_trained']:,} rounds, "
            f"price_stable={t.get('price_stable')}, "
            f"drift={_fmt(t.get('price_drift'), 3)}, "
            f"churn={t.get('final_policy_churn', 0.0):.4f}]"
        )
    final = record["final_price"]
    print(
        f"  [{index:>3}/{total}] {record['label']:<14} run {record['run']:>3}  "
        f"avg={record['avg_price']:6.2f}  "
        f"final={'—' if final is None else final:>3}  "
        f"{flag}{extra}"
    )


def _canon_exp(raw: str) -> str:
    """Normalise an --exp token (case-insensitive, keeps the 'Iw' suffix)."""
    key = raw.strip()
    for known in EXPERIMENTS:
        if key.lower() == known.lower():
            return known
    return key.upper()


def _parse_price_cut(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    parts = raw.split(":")
    if len(parts) != 3:
        raise SystemExit(
            "--price-cut expects AGENT:ROUND:PRICE, e.g. seller_1:6:11"
        )
    return {
        "agent_id": parts[0],
        "round": int(parts[1]),
        "price": int(parts[2]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Risk 1.1 supplementary experiments (Q-Learning / LLM × communication).",
    )
    parser.add_argument(
        "--exp", "-e", default="all",
        help="Comma-separated experiments: I, II, III, Iw or all "
             "(default: all; Iw = Experiment I on the wide price grid, "
             "excluded from 'all' because it trains ~5x longer).",
    )
    parser.add_argument(
        "--runs", "-n", type=int, default=30,
        help="Independent runs per condition (default: 30, as recommended in the plan).",
    )
    parser.add_argument(
        "--jobs", "-j", type=int, default=1,
        help="Parallel runs (threads for LLM conditions, processes for Q-learning).",
    )
    parser.add_argument(
        "--models", "-m", default=None,
        help="Comma-separated model overrides for the LLM conditions "
             "(default: whatever the YAML specifies).",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=None,
        help="Override every agent's max_tokens (LLM conditions). Needed when "
             "swapping in a reasoning model whose traces are longer than the "
             "config's ceiling — reasoning tokens count against it, and "
             "exhausting it yields an empty completion.",
    )
    parser.add_argument(
        "--reasoning", default=None,
        choices=["off", "minimal", "low", "medium", "high"],
        help="Override the reasoning budget of every LLM agent. 'off' sends "
             "reasoning.enabled=false; the rest send reasoning.effort. Note "
             "that OpenRouter silently drops 'effort' for models that do not "
             "advertise it (kimi-k2.6), so only 'off' changes that model.",
    )
    parser.add_argument(
        "--train-rounds", type=int, default=None,
        help="Override the Q-learning training budget (default: from YAML, 5000000). "
             "Use e.g. 200000 for a smoke test, but not for a reported "
             "number: at that budget the price path is still climbing.",
    )
    parser.add_argument(
        "--rounds", type=int, default=None,
        help="Episode length for the evaluation phase (default: the config's). "
             "Applied to the environment, the stop conditions AND the agent "
             "prompts together, so the horizon can never disagree.",
    )
    parser.add_argument(
        "--price-cut", default=None,
        help="Optional deviation probe, AGENT:ROUND:PRICE (e.g. seller_1:6:11).",
    )
    parser.add_argument(
        "--seed-offset", type=int, default=0,
        help="Shift the run seeds (use to extend an existing batch).",
    )
    parser.add_argument(
        "--output", "-o", default="results/ablation",
        help="Output directory (default: results/ablation).",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print every round of every episode.",
    )
    args = parser.parse_args()

    if args.exp.strip().lower() == "all":
        exp_keys = list(_EXP_ORDER)
    else:
        exp_keys = [_canon_exp(e) for e in args.exp.split(",") if e.strip()]
    unknown = [e for e in exp_keys if e not in EXPERIMENTS]
    if unknown:
        raise SystemExit(
            f"Unknown experiment(s): {unknown}. "
            f"Choose from {', '.join(EXPERIMENTS)}."
        )

    models = [m.strip() for m in args.models.split(",")] if args.models else [None]
    price_cut = _parse_price_cut(args.price_cut)
    raw_dir = os.path.join(args.output, "raw")
    os.makedirs(raw_dir, exist_ok=True)

    all_records: List[Dict[str, Any]] = []
    aggregates: List[Dict[str, Any]] = []

    for exp_key in exp_keys:
        meta = EXPERIMENTS[exp_key]
        exp_models = [None] if meta["kind"] == "qlearning" else models
        for model in exp_models:
            title = f"{meta['label']} — {meta['agent_type']}"
            if model:
                title += f" ({model})"
            title += f", communication={'yes' if meta['communication'] else 'no'}"
            print(f"\n{'=' * 78}\n  {title}\n  config: {meta['config']}  |  runs: {args.runs}\n{'=' * 78}")

            specs = [
                {
                    "exp": exp_key,
                    "run": i,
                    "seed": args.seed_offset + i,
                    "model": model,
                    "output_dir": raw_dir,
                    "max_tokens": args.max_tokens,
                    "reasoning": args.reasoning,
                    "train_rounds": args.train_rounds,
                    "rounds": args.rounds,
                    "price_cut": price_cut,
                    "verbose": args.verbose,
                }
                for i in range(args.runs)
            ]
            records = _dispatch(
                specs, args.jobs, use_processes=(meta["kind"] == "qlearning")
            )
            if not records:
                print("  ✗ no successful runs for this condition.")
                continue
            all_records.extend(records)
            aggregates.append(_aggregate(records))

    if not aggregates:
        raise SystemExit("No results produced.")

    # ---- Main table ----
    print(f"\n{'=' * 78}\n  Main comparison (Risk 1.1)\n{'=' * 78}")
    rows = _main_table_rows(aggregates)
    _print_table(_HEADERS, rows)
    _print_round_trajectories(aggregates)

    for agg in aggregates:
        training = agg.get("training")
        if not training:
            continue
        stable = training["price_stable_runs"]
        total = agg["n_runs"]
        print(
            f"\n  {agg['label']} training: {stable}/{total} runs ended with a "
            f"settled price path (mean drift "
            f"{_fmt(training['mean_price_drift'], 3)} credits, mean policy "
            f"churn {training['mean_policy_churn']:.4f}; "
            f"{training['converged_runs']}/{total} met Calvano's strict "
            f"argmax criterion)."
        )
        if stable < total:
            print(
                "    ⚠ Some runs had not settled. Raise `training_rounds` in "
                "the config (or --train-rounds) before reporting these "
                "numbers, or report the stability rate alongside them."
            )

    # ---- Comparisons A and B (one pair per LLM model) ----
    by_key = {(a["experiment"], a["model"]): a for a in aggregates}
    comparisons: List[Dict[str, Any]] = []
    exp_i = next(
        (a for a in aggregates if a["experiment"] in ("I", "Iw")), None
    )

    # Tag every comparison with the model whenever more than one model is in
    # play, so a cross-model batch stays readable.
    all_llm_models = list(dict.fromkeys(
        a["model"] for a in aggregates
        if EXPERIMENTS.get(a["experiment"], {}).get("kind") == "llm"
    ))
    multi_model = len(all_llm_models) > 1

    for no_comm, comm in _LLM_PAIRS:
        llm_models = [
            m for m in dict.fromkeys(
                a["model"] for a in aggregates
                if a["experiment"] in (no_comm, comm)
            )
        ]
        for model in llm_models:
            tag = f" [{model}]" if model and multi_model else ""
            exp_ii = by_key.get((no_comm, model))
            exp_iii = by_key.get((comm, model))
            label_ii = EXPERIMENTS[no_comm]["label"]
            label_iii = EXPERIMENTS[comm]["label"]

            if exp_i and exp_ii:
                cmp_a = _compare(exp_i, exp_ii)
                comparisons.append({
                    "name": f"A: Q-Learning vs LLM, both without communication{tag}",
                    **cmp_a,
                })
                _print_comparison(
                    f"Comparison A — {EXPERIMENTS['I']['label']} vs {label_ii}{tag}",
                    "Without language, does the LLM merely reproduce classical algorithmic pricing?",
                    cmp_a,
                )
            if exp_ii and exp_iii:
                cmp_b = _compare(exp_ii, exp_iii)
                comparisons.append({
                    "name": f"B: LLM without vs with communication{tag}",
                    **cmp_b,
                })
                _print_comparison(
                    f"Comparison B — {label_ii} vs {label_iii}{tag}",
                    "Does natural-language interaction change how often / how strongly collusion appears?",
                    cmp_b,
                )

    if price_cut:
        print("\n  Forced price-cut probe "
              f"({price_cut['agent_id']} → {price_cut['price']} in round {price_cut['round']})")
        dev_rows = []
        for a in aggregates:
            d = a.get("deviation")
            if not d:
                continue
            dev_rows.append([
                a["label"],
                str(d["n"]),
                _fmt(d["others_price_before_mean"]),
                _fmt(d["others_price_after_mean"]),
                f"{(d['follow_rate'] or 0) * 100:.1f}%",
                _fmt(d["market_price_pre_mean"]),
                _fmt(d["market_price_post_mean"]),
                f"{(d['recovery_rate'] or 0) * 100:.1f}%",
            ])
        if dev_rows:
            _print_table(
                ["Setting", "n", "Others before", "Others after", "Followed",
                 "Market pre", "Market post", "Recovered"],
                dev_rows,
            )

    # ---- Persist ----
    os.makedirs(args.output, exist_ok=True)
    runs_path = os.path.join(args.output, "r1_1_ablation_runs.json")
    with open(runs_path, "w", encoding="utf-8") as f:
        json.dump(all_records, f, indent=2, ensure_ascii=False, default=str)

    summary = {
        "conditions": [
            {k: v for k, v in a.items() if not k.startswith("_")}
            for a in aggregates
        ],
        "comparisons": comparisons,
        "settings": {
            "runs_per_condition": args.runs,
            "models": models,
            "train_rounds_override": args.train_rounds,
            "rounds_override": args.rounds,
            "price_cut": price_cut,
            "seed_offset": args.seed_offset,
        },
    }
    summary_path = os.path.join(args.output, "r1_1_ablation_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

    table_path = os.path.join(args.output, "r1_1_ablation_table.md")
    with open(table_path, "w", encoding="utf-8") as f:
        f.write("# Risk 1.1 — supplementary comparison\n\n")
        f.write(_markdown_table(_HEADERS, rows) + "\n")
        horizon = max((len(a["mean_price_by_round"]) for a in aggregates), default=0)
        if horizon:
            f.write("\n## Mean market price per round\n\n")
            traj_headers = ["Setting"] + [f"R{t+1}" for t in range(horizon)]
            traj_rows = []
            for a in aggregates:
                cells = [_fmt(p, 1) for p in a["mean_price_by_round"]]
                cells += ["—"] * (horizon - len(cells))
                traj_rows.append([a["label"]] + cells)
            f.write(_markdown_table(traj_headers, traj_rows) + "\n")
        if comparisons:
            f.write("\n## Statistical comparisons\n\n")
            for c in comparisons:
                rr, ap = c["risk_rate"], c["avg_price"]
                f.write(f"**{c['name']}**\n\n")
                f.write(
                    f"- Risk rate: {rr['baseline']*100:.1f}% → {rr['comparison']*100:.1f}% "
                    f"(z = {_fmt(rr.get('z'))}, p = {_fmt(rr.get('p_value'), 4)}, "
                    f"Fisher exact p = {_fmt(rr.get('fisher_exact_p'), 4)})\n"
                )
                f.write(
                    f"- Average price: {_fmt(ap.get('mean1'))} → {_fmt(ap.get('mean2'))} "
                    f"(Welch t = {_fmt(ap.get('t'))}, df = {_fmt(ap.get('df'), 1)}, "
                    f"p = {_fmt(ap.get('p_value'), 4)}, Cohen's d = {_fmt(ap.get('cohens_d'))})\n\n"
                )

    print(f"\n  Per-run records → {runs_path}")
    print(f"  Summary         → {summary_path}")
    print(f"  Markdown table  → {table_path}\n")


if __name__ == "__main__":
    main()
