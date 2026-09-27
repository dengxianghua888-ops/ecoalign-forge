"""Agreement statistics, not a quality gate for deliberately biased candidates.

Coincidences follow Krippendorff (2011): each unit contributes m coincidences,
normalized by m-1. Work is O(N * K²), not O(N²), for fixed category count K.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from ecoalign_forge.schemas.judge import JudgeEvaluation

_LEGACY_ORDER = ["T0_Block", "T1_Shadowban", "T2_Normal", "T3_Recommend"]


@dataclass(frozen=True)
class AgreementEstimate:
    value: float | None
    reason: str | None


def raw_agreement(rater_a: Sequence, rater_b: Sequence) -> float | None:
    if len(rater_a) != len(rater_b):
        raise ValueError("Raters must refer to the same units")
    pairs = [
        (a, b) for a, b in zip(rater_a, rater_b, strict=True) if a is not None and b is not None
    ]
    return sum(a == b for a, b in pairs) / len(pairs) if pairs else None


def cohens_kappa(rater_a: Sequence, rater_b: Sequence) -> float | None:
    observed = raw_agreement(rater_a, rater_b)
    if observed is None:
        return None
    pairs = [
        (a, b) for a, b in zip(rater_a, rater_b, strict=True) if a is not None and b is not None
    ]
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(ca[c] * cb[c] for c in ca) / len(pairs) ** 2
    return (observed - expected) / (1 - expected) if expected < 1 else None


def alpha_estimate(ratings_matrix, *, metric="nominal", categories=None) -> AgreementEstimate:
    if metric not in {"nominal", "ordinal", "interval"}:
        raise ValueError("Unknown agreement metric")
    units = [Counter(v for v in row if v is not None) for row in ratings_matrix]
    units = [c for c in units if c.total() >= 2]
    values = set().union(*(set(c) for c in units)) if units else set()
    if not values:
        return AgreementEstimate(None, "no_paired_observations")
    if categories is None:
        if metric == "ordinal" and values <= set(_LEGACY_ORDER):
            categories = _LEGACY_ORDER
        elif metric == "ordinal":
            raise ValueError("Ordinal labels require an explicit category order")
        else:
            categories = sorted(values, key=str)
    if len(set(categories)) != len(categories) or not values <= set(categories):
        raise ValueError("Invalid category domain")
    index = {v: i for i, v in enumerate(categories)}
    k = len(categories)
    coincidence = [[0.0] * k for _ in range(k)]
    for counts in units:
        m = counts.total()
        for a, na in counts.items():
            for b, nb in counts.items():
                coincidence[index[a]][index[b]] += na * (nb - (a == b)) / (m - 1)
    marginals = [sum(row) for row in coincidence]
    total = sum(marginals)
    prefix = [0.0]
    for n in marginals:
        prefix.append(prefix[-1] + n)
    observed = expected = 0.0
    for a in range(k):
        for b in range(k):
            if metric == "nominal":
                distance = float(a != b)
            elif metric == "interval":
                distance = (float(categories[a]) - float(categories[b])) ** 2
            else:
                lo, hi = sorted((a, b))
                distance = (prefix[hi + 1] - prefix[lo] - (marginals[a] + marginals[b]) / 2) ** 2
            observed += coincidence[a][b] * distance
            expected += marginals[a] * (marginals[b] - (a == b)) / (total - 1) * distance
    if expected == 0:
        return AgreementEstimate(None, "zero_expected_disagreement")
    return AgreementEstimate(1 - observed / expected, None)


def krippendorffs_alpha(ratings_matrix, *, metric="nominal", categories=None) -> float | None:
    return alpha_estimate(ratings_matrix, metric=metric, categories=categories).value


def compute_batch_iaa(
    judge_evals: list[JudgeEvaluation | None], persona_eval_sets: list[list[JudgeEvaluation | None]]
) -> dict:
    judge = [e.final_decision if e else None for e in judge_evals]
    if any(len(p) != len(judge) for p in persona_eval_sets):
        raise ValueError("Candidate sets must remain position aligned")
    personas = [[e.final_decision if e else None for e in p] for p in persona_eval_sets]
    kappas = {f"persona_{i}": cohens_kappa(judge, p) for i, p in enumerate(personas)}
    valid = [v for v in kappas.values() if v is not None]
    estimate = alpha_estimate([[judge[i], *(p[i] for p in personas)] for i in range(len(judge))])
    return dict(
        cohens_kappa_per_persona=kappas,
        avg_cohens_kappa=round(sum(valid) / len(valid), 4) if valid else None,
        krippendorffs_alpha=round(estimate.value, 4) if estimate.value is not None else None,
        alpha_reason=estimate.reason,
        n_raters=1 + len(personas),
        n_items=len(judge),
        low_confidence=None,
        interpretation="candidate_disagreement_diagnostic_only",
    )
