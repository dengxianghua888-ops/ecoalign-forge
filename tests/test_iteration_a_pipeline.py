"""User-visible pipeline contracts, exercised offline with real artifact persistence."""

import asyncio
import json
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ecoalign_forge.agents.constitutional import ReviewResult
from ecoalign_forge.engine.orchestrator import AgentOrchestrator
from ecoalign_forge.exceptions import ParseRetryExhaustedError, SchemaValidationError
from ecoalign_forge.schemas.chaos import ChaosCase
from ecoalign_forge.schemas.execution import ExecutionMode
from ecoalign_forge.schemas.judge import JudgeEvaluation
from ecoalign_forge.schemas.pipeline import (
    PipelineConfig,
    PipelineStatus,
    RunCounts,
)
from ecoalign_forge.schemas.policy import PolicyDimension, PolicyInput


def make_case(identifier):
    return ChaosCase(
        case_id=f"case-{identifier}",
        content=f"离线验收案例 {identifier}",
        attack_strategy="edge_case",
        target_dimension="stealth_marketing",
        expected_action="BLOCK",
        reasoning="受控输入",
    )


def evaluate(tier):
    return JudgeEvaluation(
        has_stealth_marketing=tier in {"T0_Block", "T1_Shadowban"},
        is_ai_slop=tier in {"T0_Block", "T2_Normal"},
        reasoning_trace="第一步：检查内容。第二步：对照 A-001 与 B-003。第三步：按规则分级。",
        final_decision=tier,
    )


@pytest.fixture(autouse=True)
def never_call_models():
    """A fixture mistake must fail this test rather than contact a model provider."""
    with (
        patch("ecoalign_forge.llm.client.LLMClient.generate", new_callable=AsyncMock) as generate,
        patch(
            "ecoalign_forge.llm.client.LLMClient.generate_validated", new_callable=AsyncMock
        ) as validated,
        patch(
            "ecoalign_forge.llm.client.LLMClient.batch_generate_validated", new_callable=AsyncMock
        ) as batch,
    ):
        for method in (generate, validated, batch):
            method.side_effect = AssertionError("Unexpected model call in offline acceptance test")
        yield
        for method in (generate, validated, batch):
            method.assert_not_awaited()


@pytest.fixture
def policy():
    return PolicyInput(
        policy_id="acceptance-policy",
        name="离线验收平台",
        version="9.7",
        dimensions=[PolicyDimension(name="stealth_marketing", description="元数据")],
    )


@pytest.fixture
def build_orchestrator(tmp_path):
    configured = SimpleNamespace(
        data_dir=tmp_path / "data",
        datasets_dir=tmp_path / "datasets",
        chaos_creator_model="configured-chaos",
        moderator_model="configured-moderator",
        judge_model="configured-judge",
    )

    def build(*, samples=1, batch_size=1, review=False, demo=False):
        with patch("ecoalign_forge.engine.orchestrator.settings", configured):
            return AgentOrchestrator(
                config=PipelineConfig(num_samples=samples, batch_size=batch_size),
                execution_mode="demo" if demo else "mock",
                enable_constitutional=review,
                enable_flywheel=False,
                enable_adaptive_sampling=False,
            )

    return build


def wire_success(orch, *, moderator_tier="T2_Normal", judge_tier="T1_Shadowban"):
    identifiers = count()

    async def generate(**kwargs):
        return [make_case(next(identifiers)) for _ in range(kwargs["batch_size"])]

    async def moderate(cases, **kwargs):
        return [evaluate(moderator_tier) for _ in cases]

    async def judge(cases):
        return [evaluate(judge_tier) for _ in cases]

    orch.chaos_creator.run = AsyncMock(side_effect=generate)
    orch.moderator.run = AsyncMock(side_effect=moderate)
    orch.judge.evaluate = AsyncMock(side_effect=judge)


