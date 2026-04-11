"""DashboardBridge — 连接后端持久化指标与 Streamlit Dashboard。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ecoalign_forge.config import settings
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
    avg_quality: float = 0.0
    interception_rate: float = 0.0
    dimension_rates: dict[str, float] = field(default_factory=dict)
    attack_strategy_counts: dict[str, int] = field(default_factory=dict)
    quality_scores: list[float] = field(default_factory=list)
    sub_scores: dict[str, float] = field(default_factory=dict)
    decision_distribution: dict[str, int] = field(default_factory=dict)
    moderator_decision_distribution: dict[str, int] = field(default_factory=dict)
    pipeline_runs: list[dict] = field(default_factory=list)
    timeline_data: list[dict] = field(default_factory=list)
    # 标识当前快照是否为 Demo 模式数据
    is_demo: bool = False


class DashboardBridge:
    """连接后端持久化指标与 Streamlit Dashboard。"""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or settings.data_dir

    def get_latest_snapshot(self) -> DashboardSnapshot:
        """读取最新的持久化指标，构建 DashboardSnapshot。"""
        metrics_path = self.data_dir / "metrics.json"
        runs_path = self.data_dir / "runs.jsonl"

        if not metrics_path.exists():
            return DashboardSnapshot()  # 空快照

        mc = MetricsCollector.load(metrics_path)

        # 读取管道运行历史
        pipeline_runs: list[dict] = []
        if runs_path.exists():
            with open(runs_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        pipeline_runs.append(json.loads(line))

        # 兼容字段映射：旧 dashboard 组件读 pass/flag/block，统一从 decision_counts 派生
        decision_counts = mc.decision_counts
        t0 = decision_counts.get("T0_Block", 0)
        t1 = decision_counts.get("T1_Shadowban", 0)
        t2 = decision_counts.get("T2_Normal", 0)
        t3 = decision_counts.get("T3_Recommend", 0)

        return DashboardSnapshot(
            total_cases=t0 + t1 + t2 + t3,
            pass_count=t2 + t3,         # PASS 兼容 = 进入分发的总和
            flag_count=t1,               # FLAG 兼容 = 限流档
            block_count=t0,              # BLOCK 兼容 = 屏蔽档
            dpo_pairs=mc.total_pairs,
            avg_quality=mc.avg_quality_score,
            interception_rate=mc.interception_rate,
            dimension_rates={
                dim: stats["interception_rate"]
                for dim, stats in mc.dimension_stats.items()
            },
            attack_strategy_counts=mc.strategy_counts,
            quality_scores=mc.severity_scores,
            sub_scores={
                "stealth_marketing_rate": mc.stealth_marketing_rate,
                "ai_slop_rate": mc.ai_slop_rate,
                "avg_severity": mc.avg_quality_score,
            },
            decision_distribution=decision_counts,
            moderator_decision_distribution=mc.moderator_decision_counts,
            pipeline_runs=pipeline_runs,
            timeline_data=mc.batch_timestamps,
            is_demo=False,
        )
