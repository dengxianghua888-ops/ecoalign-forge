"""ChaosCreator — 按目标分布反向生成内容分发分级测试样本。

迁移到内容分发分级 ontology 后职责变化：
- 不再生成"violence/sexual"安全审核类对抗内容
- 改为按目标 tier（T0/T1/T2/T3）和触发的策略组合（A、B、A+B、none）生成真实 UGC
- 每条用例的 ground truth 存进 `metadata['ground_truth']`，供后续评估使用
"""

from __future__ import annotations

import json
import math
import random
from typing import Any

from pydantic import ValidationError

from ecoalign_forge._guidelines import GUIDELINES_TEXT
from ecoalign_forge.agents.base import BaseAgent
from ecoalign_forge.exceptions import SchemaValidationError
from ecoalign_forge.llm.prompts import CHAOS_CREATOR_SYSTEM
from ecoalign_forge.schemas.chaos import ChaosCase
from ecoalign_forge.schemas.policy import PolicyInput

# 默认目标分布（按 final_decision tier）
DEFAULT_TARGET_DISTRIBUTION: dict[str, float] = {
    "T0_Block": 0.15,
    "T1_Shadowban": 0.30,
    "T2_Normal": 0.30,
    "T3_Recommend": 0.25,
}

# 每个 tier 的"应触发策略组合"，用于 prompt 指导和 ground_truth 标注
_TIER_TO_STRATEGIES: dict[str, dict[str, bool]] = {
    "T0_Block":     {"has_stealth_marketing": True,  "is_ai_slop": True},
    "T1_Shadowban": {"has_stealth_marketing": True,  "is_ai_slop": False},
    "T2_Normal":    {"has_stealth_marketing": False, "is_ai_slop": True},
    "T3_Recommend": {"has_stealth_marketing": False, "is_ai_slop": False},
}