def read_artifacts(orch, result):
    records = [json.loads(line) for line in Path(result.output_path).read_text().splitlines()]
    # Verify the recipient-facing file as well as the public loader, not only returned objects.
    restored = orch.store.load_dpo_pairs(result.output_path)
    assert [p.model_dump(mode="json") for p in restored] == records
    assert records == [p.model_dump(mode="json") for p in result.dpo_pairs]
    runs = orch.store.list_runs(orch._runs_path)
    run = next(row for row in runs if row["run_id"] == result.run_id)
    assert run["status"] == result.status.value
    assert run["counts"] == result.counts.model_dump()
    assert (
        result.counts.completed + result.counts.failed + result.counts.unattempted
        == result.counts.requested
    )
    return records, json.loads(Path(result.diagnostics_path).read_text())


@pytest.mark.parametrize(
    "initial,moderator,final,expected_pair",
    [
        ("T2_Normal", "T2_Normal", "T1_Shadowban", True),  # New disagreement.
        ("T1_Shadowban", "T2_Normal", "T2_Normal", False),  # Disagreement removed.
        ("T1_Shadowban", "T2_Normal", "T3_Recommend", True),  # Direction reversed.
    ],
)
@pytest.mark.asyncio
async def test_only_reviewed_final_judgments_are_paired_and_written(
    build_orchestrator,
    policy,
    initial,
    moderator,
    final,
    expected_pair,
):
    orch = build_orchestrator(samples=2, batch_size=2, review=True)
    changed_case, stable_case = make_case("changed"), make_case("stable")
    old, corrected, stable = evaluate(initial), evaluate(final), evaluate("T1_Shadowban")
    orch.chaos_creator.run = AsyncMock(return_value=[changed_case, stable_case])
    orch.moderator.run = AsyncMock(return_value=[evaluate(moderator), evaluate("T3_Recommend")])
    orch.judge.evaluate = AsyncMock(return_value=[old, stable])
    orch.constitutional.review_batch_detailed = AsyncMock(
        return_value=[
            ReviewResult("corrected", corrected, old, "controlled_correction"),
            ReviewResult("passed", stable, stable, "consistent"),
        ]
    )

    result = await orch.run(policy)

    assert result.status == PipelineStatus.COMPLETED
    assert result.counts.completed == 2
    assert result.counts.dpo_pairs == 1 + expected_pair
    assert result.counts.no_signal == (0 if expected_pair else 1)
    records, diagnostics = read_artifacts(orch, result)
    by_case = {row["source_case_id"]: row for row in records}
    assert all(row["lineage"]["source_policy_version"] == "9.7" for row in records)
    assert all(row["lineage"]["execution_mode"] == "mock" for row in records)
    assert json.loads(by_case[stable_case.case_id]["chosen"]) == stable.model_dump()
    assert by_case[stable_case.case_id]["lineage"]["review_status"] == "passed"
    if expected_pair:
        assert json.loads(by_case[changed_case.case_id]["chosen"]) == corrected.model_dump()
        assert (
            json.loads(by_case[changed_case.case_id]["rejected"])
            == evaluate(moderator).model_dump()
        )
        assert by_case[changed_case.case_id]["lineage"]["review_status"] == "corrected"
    else:
        assert changed_case.case_id not in by_case
    expected_counts = {tier: 0 for tier in orch.metrics.decision_counts}
    expected_counts[final] += 1
    expected_counts[stable.final_decision] += 1
    assert orch.metrics.decision_counts == expected_counts
    changed_review = next(
        row for row in diagnostics["entries"] if row.get("case_id") == changed_case.case_id
    )
    assert changed_review["final_evaluation"] == corrected.model_dump()


