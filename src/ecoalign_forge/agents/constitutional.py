"""Constitutional AI 自我修正循环。

参考 Anthropic Constitutional AI 方法论：
1. Judge 给出初始判决
2. 根据 guidelines.md "宪法"自我批评
3. 发现不一致则修正判决并记录修正原因
4. 区分通过、修正、失败和弃权，未完成复核的判决不进入训练对

通过 ConstitutionalReviewer 包装 SupremeJudge，在评估后
增加一轮结构化自我审查；其正确性仍需独立评估。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ValidationError

from ecoalign_forge._guidelines import GUIDELINES_TEXT
from ecoalign_forge.llm.client import LLMClient
from ecoalign_forge.schemas.judge import JudgeEvaluation

logger = logging.getLogger(__name__)

ReviewStatus = Literal["passed", "corrected", "failed", "abstain", "skipped"]

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
如果无法确认判决且没有可靠的修正，请返回 is_consistent=false、
corrected_judgment=null，并在 issues_found 中说明原因。
is_consistent=true 时 issues_found 必须为空且 corrected_judgment 必须为 null。
返回且仅返回一个 JSON 对象：
{{
  "is_consistent": bool,
  "issues_found": ["问题描述1", "问题描述2"],
  "corrected_judgment": null 或 修正后的完整 JudgeEvaluation JSON（仅在不一致时提供）
}}"""


@dataclass
class CritiqueResult:
    """旧版结果容器，保留构造兼容；新审查入口返回 ReviewResult。"""

    original: JudgeEvaluation
    is_consistent: bool
    issues_found: list[str] = field(default_factory=list)
    corrected: JudgeEvaluation | None = None
    critique_raw: str = ""
    llm_failed: bool = False  # LLM 调用失败时为 True，区分"真一致"和"未审查"
    parse_failed: bool = False  # LLM 输出无法解析为 JSON 时为 True


@dataclass(frozen=True)
class ReviewResult:
    """一次复核的明确结果；只有 passed/corrected 提供最终判决。"""

    status: ReviewStatus
    final_evaluation: JudgeEvaluation | None
    original_evaluation: JudgeEvaluation | None
    reason: str
    issues_found: list[str] = field(default_factory=list)
    critique_raw: str = ""
    llm_failed: bool = False
    parse_failed: bool = False

    @property
    def original(self) -> JudgeEvaluation | None:
        """兼容旧版 review 调用者读取原始判决。"""
        return self.original_evaluation

    @property
    def corrected(self) -> JudgeEvaluation | None:
        return self.final_evaluation if self.status == "corrected" else None

    @property
    def is_consistent(self) -> bool:
        return self.status == "passed"


