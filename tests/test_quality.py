"""数据质量评分模块的单元测试。"""

import json

from ecoalign_forge.quality.scorer import QualityReport, QualityScorer
from ecoalign_forge.schemas.dpo import DPO_Pair


def _make_pair(
    chosen_decision: str = "T0_Block",
    rejected_decision: str = "T2_Normal",
    reasoning: str = "第一步：发现微信号。第二步：命中 A-001 和 A-003 规则。第三步：判定 T0_Block。",
    gap: float = 0.8,
) -> DPO_Pair:
    chosen = json.dumps({
        "has_stealth_marketing": True,
        "is_ai_slop": False,
        "reasoning_trace": reasoning,
        "final_decision": chosen_decision,
    })
    rejected = json.dumps({
        "has_stealth_marketing": False,
        "is_ai_slop": False,
        "reasoning_trace": "第一步：看起来正常。第二步：未命中。第三步：通过。",
        "final_decision": rejected_decision,
    })
    return DPO_Pair(
        prompt="Moderate this",
        chosen=chosen,
        rejected=rejected,
        chosen_score=1.0,
        rejected_score=0.2,
        preference_gap=gap,
        dimension="stealth_marketing",
        difficulty="hard",
        source_case_id="case-001",
    )


class TestQualityScorer:
    def test_high_quality_pair(self):
        scorer = QualityScorer()
        pair = _make_pair()
        report = scorer.score(pair)
        assert report.overall > 0.5
        assert report.low_quality is False
        assert report.reasoning_depth > 0.0
        assert report.preference_clarity == 0.8

    def test_low_quality_no_reasoning(self):
        scorer = QualityScorer()
        pair = _make_pair(reasoning="判为违规", gap=0.1)
        report = scorer.score(pair)
        assert report.reasoning_depth == 0.0
        assert report.response_completeness <= 0.5

    def test_decision_consistency_normal(self):
        """chosen 比 rejected 更严格 → 一致性 1.0"""
        scorer = QualityScorer()
        pair = _make_pair(chosen_decision="T0_Block", rejected_decision="T2_Normal")
        report = scorer.score(pair)
        assert report.decision_consistency == 1.0

    def test_decision_consistency_same(self):
        """同档位 → 一致性 0.5"""
        scorer = QualityScorer()
        pair = _make_pair(
            chosen_decision="T2_Normal",
            rejected_decision="T2_Normal",
            gap=0.3,
        )
        report = scorer.score(pair)
        assert report.decision_consistency == 0.5

    def test_batch_scoring(self):
        scorer = QualityScorer()
        pairs = [_make_pair(), _make_pair(gap=0.3)]
        reports = scorer.score_batch(pairs)
        assert len(reports) == 2
        assert all(isinstance(r, QualityReport) for r in reports)

    def test_to_dict(self):
        scorer = QualityScorer()
        report = scorer.score(_make_pair())
        d = report.to_dict()
        assert "overall" in d
        assert "reasoning_depth" in d
        assert len(d) == 6


class TestTaxonomy:
    def test_harm_taxonomy_loaded(self):
        from ecoalign_forge.taxonomy import HARM_TAXONOMY
        assert "stealth_marketing" in HARM_TAXONOMY
        assert "ai_slop" in HARM_TAXONOMY
        assert "jailbreak" in HARM_TAXONOMY

    def test_attack_registry_loaded(self):
        from ecoalign_forge.taxonomy import ATTACK_REGISTRY
        assert len(ATTACK_REGISTRY) > 5
        # 验证已实现的攻击标记
        implemented = [a for a in ATTACK_REGISTRY.values() if a.implemented]
        assert len(implemented) > 3

    def test_evol_strategies_loaded(self):
        from ecoalign_forge.taxonomy import EVOL_STRATEGIES
        depth = [s for s in EVOL_STRATEGIES.values() if s.direction == "depth"]
        breadth = [s for s in EVOL_STRATEGIES.values() if s.direction == "breadth"]
        assert len(depth) >= 3
        assert len(breadth) >= 2