@pytest.mark.parametrize("missing", ["moderator", "judge", "review_failed", "review_abstain"])
@pytest.mark.asyncio
async def test_missing_required_stage_fails_only_its_case(build_orchestrator, policy, missing):
    reviewing = missing.startswith("review")
    orch = build_orchestrator(samples=2, batch_size=2, review=reviewing)
    bad, good = make_case("missing"), make_case("good")
    mod, judgment = evaluate("T2_Normal"), evaluate("T1_Shadowban")
    orch.chaos_creator.run = AsyncMock(return_value=[bad, good])
    orch.moderator.run = AsyncMock(return_value=[None if missing == "moderator" else mod, mod])
    orch.judge.evaluate = AsyncMock(
        return_value=[None if missing == "judge" else judgment, judgment]
    )
    if reviewing:
        orch.constitutional.review_batch_detailed = AsyncMock(
            return_value=[
                ReviewResult(
                    "failed" if missing == "review_failed" else "abstain", None, judgment, missing
                ),
                ReviewResult("passed", judgment, judgment, "consistent"),
            ]
        )

    result = await orch.run(policy)

    assert result.status == PipelineStatus.PARTIAL_FAILED
    assert result.status.exit_code == 3
    assert result.counts.completed == result.counts.failed == result.counts.dpo_pairs == 1
    assert result.counts.no_signal == result.counts.unattempted == 0
    assert result.counts.moderated == (1 if missing == "moderator" else 2)
    assert result.counts.judged == (1 if missing == "judge" else 2)
    records, diagnostics = read_artifacts(orch, result)
    assert [row["source_case_id"] for row in records] == [good.case_id]
    assert any(
        row.get("case_id") == bad.case_id and row["status"] in {"failed", "abstain"}
        for row in diagnostics["entries"]
    )


@pytest.mark.parametrize("with_pair", [False, True])
@pytest.mark.asyncio
async def test_success_including_zero_preference_signal(build_orchestrator, policy, with_pair):
    orch = build_orchestrator(samples=3, batch_size=2)
    wire_success(orch, judge_tier="T1_Shadowban" if with_pair else "T2_Normal")
    result = await orch.run(policy)
    assert result.status == PipelineStatus.COMPLETED
    assert result.status.exit_code == 0
    assert (
        result.counts.completed
        == result.counts.generated
        == result.counts.moderated
        == result.counts.judged
        == 3
    )
    assert result.counts.failed == result.counts.unattempted == 0
    assert result.counts.dpo_pairs == (3 if with_pair else 0)
    assert result.counts.no_signal == (0 if with_pair else 3)
    read_artifacts(orch, result)


@pytest.mark.asyncio
async def test_all_review_failures_are_failed_and_rates_are_unavailable(build_orchestrator, policy):
    orch = build_orchestrator(samples=2, batch_size=2, review=True)
    wire_success(orch)
    orch.constitutional.llm = SimpleNamespace(
        generate=AsyncMock(side_effect=RuntimeError("offline failure"))
    )

    result = await orch.run(policy)

    assert result.status == PipelineStatus.FAILED
    assert result.status.exit_code == 1
    assert result.counts.completed == result.counts.no_signal == result.counts.dpo_pairs == 0
    assert result.counts.failed == result.counts.judged == 2
    records, diagnostics = read_artifacts(orch, result)
    assert records == []
    assert diagnostics["review_stats"]["total_failed"] == 2
    assert diagnostics["review_stats"]["consistency_rate"] is None
    assert diagnostics["review_stats"]["correction_rate"] is None
    reviews = [row for row in diagnostics["entries"] if row["stage"] == "review"]
    assert all(
        row["original_evaluation"] is not None and row["final_evaluation"] is None
        for row in reviews
    )


@pytest.mark.asyncio
async def test_missing_judge_remains_aligned_through_real_review_batch(build_orchestrator, policy):
    orch = build_orchestrator(samples=2, batch_size=2, review=True)
    wire_success(orch)
    orch.judge.evaluate = AsyncMock(return_value=[None, evaluate("T1_Shadowban")])
    review_model = AsyncMock(
        return_value=json.dumps(
            {
                "is_consistent": True,
                "issues_found": [],
                "corrected_judgment": None,
            }
        )
    )
    orch.constitutional.llm = SimpleNamespace(generate=review_model)

    result = await orch.run(policy)

    assert result.status == PipelineStatus.PARTIAL_FAILED
    assert result.counts.completed == result.counts.failed == result.counts.judged == 1
    review_model.assert_awaited_once()
    records, diagnostics = read_artifacts(orch, result)
    assert records[0]["source_case_id"] == "case-1"
    review_entries = [row for row in diagnostics["entries"] if row["stage"] == "review"]
    assert [row["status"] for row in review_entries] == ["skipped", "passed"]
    assert review_entries[0]["original_evaluation"] is review_entries[0]["final_evaluation"] is None


