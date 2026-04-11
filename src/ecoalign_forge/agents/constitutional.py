"""Constitutional AI 自我修正循环。

参考 Anthropic Constitutional AI 方法论：
1. Judge 给出初始判决
2. 根据 guidelines.md "宪法"自我批评
3. 发现不一致则修正判决并记录修正原因
4. 统计修正率作为 Judge 模型可靠性指标

通过 ConstitutionalReviewer 包装 SupremeJudge，在评估后
增加一轮自我审查，提升金标判决的可靠性。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from ecoalign_forge._guidelines import GUIDELINES_TEXT
from ecoalign_forge.llm.client import LLMClient
from ecoalign_forge.schemas.judge import JudgeEvaluation

logger = logging.getLogger(__name__)

# 规则编号正则
_RULE_ID_PATTERN = re.compile(r"\b([AB]-\d{3})\b")

# 自我批评 prompt
_SELF_CRITIQUE_PROMPT = """你是一个严谨的质量审查员。请检查以下内容审核判决是否严格遵循了判决依据手册。

## 原始判决
{original_judgment}

## 判决依据手册（完整版）
{guidelines}

## 审查要求
请逐项检查：
1. has_stealth_marketing 的判定是否与手册 A-001~A-006 的规则一致？
2. is_ai_slop 的判定是否与手册 B-001~B-006 的分值制一致？
3. reasoning_trace 中引用的规则编号是否真实存在于手册中？
4. final_decision 是否与 has_stealth_marketing 和 is_ai_slop 的组合矩阵一致？

## 输出格式
返回且仅返回一个 JSON 对象：
{{
  "is_consistent": bool,
  "issues_found": ["问题描述1", "问题描述2"],
  "corrected_judgment": null 或 修正后的完整 JudgeEvaluation JSON（仅在不一致时提供）
}}"""


@dataclass
class CritiqueResult:
    """自我批评结果。"""
    original: JudgeEvaluation
    is_consistent: bool
    issues_found: list[str] = field(default_factory=list)
    corrected: JudgeEvaluation | None = None
    critique_raw: str = ""
    llm_failed: bool = False  # LLM 调用失败时为 True，区分"真一致"和"未审查"
    parse_failed: bool = False  # LLM 输出无法解析为 JSON 时为 True


@dataclass
class ConstitutionalStats:
    """Constitutional AI 修正统计。"""
    total_reviewed: int = 0
    total_corrected: int = 0
    total_llm_failures: int = 0  # LLM 调用失败次数
    total_correction_parse_failures: int = 0  # 修正解析失败次数
    issues_by_type: dict[str, int] = field(default_factory=dict)

    @property
    def correction_rate(self) -> float:
        """修正率：被修正的判决占比。"""
        if self.total_reviewed == 0:
            return 0.0
        return self.total_corrected / self.total_reviewed

    @property
    def consistency_rate(self) -> float:
        """一致性率：通过自检的判决占比（= 1 - correction_rate）。"""
        return 1.0 - self.correction_rate

    def to_dict(self) -> dict:
        return {
            "total_reviewed": self.total_reviewed,
            "total_corrected": self.total_corrected,
            "correction_rate": round(self.correction_rate, 4),
            "consistency_rate": round(self.consistency_rate, 4),
            "issues_by_type": dict(self.issues_by_type),
        }


class ConstitutionalReviewer:
    """Constitutional AI 自我修正审查器。

    在 SupremeJudge 评估后，对每个判决进行宪法一致性审查，
    发现不一致时自动修正。
    """

    def __init__(self, llm: LLMClient, model: str | None = None) -> None:
        self.llm = llm
        self.model = model
        self.stats = ConstitutionalStats()

    async def review(
        self, evaluation: JudgeEvaluation
    ) -> CritiqueResult:
        """对单条判决进行 Constitutional 审查。"""
        original_json = evaluation.model_dump_json(indent=2)
        prompt = _SELF_CRITIQUE_PROMPT.format(
            original_judgment=original_json,
            guidelines=GUIDELINES_TEXT,
        )

        self.stats.total_reviewed += 1

        try:
            raw = await self.llm.generate(
                messages=[
                    {"role": "system", "content": "你是内容审核质量审查专家。"},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
                temperature=0.1,
            )
        except Exception as e:
            # LLM 调用失败时保守处理：保留原判决，但记录日志和计数
            self.stats.total_llm_failures += 1
            logger.warning(f"Constitutional 审查 LLM 调用失败，保留原判决: {e}")
            return CritiqueResult(
                original=evaluation, is_consistent=True, llm_failed=True
            )

        return self._parse_critique(evaluation, raw)

    async def review_batch(
        self, evaluations: list[JudgeEvaluation | None]
    ) -> list[JudgeEvaluation | None]:
        """对批量判决进行并发审查，返回修正后的列表（位置对齐）。"""
        import asyncio

        sem = asyncio.Semaphore(5)

        async def _one(ev: JudgeEvaluation | None) -> JudgeEvaluation | None:
            if ev is None:
                return None
            async with sem:
                critique = await self.review(ev)
                return critique.corrected if critique.corrected is not None else critique.original

        return list(await asyncio.gather(*[_one(ev) for ev in evaluations]))

    def _parse_critique(
        self, original: JudgeEvaluation, raw: str
    ) -> CritiqueResult:
        """解析自我批评 LLM 输出。"""
        try:
            # 提取 JSON
            text = raw.strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            self.stats.total_correction_parse_failures += 1
            logger.warning(f"Constitutional 审查输出解析失败，保留原判决: {e}")
            return CritiqueResult(
                original=original,
                is_consistent=True,
                parse_failed=True,
                critique_raw=raw,
            )

        is_consistent = data.get("is_consistent", True)
        issues = data.get("issues_found", [])

        corrected = None
        if not is_consistent and data.get("corrected_judgment"):
            try:
                corrected = JudgeEvaluation(**data["corrected_judgment"])
                self.stats.total_corrected += 1
            except Exception as e:
                self.stats.total_correction_parse_failures += 1
                logger.warning(f"Constitutional 修正解析失败，保留原判决: {e}")

        # 统计问题类型
        for issue in issues:
            # 简单归类：按关键词
            if "规则编号" in issue:
                key = "rule_reference"
            elif "矩阵" in issue or "final_decision" in issue:
                key = "decision_matrix"
            elif "stealth" in issue or "marketing" in issue or "引流" in issue:
                key = "stealth_marketing_check"
            elif "slop" in issue or "洗稿" in issue:
                key = "ai_slop_check"
            else:
                key = "other"
            self.stats.issues_by_type[key] = (
                self.stats.issues_by_type.get(key, 0) + 1
            )

        return CritiqueResult(
            original=original,
            is_consistent=is_consistent,
            issues_found=issues,
            corrected=corrected,
            critique_raw=raw,
        )
