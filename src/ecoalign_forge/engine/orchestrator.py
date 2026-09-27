"""Pipeline scheduler: review final judgments before building preference pairs."""

from __future__ import annotations

import asyncio
import json
import logging
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime

from ecoalign_forge.agents.chaos_creator import ChaosCreator
from ecoalign_forge.agents.constitutional import ConstitutionalReviewer
from ecoalign_forge.agents.moderator import Moderator
from ecoalign_forge.agents.supreme_judge import SupremeJudge
from ecoalign_forge.config import settings
from ecoalign_forge.engine.adaptive_sampler import AdaptiveSampler
from ecoalign_forge.engine.flywheel import FlyWheelOrchestrator, RoundMetrics
from ecoalign_forge.exceptions import AgentError, LLMError, ParseRetryExhaustedError
from ecoalign_forge.llm.client import LLMClient
from ecoalign_forge.quality.scorer import QualityScorer
from ecoalign_forge.schemas.execution import ExecutionMode
from ecoalign_forge.schemas.lineage import DataLineage
from ecoalign_forge.schemas.pipeline import (
    PipelineConfig,
    PipelineResult,
    PipelineRun,
    PipelineStatus,
    RunCounts,
)
from ecoalign_forge.schemas.policy import PolicyInput
from ecoalign_forge.storage.agreement import compute_batch_iaa
from ecoalign_forge.storage.metrics import MetricsCollector
from ecoalign_forge.storage.store import DataStore

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    def __init__(
        self,
        config: PipelineConfig | None = None,
        *,
        demo: bool = False,
        execution_mode: ExecutionMode | str = ExecutionMode.LIVE,
        enable_constitutional: bool = True,
        enable_flywheel: bool = True,
        enable_adaptive_sampling: bool = True,
    ) -> None:
        self.config = config or PipelineConfig()
        mode = ExecutionMode(execution_mode)
        if demo and mode not in (ExecutionMode.LIVE, ExecutionMode.DEMO):
            raise ValueError("demo=True conflicts with execution_mode")
        self.execution_mode = ExecutionMode.DEMO if demo else mode
        if self.execution_mode == ExecutionMode.UNKNOWN:
            raise ValueError("unknown is reserved for historical records")
        self.demo = self.execution_mode == ExecutionMode.DEMO
        self.fixture_version = None
        self.llm = LLMClient(allow_network=self.execution_mode == ExecutionMode.LIVE)
        self.store = DataStore(settings.datasets_dir / self.execution_mode.value)
        self._data_dir = settings.data_dir / self.execution_mode.value
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._metrics_path = self._data_dir / "metrics.json"
        self._runs_path = self._data_dir / "runs.jsonl"
        self._flywheel_path = self._data_dir / "flywheel_state.json"
        self.metrics = MetricsCollector(execution_mode=self.execution_mode)
        self.chaos_creator = ChaosCreator(llm=self.llm, model=settings.chaos_creator_model)
        self.moderator = Moderator(llm=self.llm, model=settings.moderator_model)
        self.judge = SupremeJudge(llm=self.llm, model=settings.judge_model)
        if self.demo:
            self._setup_demo_agents()
        self._enable_constitutional = enable_constitutional and not self.demo
        self.constitutional = (
            ConstitutionalReviewer(llm=self.llm, model=settings.judge_model)
            if self._enable_constitutional
            else None
        )
        self.flywheel = (
            FlyWheelOrchestrator(state_path=self._flywheel_path, execution_mode=self.execution_mode)
            if enable_flywheel
            else None
        )
        self.sampler = AdaptiveSampler() if enable_adaptive_sampling else None
        self.quality_scorer = QualityScorer()
        self._all_cases = []

    async def run(self, policy: PolicyInput, num_samples: int | None = None) -> PipelineResult:
        total = self.config.num_samples if num_samples is None else num_samples
        if isinstance(total, bool) or not isinstance(total, int) or not 1 <= total <= 10000:
            raise ValueError("num_samples must be an integer between 1 and 10000")
        policy.validate_supported()
        self._all_cases = []
        self.metrics = MetricsCollector(execution_mode=self.execution_mode)
        if self.constitutional:
            self.constitutional.stats = type(self.constitutional.stats)()
        counts = RunCounts(requested=total, unattempted=total)
        run = PipelineRun(
            status=PipelineStatus.RUNNING,
            counts=counts,
            execution_mode=self.execution_mode,
            fixture_version=self.fixture_version,
            started_at=datetime.now(tz=UTC),
        )
        self.last_run = run
        self.metrics.run_id = run.run_id
        diagnostics = []
        all_evaluations, all_responses, all_pairs = [], [], []
        fatal = cancelled = False
        guidelines_hash = self._compute_guidelines_hash()
        batch_index = 0
        while counts.unattempted:
            size = min(self.config.batch_size, counts.unattempted)
            counts.unattempted -= size
            stage = "generation"
            try:
                target_dist = None
                if self.sampler and self._all_cases:
                    coverage = self.sampler.analyze_coverage(self._all_cases)
                    target_dist = self.sampler.suggest_distribution(
                        coverage,
                        curriculum_stage=self.sampler.get_curriculum_stage(len(self._all_cases)),
                    )
                cases = await self.chaos_creator.run(
                    policy=policy, batch_size=size, target_distribution=target_dist
                )
                if len(cases) != size:
                    raise AgentError(
                        "ChaosCreator", f"expected_count={size}, received_count={len(cases)}"
                    )
                counts.generated += len(cases)
                stage = "moderation"
                responses = await self.moderator.run(cases=cases, policy=policy)
                self._check_alignment(cases, responses, "Moderator")
                counts.moderated += sum(ev is not None for ev in responses)
                stage = "judgment"
                evaluations = await self.judge.evaluate(cases=cases)
                self._check_alignment(cases, evaluations, "Judge")
                counts.judged += sum(ev is not None for ev in evaluations)
                stage = "review"
                if self.constitutional:
                    reviews = await self.constitutional.review_batch_detailed(evaluations)
                    self._check_alignment(cases, reviews, "Reviewer")
                    final = [r.final_evaluation for r in reviews]
                    review_statuses = [r.status for r in reviews]
                    for case, review in zip(cases, reviews, strict=True):
                        diagnostics.append(
                            dict(
                                batch_index=batch_index,
                                case_id=case.case_id,
                                stage=stage,
                                **asdict(review),
                            )
                        )
                else:
                    final = list(evaluations)
                    review_statuses = ["skipped"] * len(cases)
                    diagnostics.extend(
                        dict(
                            batch_index=batch_index,
                            case_id=c.case_id,
                            stage=stage,
                            status="skipped",
                            reason="demo_fixture" if self.demo else "review_disabled",
                            original_evaluation=e,
                            final_evaluation=e,
                        )
                        for c, e in zip(cases, final, strict=True)
                    )
                # A case cannot complete if any necessary stage failed. Keep positions intact.
                accepted = [
                    ev if response is not None else None
                    for response, ev in zip(responses, final, strict=True)
                ]
                stage = "pairing"
                pairs = self.judge.build_dpo_pairs_multi_persona(
                    cases=cases, judge_evals=accepted, persona_eval_sets=[responses], policy=policy
                )
                review_by_case = dict(zip((c.case_id for c in cases), review_statuses, strict=True))
                live = self.execution_mode == ExecutionMode.LIVE
                for pair in pairs:
                    pair.lineage = DataLineage(
                        source_policy_id=policy.policy_id,
                        source_policy_version=policy.version,
                        execution_mode=self.execution_mode,
                        fixture_version=self.fixture_version,
                        review_status=review_by_case[pair.source_case_id],
                        chaos_model=self.chaos_creator.model if live else None,
                        moderator_model=self.moderator.model if live else None,
                        judge_model=self.judge.model if live else None,
                        moderator_persona=self.moderator.persona,
                        guidelines_hash=guidelines_hash,
                        pipeline_run_id=run.run_id,
                        batch_index=batch_index,
                    )
                    pair.lineage.quality_scores = self.quality_scorer.score(pair).to_dict()
                completed = sum(ev is not None for ev in accepted)
                paired_ids = {p.source_case_id for p in pairs}
                no_signal = sum(
                    ev is not None and c.case_id not in paired_ids
                    for c, ev in zip(cases, accepted, strict=True)
                )
                for c, response, ev in zip(cases, responses, accepted, strict=True):
                    if ev is None:
                        diagnostics.append(
                            dict(
                                batch_index=batch_index,
                                case_id=c.case_id,
                                stage="case",
                                status="failed",
                                reason="moderator_missing"
                                if response is None
                                else "final_evaluation_missing",
                            )
                        )
                batch_metrics = deepcopy(self.metrics)
                batch_metrics.record_batch(cases, responses, accepted, pairs)
                self.metrics = batch_metrics
                all_evaluations.extend(accepted)
                all_responses.extend(responses)
                all_pairs.extend(pairs)
                self._all_cases.extend(cases)
                counts.completed += completed
                counts.failed += size - completed
                counts.no_signal += no_signal
                counts.dpo_pairs += len(pairs)
            except (asyncio.CancelledError, KeyboardInterrupt) as exc:
                counts.failed += size
                cancelled = True
                run.error = f"{type(exc).__name__}: user interrupted during {stage}"
            except (AgentError, LLMError, ParseRetryExhaustedError) as exc:
                counts.failed += size
                run.error = f"{type(exc).__name__}: {exc}"
                last_error = getattr(exc, "last_error", exc)
                diagnostics.append(
                    dict(
                        batch_index=batch_index,
                        stage=stage,
                        status="failed",
                        reason=run.error,
                        **getattr(last_error, "diagnostics", {}),
                    )
                )
            except Exception as exc:
                counts.failed += size
                fatal = True
                run.error = f"{type(exc).__name__}: {exc}"
                diagnostics.append(
                    dict(
                        batch_index=batch_index,
                        stage=stage,
                        status="failed",
                        reason=run.error,
                        fatal=True,
                    )
                )
                logger.exception("Fatal pipeline error")
            counts.assert_conserved()
            logger.info(
                "Batch %s: completed=%s failed=%s unattempted=%s pairs=%s",
                batch_index,
                counts.completed,
                counts.failed,
                counts.unattempted,
                counts.dpo_pairs,
            )
            batch_index += 1
            if fatal or cancelled:
                if cancelled:
                    diagnostics.append(dict(stage=stage, status="cancelled", reason=run.error))
                break

        run.status = (
            PipelineStatus.CANCELLED
            if cancelled
            else PipelineStatus.FAILED
            if fatal or counts.completed == 0
            else PipelineStatus.PARTIAL_FAILED
            if counts.failed or counts.unattempted
            else PipelineStatus.COMPLETED
        )
        if counts.failed and not run.error:
            run.error = "One or more required case stages failed; see diagnostics"
        run.completed_at = datetime.now(tz=UTC)
        output_path = ""

        # Finalization is deliberately best-effort, not checkpoint/restart support.
        def failed_save(exc):
            nonlocal fatal
            fatal = True
            run.status = PipelineStatus.FAILED
            run.error = (
                run.error + "; " if run.error else ""
            ) + f"save: {type(exc).__name__}: {exc}"

        try:
            output_path = self.store.save_dpo_pairs(all_pairs, run.run_id)
        except Exception as exc:
            failed_save(exc)
        stats = (
            self.constitutional.stats.to_dict()
            if self.constitutional
            else {
                "consistency_rate": None,
                "correction_rate": None,
                "total_completed": 0,
                "total_failed": 0,
                "total_skipped": counts.judged,
            }
        )
        self.metrics.review_stats = stats
        try:
            self.metrics.save(self._metrics_path)
            if self.flywheel:
                iaa = compute_batch_iaa(all_evaluations, [all_responses]) if all_evaluations else {}
                self.flywheel.record_round(
                    RoundMetrics(
                        round_id=self.flywheel.state.current_round + 1,
                        execution_mode=self.execution_mode,
                        run_id=run.run_id,
                        total_dpo_pairs=len(all_pairs),
                        avg_preference_gap=sum(p.preference_gap for p in all_pairs) / len(all_pairs)
                        if all_pairs
                        else 0.0,
                        interception_rate=self.metrics.interception_rate,
                        avg_decision_severity=self.metrics.avg_decision_severity,
                        avg_pair_quality_heuristic=self.metrics.avg_pair_quality_heuristic,
                        cohens_kappa=iaa.get("avg_cohens_kappa", 0.0),
                        krippendorffs_alpha=iaa.get("krippendorffs_alpha", 0.0),
                        correction_rate=self.constitutional.stats.correction_rate
                        if self.constitutional
                        else None,
                        moderator_model=self.moderator.model
                        if self.execution_mode == ExecutionMode.LIVE
                        else None,
                        judge_model=self.judge.model
                        if self.execution_mode == ExecutionMode.LIVE
                        else None,
                    )
                )
        except Exception as exc:
            failed_save(exc)
        run.diagnostics_path = str(self._data_dir / f"diagnostics_{run.run_id}.json")
        try:
            self._write_diagnostics(run, diagnostics, stats)
        except Exception as exc:
            failed_save(exc)
        try:
            self.store.save_run(run, self._runs_path)
        except Exception as exc:
            failed_save(exc)
        if run.status == PipelineStatus.FAILED:
            # A late run-ledger failure must not leave diagnostics claiming success.
            try:
                self._write_diagnostics(run, diagnostics, stats)
            except Exception:
                logger.exception("Could not update failure diagnostics")
        counts.assert_conserved()
        return PipelineResult(
            run_id=run.run_id,
            status=run.status,
            execution_mode=self.execution_mode,
            fixture_version=self.fixture_version,
            counts=counts.model_copy(),
            error=run.error,
            diagnostics_path=run.diagnostics_path,
            total_cases=counts.completed,
            total_evaluations=counts.judged,
            total_dpo_pairs=len(all_pairs),
            dpo_pairs=all_pairs,
            output_path=output_path,
            avg_decision_severity=self.metrics.avg_decision_severity,
            avg_pair_quality_heuristic=self.metrics.avg_pair_quality_heuristic,
            interception_rate=self.metrics.interception_rate,
            dimension_stats=self.metrics.dimension_stats,
        )

    @staticmethod
    def _check_alignment(cases, values, name):
        if len(cases) != len(values):
            raise AgentError(name, f"position count mismatch: {len(values)} != {len(cases)}")

    def _write_diagnostics(self, run, entries, stats):
        from pathlib import Path

        def encode(value):
            if hasattr(value, "model_dump"):
                return value.model_dump(mode="json")
            raise TypeError(type(value).__name__)

        data = dict(run=run.model_dump(mode="json"), review_stats=stats, entries=entries)
        path = Path(run.diagnostics_path)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, default=encode, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(path)

    def _setup_demo_agents(self) -> None:
        from ecoalign_forge.demo.fixtures import (
            FIXTURE_VERSION,
            demo_chaos_run,
            demo_judge_evaluate,
            demo_moderator_run,
        )

        self.fixture_version = FIXTURE_VERSION
        self.chaos_creator.run = demo_chaos_run
        self.moderator.run = demo_moderator_run
        self.judge.evaluate = demo_judge_evaluate

    @staticmethod
    def _compute_guidelines_hash() -> str:
        from ecoalign_forge._guidelines import GUIDELINES_TEXT

        return DataLineage.hash_content(GUIDELINES_TEXT)
