"""SupremeJudge — 内容分发分级最终决策 + DPO 对生成。

迁移到统一 ontology 后变化：
- system prompt 在 user 消息阶段注入完整 guidelines.md（强契约依据）
- 不再接收 ModeratorResponse，而是接收 list[JudgeEvaluation | None]（来自 Moderator）
- 与 Moderator 的关联通过 list 位置对齐而非 case_id（JudgeEvaluation 没有 case_id 字段）
- _build_dpo_pair 重写：chosen / rejected 同 schema 直接对比，无需翻译表

DPO 配对策略（路径 3 第一组）：
1. **直接分歧**：final_decision 不同 → chosen=Judge / rejected=Moderator
2. **推理质量**：final_decision 相同，但 Judge 引用 ≥2 条规则编号、Moderator 0 条
   → 同档位但"有据 vs 无据"的偏好对（preference_gap=0.3 软信号）
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from ecoalign_forge._guidelines import GUIDELINES_TEXT
from ecoalign_forge.agents.base import BaseAgent
from ecoalign_forge.exceptions import SchemaValidationError
from ecoalign_forge.llm.prompts import JUDGE_SYSTEM
from ecoalign_forge.schemas.chaos import ChaosCase
from ecoalign_forge.schemas.dpo import DPO_Pair
from ecoalign_forge.schemas.judge import DECISION_SEVERITY, JudgeEvaluation
from ecoalign_forge.schemas.policy import PolicyInput

# 正则识别 reasoning_trace 中的规则编号引用
_RULE_ID_PATTERN = re.compile(r"\b([AB]-\d{3})\b")

# Reasoning Quality DPO 对的偏好差距（软信号，比直接分歧弱）
# 设为 0.3 而非 1.0，因为同档位的判决正确性其实是平的，只是推理过程更可追溯
_REASONING_QUALITY_GAP = 0.3
_REASONING_QUALITY_CHOSEN_SCORE = 0.8
_REASONING_QUALITY_REJECTED_SCORE = 0.5

# Judge 至少引用这么多条规则才被视为"有据可依"
_MIN_RULE_CITATIONS_FOR_QUALITY_PAIR = 2


class SupremeJudge(BaseAgent):
    """Agent 3: 终极生态法官 + DPO 训练对生成器。"""

    name = "SupremeJudge"

    async def evaluate(
        self,
        cases: list[ChaosCase],
    ) -> list[JudgeEvaluation | None]:
        """只产出 gold 判决，不做 DPO 配对。

        返回列表与 cases 按位置对齐；解析重试用尽的位置为 None。
        这个方法是 multi-persona 架构的关键：一份 gold 判决可以对多个
        persona 的 rejected 候选做配对，避免 Judge 重复调用。
        """
        self._log(f"Judging {len(cases)} content items for distribution tiering")
        prompts = [self._build_user_prompt(case) for case in cases]
        return await self.llm.batch_generate_validated(
            prompts=prompts,
            parser=self._parse_evaluation,
            model=self.model,
            temperature=0.2,
        )

    def build_dpo_pairs_multi_persona(
        self,
        cases: list[ChaosCase],
        judge_evals: list[JudgeEvaluation | None],
        persona_eval_sets: list[list[JudgeEvaluation | None]],
        policy: PolicyInput,
    ) -> list[DPO_Pair]:
        """对每个 case × 每个 persona 的组合尝试构造 DPO 对。

        Args:
            cases: 原始用例列表
            judge_evals: Judge 金标判决，与 cases 位置对齐
            persona_eval_sets: N 个 persona 的判决集合，每个都与 cases 位置对齐
            policy: 策略上下文

        Returns:
            所有有效的 DPO 对（同档位无信号的对会被 _build_dpo_pair 自动跳过）
        """
        if len(cases) != len(judge_evals):
            raise ValueError(
                f"cases ({len(cases)}) 与 judge_evals ({len(judge_evals)}) "
                f"长度不一致——位置对齐被破坏"
            )
        for idx, persona_evals in enumerate(persona_eval_sets):
            if len(persona_evals) != len(cases):
                raise ValueError(
                    f"persona_eval_sets[{idx}] 长度 {len(persona_evals)} "
                    f"与 cases 长度 {len(cases)} 不一致"
                )

        dpo_pairs: list[DPO_Pair] = []
        for i, case in enumerate(cases):
            judge_eval = judge_evals[i]
            if judge_eval is None:
                continue
            for persona_evals in persona_eval_sets:
                mod_eval = persona_evals[i]
                if mod_eval is None:
                    continue
                pair = self._build_dpo_pair(case, mod_eval, judge_eval, policy)
                if pair is not None:
                    dpo_pairs.append(pair)
        return dpo_pairs

    async def run(
        self,
        cases: list[ChaosCase],
        responses: list[JudgeEvaluation | None],
        policy: PolicyInput,
        **kwargs: Any,
    ) -> tuple[list[JudgeEvaluation | None], list[DPO_Pair]]:
        """向后兼容入口：单 persona 路径。

        对每条 case 产出 gold 判决，并按需生成 DPO 对。内部调用
        `evaluate` + `build_dpo_pairs_multi_persona`（只传 1 个 persona 集合）。

        返回的 judge_results 与 cases 保持位置对齐（失败位为 None），
        调用方按 index 关联时语义一致。
        """
        if len(cases) != len(responses):
            raise ValueError(
                f"cases ({len(cases)}) 与 responses ({len(responses)}) "
                f"长度不一致——位置对齐被破坏，无法继续"
            )
        judge_results = await self.evaluate(cases)
        dpo_pairs = self.build_dpo_pairs_multi_persona(
            cases=cases,
            judge_evals=judge_results,
            persona_eval_sets=[responses],
            policy=policy,
        )
        succeeded = sum(1 for e in judge_results if e is not None)
        self._log(
            f"Produced {succeeded} evaluations, {len(dpo_pairs)} DPO pairs"
        )
        return judge_results, dpo_pairs

    @staticmethod
    def _build_user_prompt(case: ChaosCase) -> list[dict]:
        """构造一条 (system + user) 消息对，user 部分注入完整 guidelines.md。"""
        user_text = f"""请对以下用户内容做出 T0/T1/T2/T3 分发分级判决。