@pytest.mark.asyncio
async def test_legacy_judge_run_preserves_its_tuple_api(build_orchestrator, policy):
    orch = build_orchestrator()
    judgment = evaluate("T1_Shadowban")
    orch.judge.evaluate = AsyncMock(return_value=[judgment])
    original_case = make_case("legacy-api")

    evaluations, pairs = await orch.judge.run([original_case], [evaluate("T2_Normal")], policy)

    assert evaluations == [judgment]
    assert len(pairs) == 1
    assert pairs[0].source_case_id == original_case.case_id
    assert json.loads(pairs[0].chosen) == judgment.model_dump()


@pytest.mark.asyncio
async def test_exhausted_parse_batch_is_recorded_and_next_batch_continues(
    build_orchestrator, policy
):
    orch = build_orchestrator(samples=2)
    wire_success(orch)
    orch.chaos_creator.run.side_effect = [
        ParseRetryExhaustedError(3, SchemaValidationError("missing request item")),
        [make_case("recovered")],
    ]

    result = await orch.run(policy)

    assert result.status == PipelineStatus.PARTIAL_FAILED
    assert result.counts.completed == result.counts.failed == result.counts.generated == 1
    assert result.counts.unattempted == 0
    assert orch.chaos_creator.run.await_count == 2
    records, diagnostics = read_artifacts(orch, result)
    assert [row["source_case_id"] for row in records] == ["case-recovered"]
    assert any(
        "ParseRetryExhaustedError" in row.get("reason", "") for row in diagnostics["entries"]
    )


@pytest.mark.parametrize("returned_count", [0, 1, 3])
@pytest.mark.asyncio
async def test_wrong_generator_batch_size_is_never_silently_admitted(
    build_orchestrator, policy, returned_count
):
    orch = build_orchestrator(samples=2, batch_size=2)
    wire_success(orch)
    orch.chaos_creator.run = AsyncMock(return_value=[make_case(i) for i in range(returned_count)])

    result = await orch.run(policy)

    assert result.status == PipelineStatus.FAILED
    assert result.counts.generated == result.counts.completed == 0
    assert result.counts.failed == 2
    orch.moderator.run.assert_not_awaited()
    orch.judge.evaluate.assert_not_awaited()
    read_artifacts(orch, result)


@pytest.mark.parametrize(
    "exception,status,exit_code",
    [
        (asyncio.CancelledError(), PipelineStatus.CANCELLED, 130),
        (RuntimeError("unexpected batch crash"), PipelineStatus.FAILED, 1),
    ],
)
@pytest.mark.asyncio
async def test_interruption_preserves_previous_batch_and_unattempted_work(
    build_orchestrator,
    policy,
    exception,
    status,
    exit_code,
):
    orch = build_orchestrator(samples=4)
    wire_success(orch)
    orch.chaos_creator.run.side_effect = [[make_case("before-interruption")], exception]

    result = await orch.run(policy)

    assert result.status == status
    assert result.status.exit_code == exit_code
    assert result.counts.completed == result.counts.failed == result.counts.generated == 1
    assert result.counts.unattempted == 2
    assert orch.chaos_creator.run.await_count == 2
    records, diagnostics = read_artifacts(orch, result)
    assert [row["source_case_id"] for row in records] == ["case-before-interruption"]
    assert diagnostics["run"]["status"] == status.value
    assert result.error


