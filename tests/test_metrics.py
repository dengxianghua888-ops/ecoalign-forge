"""MetricsCollector 和 DashboardBridge 测试"""

from __future__ import annotations

from pathlib import Path

import pytest

from ecoalign_forge.schemas.chaos import ChaosCase
from ecoalign_forge.schemas.dpo import DPO_Pair
from ecoalign_forge.schemas.judge import JudgeEvaluation
from ecoalign_forge.storage.dashboard_bridge import DashboardBridge, DashboardSnapshot
from ecoalign_forge.storage.metrics import MetricsCollector


def _make_case(
    dimension: str = "stealth_marketing",
    strategy: str = "direct_violation",
) -> ChaosCase:
    return ChaosCase(
        content="测试内容",
        attack_strategy=strategy,
        target_dimension=dimension,
        difficulty="medium",
        expected_action="BLOCK",
        reasoning="测试",
    )


def _make_evaluation(
    *,
    has_stealth: bool = True,
    has_slop: bool = False,
    decision: str = "T1_Shadowban",
) -> JudgeEvaluation:
    """构造一个 JudgeEvaluation，reasoning_trace 引用合法规则编号
    或显式声明未命中（满足 schema 强校验）。"""
    if has_stealth and has_slop:
        cite = "命中 A-002 + B-003"
    elif has_stealth:
        cite = "命中 A-002"
    elif has_slop:
        cite = "命中 B-003"
    else:
        cite = "未命中任何 A/B 规则"
    return JudgeEvaluation(
        has_stealth_marketing=has_stealth,
        is_ai_slop=has_slop,
        reasoning_trace=(
            f"第一步：观察到测试特征\n"
            f"第二步：{cite}\n"
            f"第三步：定级 {decision}"
        ),
        final_decision=decision,  # type: ignore[arg-type]
    )


def _make_response(decision: str = "T2_Normal") -> JudgeEvaluation:
    """Moderator 的初级判决（凭直觉，可能是任何 tier）。
    Moderator 不引用规则，全部用'未命中'声明绕过 schema 校验。"""
    return _make_evaluation(has_stealth=False, has_slop=False, decision=decision)


def _make_dpo_pair() -> DPO_Pair:
    return DPO_Pair(
        prompt="p", chosen="c", rejected="r",
        chosen_score=0.9, rejected_score=0.3,
        preference_gap=0.6, dimension="stealth_marketing",
        difficulty="medium", source_case_id="case-1",
    )