## 待审核内容
\"\"\"{case.content}\"\"\"

## 判决依据手册（必须严格遵守，所有结论必须能反推到具体条款编号）
{GUIDELINES_TEXT}

## 输出要求
返回**且仅返回**一个 JSON 对象，必须包含以下 4 个字段（字段名严格大小写）：

- "has_stealth_marketing": bool — 是否命中【策略 A：高隐蔽性私域引流】
- "is_ai_slop": bool — 是否命中【策略 B：低信息熵 AI 洗稿】
- "reasoning_trace": str — 三步思考链，必须以「第一步：」「第二步：」「第三步：」分段。
  第一步引用原文证据；第二步对照 guidelines.md 中的 A-XXX / B-XXX 规则编号；
  第三步解释 final_decision 的最终选择依据
- "final_decision": str — 严格四选一："T0_Block" / "T1_Shadowban" / "T2_Normal" / "T3_Recommend"

不要任何 markdown 包裹或额外说明文字。"""

        return [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": user_text},
        ]

    def _parse_evaluation(self, raw: str) -> JudgeEvaluation:
        """解析 LLM 输出为 JudgeEvaluation。失败抛 SchemaValidationError 触发重试。"""
        json_text = self._extract_json(raw, mode="object")
        try:
            data = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise SchemaValidationError(
                f"Judge 输出无法解析为有效 JSON: {e}"
            ) from e

        try:
            return JudgeEvaluation(**data)
        except ValidationError as e:
            raise SchemaValidationError(
                f"Judge 输出不符合 Schema 约束: {e}"
            ) from e

    def _build_dpo_pair(
        self,
        case: ChaosCase,
        moderator_eval: JudgeEvaluation,
        judge_eval: JudgeEvaluation,
        policy: PolicyInput,
    ) -> DPO_Pair | None:
        """构造 DPO 对：chosen=Judge 的 gold 判决，rejected=Moderator 的初级判决。

        两种配对策略（按优先级）：

        1. **直接分歧**：final_decision 不同 → chosen=Judge / rejected=Moderator，
           preference_gap = 严重度绝对差（最强信号）
        2. **推理质量**：final_decision 相同但 Judge 引用了 ≥2 条规则编号、
           Moderator 一条都没引用 → 同档位但"有据 vs 无据"的弱偏好对
           （preference_gap = 0.3 软信号），训练模型学会**有依据**地判决

        chosen / rejected 都是完整 JudgeEvaluation 的 JSON 序列化。
        """
        if moderator_eval.final_decision != judge_eval.final_decision:
            return self._build_direct_disagreement_pair(
                case, moderator_eval, judge_eval, policy
            )
        return self._build_reasoning_quality_pair(
            case, moderator_eval, judge_eval, policy
        )

    @staticmethod
    def _make_dpo_prompt(case: ChaosCase, policy: PolicyInput) -> str:
        return (
            f"You are a content distribution judge for the '{policy.name}' platform.\n"
            f"Read the content below and output a JudgeEvaluation JSON deciding "
            f"whether it hits stealth marketing / AI slop, with a 3-step CoT and "
            f"a final tier in [T0_Block, T1_Shadowban, T2_Normal, T3_Recommend].\n\n"
            f"Content: \"{case.content}\""
        )

    def _build_direct_disagreement_pair(
        self,
        case: ChaosCase,
        moderator_eval: JudgeEvaluation,
        judge_eval: JudgeEvaluation,
        policy: PolicyInput,
    ) -> DPO_Pair | None:
        """final_decision 不同时的直接分歧 DPO 对。

        chosen_score/rejected_score 表示"判决质量"而非"严厉程度"：
        chosen(Judge 金标)固定高分，rejected(Moderator)固定低分，
        gap 用严厉度差值衡量信号强度。保证 chosen_score > rejected_score。
        """
        severity_gap = abs(
            DECISION_SEVERITY[judge_eval.final_decision]
            - DECISION_SEVERITY[moderator_eval.final_decision]
        )

        if severity_gap < 0.1:
            return None

        # chosen=Judge 金标判决，质量固定高分；rejected=Moderator 弱判决，低分
        # gap 使用严厉度差值归一化到 [0, 1]
        chosen_score = 0.9
        rejected_score = max(0.0, 0.9 - severity_gap)
        gap = min(severity_gap, 1.0)

        return DPO_Pair(
            prompt=self._make_dpo_prompt(case, policy),
            chosen=judge_eval.model_dump_json(),
            rejected=moderator_eval.model_dump_json(),
            chosen_score=chosen_score,
            rejected_score=rejected_score,
            preference_gap=gap,
            dimension=case.target_dimension,
            difficulty=case.difficulty.value,
            source_case_id=case.case_id,
        )

    def _build_reasoning_quality_pair(
        self,
        case: ChaosCase,
        moderator_eval: JudgeEvaluation,
        judge_eval: JudgeEvaluation,
        policy: PolicyInput,
    ) -> DPO_Pair | None:
        """final_decision 相同时的推理质量 DPO 对。

        条件：Judge 引用 ≥ MIN 条规则编号 AND Moderator 一条也未引用。
        这种配对训练模型学会"有据可依"地判决，而不只是"猜对档位"。
        """
        judge_rules = set(_RULE_ID_PATTERN.findall(judge_eval.reasoning_trace))
        mod_rules = set(_RULE_ID_PATTERN.findall(moderator_eval.reasoning_trace))

        if len(judge_rules) < _MIN_RULE_CITATIONS_FOR_QUALITY_PAIR or mod_rules:
            # 不满足质量差距条件
            return None

        return DPO_Pair(
            prompt=self._make_dpo_prompt(case, policy),
            chosen=judge_eval.model_dump_json(),
            rejected=moderator_eval.model_dump_json(),
            chosen_score=_REASONING_QUALITY_CHOSEN_SCORE,
            rejected_score=_REASONING_QUALITY_REJECTED_SCORE,
            preference_gap=_REASONING_QUALITY_GAP,
            dimension=case.target_dimension,
            difficulty=case.difficulty.value,
            source_case_id=case.case_id,
        )
