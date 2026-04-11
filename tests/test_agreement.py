"""IAA (Inter-Annotator Agreement) 指标的单元测试。"""

import pytest

from ecoalign_forge.schemas.judge import JudgeEvaluation
from ecoalign_forge.storage.agreement import (
    cohens_kappa,
    compute_batch_iaa,
    krippendorffs_alpha,
    raw_agreement,
)

# ──────────────────────────────────────────────────────────────
# 辅助：快速构造 JudgeEvaluation
# ──────────────────────────────────────────────────────────────

def _eval(decision: str) -> JudgeEvaluation:
    """构造最小 JudgeEvaluation（reasoning_trace 声明未命中规则）。"""
    return JudgeEvaluation(
        has_stealth_marketing=decision in ("T0_Block", "T1_Shadowban"),
        is_ai_slop=decision in ("T0_Block", "T2_Normal"),
        reasoning_trace=(
            "第一步：无明显引流。第二步：未命中。第三步：判定。"
        ),
        final_decision=decision,
    )


# ──────────────────────────────────────────────────────────────
# Raw Agreement
# ──────────────────────────────────────────────────────────────

class TestRawAgreement:
    def test_perfect_agreement(self):
        a = ["T0_Block", "T1_Shadowban", "T2_Normal"]
        assert raw_agreement(a, a) == 1.0

    def test_no_agreement(self):
        a = ["T0_Block", "T0_Block", "T0_Block"]
        b = ["T3_Recommend", "T3_Recommend", "T3_Recommend"]
        assert raw_agreement(a, b) == 0.0

    def test_partial_agreement(self):
        a = ["T0_Block", "T1_Shadowban", "T2_Normal", "T3_Recommend"]
        b = ["T0_Block", "T1_Shadowban", "T3_Recommend", "T2_Normal"]
        assert raw_agreement(a, b) == 0.5

    def test_empty_input(self):
        assert raw_agreement([], []) == 0.0


# ──────────────────────────────────────────────────────────────
# Cohen's Kappa
# ──────────────────────────────────────────────────────────────

class TestCohensKappa:
    def test_perfect_agreement(self):
        a = ["T0_Block", "T1_Shadowban", "T2_Normal"] * 10
        assert cohens_kappa(a, a) == pytest.approx(1.0, abs=0.01)

    def test_random_agreement(self):
        """随机分布的标注应接近 0。"""
        a = ["T0_Block"] * 25 + ["T2_Normal"] * 25
        b = ["T0_Block"] * 25 + ["T2_Normal"] * 25
        # 完全相同 → kappa = 1.0
        assert cohens_kappa(a, b) == pytest.approx(1.0, abs=0.01)

    def test_moderate_agreement(self):
        """中等一致性应在 0.4~0.8 之间。"""
        a = ["T0_Block", "T0_Block", "T2_Normal", "T2_Normal", "T3_Recommend"]
        b = ["T0_Block", "T2_Normal", "T2_Normal", "T2_Normal", "T3_Recommend"]
        kappa = cohens_kappa(a, b)
        assert 0.2 < kappa < 0.9

    def test_empty_input(self):
        assert cohens_kappa([], []) == 0.0


# ──────────────────────────────────────────────────────────────
# Krippendorff's Alpha
# ──────────────────────────────────────────────────────────────

class TestKrippendorffsAlpha:
    def test_perfect_agreement(self):
        matrix = [
            ["T0_Block", "T0_Block", "T0_Block"],
            ["T2_Normal", "T2_Normal", "T2_Normal"],
            ["T3_Recommend", "T3_Recommend", "T3_Recommend"],
        ]
        assert krippendorffs_alpha(matrix) == pytest.approx(1.0, abs=0.01)

    def test_with_missing_values(self):
        """含 None 缺失值仍可计算。"""
        matrix = [
            ["T0_Block", "T0_Block", None],
            ["T2_Normal", None, "T2_Normal"],
            ["T3_Recommend", "T3_Recommend", "T3_Recommend"],
        ]
        alpha = krippendorffs_alpha(matrix)
        assert alpha > 0.5

    def test_ordinal_metric(self):
        """序数尺度下近邻不一致(T0↔T1)应比远端不一致(T0↔T3)产出更高 alpha。"""
        # 混合数据：部分一致 + 部分近邻不一致
        near = [
            ["T0_Block", "T0_Block"],
            ["T0_Block", "T1_Shadowban"],
            ["T2_Normal", "T2_Normal"],
            ["T3_Recommend", "T2_Normal"],
        ]
        # 混合数据：部分一致 + 部分远端不一致
        far = [
            ["T0_Block", "T0_Block"],
            ["T0_Block", "T3_Recommend"],
            ["T2_Normal", "T2_Normal"],
            ["T3_Recommend", "T0_Block"],
        ]
        alpha_near = krippendorffs_alpha(near, metric="ordinal")
        alpha_far = krippendorffs_alpha(far, metric="ordinal")
        assert alpha_near > alpha_far

    def test_empty_matrix(self):
        assert krippendorffs_alpha([]) == 0.0


# ──────────────────────────────────────────────────────────────
# compute_batch_iaa
# ──────────────────────────────────────────────────────────────

class TestComputeBatchIAA:
    def test_basic_iaa(self):
        judge = [_eval("T0_Block"), _eval("T2_Normal"), _eval("T3_Recommend")]
        mod_0 = [_eval("T0_Block"), _eval("T2_Normal"), _eval("T2_Normal")]
        mod_1 = [_eval("T0_Block"), _eval("T1_Shadowban"), _eval("T3_Recommend")]

        result = compute_batch_iaa(judge, [mod_0, mod_1])
        assert "cohens_kappa_per_persona" in result
        assert "krippendorffs_alpha" in result
        assert result["n_raters"] == 3
        assert result["n_items"] == 3
        assert isinstance(result["low_confidence"], bool)

    def test_with_none_evals(self):
        judge = [_eval("T0_Block"), None, _eval("T2_Normal")]
        mod_0 = [_eval("T0_Block"), _eval("T2_Normal"), None]

        result = compute_batch_iaa(judge, [mod_0])
        # 只有位置 0 两者都有效
        assert result["n_raters"] == 2
        assert "persona_0" in result["cohens_kappa_per_persona"]

    def test_perfect_agreement_high_confidence(self):
        decisions = ["T0_Block", "T2_Normal", "T3_Recommend"] * 5
        judge = [_eval(d) for d in decisions]
        mod = [_eval(d) for d in decisions]

        result = compute_batch_iaa(judge, [mod])
        assert result["low_confidence"] is False
        assert result["avg_cohens_kappa"] > 0.8