class ChaosCreator(BaseAgent):
    """Agent 1: 按目标分布反向生成 UGC 测试样本。"""

    name = "ChaosCreator"

    async def run(
        self,
        policy: PolicyInput,
        batch_size: int = 10,
        target_distribution: dict[str, float] | None = None,
        **kwargs: Any,
    ) -> list[ChaosCase]:
        """按目标 tier 分布生成 batch_size 条用例。

        Args:
            policy: 策略上下文（dimensions 现在表示待检测策略名 stealth_marketing/ai_slop）
            batch_size: 本批生成的总条数
            target_distribution: 目标 tier 分布字典，key 为 final_decision，
                value 为占比（自动归一化）。默认 T0:15% / T1:30% / T2:30% / T3:25%
        """
        distribution = target_distribution or DEFAULT_TARGET_DISTRIBUTION
        targets = self._sample_targets(batch_size, distribution)
        breakdown = self._format_target_breakdown(targets)
        self._log(
            f"Generating {batch_size} cases with target distribution: {breakdown}"
        )

        user_prompt = self._build_user_prompt(policy, batch_size, targets)

        cases = await self.llm.generate_validated(
            messages=[
                {"role": "system", "content": CHAOS_CREATOR_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            parser=self._parse_cases,
            model=self.model,
            temperature=0.9,
        )

        # 把目标 tier 与策略组合作为 hidden ground truth 写入 metadata
        # （只存不用，供后续 evaluation / 路径 3 的 active learning 复用）
        self._stamp_ground_truth(cases, targets)

        self._log(f"Generated {len(cases)} cases successfully")
        return cases

    @staticmethod
    def _sample_targets(
        batch_size: int, distribution: dict[str, float]
    ) -> list[str]:
        """按目标分布采样 batch_size 个目标 tier。

        采样逻辑：先按比例向下取整分配，剩余名额按比例随机补足，保证总和 = batch_size
        且分布尽量接近输入比例。
        """
        # 归一化（容忍输入是 1 不到或超 1）
        total = sum(distribution.values())
        if total <= 0:
            raise ValueError(f"target_distribution 总和必须 > 0: {distribution}")
        normalized = {k: v / total for k, v in distribution.items()}

        counts: dict[str, int] = {
            tier: math.floor(ratio * batch_size)
            for tier, ratio in normalized.items()
        }
        # 处理整除剩余的名额
        remainder = batch_size - sum(counts.values())
        if remainder > 0:
            # 按比例的小数部分排序，给小数部分大的 tier 优先补
            fractional = sorted(
                normalized.items(),
                key=lambda kv: (kv[1] * batch_size) - math.floor(kv[1] * batch_size),
                reverse=True,
            )
            for tier, _ in fractional:
                if remainder <= 0:
                    break
                counts[tier] += 1
                remainder -= 1

        targets: list[str] = []
        for tier, n in counts.items():
            targets.extend([tier] * n)
        # 打散顺序，避免 LLM 看到"前 5 条都是 T1"产生模式偏差
        random.shuffle(targets)
        return targets

    @staticmethod
    def _format_target_breakdown(targets: list[str]) -> str:
        from collections import Counter
        c = Counter(targets)
        return ", ".join(f"{k}={v}" for k, v in sorted(c.items()))

    @staticmethod
    def _build_user_prompt(
        policy: PolicyInput,
        batch_size: int,
        targets: list[str],
    ) -> str:
        from collections import Counter
        target_counts = Counter(targets)
        target_lines = "\n".join(
            f"- 目标 {tier}（应触发策略组合：A={_TIER_TO_STRATEGIES[tier]['has_stealth_marketing']}，"
            f"B={_TIER_TO_STRATEGIES[tier]['is_ai_slop']}）：**{n} 条**"
            for tier, n in sorted(target_counts.items())
        )

        return f"""请按下方目标分布生成共 **{batch_size} 条** UGC 测试内容。

## 判决依据手册（生成时必须参照，确保每条内容真的会被对应规则命中）
{GUIDELINES_TEXT}

## 本批目标分布
{target_lines}

## 策略上下文
- 平台：{policy.name}（{policy.language}）
- 待检测策略：{', '.join(d.name for d in policy.dimensions)}

## 生成要求
1. 每条内容必须像真实用户发布的小红书 / 知乎 / B 站 / 微博动态
2. 对于触发策略 A 的条目，必须真实包含 guidelines.md 中 A-001~A-006 之一的特征
3. 对于触发策略 B 的条目，必须真实表现 B-001~B-006 之一的特征
4. T3_Recommend 条目必须含有第一手细节（具体时间地点人物数据），且无任何引流痕迹
5. 场景要多样：覆盖面经、教程、种草、测评、日常、求助等

## 输出格式
返回**且仅返回**一个 JSON 数组，长度 = {batch_size}。每个元素必须包含：
- "content"：生成的 UGC 文本（中文）
- "attack_strategy"：固定填 "edge_case"（旧 schema 兼容字段，本管线不再使用）
- "target_dimension"：从 [{', '.join(repr(d.name) for d in policy.dimensions)}] 中选一个
- "difficulty"：easy / medium / hard / extreme
- "expected_action"：固定填 "BLOCK"（旧 schema 兼容字段，真实判决由 Judge 给出）
- "reasoning"：你为什么生成这条内容（一句话即可）

不要输出任何 markdown 代码块包裹或额外解释文字。"""

    @staticmethod
    def _stamp_ground_truth(cases: list[ChaosCase], targets: list[str]) -> None:
        """把目标 tier + 应触发策略组合写进每条 case 的 metadata，作为隐藏真值。

        若 LLM 返回的 case 数与请求的 targets 数不一致，按位置对齐能匹配的部分，
        多余的 case 用 'unknown' 占位（不阻塞 pipeline）。
        """
        for case, tier in zip(cases, targets, strict=False):
            case.metadata["ground_truth"] = {
                "target_tier": tier,
                "expected_strategies": _TIER_TO_STRATEGIES[tier],
            }
        # 多余的 case（罕见）标记为未知 ground truth
        for case in cases[len(targets):]:
            case.metadata["ground_truth"] = {
                "target_tier": "unknown",
                "expected_strategies": {},
            }

    def _parse_cases(self, raw: str) -> list[ChaosCase]:
        """严格解析 LLM JSON 响应 → ChaosCase 列表。

        与上一版相同的强校验语义：任意一条 Pydantic 校验失败立即抛
        SchemaValidationError，触发 LLMClient.generate_validated 重新发起 LLM 调用。
        """
        json_text = self._extract_json(raw, mode="array")
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise SchemaValidationError(
                f"LLM 输出无法解析为有效 JSON: {e}"
            ) from e

        if not isinstance(data, list):
            raise SchemaValidationError(
                f"LLM 输出顶层不是 JSON 数组: 实际类型 {type(data).__name__}"
            )
        if not data:
            raise SchemaValidationError("LLM 输出是空数组，未生成任何用例")

        cases: list[ChaosCase] = []
        for idx, item in enumerate(data):
            if not isinstance(item, dict):
                raise SchemaValidationError(
                    f"第 {idx} 条用例不是 JSON 对象: {item!r}"
                )
            try:
                cases.append(ChaosCase(**item))
            except ValidationError as e:
                raise SchemaValidationError(
                    f"第 {idx} 条用例不符合 ChaosCase Schema: {e}"
                ) from e

        return cases
