"""QualityScorer — DPO 偏好对多维度质量评分。

参考 UltraFeedback 四维评分 + CLEAR 管道质量评估方法论。
每个维度输出 [0.0, 1.0] 的标准化分数，综合分为加权平均。

维度权重可通过构造函数调节，满足不同场景侧重。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ecoalign_forge.schemas.dpo import DPO_Pair
from ecoalign_forge.schemas.judge import DECISION_SEVERITY

# 规则编号正则
_RULE_ID_PATTERN = re.compile(r"\b([AB]-\d{3})\b")

# 默认维度权重
_DEFAULT_WEIGHTS: dict[str, float] = {
    "reasoning_depth": 0.25,
    "information_density": 0.15,
    "preference_clarity": 0.25,
    "decision_consistency": 0.20,
    "response_completeness": 0.15,
}


@dataclass(frozen=True)
class QualityReport:
    """单条 DPO_Pair 的质量评估报告。"""

    # 各维度分数 [0.0, 1.0]
    reasoning_depth: float
    information_density: float
    preference_clarity: float
    decision_consistency: float
    response_completeness: float

    # 综合分
    overall: float

    # 是否为低质量
    low_quality: bool

    def to_dict(self) -> dict[str, float]:
        return {
            "reasoning_depth": self.reasoning_depth,
            "information_density": self.information_density,
            "preference_clarity": self.preference_clarity,
            "decision_consistency": self.decision_consistency,
            "response_completeness": self.response_completeness,
            "overall": self.overall,
        }


class QualityScorer:
    """DPO 数据质量评分器。"""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        low_quality_threshold: float = 0.4,
    ) -> None:
        self.weights = weights or _DEFAULT_WEIGHTS
        self.low_quality_threshold = low_quality_threshold

    def score(self, pair: DPO_Pair) -> QualityReport:
        """对单条 DPO_Pair 评分。"""
        rd = self._reasoning_depth(pair)
        id_ = self._information_density(pair)
        pc = self._preference_clarity(pair)
        dc = self._decision_consistency(pair)
        rc = self._response_completeness(pair)

        scores = {
            "reasoning_depth": rd,
            "information_density": id_,
            "preference_clarity": pc,
            "decision_consistency": dc,
            "response_completeness": rc,
        }

        # 加权平均
        total_weight = sum(self.weights.get(k, 0.0) for k in scores)
        overall = (
            sum(scores[k] * self.weights.get(k, 0.0) for k in scores) / total_weight
            if total_weight > 0
            else 0.0
        )

        return QualityReport(
            reasoning_depth=round(rd, 4),
            information_density=round(id_, 4),
            preference_clarity=round(pc, 4),
            decision_consistency=round(dc, 4),
            response_completeness=round(rc, 4),
            overall=round(overall, 4),
            low_quality=overall < self.low_quality_threshold,
        )

    def score_batch(self, pairs: list[DPO_Pair]) -> list[QualityReport]:
        """对批量 DPO_Pair 评分。"""
        return [self.score(pair) for pair in pairs]

    @staticmethod
    def _reasoning_depth(pair: DPO_Pair) -> float:
        """推理深度：chosen 响应中引用的规则编号数量。

        0 条 → 0.0, 1 条 → 0.3, 2 条 → 0.6, 3+ 条 → 1.0
        """
        chosen_data = _safe_parse_json(pair.chosen)
        trace = chosen_data.get("reasoning_trace", "")
        rule_count = len(set(_RULE_ID_PATTERN.findall(trace)))

        if rule_count >= 3:
            return 1.0
        if rule_count == 2:
            return 0.6
        if rule_count == 1:
            return 0.3
        return 0.0

    @staticmethod
    def _information_density(pair: DPO_Pair) -> float:
        """信息密度：chosen 响应中唯一 token 的比例。

        去重比越高 → 信息密度越高（非重复内容多）。
        对中文使用字符级 token（避免空格分词导致中文恒为 1.0）。
        """
        chosen_data = _safe_parse_json(pair.chosen)
        trace = chosen_data.get("reasoning_trace", "")
        if not trace:
            return 0.0

        # 混合分词：空格分词用于英文，bigram 用于中文（单字符去重比中文恒为 ~1.0）
        space_tokens = trace.split()
        # 中文 bigram 能真正区分语义重复度（"的的的" → 高重复，正常文本 → 低重复）
        chars = trace.replace(" ", "")
        bigrams = [chars[i:i+2] for i in range(len(chars) - 1)] if len(chars) > 1 else list(chars)
        # 若空格分词产出足够多 token（英文为主），使用空格分词；否则用 bigram
        tokens = space_tokens if len(space_tokens) >= 5 else bigrams

        if not tokens:
            return 0.0

        unique_ratio = len(set(tokens)) / len(tokens)
        # 映射到 [0, 1]：0.3 以下视为极低密度
        return min(1.0, max(0.0, (unique_ratio - 0.3) / 0.7))

    @staticmethod
    def _preference_clarity(pair: DPO_Pair) -> float:
        """偏好清晰度：直接使用 preference_gap。

        gap 越大 → 偏好越清晰 → 训练信号越强。
        """
        return pair.preference_gap

    @staticmethod
    def _decision_consistency(pair: DPO_Pair) -> float:
        """决策一致性：chosen 和 rejected 的 final_decision 是否合理。

        - chosen 比 rejected 更严格（severity 更高）→ 1.0
        - 两者相同 → 0.5（推理质量对，合理但弱信号）
        - chosen 比 rejected 宽松 → 0.0（异常数据）
        """
        chosen_data = _safe_parse_json(pair.chosen)
        rejected_data = _safe_parse_json(pair.rejected)

        # 使用权威映射 DECISION_SEVERITY，避免与 judge.py 不一致
        c_sev = DECISION_SEVERITY.get(chosen_data.get("final_decision", ""), 0.0)
        r_sev = DECISION_SEVERITY.get(rejected_data.get("final_decision", ""), 0.0)

        if c_sev > r_sev:
            return 1.0
        if c_sev == r_sev:
            return 0.5
        return 0.0

    @staticmethod
    def _response_completeness(pair: DPO_Pair) -> float:
        """响应完整性：chosen 响应是否包含完整的三步推理结构。"""
        chosen_data = _safe_parse_json(pair.chosen)
        trace = chosen_data.get("reasoning_trace", "")

        steps_found = 0
        for marker in ("第一步", "第二步", "第三步"):
            if marker in trace:
                steps_found += 1

        # 4 个必填字段是否存在
        required_fields = (
            "has_stealth_marketing",
            "is_ai_slop",
            "reasoning_trace",
            "final_decision",
        )
        fields_present = sum(1 for f in required_fields if f in chosen_data)

        # 步骤完整度 (0~0.5) + 字段完整度 (0~0.5)
        step_score = steps_found / 3.0 * 0.5
        field_score = fields_present / 4.0 * 0.5
        return step_score + field_score


def _safe_parse_json(text: str) -> dict:
    """安全解析 JSON 字符串，失败返回空字典。"""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
