"""Phase 2 模块的单元测试：Constitutional AI、飞轮、自适应采样、HTML 报告。"""

import json

import pytest

from ecoalign_forge.exceptions import EcoAlignError
from ecoalign_forge.schemas.chaos import (
    AttackStrategy,
    ChaosCase,
    Difficulty,
    ExpectedAction,
)
from ecoalign_forge.schemas.dpo import DPO_Pair
from ecoalign_forge.schemas.execution import ExecutionMode
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
        chosen=json.dumps(
            {
                "has_stealth_marketing": True,
                "is_ai_slop": False,
                "reasoning_trace": "第一步：发现。第二步：命中 A-001。第三步：判定。",
                "final_decision": "T0_Block",
            }
        ),
        rejected=json.dumps(
            {
                "has_stealth_marketing": False,
                "is_ai_slop": False,
                "reasoning_trace": "未命中",
                "final_decision": "T2_Normal",
            }
        ),
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
        assert stats.correction_rate is None
        assert stats.consistency_rate is None

    def test_stats_tracking(self):
        from ecoalign_forge.agents.constitutional import ConstitutionalStats

        stats = ConstitutionalStats()
        stats.total_reviewed = 10
        stats.total_passed = 7
        stats.total_corrected = 3
        assert stats.correction_rate == 0.3
        assert stats.consistency_rate == 0.7

    def test_stats_to_dict(self):
        from ecoalign_forge.agents.constitutional import ConstitutionalStats

        stats = ConstitutionalStats(total_reviewed=5, total_passed=4, total_corrected=1)
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
    def test_legacy_python_constructor_warns_and_preserves_severity(self):
        from ecoalign_forge.engine.flywheel import RoundMetrics

        with pytest.warns(DeprecationWarning, match="avg_decision_severity"):
            metrics = RoundMetrics(round_id=1, avg_quality_score=0.8)
        assert metrics.avg_decision_severity == 0.8
        assert metrics.avg_pair_quality_heuristic is None
        with pytest.warns(DeprecationWarning, match="avg_decision_severity"):
            canonical = RoundMetrics(round_id=1, avg_quality_score=0.8, avg_decision_severity=0.2)
        assert canonical.avg_decision_severity == 0.2

    def test_round_metrics(self):
        from ecoalign_forge.engine.flywheel import RoundMetrics

        metrics = RoundMetrics(
            round_id=1,
            execution_mode=ExecutionMode.DEMO,
            run_id="demo-1",
            total_dpo_pairs=100,
            avg_decision_severity=0.7,
            avg_pair_quality_heuristic=0.8,
        )
        data = metrics.to_dict()
        assert data["round_id"] == 1
        assert data["execution_mode"] == "demo"
        assert data["run_id"] == "demo-1"
        assert data["avg_decision_severity"] == 0.7
        assert data["avg_pair_quality_heuristic"] == 0.8
        assert data["correction_rate"] is None
        assert data["judge_model"] is None
        assert "avg_quality_score" not in data
        with pytest.warns(DeprecationWarning, match="avg_decision_severity"):
            assert metrics.avg_quality_score == 0.7

    def test_flywheel_state_does_not_infer_quality(self):
        from ecoalign_forge.engine.flywheel import FlyWheelState, RoundMetrics

        state = FlyWheelState(execution_mode=ExecutionMode.MOCK)
        state.add_round(
            RoundMetrics(
                round_id=1,
                execution_mode=ExecutionMode.MOCK,
                total_dpo_pairs=50,
                avg_decision_severity=0.5,
                avg_pair_quality_heuristic=0.6,
            )
        )
        state.add_round(
            RoundMetrics(
                round_id=2,
                execution_mode=ExecutionMode.MOCK,
                total_dpo_pairs=60,
                avg_decision_severity=0.7,
                avg_pair_quality_heuristic=0.9,
            )
        )
        assert state.current_round == 2
        assert state.cumulative_dpo_pairs == 110
        assert state.severity_trend == [0.5, 0.7]
        assert state.pair_quality_heuristic_trend == [0.6, 0.9]
        assert state.quality_trend == []
        assert state.quality_improvement is None
        assert state.round_over_round_improvement is None

    def test_flywheel_persistence(self, tmp_path):
        from ecoalign_forge.engine.flywheel import FlyWheelState, RoundMetrics

        path = tmp_path / "fw.json"
        state = FlyWheelState(execution_mode=ExecutionMode.DEMO)
        state.add_round(
            RoundMetrics(
                round_id=1,
                execution_mode=ExecutionMode.DEMO,
                run_id="run-1",
                total_dpo_pairs=50,
                avg_decision_severity=0.6,
            )
        )
        state.save(path)
        loaded = FlyWheelState.load(path)
        assert loaded.current_round == 1
        assert loaded.cumulative_dpo_pairs == 50
        assert loaded.execution_mode is ExecutionMode.DEMO
        assert loaded.rounds[0].run_id == "run-1"
        assert loaded.rounds[0].avg_pair_quality_heuristic is None
        assert loaded.to_dict()["quality_improvement"] is None

    def test_severity_cannot_trigger_convergence(self, tmp_path):
        from ecoalign_forge.engine.flywheel import FlyWheelOrchestrator, RoundMetrics

        fw = FlyWheelOrchestrator(
            state_path=tmp_path / "fw.json",
            convergence_threshold=0.02,
            execution_mode=ExecutionMode.MOCK,
            max_rounds=3,
        )
        for number, severity in enumerate([0.70, 0.705], 1):
            fw.record_round(
                RoundMetrics(
                    round_id=number,
                    execution_mode=ExecutionMode.MOCK,
                    total_dpo_pairs=50,
                    avg_decision_severity=severity,
                )
            )
        assert fw.has_converged is None
        assert fw.should_continue is True
        assert fw.get_summary()["total_improvement"] is None
        assert fw.get_summary()["evaluation_status"] == "not_evaluated"
        fw.record_round(RoundMetrics(round_id=3, execution_mode=ExecutionMode.MOCK))
        assert fw.should_continue is False  # Only the explicit round cap applies.

    def test_legacy_quality_is_read_as_severity_only(self, tmp_path):
        from ecoalign_forge.engine.flywheel import FlyWheelOrchestrator, FlyWheelState

        path = tmp_path / "legacy.json"
        path.write_text(
            json.dumps(
                {
                    "current_round": 1,
                    "cumulative_dpo_pairs": 10,
                    "quality_trend": [0.8],
                    "quality_improvement": 0.9,
                    "rounds": [{"round_id": 1, "total_dpo_pairs": 10, "avg_quality_score": 0.8}],
                }
            )
        )
        with pytest.warns(DeprecationWarning, match="avg_decision_severity"):
            state = FlyWheelState.load(path)
        assert state.execution_mode is ExecutionMode.UNKNOWN
        assert state.rounds[0].execution_mode is ExecutionMode.UNKNOWN
        assert state.rounds[0].avg_decision_severity == 0.8
        assert state.rounds[0].avg_pair_quality_heuristic is None
        assert state.quality_trend == []
        assert state.quality_improvement is None
        with pytest.warns(DeprecationWarning), pytest.raises(EcoAlignError, match="mode"):
            FlyWheelOrchestrator(state_path=path, execution_mode=ExecutionMode.LIVE)

    def test_modes_cannot_mix(self):
        from ecoalign_forge.engine.flywheel import FlyWheelState, RoundMetrics

        state = FlyWheelState(execution_mode=ExecutionMode.LIVE)
        with pytest.raises(EcoAlignError, match="modes"):
            state.add_round(RoundMetrics(round_id=1, execution_mode=ExecutionMode.DEMO))
        assert state.rounds == []
        assert state.cumulative_dpo_pairs == 0


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
            avg_decision_severity=0.72,
            avg_preference_gap=0.65,
            interception_rate=0.45,
            decision_counts={
                "T0_Block": 20,
                "T1_Shadowban": 25,
                "T2_Normal": 40,
                "T3_Recommend": 15,
            },
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
            avg_decision_severity=0.6,
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
            avg_decision_severity=0.8,
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
        assert "+60.0%" not in content
        assert "未评估" in content
        assert "模型质量提升" in content
        assert "训练收敛" in content

    def test_report_with_quality_histogram(self, tmp_path):
        from ecoalign_forge.reports.html_report import generate_html_report

        scores = [0.1, 0.3, 0.5, 0.7, 0.9, 0.6, 0.8, 0.4, 0.85, 0.65]
        path = generate_html_report(
            total_pairs=10,
            avg_decision_severity=0.6,
            severity_distribution=scores,
            output_path=tmp_path / "report_hist.html",
        )
        content = path.read_text()
        assert "判决严重度分布" in content
        assert "<svg" in content