@dataclass
class ConstitutionalStats:
    """Constitutional AI 修正统计。"""

    total_reviewed: int = 0
    total_passed: int = 0
    total_corrected: int = 0
    total_failed: int = 0
    total_abstained: int = 0
    total_skipped: int = 0
    total_llm_failures: int = 0  # LLM 调用失败次数
    total_correction_parse_failures: int = 0  # 修正解析失败次数
    issues_by_type: dict[str, int] = field(default_factory=dict)

    @property
    def total_completed(self) -> int:
        return self.total_passed + self.total_corrected

    @property
    def correction_rate(self) -> float | None:
        """已完成有效复核中的修正率；没有有效复核时不可估计。"""
        if self.total_completed == 0:
            return None
        return self.total_corrected / self.total_completed

    @property
    def consistency_rate(self) -> float | None:
        if self.total_completed == 0:
            return None
        return self.total_passed / self.total_completed

    def to_dict(self) -> dict:
        return {
            "total_reviewed": self.total_reviewed,
            "total_completed": self.total_completed,
            "total_passed": self.total_passed,
            "total_corrected": self.total_corrected,
            "total_failed": self.total_failed,
            "total_abstained": self.total_abstained,
            "total_skipped": self.total_skipped,
            "total_llm_failures": self.total_llm_failures,
            "total_correction_parse_failures": self.total_correction_parse_failures,
            "correction_rate": (
                round(self.correction_rate, 4) if self.correction_rate is not None else None
            ),
            "consistency_rate": (
                round(self.consistency_rate, 4) if self.consistency_rate is not None else None
            ),
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

    async def review(self, evaluation: JudgeEvaluation) -> ReviewResult:
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
            logger.warning("Constitutional 审查 LLM 调用失败: %s", type(e).__name__)
            result = ReviewResult(
                status="failed",
                final_evaluation=None,
                original_evaluation=evaluation,
                reason="llm_error",
                llm_failed=True,
            )
        else:
            result = self._parse_critique(evaluation, raw)

        self._record_result(result)
        return result

    async def review_batch(
        self, evaluations: list[JudgeEvaluation | None]
    ) -> list[JudgeEvaluation | None]:
        """兼容入口：返回最终判决；失败/弃权/上游缺失的位置返回 None。"""
        results = await self.review_batch_detailed(evaluations)
        return [result.final_evaluation for result in results]

    async def review_batch_detailed(
        self, evaluations: list[JudgeEvaluation | None]
    ) -> list[ReviewResult]:
        """并发审查，保留每个输入位置的状态与诊断。"""
        import asyncio

        sem = asyncio.Semaphore(5)

        async def _one(ev: JudgeEvaluation | None) -> ReviewResult:
            if ev is None:
                result = ReviewResult(
                    status="skipped",
                    final_evaluation=None,
                    original_evaluation=None,
                    reason="upstream_evaluation_missing",
                )
                self._record_result(result)
                return result
            async with sem:
                return await self.review(ev)

        return list(await asyncio.gather(*[_one(ev) for ev in evaluations]))

    def _parse_critique(self, original: JudgeEvaluation, raw: str) -> ReviewResult:
        """校验复核响应结构，不能把未审查或矛盾响应解释为通过。"""

        def failed(reason: str) -> ReviewResult:
            return ReviewResult(
                status="failed",
                final_evaluation=None,
                original_evaluation=original,
                reason=reason,
                parse_failed=True,
                critique_raw=raw if isinstance(raw, str) else "",
            )

        if not isinstance(raw, str):
            return failed("invalid_response_type")
        try:
            text = raw.strip()
            # 兼容完整代码块，但不能从数组/额外文本中截出对象并误认为通过。
            if text.startswith(("```json\n", "```\n")) and text.endswith("```"):
                text = text.split("\n", 1)[1][:-3].strip()

            def unique_fields(pairs: list[tuple[str, object]]) -> dict:
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Duplicate JSON field")
                    result[key] = value
                return result

            data = json.loads(text, object_pairs_hook=unique_fields)
        except (json.JSONDecodeError, ValueError):
            return failed("invalid_json")

        if not isinstance(data, dict):
            return failed("invalid_response_shape")
        required = {"is_consistent", "issues_found", "corrected_judgment"}
        if not required.issubset(data):
            return failed("missing_fields")
        if set(data) != required:
            return failed("unexpected_fields")
        if type(data["is_consistent"]) is not bool:
            return failed("invalid_is_consistent")
        issues = data["issues_found"]
        if not isinstance(issues, list) or any(not isinstance(issue, str) for issue in issues):
            return failed("invalid_issues_found")
        correction = data["corrected_judgment"]
        if correction is not None and not isinstance(correction, dict):
            return failed("invalid_corrected_judgment")

        if data["is_consistent"]:
            if correction is not None or issues:
                return failed("contradictory_fields")
            return ReviewResult(
                status="passed",
                final_evaluation=original,
                original_evaluation=original,
                reason="consistent",
                critique_raw=raw,
            )

        if correction is None:
            return ReviewResult(
                status="abstain",
                final_evaluation=None,
                original_evaluation=original,
                reason="no_correction_provided",
                issues_found=issues,
                critique_raw=raw,
            )
        try:
            corrected = JudgeEvaluation(**correction)
        except ValidationError:
            return failed("invalid_correction")

        if corrected == original:
            return ReviewResult(
                status="abstain",
                final_evaluation=None,
                original_evaluation=original,
                reason="unchanged_correction",
                issues_found=issues,
                critique_raw=raw,
            )
        return ReviewResult(
            status="corrected",
            final_evaluation=corrected,
            original_evaluation=original,
            reason="judgment_corrected",
            issues_found=issues,
            critique_raw=raw,
        )

    def _record_result(self, result: ReviewResult) -> None:
        counters = {
            "passed": "total_passed",
            "corrected": "total_corrected",
            "failed": "total_failed",
            "abstain": "total_abstained",
            "skipped": "total_skipped",
        }
        counter = counters[result.status]
        setattr(self.stats, counter, getattr(self.stats, counter) + 1)
        if result.llm_failed:
            self.stats.total_llm_failures += 1
        if result.parse_failed:
            self.stats.total_correction_parse_failures += 1

        # 统计问题类型
        for issue in result.issues_found:
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
            self.stats.issues_by_type[key] = self.stats.issues_by_type.get(key, 0) + 1
