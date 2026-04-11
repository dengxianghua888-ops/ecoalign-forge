"""Inter-Annotator Agreement — 多评审 Agent 标注者一致性指标。

核心指标：
- Cohen's Kappa：衡量两个评审者间的一致性（排除偶然一致）
- Krippendorff's Alpha：支持多评审者、缺失值和序数尺度
- 原始一致率（Raw Agreement）：基础参考线

使用场景：
- Judge vs 单个 Moderator persona → Cohen's Kappa
- Judge vs 多个 Moderator persona → Krippendorff's Alpha
- IAA 低于阈值时标记该批次数据为"低置信度"
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from itertools import combinations

from ecoalign_forge.schemas.judge import JudgeEvaluation

# 分发分级 → 序数编码（用于 Krippendorff's Alpha 的距离函数）
_DECISION_ORDINAL: dict[str, int] = {
    "T0_Block": 0,
    "T1_Shadowban": 1,
    "T2_Normal": 2,
    "T3_Recommend": 3,
}

# IAA 置信度阈值（低于此值标记为低置信度）
IAA_LOW_CONFIDENCE_THRESHOLD = 0.4


def raw_agreement(
    rater_a: Sequence[str],
    rater_b: Sequence[str],
) -> float:
    """计算两个评审者的原始一致率。

    Args:
        rater_a: 评审者 A 的决策序列
        rater_b: 评审者 B 的决策序列

    Returns:
        一致比例 [0.0, 1.0]
    """
    if len(rater_a) != len(rater_b) or not rater_a:
        return 0.0
    matches = sum(1 for a, b in zip(rater_a, rater_b, strict=True) if a == b)
    return matches / len(rater_a)


def cohens_kappa(
    rater_a: Sequence[str],
    rater_b: Sequence[str],
) -> float:
    """计算 Cohen's Kappa 系数。

    κ = (p_o - p_e) / (1 - p_e)
    其中 p_o 是观察到的一致率，p_e 是偶然一致的概率。

    Args:
        rater_a: 评审者 A 的决策序列
        rater_b: 评审者 B 的决策序列

    Returns:
        Kappa 系数 [-1.0, 1.0]，> 0.6 表示中等以上一致性
    """
    n = len(rater_a)
    if n != len(rater_b) or n == 0:
        return 0.0

    # 观察一致率
    p_o = raw_agreement(rater_a, rater_b)

    # 偶然一致率（基于各评审者的边际分布）
    categories = set(rater_a) | set(rater_b)
    count_a = Counter(rater_a)
    count_b = Counter(rater_b)
    p_e = sum((count_a[c] / n) * (count_b[c] / n) for c in categories)

    if p_e == 1.0:
        # 完全偶然一致（理论边界），返回 0
        return 0.0

    return (p_o - p_e) / (1.0 - p_e)


def krippendorffs_alpha(
    ratings_matrix: list[list[str | None]],
    *,
    metric: str = "nominal",
) -> float:
    """计算 Krippendorff's Alpha 系数（支持多评审者和缺失值）。

    Alpha = 1 - D_o / D_e
    其中 D_o 是观察到的不一致度，D_e 是期望不一致度。

    Args:
        ratings_matrix: N_items × N_raters 的矩阵，None 表示缺失
        metric: 距离函数类型
            - "nominal": 名义尺度（相同=0, 不同=1）
            - "ordinal": 序数尺度（基于 T0~T3 的距离平方）

    Returns:
        Alpha 系数 [-1.0, 1.0]，> 0.667 表示可接受
    """
    if not ratings_matrix:
        return 0.0

    # 距离函数
    if metric == "ordinal":
        def distance(a: str, b: str) -> float:
            return (_DECISION_ORDINAL.get(a, 0) - _DECISION_ORDINAL.get(b, 0)) ** 2
    else:
        def distance(a: str, b: str) -> float:
            return 0.0 if a == b else 1.0

    # 收集所有有效配对
    # D_o: 每个 item 内所有 rater 配对的不一致度
    d_o_sum = 0.0
    n_pairs_total = 0
    all_values: list[str] = []

    for item_ratings in ratings_matrix:
        # 过滤 None
        valid = [r for r in item_ratings if r is not None]
        if len(valid) < 2:
            continue
        all_values.extend(valid)

        # 该 item 内所有 rater 配对
        for a, b in combinations(valid, 2):
            d_o_sum += distance(a, b)
            n_pairs_total += 1

    if n_pairs_total == 0:
        return 0.0

    d_o = d_o_sum / n_pairs_total

    # D_e: 期望不一致度（从全部观察值的边际分布计算）
    n_total = len(all_values)
    if n_total < 2:
        return 0.0

    d_e_sum = 0.0
    n_e_pairs = 0
    for a, b in combinations(all_values, 2):
        d_e_sum += distance(a, b)
        n_e_pairs += 1

    d_e = d_e_sum / n_e_pairs if n_e_pairs > 0 else 0.0

    if d_e == 0.0:
        # 所有评审完全一致
        return 1.0

    return 1.0 - d_o / d_e


def compute_batch_iaa(
    judge_evals: list[JudgeEvaluation | None],
    persona_eval_sets: list[list[JudgeEvaluation | None]],
) -> dict:
    """计算一个批次的 IAA 指标。

    Args:
        judge_evals: Judge 金标判决（与 cases 位置对齐）
        persona_eval_sets: N 个 Moderator persona 的判决集合

    Returns:
        包含 kappa_per_persona、alpha、raw_agreement、low_confidence 的字典
    """
    n_items = len(judge_evals)

    # 提取 Judge 决策序列（跳过 None 位置）
    judge_decisions = [
        e.final_decision if e is not None else None
        for e in judge_evals
    ]

    # 每个 persona 计算 Cohen's Kappa
    kappa_per_persona: dict[str, float] = {}
    for idx, persona_evals in enumerate(persona_eval_sets):
        persona_decisions = [
            e.final_decision if e is not None else None
            for e in persona_evals
        ]
        # 只取两者都有效的位置
        valid_pairs = [
            (j, p)
            for j, p in zip(judge_decisions, persona_decisions, strict=True)
            if j is not None and p is not None
        ]
        if valid_pairs:
            j_valid, p_valid = zip(*valid_pairs, strict=True)
            kappa = cohens_kappa(list(j_valid), list(p_valid))
        else:
            kappa = 0.0
        kappa_per_persona[f"persona_{idx}"] = kappa

    # 构造 Krippendorff's Alpha 的评分矩阵（所有评审者）
    n_raters = 1 + len(persona_eval_sets)  # Judge + N personas
    ratings_matrix: list[list[str | None]] = []
    for i in range(n_items):
        item_ratings: list[str | None] = [judge_decisions[i]]
        for persona_evals in persona_eval_sets:
            if i < len(persona_evals) and persona_evals[i] is not None:
                item_ratings.append(persona_evals[i].final_decision)
            else:
                item_ratings.append(None)
        ratings_matrix.append(item_ratings)

    alpha = krippendorffs_alpha(ratings_matrix, metric="ordinal")
    avg_kappa = (
        sum(kappa_per_persona.values()) / len(kappa_per_persona)
        if kappa_per_persona
        else 0.0
    )

    return {
        "cohens_kappa_per_persona": kappa_per_persona,
        "avg_cohens_kappa": round(avg_kappa, 4),
        "krippendorffs_alpha": round(alpha, 4),
        "n_raters": n_raters,
        "n_items": n_items,
        "low_confidence": alpha < IAA_LOW_CONFIDENCE_THRESHOLD,
    }