@pytest.mark.asyncio
async def test_failed_batch_cannot_leave_partially_committed_metrics(build_orchestrator, policy):
    orch = build_orchestrator(samples=3)
    wire_success(orch)
    record_batch = type(orch.metrics).record_batch
    calls = 0

    def record_then_fail(collector, *args, **kwargs):
        nonlocal calls
        calls += 1
        record_batch(collector, *args, **kwargs)
        if calls == 2:
            raise RuntimeError("controlled failure after metric mutation")

    with patch.object(type(orch.metrics), "record_batch", record_then_fail):
        result = await orch.run(policy)

    assert result.status == PipelineStatus.FAILED
    assert result.counts.completed == result.counts.failed == result.counts.unattempted == 1
    assert result.counts.dpo_pairs == 1
    assert "controlled failure after metric mutation" in result.error
    records, diagnostics = read_artifacts(orch, result)
    assert [row["source_case_id"] for row in records] == ["case-0"]
    assert len(orch._all_cases) == 1
    assert orch.metrics.total_pairs == 1
    assert sum(orch.metrics.decision_counts.values()) == 1
    saved_metrics = json.loads(orch._metrics_path.read_text())
    assert saved_metrics["total_pairs"] == 1
    assert sum(saved_metrics["decision_counts"].values()) == 1
    assert diagnostics["run"]["counts"] == result.counts.model_dump()


@pytest.mark.asyncio
async def test_run_record_save_failure_updates_persisted_diagnostics(build_orchestrator, policy):
    orch = build_orchestrator()
    wire_success(orch)

    with patch.object(
        orch.store, "save_run", side_effect=OSError("controlled final run record failure")
    ):
        result = await orch.run(policy)

    assert result.status == PipelineStatus.FAILED
    assert "controlled final run record failure" in result.error
    assert result.counts.completed == result.counts.dpo_pairs == 1
    restored = orch.store.load_dpo_pairs(result.output_path)
    assert [pair.model_dump(mode="json") for pair in restored] == [
        pair.model_dump(mode="json") for pair in result.dpo_pairs
    ]
    diagnostics = json.loads(Path(result.diagnostics_path).read_text())
    assert diagnostics["run"]["status"] == "failed"
    assert diagnostics["run"]["error"] == result.error
    assert diagnostics["run"]["counts"] == result.counts.model_dump()
    assert orch.store.list_runs(orch._runs_path) == []


@pytest.mark.parametrize("target", ["dataset", "metrics", "diagnostics", "run_record"])
@pytest.mark.asyncio
async def test_persistence_failure_cannot_be_reported_as_completed(
    build_orchestrator, policy, target
):
    orch = build_orchestrator()
    wire_success(orch)
    owner, attribute = {
        "dataset": (orch.store, "save_dpo_pairs"),
        "metrics": (orch.metrics, "save"),
        "diagnostics": (orch, "_write_diagnostics"),
        "run_record": (orch.store, "save_run"),
    }[target]
    # MetricsCollector is reset per run, so inject failure at the class boundary.
    if target == "metrics":
        owner = type(orch.metrics)
    with patch.object(owner, attribute, side_effect=OSError("controlled disk failure")):
        result = await orch.run(policy)

    assert result.status == PipelineStatus.FAILED
    assert result.status.exit_code == 1
    assert "controlled disk failure" in result.error
    assert result.counts.completed == 1
    if target == "dataset":
        assert result.output_path == ""
    else:
        assert Path(result.output_path).is_file()


@pytest.mark.parametrize("invalid", [0, 10001, -1, True, 1.5, "2"])
@pytest.mark.asyncio
async def test_invalid_sample_count_rejected_before_generation(build_orchestrator, policy, invalid):
    orch = build_orchestrator()
    wire_success(orch)
    with pytest.raises(ValueError, match="num_samples"):
        await orch.run(policy, num_samples=invalid)
    orch.chaos_creator.run.assert_not_awaited()
    assert orch.store.list_runs(orch._runs_path) == []


@pytest.mark.asyncio
async def test_none_uses_configured_count(build_orchestrator, policy):
    orch = build_orchestrator(samples=2, batch_size=2)
    wire_success(orch)
    result = await orch.run(policy, num_samples=None)
    assert result.counts.requested == result.counts.completed == 2
    assert result.status == PipelineStatus.COMPLETED


