"""
Small-sample statistics shared by the reproduction drivers.

Every reported rate and mean carries its uncertainty, so the drivers report
confidence intervals and tests rather than bare means.  The Risk 1.3 and
Risk 1.5 drivers share these implementations, so their numbers are directly
comparable.

Pure standard library on purpose: the drivers must run in a bare environment
without SciPy.

    - ``wilson_ci``            score interval for a proportion (small n safe)
    - ``two_proportion_test``  z-test on two independent proportions
    - ``fisher_exact``         exact two-sided test on a 2x2 table
    - ``welch_t_test``         unequal-variance t-test with Cohen's d
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "mean",
    "std",
    "wilson_ci",
    "two_proportion_test",
    "fisher_exact",
    "welch_t_test",
]


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def std(xs: Sequence[float], ddof: int = 1) -> float:
    n = len(xs)
    if n <= ddof:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - ddof))


def p_from_z(z: float) -> float:
    """Two-sided p-value of a standard normal deviate."""
    return math.erfc(abs(z) / math.sqrt(2.0))


def betacf(a: float, b: float, x: float) -> float:
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


def betai(a: float, b: float, x: float) -> float:
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
        return front * betacf(a, b, x) / a
    return 1.0 - front * betacf(b, a, 1.0 - x) / b


def p_from_t(t: float, df: float) -> float:
    """Two-sided p-value of a Student-t deviate (exact, no scipy needed)."""
    if df <= 0:
        return float("nan")
    return betai(df / 2.0, 0.5, df / (df + t * t))


def wilson_ci(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval for a proportion (well behaved for small n)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def two_proportion_test(k1: int, n1: int, k2: int, n2: int) -> Dict[str, Any]:
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
        "p_value": p_from_z(z),
    }


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
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


def welch_t_test(xs: Sequence[float], ys: Sequence[float]) -> Dict[str, Any]:
    """Welch's unequal-variance t-test."""
    n1, n2 = len(xs), len(ys)
    if n1 < 2 or n2 < 2:
        return {"t": None, "df": None, "p_value": None}
    m1, m2 = mean(xs), mean(ys)
    v1, v2 = std(xs) ** 2, std(ys) ** 2
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
        "p_value": p_from_t(t, df),
        "cohens_d": (m2 - m1) / pooled_sd if pooled_sd else None,
    }


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------
