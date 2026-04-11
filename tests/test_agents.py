"""Agent 单元测试 — Mock LLM 响应"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from ecoalign_forge.agents.chaos_creator import ChaosCreator
from ecoalign_forge.agents.moderator import Moderator
from ecoalign_forge.agents.supreme_judge import SupremeJudge
from ecoalign_forge.exceptions import SchemaValidationError
from ecoalign_forge.llm.client import LLMClient
from ecoalign_forge.schemas.chaos import ChaosCase
from ecoalign_forge.schemas.judge import JudgeEvaluation

# ── ChaosCreator 测试 ──────────────────────────────────────


class TestChaosCreator:
    """ChaosCreator Agent 测试"""

    @pytest.fixture
    def creator(self) -> ChaosCreator:
        llm = LLMClient()
        return ChaosCreator(llm=llm, model="test-model")

    def test_parse_cases_valid_json(self, creator: ChaosCreator) -> None:
        """解析有效 JSON 数组"""
        raw = json.dumps([{
            "content": "测试内容",
            "attack_strategy": "direct_violation",
            "target_dimension": "stealth_marketing",
            "difficulty": "medium",
            "expected_action": "BLOCK",
            "reasoning": "直接违规测试",
        }])
        cases = creator._parse_cases(raw)
        assert len(cases) == 1
        assert cases[0].attack_strategy.value == "direct_violation"

    def test_parse_cases_markdown_fenced(self, creator: ChaosCreator) -> None:
        """解析 markdown 代码块包裹的 JSON"""
        raw = "```json\n" + json.dumps([{
            "content": "测试", "attack_strategy": "edge_case",
            "target_dimension": "ai_slop", "difficulty": "easy",
            "expected_action": "PASS", "reasoning": "安全内容",
        }]) + "\n```"
        cases = creator._parse_cases(raw)
        assert len(cases) == 1

    def test_parse_cases_strict_raises_on_malformed(
        self, creator: ChaosCreator
    ) -> None:
        """强校验：任一条 Pydantic 校验失败立即抛 SchemaValidationError"""
        raw = json.dumps([
            {"content": "好的", "attack_strategy": "edge_case",
             "target_dimension": "stealth_marketing", "difficulty": "easy",
             "expected_action": "PASS", "reasoning": "ok"},
            {"content": "缺少必填字段"},  # 缺少 attack_strategy 等
        ])
        with pytest.raises(SchemaValidationError, match="ChaosCase Schema"):
            creator._parse_cases(raw)

    def test_parse_cases_empty_array_raises(
        self, creator: ChaosCreator
    ) -> None:
        """空数组也算解析失败，需触发上层重试"""
        with pytest.raises(SchemaValidationError, match="空数组"):
            creator._parse_cases("[]")

    def test_parse_cases_non_array_top_level_raises(
        self, creator: ChaosCreator
    ) -> None:
        """顶层不是数组（例如 LLM 返回了对象）"""
        with pytest.raises(SchemaValidationError, match="不是 JSON 数组"):
            creator._parse_cases('{"foo": "bar"}')

    def test_parse_cases_invalid_json_raises(
        self, creator: ChaosCreator
    ) -> None:
        """非法 JSON 同样抛 SchemaValidationError"""
        with pytest.raises(SchemaValidationError, match="无法解析"):
            creator._parse_cases("not json at all {{{")

    def test_parse_cases_array_with_non_dict_item_raises(
        self, creator: ChaosCreator
    ) -> None:
        """数组中混入非对象元素（字符串/数字）应触发强校验失败"""
        raw = json.dumps([
            {
                "content": "ok", "attack_strategy": "edge_case",
                "target_dimension": "stealth_marketing", "difficulty": "easy",
                "expected_action": "PASS", "reasoning": "ok",
            },
            "not a dict",
        ])
        with pytest.raises(SchemaValidationError, match="不是 JSON 对象"):
            creator._parse_cases(raw)

    async def test_run_generates_cases(
        self, creator: ChaosCreator, sample_policy
    ) -> None:
        """完整 run 流程（mock generate_validated 直接返回解析后的对象）"""
        cases_fixture = [
            ChaosCase(
                content=f"测试内容_{i}",
                attack_strategy="direct_violation",
                target_dimension="stealth_marketing",
                difficulty="medium",
                expected_action="BLOCK",
                reasoning="测试",
            )
            for i in range(4)
        ]

        creator.llm.generate_validated = AsyncMock(return_value=cases_fixture)
        cases = await creator.run(policy=sample_policy, batch_size=4)
        assert len(cases) == 4
        creator.llm.generate_validated.assert_called_once()
        # 每条 case 都应被打上 ground_truth 标签
        for c in cases:
            assert "ground_truth" in c.metadata
            assert "target_tier" in c.metadata["ground_truth"]
            assert c.metadata["ground_truth"]["target_tier"] in (
                "T0_Block", "T1_Shadowban", "T2_Normal", "T3_Recommend"
            )

    def test_sample_targets_respects_distribution(
        self, creator: ChaosCreator
    ) -> None:
        """采样器应严格按比例分配 batch_size，名额可整除时无误差"""
        targets = creator._sample_targets(
            batch_size=20,
            distribution={
                "T0_Block": 0.25, "T1_Shadowban": 0.25,
                "T2_Normal": 0.25, "T3_Recommend": 0.25,
            },
        )
        from collections import Counter
        c = Counter(targets)
        assert c["T0_Block"] == 5
        assert c["T1_Shadowban"] == 5
        assert c["T2_Normal"] == 5
        assert c["T3_Recommend"] == 5

    def test_sample_targets_handles_remainder(
        self, creator: ChaosCreator
    ) -> None:
        """名额无法整除时，剩余条目按小数部分大小补足，保证总数 = batch_size"""
        targets = creator._sample_targets(
            batch_size=10,
            distribution={
                "T0_Block": 0.15, "T1_Shadowban": 0.30,
                "T2_Normal": 0.30, "T3_Recommend": 0.25,
            },
        )
        assert len(targets) == 10
        # 所有目标必须在合法集合内
        assert all(
            t in ("T0_Block", "T1_Shadowban", "T2_Normal", "T3_Recommend")
            for t in targets
        )


# ── Moderator 测试 ─────────────────────────────────────────


class TestModerator:
    """Moderator Agent 测试（弱版本初级审核员，输出 JudgeEvaluation）"""

    @pytest.fixture
    def moderator(self) -> Moderator:
        llm = LLMClient()
        return Moderator(llm=llm, model="test-model")

    def test_parse_judgment_valid(self, moderator: Moderator) -> None:
        """解析有效的 JudgeEvaluation JSON（含规则编号引用）"""
        raw = json.dumps({
            "has_stealth_marketing": False,
            "is_ai_slop": True,
            "reasoning_trace": "第一步：套话很多\n第二步：命中 B-001\n第三步：T2_Normal",
            "final_decision": "T2_Normal",
        })
        ev = moderator._parse_judgment(raw)
        assert ev.has_stealth_marketing is False
        assert ev.is_ai_slop is True
        assert ev.final_decision == "T2_Normal"

    def test_parse_judgment_invalid_json_raises(
        self, moderator: Moderator
    ) -> None:
        """非法 JSON 应抛 SchemaValidationError 触发外层重试"""
        with pytest.raises(SchemaValidationError, match="无法解析"):
            moderator._parse_judgment("not json {")

    def test_parse_judgment_pydantic_failure_raises(
        self, moderator: Moderator
    ) -> None:
        """非法 final_decision 应抛 SchemaValidationError"""
        raw = json.dumps({
            "has_stealth_marketing": False,
            "is_ai_slop": False,
            "reasoning_trace": "第一步\n第二步：未命中规则\n第三步",
            "final_decision": "T9_Unknown",  # 不在 Literal 集合
        })
        with pytest.raises(SchemaValidationError, match="JudgeEvaluation Schema"):
            moderator._parse_judgment(raw)

    async def test_run_moderates_cases(
        self, moderator: Moderator, sample_policy
    ) -> None:
        """完整 run 流程（mock batch_generate_validated 返回 JudgeEvaluation）"""
        cases = [
            ChaosCase(
                content="测试内容",
                attack_strategy="direct_violation",
                target_dimension="stealth_marketing",
                difficulty="medium",
                expected_action="BLOCK",
                reasoning="测试",
            )
        ]
        parsed = JudgeEvaluation(
            has_stealth_marketing=False,
            is_ai_slop=False,
            reasoning_trace="第一步：常识判断\n第二步：未命中任何规则\n第三步：T2",
            final_decision="T2_Normal",
        )
        moderator.llm.batch_generate_validated = AsyncMock(return_value=[parsed])
        results = await moderator.run(cases=cases, policy=sample_policy)
        assert len(results) == 1
        assert results[0].final_decision == "T2_Normal"
        moderator.llm.batch_generate_validated.assert_called_once()

    def test_default_persona_is_naive(self, moderator: Moderator) -> None:
        """默认构造 Moderator 的 persona 应该是 'naive'（向后兼容）"""
        assert moderator.persona == "naive"
        assert "naive" in moderator.name.lower() or "moderator" in moderator.name.lower()

    def test_accepts_all_defined_personas(self) -> None:
        """四个 persona 都应能正常构造 Moderator 实例"""
        from ecoalign_forge.llm.prompts import MODERATOR_PERSONAS
        llm = LLMClient()
        for persona in MODERATOR_PERSONAS:
            m = Moderator(llm=llm, model="test", persona=persona)
            assert m.persona == persona
            assert persona in m.name

    def test_rejects_unknown_persona(self) -> None:
        """未注册的 persona 名应立刻抛 ValueError，避免静默降级"""
        with pytest.raises(ValueError, match="Unknown moderator persona"):
            Moderator(llm=LLMClient(), model="test", persona="imaginary_one")

    async def test_different_personas_use_different_system_prompts(
        self, sample_policy
    ) -> None:
        """不同 persona 的 Moderator 发给 LLM 的 system prompt 应该不同"""
        from ecoalign_forge.llm.prompts import MODERATOR_PERSONAS

        cases = [
            ChaosCase(
                content="测试", attack_strategy="direct_violation",
                target_dimension="stealth_marketing", difficulty="medium",
                expected_action="BLOCK", reasoning="测试",
            )
        ]
        ok_eval = JudgeEvaluation(
            has_stealth_marketing=False, is_ai_slop=False,
            reasoning_trace="第一步\n第二步：未命中任何规则\n第三步：T2",
            final_decision="T2_Normal",
        )

        captured_prompts: dict[str, list] = {}

        def _make_capture(persona_name: str):
            """闭包绑定当前 persona_name，避免 B023 loop 变量陷阱"""
            async def _capture(prompts, parser, **kwargs):
                captured_prompts[persona_name] = prompts[0]
                return [ok_eval]
            return _capture

        for persona in MODERATOR_PERSONAS:
            m = Moderator(llm=LLMClient(), model="test", persona=persona)
            m.llm.batch_generate_validated = _make_capture(persona)  # type: ignore[method-assign]
            await m.run(cases=cases, policy=sample_policy)

        # 4 个 persona 的 system prompt 应该两两不同
        system_texts = {
            p: msgs[0]["content"] for p, msgs in captured_prompts.items()
        }
        assert len(set(system_texts.values())) == len(MODERATOR_PERSONAS)

    async def test_run_keeps_none_for_failed_positions(
        self, moderator: Moderator, sample_policy
    ) -> None:
        """batch_generate_validated 返回 None 的位置必须**保留**为 None，
        而不是被过滤掉——下游 SupremeJudge 依赖位置对齐。"""
        cases = [
            ChaosCase(
                content=f"内容_{i}",
                attack_strategy="direct_violation",
                target_dimension="stealth_marketing",
                difficulty="medium",
                expected_action="BLOCK",
                reasoning="测试",
            )
            for i in range(2)
        ]
        ok_eval = JudgeEvaluation(
            has_stealth_marketing=True, is_ai_slop=False,
            reasoning_trace="第一步：发现暗号\n第二步：命中 A-004\n第三步：T1",
            final_decision="T1_Shadowban",
        )
        moderator.llm.batch_generate_validated = AsyncMock(
            return_value=[ok_eval, None]
        )
        results = await moderator.run(cases=cases, policy=sample_policy)
        # 必须保持长度 = cases 长度，None 占位仍在
        assert len(results) == 2
        assert results[0] is not None
        assert results[0].final_decision == "T1_Shadowban"
        assert results[1] is None


# ── SupremeJudge 测试 ──────────────────────────────────────


class TestSupremeJudge:
    """SupremeJudge Agent 测试"""

    @pytest.fixture
    def judge(self) -> SupremeJudge:
        llm = LLMClient()
        return SupremeJudge(llm=llm, model="test-model")

    def test_parse_evaluation_invalid_json_raises(
        self, judge: SupremeJudge
    ) -> None:
        """非法 JSON 应抛 SchemaValidationError 触发外层重试"""
        with pytest.raises(SchemaValidationError, match="无法解析"):
            judge._parse_evaluation("not json")

    def test_parse_evaluation_pydantic_failure_raises(
        self, judge: SupremeJudge
    ) -> None:
        """非法 final_decision 应抛 SchemaValidationError"""
        raw = json.dumps({
            "has_stealth_marketing": True,
            "is_ai_slop": False,
            "reasoning_trace": "第一步: x\n第二步: y\n第三步: z",
            "final_decision": "T4_FullBlast",  # 不在 Literal 集合内
        })
        with pytest.raises(SchemaValidationError, match="Schema 约束"):
            judge._parse_evaluation(raw)

    @staticmethod
    def _make_case_mod_judge(
        mod_decision: str,
        judge_decision: str,
        judge_has_stealth: bool = True,
    ):
        """构造一组 (case, mod_eval, judge_eval) 用于 _build_dpo_pair 测试"""
        case = ChaosCase(
            content="待审核内容",
            attack_strategy="direct_violation",
            target_dimension="stealth_marketing",
            difficulty="medium",
            expected_action="BLOCK",
            reasoning="测试",
        )
        mod_eval = JudgeEvaluation(
            has_stealth_marketing=False,
            is_ai_slop=False,
            reasoning_trace=(
                "第一步：粗看内容\n"
                "第二步：凭直觉判断，未命中任何已知规则\n"
                f"第三步：定级 {mod_decision}"
            ),
            final_decision=mod_decision,  # type: ignore[arg-type]
        )
        judge_eval = JudgeEvaluation(
            has_stealth_marketing=judge_has_stealth,
            is_ai_slop=False,
            reasoning_trace=(
                "第一步：发现 vx 字样\n"
                "第二步：命中 A-002（vx 谐音字替代）\n"
                f"第三步：定级 {judge_decision}"
            ),
            final_decision=judge_decision,  # type: ignore[arg-type]
        )
        return case, mod_eval, judge_eval

    def test_build_dpo_pair_judge_t0_moderator_t2(
        self, judge: SupremeJudge, sample_policy
    ) -> None:
        """Judge=T0_Block，Moderator=T2_Normal：最大严重度差距，应生成 DPO 对"""
        case, mod_eval, judge_eval = self._make_case_mod_judge(
            mod_decision="T2_Normal", judge_decision="T0_Block"
        )
        pair = judge._build_dpo_pair(case, mod_eval, judge_eval, sample_policy)
        assert pair is not None
        # chosen / rejected 都是合法的 JudgeEvaluation JSON
        chosen_obj = json.loads(pair.chosen)
        rejected_obj = json.loads(pair.rejected)
        assert chosen_obj["final_decision"] == "T0_Block"
        assert rejected_obj["final_decision"] == "T2_Normal"
        # chosen=Judge 金标固定 0.9，rejected=0.9-gap，gap=|1.0-0.3|=0.7
        assert abs(pair.chosen_score - 0.9) < 1e-9
        assert abs(pair.rejected_score - 0.2) < 1e-9
        assert abs(pair.preference_gap - 0.7) < 1e-9

    def test_build_dpo_pair_aligned_returns_none(
        self, judge: SupremeJudge, sample_policy
    ) -> None:
        """Judge=T1_Shadowban，Moderator=T1_Shadowban：同档位无 DPO 信号 → None"""
        case, mod_eval, judge_eval = self._make_case_mod_judge(
            mod_decision="T1_Shadowban", judge_decision="T1_Shadowban"
        )
        pair = judge._build_dpo_pair(case, mod_eval, judge_eval, sample_policy)
        assert pair is None

    def test_build_dpo_pair_judge_t3_moderator_t0(
        self, judge: SupremeJudge, sample_policy
    ) -> None:
        """Judge=T3_Recommend，Moderator=T0_Block：审核员过度拦截，应生成 DPO 对"""
        case, mod_eval, judge_eval = self._make_case_mod_judge(
            mod_decision="T0_Block",
            judge_decision="T3_Recommend",
            judge_has_stealth=False,
        )
        pair = judge._build_dpo_pair(case, mod_eval, judge_eval, sample_policy)
        assert pair is not None
        chosen_obj = json.loads(pair.chosen)
        rejected_obj = json.loads(pair.rejected)
        assert chosen_obj["final_decision"] == "T3_Recommend"
        assert rejected_obj["final_decision"] == "T0_Block"
        # chosen=Judge 金标 0.9, gap=|0.0-1.0|=1.0, rejected=max(0,0.9-1.0)=0.0
        assert abs(pair.chosen_score - 0.9) < 1e-9
        assert pair.rejected_score == 0.0
        assert abs(pair.preference_gap - 1.0) < 1e-9

    def test_build_dpo_pair_unified_schema(
        self, judge: SupremeJudge, sample_policy
    ) -> None:
        """chosen / rejected 都必须是合法的 JudgeEvaluation JSON（同 schema 对比）"""
        case, mod_eval, judge_eval = self._make_case_mod_judge(
            mod_decision="T2_Normal", judge_decision="T0_Block"
        )
        pair = judge._build_dpo_pair(case, mod_eval, judge_eval, sample_policy)
        assert pair is not None
        # 反序列化后两边都应是合法 JudgeEvaluation
        chosen_round = JudgeEvaluation.model_validate_json(pair.chosen)
        rejected_round = JudgeEvaluation.model_validate_json(pair.rejected)
        assert chosen_round.final_decision == "T0_Block"
        assert rejected_round.final_decision == "T2_Normal"

    def test_build_dpo_pair_reasoning_quality_pair(
        self, judge: SupremeJudge, sample_policy
    ) -> None:
        """同 final_decision，但 Judge 引用 2 条规则、Moderator 0 条 → 生成质量对"""
        case = ChaosCase(
            content="测试", attack_strategy="edge_case",
            target_dimension="stealth_marketing", difficulty="medium",
            expected_action="BLOCK", reasoning="r",
        )
        # 都判 T1，但 Judge 有 2 条规则引用，Moderator 凭直觉
        judge_eval = JudgeEvaluation(
            has_stealth_marketing=True, is_ai_slop=False,
            reasoning_trace=(
                "第一步：发现 vx 谐音 + 主页简介暗号\n"
                "第二步：命中 A-002 + A-004\n"
                "第三步：T1_Shadowban"
            ),
            final_decision="T1_Shadowban",
        )
        mod_eval = JudgeEvaluation(
            has_stealth_marketing=True, is_ai_slop=False,
            reasoning_trace=(
                "第一步：感觉像引流\n"
                "第二步：未命中明确规则\n"
                "第三步：T1_Shadowban"
            ),
            final_decision="T1_Shadowban",
        )
        pair = judge._build_dpo_pair(case, mod_eval, judge_eval, sample_policy)
        assert pair is not None
        assert abs(pair.preference_gap - 0.3) < 1e-9
        # chosen 包含 2 条规则引用
        chosen_obj = JudgeEvaluation.model_validate_json(pair.chosen)
        assert "A-002" in chosen_obj.reasoning_trace
        assert "A-004" in chosen_obj.reasoning_trace

    def test_build_dpo_pair_quality_pair_skipped_when_judge_too_few_rules(
        self, judge: SupremeJudge, sample_policy
    ) -> None:
        """同档位但 Judge 只引用 1 条规则 → 不生成质量对"""
        case = ChaosCase(
            content="x", attack_strategy="edge_case",
            target_dimension="stealth_marketing", difficulty="easy",
            expected_action="PASS", reasoning="r",
        )
        judge_eval = JudgeEvaluation(
            has_stealth_marketing=True, is_ai_slop=False,
            reasoning_trace="第一步\n第二步：命中 A-002\n第三步：T1",
            final_decision="T1_Shadowban",
        )
        mod_eval = JudgeEvaluation(
            has_stealth_marketing=False, is_ai_slop=False,
            reasoning_trace="第一步\n第二步：未命中\n第三步：T1",
            final_decision="T1_Shadowban",
        )
        pair = judge._build_dpo_pair(case, mod_eval, judge_eval, sample_policy)
        assert pair is None

    def test_build_dpo_pair_quality_pair_skipped_when_moderator_has_rules(
        self, judge: SupremeJudge, sample_policy
    ) -> None:
        """Moderator 也引用了规则 → 不算"无据 vs 有据"，跳过"""
        case = ChaosCase(
            content="x", attack_strategy="edge_case",
            target_dimension="stealth_marketing", difficulty="easy",
            expected_action="PASS", reasoning="r",
        )
        judge_eval = JudgeEvaluation(
            has_stealth_marketing=True, is_ai_slop=False,
            reasoning_trace="第一步\n第二步：命中 A-002 + A-004\n第三步：T1",
            final_decision="T1_Shadowban",
        )
        mod_eval = JudgeEvaluation(
            has_stealth_marketing=True, is_ai_slop=False,
            reasoning_trace="第一步\n第二步：命中 A-001\n第三步：T1",
            final_decision="T1_Shadowban",
        )
        pair = judge._build_dpo_pair(case, mod_eval, judge_eval, sample_policy)
        assert pair is None

    def test_build_dpo_pairs_multi_persona(
        self, judge: SupremeJudge, sample_policy
    ) -> None:
        """对同一份 judge_eval，给 3 个不同 persona 的 rejected 候选构造配对"""
        case = ChaosCase(
            content="测试", attack_strategy="edge_case",
            target_dimension="stealth_marketing", difficulty="medium",
            expected_action="BLOCK", reasoning="r",
        )
        # Judge 判 T1，引用 2 条规则
        judge_eval = JudgeEvaluation(
            has_stealth_marketing=True, is_ai_slop=False,
            reasoning_trace=(
                "第一步：发现 vx + 主页简介暗号\n"
                "第二步：命中 A-002 + A-004\n"
                "第三步：T1_Shadowban"
            ),
            final_decision="T1_Shadowban",
        )

        def _mod(decision: str) -> JudgeEvaluation:
            return JudgeEvaluation(
                has_stealth_marketing=False, is_ai_slop=False,
                reasoning_trace=f"第一步\n第二步：未命中任何规则\n第三步：{decision}",
                final_decision=decision,  # type: ignore[arg-type]
            )

        # 3 个 persona：
        #  naive → T1（同档位，应走 reasoning_quality 分支）
        #  lax   → T2（直接分歧）
        #  strict → T0（直接分歧）
        persona_evals = [
            [_mod("T1_Shadowban")],  # naive
            [_mod("T2_Normal")],     # lax
            [_mod("T0_Block")],      # strict
        ]

        pairs = judge.build_dpo_pairs_multi_persona(
            cases=[case],
            judge_evals=[judge_eval],
            persona_eval_sets=persona_evals,
            policy=sample_policy,
        )

        # 期望：naive 产出 reasoning_quality pair（Judge 引用 2 条规则，mod 引用 0）
        #       lax 产出 direct_disagreement（T1 vs T2，gap=0.4）
        #       strict 产出 direct_disagreement（T1 vs T0，gap=0.3）
        assert len(pairs) == 3
        gaps = sorted(p.preference_gap for p in pairs)
        # 两个 direct 对：|0.7-0.3|=0.4 和 |0.7-1.0|=0.3；一个 quality 对：0.3
        assert any(abs(g - 0.4) < 1e-9 for g in gaps)

    def test_build_dpo_pairs_multi_persona_skips_none(
        self, judge: SupremeJudge, sample_policy
    ) -> None:
        """persona 列表中的 None 位置应被跳过"""
        case = ChaosCase(
            content="x", attack_strategy="edge_case",
            target_dimension="stealth_marketing", difficulty="easy",
            expected_action="PASS", reasoning="r",
        )
        judge_eval = JudgeEvaluation(
            has_stealth_marketing=True, is_ai_slop=False,
            reasoning_trace="第一步\n第二步：命中 A-002\n第三步：T1",
            final_decision="T1_Shadowban",
        )
        pairs = judge.build_dpo_pairs_multi_persona(
            cases=[case],
            judge_evals=[judge_eval],
            persona_eval_sets=[[None], [None]],  # 两个 persona 都失败
            policy=sample_policy,
        )
        assert pairs == []

    def test_build_dpo_pairs_multi_persona_length_mismatch(
        self, judge: SupremeJudge, sample_policy
    ) -> None:
        """persona 列表长度与 cases 不一致应立刻抛 ValueError"""
        case = ChaosCase(
            content="x", attack_strategy="edge_case",
            target_dimension="stealth_marketing", difficulty="easy",
            expected_action="PASS", reasoning="r",
        )
        judge_eval = JudgeEvaluation(
            has_stealth_marketing=True, is_ai_slop=False,
            reasoning_trace="第一步\n第二步：命中 A-002\n第三步：T1",
            final_decision="T1_Shadowban",
        )
        with pytest.raises(ValueError, match="长度"):
            judge.build_dpo_pairs_multi_persona(
                cases=[case],
                judge_evals=[judge_eval],
                persona_eval_sets=[[judge_eval, judge_eval]],  # 长度 2 vs 1
                policy=sample_policy,
            )

    async def test_run_judge_prompt_contains_guidelines(
        self, judge: SupremeJudge, sample_policy
    ) -> None:
        """Judge run 时必须把 guidelines.md 注入到 user prompt 里"""
        case = ChaosCase(
            content="test",
            attack_strategy="edge_case",
            target_dimension="stealth_marketing",
            difficulty="easy",
            expected_action="PASS",
            reasoning="r",
        )
        mod_eval = JudgeEvaluation(
            has_stealth_marketing=False, is_ai_slop=False,
            reasoning_trace="第一步\n第二步：未命中任何规则\n第三步",
            final_decision="T2_Normal",
        )
        judge_eval = JudgeEvaluation(
            has_stealth_marketing=False, is_ai_slop=False,
            reasoning_trace="第一步\n第二步：未命中任何规则\n第三步",
            final_decision="T2_Normal",
        )
        captured_prompts: list = []

        async def _capture(prompts, parser, **kwargs):
            captured_prompts.extend(prompts)
            return [judge_eval]

        judge.llm.batch_generate_validated = _capture  # type: ignore[method-assign]
        await judge.run(cases=[case], responses=[mod_eval], policy=sample_policy)

        assert len(captured_prompts) == 1
        # user message 应包含 guidelines.md 中的关键 token
        user_text = captured_prompts[0][1]["content"]
        assert "A-001" in user_text or "策略 A" in user_text
        assert "B-001" in user_text or "策略 B" in user_text
