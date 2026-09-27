"""DashboardBridge — 连接后端持久化指标与 Streamlit Dashboard。"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from ecoalign_forge.config import settings
from ecoalign_forge.schemas.execution import ExecutionMode
from ecoalign_forge.schemas.pipeline import PipelineRun
from ecoalign_forge.storage.metrics import MetricsCollector


@dataclass(frozen=True)
class DashboardSnapshot:
    """Dashboard 渲染所需的全部数据快照。

    迁移到统一 ontology 后字段含义：
    - `decision_distribution`: Judge 的 T0–T3 计数（取代旧的 pass/flag/block）
    - `pass_count / flag_count / block_count`: 兼容字段，分别等于
      T2_Normal+T3_Recommend / 0 / T0_Block+T1_Shadowban，便于旧 dashboard 组件无缝读取
    - `sub_scores`: 三个核心指标 stealth_marketing_rate / ai_slop_rate / avg_severity
    """

    total_cases: int = 0
    pass_count: int = 0
    flag_count: int = 0
    block_count: int = 0
    dpo_pairs: int = 0
    avg_decision_severity: float = 0.0
    avg_pair_quality_heuristic: float | None = None
    execution_mode: ExecutionMode = ExecutionMode.UNKNOWN
    run_id: str | None = None
    review_consistency_rate: float | None = None
    review_correction_rate: float | None = None
    review_failed: int = 0
    load_error: str | None = None
    interception_rate: float = 0.0
    dimension_rates: dict[str, float] = field(default_factory=dict)
    attack_strategy_counts: dict[str, int] = field(default_factory=dict)
    severity_scores: list[float] = field(default_factory=list)
    sub_scores: dict[str, float] = field(default_factory=dict)
    decision_distribution: dict[str, int] = field(default_factory=dict)
    moderator_decision_distribution: dict[str, int] = field(default_factory=dict)
    pipeline_runs: list[dict] = field(default_factory=list)
    timeline_data: list[dict] = field(default_factory=list)

    # 标识当前快照是否为 Demo 模式数据
    @property
    def is_demo(self) -> bool:
        return self.execution_mode == ExecutionMode.DEMO

    @property
    def avg_quality(self) -> float:
        warnings.warn(
            "avg_quality is deprecated; use avg_decision_severity", DeprecationWarning, stacklevel=2
        )
        return self.avg_decision_severity


class DashboardBridge:
    """连接后端持久化指标与 Streamlit Dashboard。"""

    def __init__(
        self, data_dir: Path | None = None, execution_mode: ExecutionMode | str = ExecutionMode.LIVE
    ) -> None:
        self.execution_mode = ExecutionMode(execution_mode)
        base = data_dir or settings.data_dir
        self.data_dir = (
            base
            if self.execution_mode == ExecutionMode.UNKNOWN
            else base / self.execution_mode.value
        )

    def get_latest_snapshot(self) -> DashboardSnapshot:
        """读取最新的持久化指标，构建 DashboardSnapshot。"""
        metrics_path = self.data_dir / "metrics.json"
        runs_path = self.data_dir / "runs.jsonl"

        if not metrics_path.exists():
            return DashboardSnapshot(execution_mode=self.execution_mode)

        mc = MetricsCollector.load(metrics_path)
        if mc.execution_mode != self.execution_mode:
            raise ValueError("Metrics execution mode does not match selected source")

        # 读取管道运行历史
        pipeline_runs: list[dict] = []
        if runs_path.exists():
            with open(runs_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        record = json.loads(line)
                        if not isinstance(record, dict):
                            raise ValueError("Run record must be a JSON object")
                        if record.get("execution_mode", "unknown") == self.execution_mode.value:
                            pipeline_runs.append(
                                PipelineRun.model_validate(record).model_dump(mode="json")
                            )

        # 兼容字段映射：旧 dashboard 组件读 pass/flag/block，统一从 decision_counts 派生
        decision_counts = mc.decision_counts
        t0 = decision_counts.get("T0_Block", 0)
        t1 = decision_counts.get("T1_Shadowban", 0)
        t2 = decision_counts.get("T2_Normal", 0)
        t3 = decision_counts.get("T3_Recommend", 0)

        return DashboardSnapshot(
            total_cases=t0 + t1 + t2 + t3,
            pass_count=t2 + t3,  # PASS 兼容 = 进入分发的总和
            flag_count=t1,  # FLAG 兼容 = 限流档
            block_count=t0,  # BLOCK 兼容 = 屏蔽档
            dpo_pairs=mc.total_pairs,
            avg_decision_severity=mc.avg_decision_severity,
            avg_pair_quality_heuristic=mc.avg_pair_quality_heuristic,
            execution_mode=mc.execution_mode,
            run_id=mc.run_id,
            review_consistency_rate=mc.review_stats.get("consistency_rate"),
            review_correction_rate=mc.review_stats.get("correction_rate"),
            review_failed=mc.review_stats.get("total_failed", 0),
            interception_rate=mc.interception_rate,
            dimension_rates={
                dim: stats["interception_rate"] for dim, stats in mc.dimension_stats.items()
            },
            attack_strategy_counts=mc.strategy_counts,
            severity_scores=mc.severity_scores,
            sub_scores={
                "stealth_marketing_rate": mc.stealth_marketing_rate,
                "ai_slop_rate": mc.ai_slop_rate,
                "avg_severity": mc.avg_decision_severity,
            },
            decision_distribution=decision_counts,
            moderator_decision_distribution=mc.moderator_decision_counts,
            pipeline_runs=pipeline_runs,
            timeline_data=mc.batch_timestamps,
        )
