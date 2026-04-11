"""FlyWheelOrchestrator — 数据飞轮多轮迭代编排器。

参考 Arena Learning (WizardLM) 数据飞轮方法论：
  Round N: 合成 DPO 数据 → 训练 → 得到新模型
  Round N+1: 用新模型替换 Moderator → 新一轮合成
  对比 Round N 与 N+1 的质量指标 → 筛选增量数据

核心价值（面试叙事）：
- 构建 "数据 → 训练 → 评估 → 数据回流" 闭环
- 每轮迭代自动追踪质量提升曲线
- 数据版本化管理，支持回归分析
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import orjson

logger = logging.getLogger(__name__)


@dataclass
class RoundMetrics:
    """单轮迭代的质量指标快照。"""
    round_id: int
    timestamp: str = field(
        default_factory=lambda: datetime.now(tz=UTC).isoformat()
    )
    total_dpo_pairs: int = 0
    avg_preference_gap: float = 0.0
    interception_rate: float = 0.0
    avg_quality_score: float = 0.0
    cohens_kappa: float = 0.0
    krippendorffs_alpha: float = 0.0
    correction_rate: float = 0.0  # Constitutional AI 修正率
    moderator_model: str = ""
    judge_model: str = ""

    def to_dict(self) -> dict:
        return {
            "round_id": self.round_id,
            "timestamp": self.timestamp,
            "total_dpo_pairs": self.total_dpo_pairs,
            "avg_preference_gap": round(self.avg_preference_gap, 4),
            "interception_rate": round(self.interception_rate, 4),
            "avg_quality_score": round(self.avg_quality_score, 4),
            "cohens_kappa": round(self.cohens_kappa, 4),
            "krippendorffs_alpha": round(self.krippendorffs_alpha, 4),
            "correction_rate": round(self.correction_rate, 4),
            "moderator_model": self.moderator_model,
            "judge_model": self.judge_model,
        }


@dataclass
class FlyWheelState:
    """飞轮全局状态，跨轮持久化。"""
    current_round: int = 0
    rounds: list[RoundMetrics] = field(default_factory=list)
    quality_trend: list[float] = field(default_factory=list)
    cumulative_dpo_pairs: int = 0

    def add_round(self, metrics: RoundMetrics) -> None:
        """记录新一轮迭代。"""
        self.rounds.append(metrics)
        self.quality_trend.append(metrics.avg_quality_score)
        self.cumulative_dpo_pairs += metrics.total_dpo_pairs
        self.current_round = metrics.round_id

    @property
    def quality_improvement(self) -> float:
        """最近一轮相对于第一轮的质量提升幅度。"""
        if len(self.quality_trend) < 2:
            return 0.0
        baseline = self.quality_trend[0]
        if baseline == 0.0:
            return 0.0
        latest = self.quality_trend[-1]
        return (latest - baseline) / baseline

    @property
    def round_over_round_improvement(self) -> float:
        """最近两轮之间的质量提升幅度。"""
        if len(self.quality_trend) < 2:
            return 0.0
        prev = self.quality_trend[-2]
        if prev == 0.0:
            return 0.0
        current = self.quality_trend[-1]
        return (current - prev) / prev

    def to_dict(self) -> dict:
        return {
            "current_round": self.current_round,
            "rounds": [r.to_dict() for r in self.rounds],
            "quality_trend": [round(q, 4) for q in self.quality_trend],
            "cumulative_dpo_pairs": self.cumulative_dpo_pairs,
            "quality_improvement": round(self.quality_improvement, 4),
        }

    def save(self, path: Path) -> None:
        """持久化飞轮状态。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = orjson.dumps(self.to_dict(), option=orjson.OPT_INDENT_2)
        path.write_bytes(data)

    @classmethod
    def load(cls, path: Path) -> FlyWheelState:
        """从文件恢复飞轮状态。"""
        if not path.exists():
            return cls()
        raw = orjson.loads(path.read_bytes())
        state = cls()
        state.current_round = raw.get("current_round", 0)
        state.cumulative_dpo_pairs = raw.get("cumulative_dpo_pairs", 0)
        state.quality_trend = raw.get("quality_trend", [])
        for r in raw.get("rounds", []):
            state.rounds.append(RoundMetrics(**r))
        return state


class FlyWheelOrchestrator:
    """数据飞轮编排器。

    管理多轮迭代的生命周期：
    1. 执行当前轮次的数据合成管道
    2. 收集质量指标快照
    3. 与前一轮对比，判断是否收敛
    4. 记录迭代历史，输出质量提升曲线

    注意：实际的模型训练步骤在框架外部完成（TRL/LLaMA-Factory），
    FlyWheelOrchestrator 负责管理数据合成侧的迭代。
    """

    def __init__(
        self,
        state_path: Path | None = None,
        convergence_threshold: float = 0.01,
        max_rounds: int = 10,
    ) -> None:
        self._state_path = state_path or Path("./data/flywheel_state.json")
        self.state = FlyWheelState.load(self._state_path)
        self.convergence_threshold = convergence_threshold
        self.max_rounds = max_rounds

    def record_round(self, metrics: RoundMetrics) -> None:
        """记录一轮迭代结果。"""
        self.state.add_round(metrics)
        self.state.save(self._state_path)
        logger.info(
            f"飞轮 Round {metrics.round_id} 完成: "
            f"DPO pairs={metrics.total_dpo_pairs}, "
            f"quality={metrics.avg_quality_score:.4f}, "
            f"improvement={self.state.round_over_round_improvement:+.2%}"
        )

    @property
    def has_converged(self) -> bool:
        """判断飞轮是否已收敛（质量提升低于阈值）。"""
        if len(self.state.quality_trend) < 2:
            return False
        return (
            abs(self.state.round_over_round_improvement)
            < self.convergence_threshold
        )

    @property
    def should_continue(self) -> bool:
        """判断是否应继续迭代。"""
        if self.state.current_round >= self.max_rounds:
            logger.info(f"已达最大轮次 {self.max_rounds}，停止迭代")
            return False
        if self.has_converged:
            logger.info(
                f"质量提升已收敛（{self.state.round_over_round_improvement:+.2%} "
                f"< {self.convergence_threshold:+.2%}），停止迭代"
            )
            return False
        return True

    def get_summary(self) -> dict:
        """生成飞轮摘要报告。"""
        return {
            "total_rounds": self.state.current_round,
            "cumulative_dpo_pairs": self.state.cumulative_dpo_pairs,
            "quality_trend": self.state.quality_trend,
            "total_improvement": f"{self.state.quality_improvement:+.2%}",
            "converged": self.has_converged,
            "rounds_detail": [r.to_dict() for r in self.state.rounds],
        }
