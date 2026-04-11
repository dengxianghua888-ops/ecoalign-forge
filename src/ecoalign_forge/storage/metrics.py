"""MetricsCollector — 聚合内容分发分级管线的指标，支持持久化。

迁移到统一 ontology 后变化：
- responses 类型从 list[ModeratorResponse] 改为 list[JudgeEvaluation | None]
- 不再有 PASS/FLAG/BLOCK 概念，全部用 final_decision (T0/T1/T2/T3)
- 同时跟踪两套档位计数：
  * decision_counts —— Judge 的最终判决分布
  * moderator_decision_counts —— Moderator 的初级判决分布（用于评估弱版本质量）
- 拦截率 = (T0 + T1) / total（基于 Judge）
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import orjson

from ecoalign_forge._guidelines import KNOWN_RULE_IDS
from ecoalign_forge.schemas.chaos import ChaosCase
from ecoalign_forge.schemas.dpo import DPO_Pair
from ecoalign_forge.schemas.judge import DECISION_SEVERITY, JudgeEvaluation

# 正则识别 reasoning_trace 中的规则编号引用（与 schemas/judge.py 同模式）
_RULE_ID_PATTERN = re.compile(r"\b([AB]-\d{3})\b")


class MetricsCollector:
    """跨批次收集和聚合管道指标，支持序列化与反序列化。"""

    def __init__(self) -> None:
        self._severity_scores: list[float] = []
        self._dimension_counts: dict[str, dict[str, int]] = {}
        self._total_pairs: int = 0
        # 攻击场景计数（来自 ChaosCase.attack_strategy，旧字段语义保留）
        self._strategy_counts: dict[str, int] = {}
        # 内容分发分级信号
        self._stealth_hits: int = 0
        self._slop_hits: int = 0
        # Judge 判决分布
        self._decision_counts: dict[str, int] = {
            "T0_Block": 0,
            "T1_Shadowban": 0,
            "T2_Normal": 0,
            "T3_Recommend": 0,
        }
        # Moderator 初级判决分布（用于评估弱版本质量、生成 DPO 信号充足度）
        self._moderator_decision_counts: dict[str, int] = {
            "T0_Block": 0,
            "T1_Shadowban": 0,
            "T2_Normal": 0,
            "T3_Recommend": 0,
        }
        # 规则覆盖率：每条 KNOWN_RULE_IDS 被多少 Judge reasoning_trace 引用
        # 初始化时把所有已注册规则置 0，便于一眼看出哪些规则从未被命中
        self._rule_hits: dict[str, int] = {rule_id: 0 for rule_id in KNOWN_RULE_IDS}
        # 批次时间线
        self._batch_timestamps: list[dict] = []

    def record_batch(
        self,
        cases: list[ChaosCase],
        responses: list[JudgeEvaluation | None],
        evaluations: list[JudgeEvaluation | None],
        dpo_pairs: list[DPO_Pair],
    ) -> None:
        """记录单个批次的指标。

        Args:
            cases: ChaosCreator 输出的种子内容
            responses: Moderator 的初级判决（按位置对齐 cases，可能含 None）
            evaluations: SupremeJudge 的金标判决（按位置对齐 cases，可能含 None）
            dpo_pairs: 本批生成的 DPO 训练对
        """
        for ev in evaluations:
            if ev is None:
                continue
            self._severity_scores.append(DECISION_SEVERITY[ev.final_decision])
            self._decision_counts[ev.final_decision] = (
                self._decision_counts.get(ev.final_decision, 0) + 1
            )
            if ev.has_stealth_marketing:
                self._stealth_hits += 1
            if ev.is_ai_slop:
                self._slop_hits += 1
            # 解析 reasoning_trace 引用的规则编号，累加到覆盖率统计
            # （field_validator 已保证编号合法或显式声明未命中）
            for rule_id in set(_RULE_ID_PATTERN.findall(ev.reasoning_trace)):
                if rule_id in self._rule_hits:
                    self._rule_hits[rule_id] += 1

        # 记录 Moderator 的弱判决分布（None 跳过）
        for mod_eval in responses:
            if mod_eval is None:
                continue
            self._moderator_decision_counts[mod_eval.final_decision] = (
                self._moderator_decision_counts.get(mod_eval.final_decision, 0) + 1
            )

        # 按用例的 target_dimension 统计 total
        for case in cases:
            dim = case.target_dimension
            if dim not in self._dimension_counts:
                self._dimension_counts[dim] = {"total": 0, "intercepted": 0}
            self._dimension_counts[dim]["total"] += 1
            # 统计攻击场景（旧字段语义保留）
            strategy = case.attack_strategy.value
            self._strategy_counts[strategy] = self._strategy_counts.get(strategy, 0) + 1

        # 拦截统计：按 Judge 的 final_decision (T0/T1) 累加到对应 case 的 dimension
        # 由于 cases 与 evaluations 按位置对齐，这里也按位置匹配
        for case, ev in zip(cases, evaluations, strict=False):
            if ev is None:
                continue
            if ev.final_decision in ("T0_Block", "T1_Shadowban"):
                dim = case.target_dimension
                if dim not in self._dimension_counts:
                    self._dimension_counts[dim] = {"total": 0, "intercepted": 0}
                self._dimension_counts[dim]["intercepted"] += 1

        self._total_pairs += len(dpo_pairs)

        # 记录批次时间线
        self._batch_timestamps.append({
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "cases": len(cases),
            "dpo_pairs": len(dpo_pairs),
        })

    @property
    def avg_quality_score(self) -> float:
        """平均严重度评分（高 = 内容越违规）。"""
        if not self._severity_scores:
            return 0.0
        return sum(self._severity_scores) / len(self._severity_scores)

    @property
    def interception_rate(self) -> float:
        """拦截率 = (T0 + T1) / 总判决数，基于 Judge 的最终判决。"""
        total = sum(self._decision_counts.values())
        if total == 0:
            return 0.0
        intercepted = (
            self._decision_counts.get("T0_Block", 0)
            + self._decision_counts.get("T1_Shadowban", 0)
        )
        return intercepted / total

    @property
    def total_pairs(self) -> int:
        """累积生成的 DPO 对总数。"""
        return self._total_pairs

    @property
    def strategy_counts(self) -> dict[str, int]:
        """各攻击场景的用例计数（返回副本）。"""
        return dict(self._strategy_counts)

    @property
    def severity_scores(self) -> list[float]:
        """全部严重度评分（返回副本）。"""
        return list(self._severity_scores)

    @property
    def stealth_hits(self) -> int:
        """命中策略 A（高隐蔽性私域引流）的次数。"""
        return self._stealth_hits

    @property
    def slop_hits(self) -> int:
        """命中策略 B（低信息熵 AI 洗稿）的次数。"""
        return self._slop_hits

    @property
    def stealth_marketing_rate(self) -> float:
        """策略 A 命中率（占已评估总数的比例）。"""
        total = len(self._severity_scores)
        return self._stealth_hits / total if total > 0 else 0.0

    @property
    def ai_slop_rate(self) -> float:
        """策略 B 命中率。"""
        total = len(self._severity_scores)
        return self._slop_hits / total if total > 0 else 0.0

    @property
    def decision_counts(self) -> dict[str, int]:
        """Judge 的各 final_decision 档位计数（返回副本）。"""
        return dict(self._decision_counts)

    @property
    def moderator_decision_counts(self) -> dict[str, int]:
        """Moderator 初级判决的档位计数（返回副本）。"""
        return dict(self._moderator_decision_counts)

    @property
    def rule_coverage(self) -> dict[str, int]:
        """每条 A-XXX/B-XXX 规则被 Judge reasoning_trace 引用的次数（副本）。

        值为 0 的规则代表"覆盖率盲区"——未被任何样本触发，需要 ContentSeeder
        定向生成更多触发该规则的内容。
        """
        return dict(self._rule_hits)

    @property
    def uncovered_rules(self) -> list[str]:
        """从未被任何样本引用的规则编号列表（覆盖率盲区）。"""
        return sorted([rid for rid, hits in self._rule_hits.items() if hits == 0])

    @property
    def batch_timestamps(self) -> list[dict]:
        """批次时间线（返回副本）。"""
        return list(self._batch_timestamps)

    @property
    def dimension_stats(self) -> dict[str, dict]:
        """每维度（target_dimension）拦截率。"""
        stats = {}
        for dim, counts in self._dimension_counts.items():
            total = counts["total"]
            intercepted = counts["intercepted"]
            stats[dim] = {
                "total": total,
                "intercepted": intercepted,
                "interception_rate": intercepted / total if total > 0 else 0.0,
            }
        return stats

    def to_dict(self) -> dict:
        """导出全部内部状态为字典。"""
        return {
            "severity_scores": self._severity_scores,
            "dimension_counts": self._dimension_counts,
            "total_pairs": self._total_pairs,
            "strategy_counts": self._strategy_counts,
            "stealth_hits": self._stealth_hits,
            "slop_hits": self._slop_hits,
            "decision_counts": self._decision_counts,
            "moderator_decision_counts": self._moderator_decision_counts,
            "rule_hits": self._rule_hits,
            "batch_timestamps": self._batch_timestamps,
        }

    def save(self, path: Path) -> None:
        """用 orjson 将指标持久化为 JSON 文件。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = orjson.dumps(self.to_dict(), option=orjson.OPT_INDENT_2)
        path.write_bytes(data)

    @classmethod
    def load(cls, path: Path) -> MetricsCollector:
        """从 JSON 文件恢复 MetricsCollector 实例。"""
        raw = orjson.loads(path.read_bytes())
        mc = cls()
        mc._severity_scores = raw.get("severity_scores", [])
        mc._dimension_counts = raw.get("dimension_counts", {})
        mc._total_pairs = raw.get("total_pairs", 0)
        mc._strategy_counts = raw.get("strategy_counts", {})
        mc._stealth_hits = raw.get("stealth_hits", 0)
        mc._slop_hits = raw.get("slop_hits", 0)
        # decision_counts / moderator_decision_counts 用默认四档兜底
        loaded_decisions = raw.get("decision_counts", {})
        for k in mc._decision_counts:
            mc._decision_counts[k] = loaded_decisions.get(k, 0)
        loaded_mod_decisions = raw.get("moderator_decision_counts", {})
        for k in mc._moderator_decision_counts:
            mc._moderator_decision_counts[k] = loaded_mod_decisions.get(k, 0)
        # rule_hits 用 KNOWN_RULE_IDS 作为骨架，避免老数据缺字段
        loaded_rule_hits = raw.get("rule_hits", {})
        for rule_id in mc._rule_hits:
            mc._rule_hits[rule_id] = loaded_rule_hits.get(rule_id, 0)
        mc._batch_timestamps = raw.get("batch_timestamps", [])
        return mc
