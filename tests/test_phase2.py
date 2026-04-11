"""Phase 2 模块的单元测试：Constitutional AI、飞轮、自适应采样、HTML 报告。"""

import json

from ecoalign_forge.schemas.chaos import (
    AttackStrategy,
    ChaosCase,
    Difficulty,
    ExpectedAction,
)
from ecoalign_forge.schemas.dpo import DPO_Pair
from ecoalign_forge.schemas.judge import JudgeEvaluation

# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

def _eval(decision: str = "T0_Block") -> JudgeEvaluation:
    return JudgeEvaluation(
        has_stealth_marketing=decision in ("T0_Block", "T1_Shadowban"),
        is_ai_slop=decision in ("T0_Block", "T2_Normal"),
        reasoning_trace="第一步：发现微信号。第二步：命中 A-001 规则。第三步：未命中。",
        final_decision=decision,
    )


def _case(
    dim: str = "stealth_marketing",
    diff: str = "medium",
) -> ChaosCase:
    return ChaosCase(
        content="测试内容",
        attack_strategy=AttackStrategy.DIRECT,
        target_dimension=dim,
        difficulty=Difficulty(diff),
        expected_action=ExpectedAction.BLOCK,
        reasoning="测试",
    )


def _pair(gap: float = 0.8) -> DPO_Pair:
    return DPO_Pair(
        prompt="Moderate",
        chosen=json.dumps({
            "has_stealth_marketing": True, "is_ai_slop": False,
            "reasoning_trace": "第一步：发现。第二步：命中 A-001。第三步：判定。",
            "final_decision": "T0_Block",
        }),
        rejected=json.dumps({
            "has_stealth_marketing": False, "is_ai_slop": False,
            "reasoning_trace": "未命中", "final_decision": "T2_Normal",
        }),
        chosen_score=1.0,
        rejected_score=0.2,
        preference_gap=gap,
        dimension="stealth_marketing",
        difficulty="hard",
        source_case_id="c1",
    )


# ──────────────────────────────────────────────────────────────
# Constitutional AI
# ──────────────────────────────────────────────────────────────

class TestConstitutionalReviewer:
    def test_stats_initial(self):
        from ecoalign_forge.agents.constitutional import ConstitutionalStats
        stats = ConstitutionalStats()
        assert stats.correction_rate == 0.0
        assert stats.consistency_rate == 1.0

    def test_stats_tracking(self):
        from ecoalign_forge.agents.constitutional import ConstitutionalStats
        stats = ConstitutionalStats()
        stats.total_reviewed = 10
        stats.total_corrected = 3
        assert stats.correction_rate == 0.3
        assert stats.consistency_rate == 0.7

    def test_stats_to_dict(self):
        from ecoalign_forge.agents.constitutional import ConstitutionalStats
        stats = ConstitutionalStats(total_reviewed=5, total_corrected=1)
        d = stats.to_dict()
        assert d["correction_rate"] == 0.2
        assert d["consistency_rate"] == 0.8

    def test_critique_result_dataclass(self):
        from ecoalign_forge.agents.constitutional import CritiqueResult
        ev = _eval("T0_Block")
        result = CritiqueResult(original=ev, is_consistent=True)
        assert result.corrected is None
        assert result.issues_found == []


# ──────────────────────────────────────────────────────────────
# FlyWheel
# ──────────────────────────────────────────────────────────────

class TestFlyWheel:
    def test_round_metrics(self):
        from ecoalign_forge.engine.flywheel import RoundMetrics
        m = RoundMetrics(round_id=1, total_dpo_pairs=100, avg_quality_score=0.7)
        d = m.to_dict()
        assert d["round_id"] == 1
        assert d["avg_quality_score"] == 0.7

    def test_flywheel_state(self):
        from ecoalign_forge.engine.flywheel import FlyWheelState, RoundMetrics
        state = FlyWheelState()
        state.add_round(RoundMetrics(round_id=1, total_dpo_pairs=50, avg_quality_score=0.5))
        state.add_round(RoundMetrics(round_id=2, total_dpo_pairs=60, avg_quality_score=0.7))
        assert state.current_round == 2
        assert state.cumulative_dpo_pairs == 110
        assert state.quality_improvement > 0

    def test_flywheel_persistence(self, tmp_path):
        from ecoalign_forge.engine.flywheel import FlyWheelState, RoundMetrics
        path = tmp_path / "fw.json"
        state = FlyWheelState()
        state.add_round(RoundMetrics(round_id=1, total_dpo_pairs=50, avg_quality_score=0.6))
        state.save(path)

        loaded = FlyWheelState.load(path)
        assert loaded.current_round == 1
        assert loaded.cumulative_dpo_pairs == 50

    def test_convergence_detection(self):
        from ecoalign_forge.engine.flywheel import FlyWheelOrchestrator, RoundMetrics
        fw = FlyWheelOrchestrator(convergence_threshold=0.02)
        fw.record_round(RoundMetrics(round_id=1, total_dpo_pairs=50, avg_quality_score=0.70))
        fw.record_round(RoundMetrics(round_id=2, total_dpo_pairs=50, avg_quality_score=0.705))
        # 0.7% 提升 < 2% 阈值 → 已收敛
        assert fw.has_converged is True
        assert fw.should_continue is False