@pytest.mark.asyncio
async def test_second_run_resets_coverage_metrics_review_stats_and_counts(
    build_orchestrator, policy
):
    orch = build_orchestrator(review=True)
    wire_success(orch)
    orch.constitutional.llm = SimpleNamespace(
        generate=AsyncMock(
            return_value=json.dumps(
                {
                    "is_consistent": True,
                    "issues_found": [],
                    "corrected_judgment": None,
                }
            )
        )
    )
    first = await orch.run(policy)
    assert orch.constitutional.stats.total_reviewed == 1
    orch.judge.evaluate = AsyncMock(return_value=[evaluate("T3_Recommend")])

    second = await orch.run(policy)

    assert second.run_id != first.run_id
    assert second.counts.completed == second.counts.generated == second.total_dpo_pairs == 1
    assert len(orch._all_cases) == 1
    assert sum(orch.metrics.decision_counts.values()) == 1
    assert orch.metrics.decision_counts["T3_Recommend"] == 1
    assert orch.metrics.decision_counts["T1_Shadowban"] == 0
    assert orch.constitutional.stats.total_reviewed == orch.constitutional.stats.total_passed == 1
    assert second.avg_decision_severity == 0
    assert len(orch.store.list_runs(orch._runs_path)) == 2
    assert (
        json.loads(orch.store.load_dpo_pairs(first.output_path)[0].chosen)["final_decision"]
        == "T1_Shadowban"
    )
    records, _ = read_artifacts(orch, second)
    assert json.loads(records[0]["chosen"])["final_decision"] == "T3_Recommend"


@pytest.mark.asyncio
async def test_demo_preserves_fixture_identity_without_configured_model_provenance(
    build_orchestrator, policy
):
    orch = build_orchestrator(samples=5, batch_size=5, review=True, demo=True)

    result = await orch.run(policy)

    assert result.status == PipelineStatus.COMPLETED
    assert result.execution_mode == ExecutionMode.DEMO
    assert result.fixture_version
    assert result.total_dpo_pairs > 0
    assert orch.constitutional is None
    records, diagnostics = read_artifacts(orch, result)
    for row in records:
        lineage = row["lineage"]
        assert lineage["execution_mode"] == "demo"
        assert lineage["fixture_version"] == result.fixture_version
        assert lineage["source_policy_version"] == "9.7"
        assert (
            lineage["chaos_model"] is lineage["moderator_model"] is lineage["judge_model"] is None
        )
        assert lineage["review_status"] == "skipped"
    assert "demo" in Path(result.output_path).parts
    assert diagnostics["run"]["execution_mode"] == "demo"


@pytest.mark.parametrize(
    "status,exit_code",
    [
        (PipelineStatus.COMPLETED, 0),
        (PipelineStatus.PARTIAL_FAILED, 3),
        (PipelineStatus.FAILED, 1),
        (PipelineStatus.CANCELLED, 130),
    ],
)
def test_cli_returns_terminal_status_exit_code(monkeypatch, capsys, status, exit_code):
    from ecoalign_forge.__main__ import main

    counts = (
        RunCounts(requested=1, completed=1)
        if status == PipelineStatus.COMPLETED
        else RunCounts(requested=1, failed=1)
    )
    result = dict(
        status=status.value, execution_mode="mock", counts=counts.model_dump(), exit_code=exit_code
    )
    mock_orch = SimpleNamespace(run=AsyncMock(return_value=result))
    monkeypatch.setattr("sys.argv", ["ecoalign-forge", "--num-samples", "1"])
    with (
        patch("ecoalign_forge.engine.kernel.SynthesisKernel", return_value=mock_orch),
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == exit_code
    assert f"Pipeline {status.value}" in capsys.readouterr().out
    mock_orch.run.assert_awaited_once()


@pytest.mark.parametrize("invalid", ["0", "10001"])
def test_cli_rejects_out_of_range_count_before_constructing_pipeline(monkeypatch, invalid):
    from ecoalign_forge.__main__ import main

    monkeypatch.setattr("sys.argv", ["ecoalign-forge", "--num-samples", invalid])
    constructor = MagicMock()
    with (
        patch("ecoalign_forge.engine.kernel.SynthesisKernel", constructor),
        pytest.raises(SystemExit) as exc,
    ):
        main()
    assert exc.value.code == 2
    constructor.assert_not_called()
