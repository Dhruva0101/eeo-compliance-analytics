"""Adverse impact analysis of hiring selection rates.

For each EEO-1 job category and each demographic dimension (sex, race/ethnicity):
  * selection rate     = hired / applicants (Hired + Rejected decisions only)
  * reference group    = group with the highest selection rate among groups
                         with at least MIN_REFERENCE_N applicants
  * impact ratio       = group rate / reference rate
  * four-fifths rule   = impact ratio below 0.80 indicates possible adverse impact
                         (Uniform Guidelines on Employee Selection Procedures, 1978)
  * two-proportion z   = pooled z-test of group rate vs reference rate

Applicants who did not disclose a value are excluded for that dimension.
"""

from __future__ import annotations

import math

import pandas as pd

FOUR_FIFTHS = 0.80
ALPHA = 0.05
MIN_REFERENCE_N = 100  # a reference group must be large enough to be a stable benchmark
SMALL_GROUP_N = 30     # results for groups below this are flagged as low-confidence
NOT_DISCLOSED = "Not disclosed"


def two_proportion_z(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    """Pooled two-proportion z-test. Returns (z, two-sided p-value)."""
    if n1 == 0 or n2 == 0:
        return float("nan"), float("nan")
    p_pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (x1 / n1 - x2 / n2) / se
    p = math.erfc(abs(z) / math.sqrt(2))
    return z, p


def classify(ratio: float, p: float, n: int) -> str:
    fails_80 = ratio < FOUR_FIFTHS
    significant = p < ALPHA
    if fails_80 and significant:
        return "Adverse impact indicated" if n >= SMALL_GROUP_N else "Review (small group)"
    if fails_80:
        return "Review: fails 80% rule only"
    if significant and ratio < 1:
        return "Review: significant only"
    return "No indication"


def analyze(pool: pd.DataFrame) -> pd.DataFrame:
    """pool columns: eeo1_category, sex, race_ethnicity, hired (0/1)."""
    rows = []
    for dim in ["sex", "race_ethnicity"]:
        data = pool[pool[dim] != NOT_DISCLOSED]
        for cat, g in data.groupby("eeo1_category"):
            stats = g.groupby(dim)["hired"].agg(hired="sum", applicants="count")
            stats["rate"] = stats.hired / stats.applicants
            eligible = stats[stats.applicants >= MIN_REFERENCE_N]
            if eligible.empty:
                continue
            ref = eligible.rate.idxmax()
            r = stats.loc[ref]
            for grp, s in stats.iterrows():
                ratio = s.rate / r.rate if r.rate > 0 else float("nan")
                if grp == ref:
                    z, p = 0.0, 1.0
                else:
                    z, p = two_proportion_z(int(s.hired), int(s.applicants),
                                            int(r.hired), int(r.applicants))
                rows.append({
                    "eeo1_category": cat,
                    "dimension": dim,
                    "group": grp,
                    "applicants": int(s.applicants),
                    "hired": int(s.hired),
                    "selection_rate": round(s.rate, 4),
                    "reference_group": ref,
                    "reference_rate": round(r.rate, 4),
                    "impact_ratio": round(ratio, 3),
                    "fails_four_fifths": bool(ratio < FOUR_FIFTHS),
                    "z_score": round(z, 2),
                    "p_value": round(p, 4),
                    "small_group": bool(s.applicants < SMALL_GROUP_N),
                    "finding": "Reference group" if grp == ref else classify(ratio, p, int(s.applicants)),
                })
    out = pd.DataFrame(rows)
    return out.sort_values(["dimension", "eeo1_category", "impact_ratio"]).reset_index(drop=True)