class TestMetricsCollector:
    """MetricsCollector 单元测试"""

    def test_empty_metrics(self) -> None:
        """空状态返回零值"""
        mc = MetricsCollector()
        assert mc.avg_quality_score == 0.0
        assert mc.interception_rate == 0.0
        assert mc.decision_counts == {
            "T0_Block": 0, "T1_Shadowban": 0, "T2_Normal": 0, "T3_Recommend": 0
        }
        assert mc.dimension_stats == {}

    def test_record_batch_updates_counts(self) -> None:
        """record_batch 正确更新计数"""
        mc = MetricsCollector()
        case = _make_case()
        mod_eval = _make_response(decision="T2_Normal")
        ev = _make_evaluation(decision="T1_Shadowban")
        pair = _make_dpo_pair()

        mc.record_batch([case], [mod_eval], [ev], [pair])

        # Judge 判定 T1 → 拦截 1 条；总判决 1 条 → interception_rate = 1.0
        assert mc.decision_counts["T1_Shadowban"] == 1
        assert mc.decision_counts["T2_Normal"] == 0
        assert mc.total_pairs == 1
        # T1_Shadowban 严重度 = 0.7
        assert abs(mc.avg_quality_score - 0.7) < 1e-9
        assert mc.interception_rate == 1.0
        assert mc.stealth_hits == 1
        assert mc.slop_hits == 0
        # Moderator 弱判决也被记录
        assert mc.moderator_decision_counts["T2_Normal"] == 1

    def test_record_batch_strategy_counts(self) -> None:
        """攻击场景计数（旧字段语义保留）"""
        mc = MetricsCollector()
        c1 = _make_case(strategy="direct_violation")
        c2 = _make_case(strategy="edge_case")
        c3 = _make_case(strategy="direct_violation")

        mc.record_batch(
            [c1, c2, c3],
            [_make_response() for _ in range(3)],
            [_make_evaluation() for _ in range(3)],
            [],
        )

        assert mc.strategy_counts["direct_violation"] == 2
        assert mc.strategy_counts["edge_case"] == 1

    def test_rule_coverage_tracks_cited_rules(self) -> None:
        """rule_coverage 累加 reasoning_trace 中引用的 A-XXX/B-XXX"""
        mc = MetricsCollector()
        case = _make_case()
        # _make_evaluation(has_stealth=True) 会在 trace 里写"命中 A-002"
        ev = _make_evaluation(has_stealth=True, has_slop=False, decision="T1_Shadowban")
        mc.record_batch([case], [_make_response()], [ev], [])

        coverage = mc.rule_coverage
        assert coverage["A-002"] == 1
        # 其它规则应为 0
        assert coverage["A-001"] == 0
        assert coverage["B-001"] == 0
        # 未覆盖规则列表应包含其他 11 条
        assert "A-001" in mc.uncovered_rules
        assert "A-002" not in mc.uncovered_rules
        assert len(mc.uncovered_rules) == 11

    def test_rule_coverage_handles_multiple_rules_in_one_trace(self) -> None:
        """单条 reasoning_trace 引用多条规则，每条各 +1"""
        mc = MetricsCollector()
        case = _make_case()
        ev = _make_evaluation(has_stealth=True, has_slop=True, decision="T0_Block")
        # _make_evaluation(stealth+slop) 会写"命中 A-002 + B-003"
        mc.record_batch([case], [_make_response()], [ev], [])

        coverage = mc.rule_coverage
        assert coverage["A-002"] == 1
        assert coverage["B-003"] == 1

    def test_rule_coverage_persisted_in_to_dict(self) -> None:
        """rule_hits 必须在 to_dict 输出和 load 往返中保留"""
        mc = MetricsCollector()
        case = _make_case()
        ev = _make_evaluation(has_stealth=True, decision="T1_Shadowban")
        mc.record_batch([case], [_make_response()], [ev], [])

        d = mc.to_dict()
        assert "rule_hits" in d
        assert d["rule_hits"]["A-002"] == 1

    def test_record_batch_decision_signals(self) -> None:
        """风险信号收集：策略 A/B 命中数 + 各档位计数 + 严重度评分"""
        mc = MetricsCollector()
        case = _make_case()
        ev = _make_evaluation(has_stealth=True, has_slop=True, decision="T0_Block")
        mc.record_batch([case], [_make_response()], [ev], [])

        assert mc.stealth_hits == 1
        assert mc.slop_hits == 1
        assert mc.decision_counts["T0_Block"] == 1
        assert mc.decision_counts["T2_Normal"] == 0
        assert len(mc.severity_scores) == 1
        assert mc.severity_scores[0] == 1.0  # T0_Block 严重度
        assert mc.stealth_marketing_rate == 1.0
        assert mc.ai_slop_rate == 1.0

    def test_moderator_response_can_be_none(self) -> None:
        """Moderator 解析重试用尽（None）应被跳过，不影响其他指标"""
        mc = MetricsCollector()
        case = _make_case()
        ev = _make_evaluation(decision="T1_Shadowban")
        # Moderator 失败 → None
        mc.record_batch([case], [None], [ev], [])

        # Judge 的指标正常累积
        assert mc.decision_counts["T1_Shadowban"] == 1
        # Moderator 没贡献任何数据
        assert sum(mc.moderator_decision_counts.values()) == 0

    def test_record_batch_timeline(self) -> None:
        """批次时间线记录"""
        mc = MetricsCollector()
        case = _make_case()
        mc.record_batch(
            [case], [_make_response()], [_make_evaluation()], [_make_dpo_pair()]
        )

        assert len(mc.batch_timestamps) == 1
        ts = mc.batch_timestamps[0]
        assert ts["cases"] == 1
        assert ts["dpo_pairs"] == 1
        assert "timestamp" in ts

    def test_mixed_decisions(self) -> None:
        """混合 final_decision 的统计"""
        mc = MetricsCollector()
        cases = [_make_case() for _ in range(4)]
        resps = [_make_response() for _ in range(4)]
        evs = [
            _make_evaluation(decision="T0_Block"),
            _make_evaluation(decision="T1_Shadowban"),
            _make_evaluation(decision="T2_Normal"),
            _make_evaluation(decision="T3_Recommend"),
        ]

        mc.record_batch(cases, resps, evs, [])

        assert mc.decision_counts == {
            "T0_Block": 1, "T1_Shadowban": 1, "T2_Normal": 1, "T3_Recommend": 1
        }
        # 拦截率 = (T0 + T1) / 4 = 0.5
        assert abs(mc.interception_rate - 0.5) < 1e-9

    def test_dimension_stats(self) -> None:
        """维度统计：按 target_dimension 累计 + 按 Judge final_decision 计算拦截"""
        mc = MetricsCollector()
        c1 = _make_case(dimension="stealth_marketing")
        c2 = _make_case(dimension="ai_slop")
        evs = [
            _make_evaluation(decision="T0_Block"),    # 拦截
            _make_evaluation(decision="T2_Normal"),   # 不拦截
        ]

        mc.record_batch([c1, c2], [_make_response(), _make_response()], evs, [])

        stats = mc.dimension_stats
        assert stats["stealth_marketing"]["total"] == 1
        assert stats["ai_slop"]["total"] == 1
        # stealth_marketing 被 T0_Block，应有 1 次拦截
        assert stats["stealth_marketing"]["intercepted"] == 1
        assert stats["stealth_marketing"]["interception_rate"] == 1.0
        # ai_slop 被 T2_Normal，无拦截
        assert stats["ai_slop"]["intercepted"] == 0
        assert stats["ai_slop"]["interception_rate"] == 0.0

    def test_to_dict(self) -> None:
        """to_dict 导出所有字段"""
        mc = MetricsCollector()
        case = _make_case()
        mc.record_batch(
            [case], [_make_response()], [_make_evaluation()], [_make_dpo_pair()]
        )

        d = mc.to_dict()
        assert "severity_scores" in d
        assert "strategy_counts" in d
        assert "batch_timestamps" in d
        assert "decision_counts" in d
        assert "moderator_decision_counts" in d
        assert "stealth_hits" in d
        assert "slop_hits" in d
        assert d["total_pairs"] == 1

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """序列化往返"""
        mc = MetricsCollector()
        case = _make_case()
        mc.record_batch(
            [case], [_make_response()], [_make_evaluation()],
            [_make_dpo_pair(), _make_dpo_pair()],
        )

        path = tmp_path / "metrics.json"
        mc.save(path)
        assert path.exists()

        loaded = MetricsCollector.load(path)
        assert loaded.avg_quality_score == mc.avg_quality_score
        assert loaded.decision_counts == mc.decision_counts
        assert loaded.moderator_decision_counts == mc.moderator_decision_counts
        assert loaded.total_pairs == 2
        assert loaded.strategy_counts == mc.strategy_counts

    def test_multiple_batches(self) -> None:
        """多批次累积"""
        mc = MetricsCollector()
        for _ in range(3):
            case = _make_case()
            mc.record_batch(
                [case], [_make_response()],
                [_make_evaluation(decision="T0_Block")], [_make_dpo_pair()],
            )

        assert mc.decision_counts["T0_Block"] == 3
        assert mc.total_pairs == 3
        assert len(mc.batch_timestamps) == 3


