"""AgentOrchestrator — pipeline scheduler for the multi-agent workflow.

集成全部模块的完整管道：
  Stage 1: ChaosCreator 红队生成（自适应采样驱动）
  Stage 2: Moderator 多 persona 审核
  Stage 3: SupremeJudge 终审裁决
  Stage 4: Constitutional AI 自我修正（可选）
  Post:    DataLineage 注入 + 质量评分 + IAA 计算 + 飞轮记录
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ecoalign_forge.agents.chaos_creator import ChaosCreator
from ecoalign_forge.agents.constitutional import ConstitutionalReviewer
from ecoalign_forge.agents.moderator import Moderator
from ecoalign_forge.agents.supreme_judge import SupremeJudge
from ecoalign_forge.config import settings
from ecoalign_forge.engine.adaptive_sampler import AdaptiveSampler
from ecoalign_forge.engine.flywheel import FlyWheelOrchestrator, RoundMetrics
from ecoalign_forge.exceptions import AgentError, LLMError, PipelineError
from ecoalign_forge.llm.client import LLMClient
from ecoalign_forge.quality.scorer import QualityScorer
from ecoalign_forge.schemas.chaos import ChaosCase
from ecoalign_forge.schemas.dpo import DPO_Pair
from ecoalign_forge.schemas.judge import JudgeEvaluation
from ecoalign_forge.schemas.lineage import DataLineage
from ecoalign_forge.schemas.pipeline import (
    PipelineConfig,
    PipelineResult,
    PipelineRun,
    PipelineStatus,
)
from ecoalign_forge.schemas.policy import PolicyInput
from ecoalign_forge.storage.agreement import compute_batch_iaa
from ecoalign_forge.storage.metrics import MetricsCollector
from ecoalign_forge.storage.store import DataStore

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Orchestrates the full multi-agent pipeline with all integrated modules."""

    def __init__(
        self,
        config: PipelineConfig | None = None,
        *,
        demo: bool = False,
        enable_constitutional: bool = True,
        enable_flywheel: bool = True,
        enable_adaptive_sampling: bool = True,
    ) -> None:
        self.config = config or PipelineConfig()
        self.demo = demo
        self.llm = LLMClient()
        self.store = DataStore()
        self.metrics = MetricsCollector()

        # 持久化路径
        self._metrics_path = settings.data_dir / "metrics.json"
        self._runs_path = settings.data_dir / "runs.jsonl"
        self._flywheel_path = settings.data_dir / "flywheel_state.json"
        settings.ensure_dirs()

        # 初始化各 Agent
        self.chaos_creator = ChaosCreator(
            llm=self.llm, model=settings.chaos_creator_model
        )
        self.moderator = Moderator(
            llm=self.llm, model=settings.moderator_model
        )
        self.judge = SupremeJudge(
            llm=self.llm, model=settings.judge_model
        )

        # Demo 模式：用预录制数据替换 Agent 调用
        if demo:
            self._setup_demo_agents()

        # 集成模块（可按需关闭，demo 模式下关闭 Constitutional 避免 LLM 调用）
        self._enable_constitutional = enable_constitutional and not demo
        self.constitutional = (
            ConstitutionalReviewer(llm=self.llm, model=settings.judge_model)
            if self._enable_constitutional
            else None
        )

        self._enable_flywheel = enable_flywheel
        self.flywheel = (
            FlyWheelOrchestrator(state_path=self._flywheel_path)
            if enable_flywheel
            else None
        )

        self._enable_adaptive = enable_adaptive_sampling
        self.sampler = AdaptiveSampler() if enable_adaptive_sampling else None

        self.quality_scorer = QualityScorer()

        # 跨批次累积（用于自适应采样和 IAA）
        self._all_cases: list[ChaosCase] = []

    async def run(
        self,
        policy: PolicyInput,
        num_samples: int | None = None,
    ) -> PipelineResult:
        """Execute the full multi-agent pipeline."""
        total = num_samples or self.config.num_samples
        batch_size = self.config.batch_size
        run = PipelineRun(
            total=total,
            status=PipelineStatus.RUNNING,
            started_at=datetime.now(tz=UTC),
        )

        # 加载 guidelines hash（用于 DataLineage）
        guidelines_hash = self._compute_guidelines_hash()

        logger.info(
            f"Starting pipeline run {run.run_id} — "
            f"{total} samples in batches of {batch_size}"
        )

        all_evaluations: list[JudgeEvaluation | None] = []
        all_dpo_pairs: list[DPO_Pair] = []
        all_responses: list[list[JudgeEvaluation | None]] = []
        batch_index = 0

        remaining = total
        while remaining > 0:
            current_batch = min(batch_size, remaining)

            try:
                # === 自适应采样：根据已有覆盖率调整分布 ===
                target_dist = None
                if self.sampler and self._all_cases:
                    coverage = self.sampler.analyze_coverage(self._all_cases)
                    stage = self.sampler.get_curriculum_stage(len(self._all_cases))
                    target_dist = self.sampler.suggest_distribution(
                        coverage, curriculum_stage=stage
                    )
                    logger.info(
                        f"  自适应采样: stage={stage}, "
                        f"coverage={coverage.coverage_score:.2f}, "
                        f"dist={target_dist}"
                    )

                # Stage 1: ChaosCreator 红队生成
                cases = await self.chaos_creator.run(
                    policy=policy,
                    batch_size=current_batch,
                    target_distribution=target_dist,
                )

                # Stage 2: Moderator 审核
                responses = await self.moderator.run(
                    cases=cases, policy=policy
                )

                # Stage 3: SupremeJudge 终审
                evaluations, dpo_pairs = await self.judge.run(
                    cases=cases, responses=responses, policy=policy
                )

                # Stage 4: Constitutional AI 自我修正（可选）
                if self.constitutional and evaluations:
                    evaluations = await self.constitutional.review_batch(
                        evaluations
                    )

                # 构建/重建 DPO 对（Constitutional 修正后或 demo 模式下 judge 返回空 pairs 时）
                if not dpo_pairs:
                    dpo_pairs = self.judge.build_dpo_pairs_multi_persona(
                        cases=cases,
                        judge_evals=evaluations,
                        persona_eval_sets=[responses],
                        policy=policy,
                    )

                # === 注入 DataLineage ===
                for pair in dpo_pairs:
                    pair.lineage = DataLineage(
                        source_policy_id=policy.policy_id,
                        chaos_model=settings.chaos_creator_model,
                        moderator_model=settings.moderator_model,
                        judge_model=settings.judge_model,
                        moderator_persona=self.moderator.persona,
                        guidelines_hash=guidelines_hash,
                        pipeline_run_id=run.run_id,
                        batch_index=batch_index,
                    )

                # === 质量评分 ===
                for pair in dpo_pairs:
                    report = self.quality_scorer.score(pair)
                    if pair.lineage is not None:
                        pair.lineage.quality_scores = report.to_dict()

                all_evaluations.extend(evaluations)
                all_dpo_pairs.extend(dpo_pairs)
                all_responses.append(responses)
                # 批次成功后才写入覆盖率统计，避免失败批次污染 adaptive sampler
                self._all_cases.extend(cases)

                # 累加进度
                run.completed += current_batch
                run.dpo_pairs_generated += len(dpo_pairs)
                run.progress_pct = run.completed / total * 100

                # 收集并持久化批次指标
                self.metrics.record_batch(
                    cases, responses, evaluations, dpo_pairs
                )
                self.metrics.save(self._metrics_path)

                logger.info(
                    f"  Batch {batch_index} done: {run.completed}/{total} cases, "
                    f"{run.dpo_pairs_generated} DPO pairs"
                )

            except (AgentError, LLMError) as e:
                run.failed += current_batch
                run.error = str(e)
                logger.error(f"  批次失败 ({type(e).__name__}): {e}")
            except Exception as e:
                run.failed += current_batch
                run.error = str(e)
                logger.error(f"  批次失败 (未知异常): {e}")
                raise PipelineError(
                    f"管道执行过程中发生未知错误: {e}"
                ) from e

            remaining -= current_batch
            batch_index += 1

        # === 计算 IAA 指标 ===
        iaa_metrics = None
        if all_responses and all_evaluations:
            # 合并所有批次的 responses 为单一列表
            flat_responses: list[JudgeEvaluation | None] = []
            for resp_batch in all_responses:
                flat_responses.extend(resp_batch)
            if len(flat_responses) == len(all_evaluations):
                iaa_metrics = compute_batch_iaa(
                    all_evaluations, [flat_responses]
                )
                logger.info(
                    f"  IAA: kappa={iaa_metrics['avg_cohens_kappa']:.3f}, "
                    f"alpha={iaa_metrics['krippendorffs_alpha']:.3f}"
                )

        # 保存结果
        output_path = self.store.save_dpo_pairs(all_dpo_pairs, run.run_id)

        # 完成管道运行
        if run.completed == 0 and run.failed > 0:
            run.status = PipelineStatus.FAILED
        else:
            run.status = PipelineStatus.COMPLETED
        run.completed_at = datetime.now(tz=UTC)

        self.store.save_run(run, self._runs_path)

        # === 飞轮记录 ===
        if self.flywheel and all_dpo_pairs:
            avg_gap = (
                sum(p.preference_gap for p in all_dpo_pairs)
                / len(all_dpo_pairs)
            )
            round_metrics = RoundMetrics(
                round_id=self.flywheel.state.current_round + 1,
                total_dpo_pairs=len(all_dpo_pairs),
                avg_preference_gap=avg_gap,
                interception_rate=self.metrics.interception_rate,
                avg_quality_score=self.metrics.avg_quality_score,
                cohens_kappa=(
                    iaa_metrics["avg_cohens_kappa"] if iaa_metrics else 0.0
                ),
                krippendorffs_alpha=(
                    iaa_metrics["krippendorffs_alpha"] if iaa_metrics else 0.0
                ),
                correction_rate=(
                    self.constitutional.stats.correction_rate
                    if self.constitutional
                    else 0.0
                ),
                moderator_model=settings.moderator_model,
                judge_model=settings.judge_model,
            )
            self.flywheel.record_round(round_metrics)

        result = PipelineResult(
            run_id=run.run_id,
            total_cases=run.completed,
            total_evaluations=sum(
                1 for e in all_evaluations if e is not None
            ),
            total_dpo_pairs=len(all_dpo_pairs),
            dpo_pairs=all_dpo_pairs,
            output_path=output_path,
            avg_quality_score=self.metrics.avg_quality_score,
            interception_rate=self.metrics.interception_rate,
            dimension_stats=self.metrics.dimension_stats,
        )

        logger.info(
            f"Pipeline {run.run_id} complete! "
            f"{len(all_dpo_pairs)} DPO pairs saved to {output_path}"
        )
        return result

    def _setup_demo_agents(self) -> None:
        """替换 Agent 调用为预录制数据（demo 模式）。"""
        from ecoalign_forge.demo.fixtures import (
            demo_chaos_run,
            demo_judge_run,
            demo_moderator_run,
        )

        self.chaos_creator.run = demo_chaos_run  # type: ignore[assignment]
        self.moderator.run = demo_moderator_run  # type: ignore[assignment]
        self.judge.run = demo_judge_run  # type: ignore[assignment]
        logger.info("DEMO MODE: using pre-recorded agent responses (no API key needed)")

    @staticmethod
    def _compute_guidelines_hash() -> str:
        """计算 guidelines.md 的哈希（用于 DataLineage）。"""
        try:
            from ecoalign_forge._guidelines import GUIDELINES_TEXT

            return DataLineage.hash_content(GUIDELINES_TEXT)
        except Exception:
            return "unknown"
