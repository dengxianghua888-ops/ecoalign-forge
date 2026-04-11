"""AgentOrchestrator 集成测试 — Mock 三个 Agent"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ecoalign_forge.engine.orchestrator import AgentOrchestrator
from ecoalign_forge.exceptions import AgentError
from ecoalign_forge.schemas.chaos import ChaosCase
from ecoalign_forge.schemas.dpo import DPO_Pair
from ecoalign_forge.schemas.judge import JudgeEvaluation
from ecoalign_forge.schemas.pipeline import PipelineConfig


def _make_case() -> ChaosCase:
    return ChaosCase(
        content="测试内容",
        attack_strategy="direct_violation",
        target_dimension="stealth_marketing",
        difficulty="medium",
        expected_action="BLOCK",
        reasoning="测试",
    )


def _make_response(case_id: str = "") -> JudgeEvaluation:
    """Moderator 的初级判决（与 Judge 同 schema 的弱版本）。
    凭直觉判定，未命中任何规则。"""
    del case_id
    return JudgeEvaluation(
        has_stealth_marketing=False,
        is_ai_slop=False,
        reasoning_trace="第一步：常识判断\n第二步：未命中明显违规规则\n第三步：T2_Normal",
        final_decision="T2_Normal",
    )


def _make_evaluation(case_id: str) -> JudgeEvaluation:
    # case_id 参数保留以兼容旧调用签名；新模型不持有 case_id 字段
    del case_id
    return JudgeEvaluation(
        has_stealth_marketing=True,
        is_ai_slop=False,
        reasoning_trace=(
            "第一步：发现 vx 谐音字\n"
            "第二步：命中 A-002（vx 谐音字替代）\n"
            "第三步：单独命中策略 A，定级 T1_Shadowban"
        ),
        final_decision="T1_Shadowban",
    )


def _make_dpo_pair(case_id: str) -> DPO_Pair:
    return DPO_Pair(
        prompt="p", chosen="c", rejected="r",
        chosen_score=0.9, rejected_score=0.2,
        preference_gap=0.7, dimension="violence",
        difficulty="medium", source_case_id=case_id,
    )


class TestAgentOrchestrator:
    """AgentOrchestrator 集成测试"""

    @pytest.fixture
    def orchestrator(self, tmp_path: Path):
        """创建配置好的 Orchestrator，使用临时目录"""
        config = PipelineConfig(num_samples=5, batch_size=5)
        with (
            patch("ecoalign_forge.engine.orchestrator.settings") as mock_settings,
            patch("ecoalign_forge.storage.store.settings") as mock_store_settings,
        ):
            mock_settings.data_dir = tmp_path / "data"
            mock_settings.datasets_dir = tmp_path / "data" / "datasets"
            mock_settings.chaos_creator_model = "test-model"
            mock_settings.moderator_model = "test-model"
            mock_settings.judge_model = "test-model"
            mock_settings.ensure_dirs = MagicMock()

            mock_store_settings.datasets_dir = tmp_path / "data" / "datasets"

            orch = AgentOrchestrator(
                config=config,
                enable_constitutional=False,
                enable_flywheel=False,
                enable_adaptive_sampling=False,
            )

            # 确保目录存在
            (tmp_path / "data" / "datasets").mkdir(parents=True, exist_ok=True)

            return orch

    async def test_full_pipeline(self, orchestrator, sample_policy) -> None:
        """完整管道流程"""
        case = _make_case()
        cases = [case]
        resp = _make_response(case.case_id)
        ev = _make_evaluation(case.case_id)
        pair = _make_dpo_pair(case.case_id)

        orchestrator.chaos_creator.run = AsyncMock(return_value=cases)
        orchestrator.moderator.run = AsyncMock(return_value=[resp])
        orchestrator.judge.run = AsyncMock(return_value=([ev], [pair]))

        result = await orchestrator.run(policy=sample_policy, num_samples=1)

        assert result.total_cases == 1
        assert result.total_dpo_pairs == 1
        assert result.total_evaluations == 1
        orchestrator.chaos_creator.run.assert_called_once()
        orchestrator.moderator.run.assert_called_once()
        orchestrator.judge.run.assert_called_once()

    async def test_multiple_batches(self, orchestrator, sample_policy) -> None:
        """多批次执行"""
        orchestrator.config.batch_size = 2

        case = _make_case()
        orchestrator.chaos_creator.run = AsyncMock(return_value=[case])
        orchestrator.moderator.run = AsyncMock(
            return_value=[_make_response(case.case_id)]
        )
        orchestrator.judge.run = AsyncMock(
            return_value=([_make_evaluation(case.case_id)], [_make_dpo_pair(case.case_id)])
        )

        await orchestrator.run(policy=sample_policy, num_samples=5)

        # 5 样本，batch_size=2，应执行 3 批
        assert orchestrator.chaos_creator.run.call_count == 3

    async def test_agent_error_recovery(self, orchestrator, sample_policy) -> None:
        """Agent 异常后管道继续"""
        case = _make_case()

        # 第一次调用抛异常，后续正常
        orchestrator.chaos_creator.run = AsyncMock(
            side_effect=[
                AgentError("ChaosCreator", "测试错误"),
                [case],
            ]
        )
        orchestrator.moderator.run = AsyncMock(
            return_value=[_make_response(case.case_id)]
        )
        orchestrator.judge.run = AsyncMock(
            return_value=([_make_evaluation(case.case_id)], [])
        )

        orchestrator.config.batch_size = 3
        await orchestrator.run(policy=sample_policy, num_samples=6)

        # 第一批失败，第二批成功
        assert orchestrator.chaos_creator.run.call_count == 2

    async def test_result_output_path(self, orchestrator, sample_policy) -> None:
        """结果包含输出路径"""
        case = _make_case()
        orchestrator.chaos_creator.run = AsyncMock(return_value=[case])
        orchestrator.moderator.run = AsyncMock(
            return_value=[_make_response(case.case_id)]
        )
        orchestrator.judge.run = AsyncMock(
            return_value=([_make_evaluation(case.case_id)], [_make_dpo_pair(case.case_id)])
        )

        result = await orchestrator.run(policy=sample_policy, num_samples=1)

        assert result.output_path != ""
        assert Path(result.output_path).exists()

    async def test_metrics_persistence(self, orchestrator, sample_policy) -> None:
        """管道执行后指标被持久化"""
        case = _make_case()
        orchestrator.chaos_creator.run = AsyncMock(return_value=[case])
        orchestrator.moderator.run = AsyncMock(
            return_value=[_make_response(case.case_id)]
        )
        orchestrator.judge.run = AsyncMock(
            return_value=([_make_evaluation(case.case_id)], [])
        )

        await orchestrator.run(policy=sample_policy, num_samples=1)

        assert orchestrator._metrics_path.exists()
        assert orchestrator._runs_path.exists()
