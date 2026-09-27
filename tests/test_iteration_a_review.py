"""Deterministic review outcomes: failures cannot silently enter preference pairs."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from ecoalign_forge.agents.constitutional import ConstitutionalReviewer, ConstitutionalStats
from ecoalign_forge.schemas.judge import JudgeEvaluation


def evaluation(decision="T1_Shadowban"):
    return JudgeEvaluation(
        has_stealth_marketing=decision == "T1_Shadowban",
        is_ai_slop=False,
        reasoning_trace="第一步：检查内容。第二步：未命中。第三步：判定。",
        final_decision=decision,
    )


def payload(consistent=True, issues=None, corrected=None):
    return json.dumps(
        {
            "is_consistent": consistent,
            "issues_found": issues if issues is not None else [],
            "corrected_judgment": corrected,
        }
    )


@pytest.mark.asyncio
async def test_pass_and_correction_expose_only_the_accepted_final_evaluation():
    original, corrected = evaluation(), evaluation("T3_Recommend")
    llm = AsyncMock()
    llm.generate.side_effect = [payload(), payload(False, ["原判决需修正"], corrected.model_dump())]
    reviewer = ConstitutionalReviewer(llm)

    passed, changed = await reviewer.review_batch_detailed([original, original])

    assert passed.status == "passed"
    assert passed.final_evaluation is original
    assert changed.status == "corrected"
    assert changed.final_evaluation == corrected
    assert changed.original_evaluation is original
    assert changed.original is original
    assert changed.corrected == corrected
    assert changed.is_consistent is False
    assert reviewer.stats.total_completed == 2
    assert reviewer.stats.correction_rate == reviewer.stats.consistency_rate == 0.5


@pytest.mark.asyncio
async def test_llm_failure_has_no_final_and_no_estimated_success_rate():
    llm = AsyncMock()
    llm.generate.side_effect = RuntimeError("offline test failure")
    reviewer = ConstitutionalReviewer(llm)
    original = evaluation()

    result = await reviewer.review(original)

    assert result.status == "failed"
    assert result.reason == "llm_error"
    assert result.final_evaluation is None
    assert result.original_evaluation is original
    assert result.is_consistent is False
    assert result.llm_failed is True
    stats = reviewer.stats.to_dict()
    assert stats["total_reviewed"] == stats["total_failed"] == stats["total_llm_failures"] == 1
    assert stats["total_completed"] == 0
    assert stats["correction_rate"] is stats["consistency_rate"] is None
    assert '"consistency_rate": null' in json.dumps(stats)


@pytest.mark.parametrize(
    "raw,reason",
    [
        ("not json", "invalid_json"),
        ("[]", "invalid_response_shape"),
        ("[" + payload() + "]", "invalid_response_shape"),
        ("null", "invalid_response_shape"),
        ("{}", "missing_fields"),
        (json.dumps({"is_consistent": True, "issues_found": []}), "missing_fields"),
        (payload("true"), "invalid_is_consistent"),
        (payload(1), "invalid_is_consistent"),
        (payload(issues="fine"), "invalid_issues_found"),
        (payload(issues=[1]), "invalid_issues_found"),
        (payload(corrected=[]), "invalid_corrected_judgment"),
        (payload(issues=["存在问题"]), "contradictory_fields"),
        (payload(corrected=evaluation("T3_Recommend").model_dump()), "contradictory_fields"),
        (payload(False, ["需要修正"], {}), "invalid_correction"),
        (payload(False, ["需要修正"], {"final_decision": "T9"}), "invalid_correction"),
        (payload()[:-1] + ', "status": "failed"}', "unexpected_fields"),
        (payload()[:-1] + ', "is_consistent": false}', "invalid_json"),
    ],
)
@pytest.mark.asyncio
async def test_malformed_or_contradictory_review_never_passes(raw, reason):
    llm = AsyncMock()
    llm.generate.return_value = raw
    reviewer = ConstitutionalReviewer(llm)
    original = evaluation()

    result = await reviewer.review(original)

    assert result.status == "failed"
    assert result.reason == reason
    assert result.final_evaluation is None
    assert result.original_evaluation is original
    assert result.critique_raw == raw
    assert result.parse_failed is True
    assert reviewer.stats.total_failed == reviewer.stats.total_correction_parse_failures == 1
    assert reviewer.stats.consistency_rate is None


@pytest.mark.parametrize("same_correction", [False, True])
@pytest.mark.asyncio
async def test_unresolved_review_abstains_instead_of_falling_back(same_correction):
    original = evaluation()
    llm = AsyncMock()
    llm.generate.return_value = payload(
        False,
        ["证据不足"],
        original.model_dump() if same_correction else None,
    )
    reviewer = ConstitutionalReviewer(llm)

    result = await reviewer.review(original)

    assert result.status == "abstain"
    assert result.final_evaluation is None
    assert result.issues_found == ["证据不足"]
    assert reviewer.stats.total_abstained == 1
    assert reviewer.stats.total_completed == 0
    assert reviewer.stats.consistency_rate is None


@pytest.mark.asyncio
async def test_detailed_batch_preserves_positions_with_missing_and_mixed_outcomes():
    originals = [
        evaluation(tier) for tier in ("T0_Block", "T1_Shadowban", "T2_Normal", "T3_Recommend")
    ]
    responses = {
        "T0_Block": payload(),
        "T1_Shadowban": payload(False, ["调整档位"], originals[3].model_dump()),
        "T2_Normal": "invalid",
        "T3_Recommend": payload(False, ["无法确认"]),
    }

    async def generate(**kwargs):
        prompt = kwargs["messages"][1]["content"]
        tier = next(tier for tier in responses if f'"final_decision": "{tier}"' in prompt)
        # Interleave completion without adding time-based test flakiness.
        if tier == "T0_Block":
            await asyncio.sleep(0)
        return responses[tier]

    llm = AsyncMock()
    llm.generate.side_effect = generate
    reviewer = ConstitutionalReviewer(llm)

    results = await reviewer.review_batch_detailed([originals[0], None, *originals[1:]])

    assert [r.status for r in results] == ["passed", "skipped", "corrected", "failed", "abstain"]
    assert [r.final_evaluation for r in results] == [originals[0], None, originals[3], None, None]
    assert results[1].original_evaluation is None
    assert results[1].reason == "upstream_evaluation_missing"
    assert llm.generate.await_count == 4
    stats = reviewer.stats.to_dict()
    assert stats["total_reviewed"] == 4
    assert stats["total_completed"] == 2
    assert [
        stats[key]
        for key in (
            "total_passed",
            "total_corrected",
            "total_failed",
            "total_abstained",
            "total_skipped",
        )
    ] == [1, 1, 1, 1, 1]
    assert stats["consistency_rate"] == stats["correction_rate"] == 0.5


@pytest.mark.asyncio
async def test_legacy_batch_returns_none_for_failure_and_abstention():
    llm = AsyncMock()
    llm.generate.side_effect = [payload(), "bad JSON", payload(False, ["无法确认"])]
    reviewer = ConstitutionalReviewer(llm)
    original = evaluation()

    assert await reviewer.review_batch([original, None, original, original]) == [
        original,
        None,
        None,
        None,
    ]


@pytest.mark.asyncio
async def test_empty_and_all_missing_batches_make_no_model_requests():
    llm = AsyncMock()
    reviewer = ConstitutionalReviewer(llm)
    assert await reviewer.review_batch_detailed([]) == []
    results = await reviewer.review_batch_detailed([None, None])
    assert all(result.status == "skipped" for result in results)
    llm.generate.assert_not_awaited()
    assert reviewer.stats.total_reviewed == 0
    assert reviewer.stats.total_skipped == 2
    assert ConstitutionalStats().to_dict()["consistency_rate"] is None


@pytest.mark.asyncio
async def test_complete_json_fence_is_supported():
    llm = AsyncMock()
    llm.generate.return_value = f"```json\n{payload()}\n```"
    result = await ConstitutionalReviewer(llm).review(evaluation())
    assert result.status == "passed"