# ──────────────────────────────────────────────────────────────
# Adaptive Sampler
# ──────────────────────────────────────────────────────────────

class TestAdaptiveSampler:
    def test_coverage_analysis(self):
        from ecoalign_forge.engine.adaptive_sampler import AdaptiveSampler
        sampler = AdaptiveSampler()
        cases = [
            _case("stealth_marketing", "easy"),
            _case("stealth_marketing", "medium"),
            _case("stealth_marketing", "hard"),
        ]
        report = sampler.analyze_coverage(cases)
        assert report.dimension_counts["stealth_marketing"] == 3
        assert "ai_slop" in report.undersampled_dimensions
        assert report.coverage_score > 0

    def test_undersampled_combinations(self):
        from ecoalign_forge.engine.adaptive_sampler import AdaptiveSampler
        sampler = AdaptiveSampler(min_samples_per_cell=10)
        cases = [_case("stealth_marketing", "easy") for _ in range(5)]
        report = sampler.analyze_coverage(cases)
        # 很多组合都是欠采样的
        assert len(report.undersampled_combinations) > 0

    def test_suggest_distribution(self):
        from ecoalign_forge.engine.adaptive_sampler import AdaptiveSampler
        sampler = AdaptiveSampler()
        cases = [_case() for _ in range(10)]
        report = sampler.analyze_coverage(cases)
        dist = sampler.suggest_distribution(report, curriculum_stage="mid")
        assert abs(sum(dist.values()) - 1.0) < 0.01

    def test_curriculum_stages(self):
        from ecoalign_forge.engine.adaptive_sampler import AdaptiveSampler
        sampler = AdaptiveSampler()
        assert sampler.get_curriculum_stage(10) == "early"
        assert sampler.get_curriculum_stage(100) == "mid"
        assert sampler.get_curriculum_stage(500) == "late"

    def test_coverage_report_to_dict(self):
        from ecoalign_forge.engine.adaptive_sampler import AdaptiveSampler
        sampler = AdaptiveSampler()
        cases = [_case() for _ in range(5)]
        report = sampler.analyze_coverage(cases)
        d = report.to_dict()
        assert "coverage_score" in d
        assert "undersampled_dimensions" in d


# ──────────────────────────────────────────────────────────────
# HTML Report
# ──────────────────────────────────────────────────────────────

class TestHTMLReport:
    def test_basic_report(self, tmp_path):
        from ecoalign_forge.reports.html_report import generate_html_report
        path = generate_html_report(
            total_pairs=100,
            avg_quality=0.72,
            avg_preference_gap=0.65,
            interception_rate=0.45,
            decision_counts={"T0_Block": 20, "T1_Shadowban": 25, "T2_Normal": 40, "T3_Recommend": 15},
            output_path=tmp_path / "report.html",
        )
        assert path.exists()
        content = path.read_text()
        assert "EcoAlign-Forge" in content
        assert "100" in content
        assert "0.72" in content

    def test_report_with_iaa(self, tmp_path):
        from ecoalign_forge.reports.html_report import generate_html_report
        path = generate_html_report(
            total_pairs=50,
            avg_quality=0.6,
            iaa_metrics={
                "avg_cohens_kappa": 0.75,
                "krippendorffs_alpha": 0.68,
                "low_confidence": False,
            },
            output_path=tmp_path / "report_iaa.html",
        )
        content = path.read_text()
        assert "Kappa" in content
        assert "0.75" in content

    def test_report_with_flywheel(self, tmp_path):
        from ecoalign_forge.reports.html_report import generate_html_report
        path = generate_html_report(
            total_pairs=200,
            avg_quality=0.8,
            flywheel_summary={
                "total_rounds": 3,
                "cumulative_dpo_pairs": 200,
                "quality_trend": [0.5, 0.65, 0.8],
                "total_improvement": "+60.0%",
            },
            output_path=tmp_path / "report_fw.html",
        )
        content = path.read_text()
        assert "飞轮" in content
        assert "+60.0%" in content

    def test_report_with_quality_histogram(self, tmp_path):
        from ecoalign_forge.reports.html_report import generate_html_report
        scores = [0.1, 0.3, 0.5, 0.7, 0.9, 0.6, 0.8, 0.4, 0.85, 0.65]
        path = generate_html_report(
            total_pairs=10,
            avg_quality=0.6,
            quality_distribution=scores,
            output_path=tmp_path / "report_hist.html",
        )
        content = path.read_text()
        assert "质量分数分布" in content
        assert "<svg" in content