class TestDashboardBridge:
    """DashboardBridge 测试"""

    def test_empty_data_dir(self, tmp_path: Path) -> None:
        """无数据时返回空快照"""
        bridge = DashboardBridge(data_dir=tmp_path)
        snap = bridge.get_latest_snapshot()
        assert snap.total_cases == 0
        assert snap.dpo_pairs == 0

    def test_snapshot_from_metrics(self, tmp_path: Path) -> None:
        """从持久化指标构建快照"""
        # 先保存指标
        mc = MetricsCollector()
        case = _make_case()
        mc.record_batch(
            [case],
            [_make_response(decision="T2_Normal")],  # Moderator 弱判决
            [_make_evaluation(has_stealth=True, decision="T1_Shadowban")],  # Judge 金标
            [_make_dpo_pair()],
        )
        mc.save(tmp_path / "metrics.json")

        # 通过 bridge 加载
        bridge = DashboardBridge(data_dir=tmp_path)
        snap = bridge.get_latest_snapshot()

        assert snap.total_cases == 1
        # T1_Shadowban → flag_count 兼容字段
        assert snap.flag_count == 1
        assert snap.block_count == 0
        assert snap.dpo_pairs == 1
        assert snap.avg_quality > 0
        # sub_scores 三键
        assert "stealth_marketing_rate" in snap.sub_scores
        assert "ai_slop_rate" in snap.sub_scores
        assert "avg_severity" in snap.sub_scores
        assert snap.sub_scores["stealth_marketing_rate"] == 1.0
        assert len(snap.quality_scores) == 1
        # decision_distribution 必须包含 T1_Shadowban=1
        assert snap.decision_distribution["T1_Shadowban"] == 1
        # 同时记录 Moderator 的弱判决分布
        assert snap.moderator_decision_distribution["T2_Normal"] == 1

    def test_snapshot_with_runs(self, tmp_path: Path) -> None:
        """包含管道运行历史"""
        import json

        mc = MetricsCollector()
        case = _make_case()
        mc.record_batch([case], [_make_response()], [_make_evaluation()], [])
        mc.save(tmp_path / "metrics.json")

        # 写入运行记录
        runs_path = tmp_path / "runs.jsonl"
        with open(runs_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"run_id": "test-run", "status": "completed"}) + "\n")

        bridge = DashboardBridge(data_dir=tmp_path)
        snap = bridge.get_latest_snapshot()
        assert len(snap.pipeline_runs) == 1
        assert snap.pipeline_runs[0]["run_id"] == "test-run"

    def test_dashboard_snapshot_frozen(self) -> None:
        """DashboardSnapshot 是不可变的"""
        snap = DashboardSnapshot()
        with pytest.raises(AttributeError):
            snap.total_cases = 100  # type: ignore[misc]
