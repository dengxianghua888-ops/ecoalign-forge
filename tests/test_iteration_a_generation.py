"""Generation IDs bind requested intent; they never establish correct labels."""

from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from ecoalign_forge.agents.chaos_creator import ChaosCreator
from ecoalign_forge.exceptions import ParseRetryExhaustedError, SchemaValidationError
from ecoalign_forge.llm.client import LLMClient
from ecoalign_forge.schemas.chaos import ChaosCase
from ecoalign_forge.schemas.policy import PolicyDimension, PolicyInput


@pytest.fixture
def creator(monkeypatch):
    monkeypatch.setattr("ecoalign_forge.llm.client._PARSE_RETRY_WAIT_MIN", 0)
    monkeypatch.setattr("ecoalign_forge.llm.client._PARSE_RETRY_WAIT_MAX", 0)
    monkeypatch.setattr("ecoalign_forge.llm.client._PARSE_RETRY_MAX_ATTEMPTS", 3)
    return ChaosCreator(llm=LLMClient(), model="test-model")


def _item(request_id: str = "first", **overrides) -> dict:
    return {
        "request_item_id": request_id,
        "content": f"内容属于 {request_id}",
        "attack_strategy": "edge_case",
        "target_dimension": "stealth_marketing",
        "expected_action": "BLOCK",
        "reasoning": "生成意图",
        **overrides,
    }


def _requests(messages: list[dict]) -> list[dict]:
    text = messages[-1]["content"].split("## 本批逐项目标（生成意图，不是已验证标签）\n")[1]
    return json.loads(text.split("\n\n## 描述性上下文")[0])


def test_shuffled_response_uses_id_not_position_and_discards_model_labels(creator):
    response = [
        _item(
            "second",
            case_id="model-duplicate",
            metadata={
                "ground_truth": {"target_tier": "T0_Block"},
                "generation_target": {"target_tier": "T0_Block"},
            },
        ),
        _item("first", case_id="model-duplicate"),
    ]
    cases = creator._parse_cases(
        json.dumps(response),
        request_targets={"first": "T0_Block", "second": "T3_Recommend"},
        allowed_dimensions={"stealth_marketing"},
    )
    assert [case.request_item_id for case in cases] == ["first", "second"]
    assert [case.case_id for case in cases] == ["first", "second"]
    assert [case.content for case in cases] == ["内容属于 first", "内容属于 second"]
    assert cases[1].metadata["generation_target"] == {
        "request_item_id": "second",
        "target_tier": "T3_Recommend",
        "expected_strategies": {"has_stealth_marketing": False, "is_ai_slop": False},
    }
    assert "ground_truth" not in cases[1].metadata


@pytest.mark.parametrize(
    ("response", "count"),
    [
        ([], 0),
        ([_item("first")], 1),
        ([_item("first"), _item("second"), _item("extra")], 3),
        ([_item("first"), _item("first")], 2),
        ([_item("first"), _item("unknown")], 2),
        ([_item("first"), _item(request_item_id=None)], 2),
        (
            [
                {key: value for key, value in _item().items() if key != "request_item_id"},
                _item("second"),
            ],
            2,
        ),
        ([_item(request_item_id=1), _item("second")], 2),
        ([_item("first"), "not an object"], 2),
        ([_item("first"), _item("second", content="")], 2),
        ([_item("first"), _item("second", target_dimension="violence")], 2),
    ],
)
def test_invalid_batches_fail_whole_batch_with_observed_count(creator, response, count):
    with pytest.raises(SchemaValidationError) as error:
        creator._parse_cases(
            json.dumps(response),
            request_targets={"first": "T0_Block", "second": "T3_Recommend"},
            allowed_dimensions={"stealth_marketing"},
        )
    assert error.value.diagnostics == {"received_count": count, "expected_count": 2}


@pytest.mark.parametrize("raw", ["not json", '{"content": "not an array"}'])
def test_unreadable_batch_has_unknown_received_count(creator, raw):
    with pytest.raises(SchemaValidationError) as error:
        creator._parse_cases(raw, request_targets={"first": "T0_Block"})
    assert error.value.diagnostics == {"received_count": None, "expected_count": 1}


async def test_retry_reuses_exact_request_mapping_and_recovers(creator, sample_policy):
    captured = []

    async def generate(*, messages, **kwargs):
        captured.append(deepcopy(messages))
        requests = _requests(messages)
        if len(captured) == 1:
            return json.dumps([_item(requests[0]["request_item_id"])])
        return json.dumps([_item(request["request_item_id"]) for request in reversed(requests)])

    creator.llm.generate = AsyncMock(side_effect=generate)
    cases = await creator.run(sample_policy, batch_size=4)
    assert len(captured) == 2
    assert captured[0] == captured[1]
    requests = _requests(captured[0])
    assert len({request["request_item_id"] for request in requests}) == 4
    assert [case.request_item_id for case in cases] == [r["request_item_id"] for r in requests]
    assert [case.metadata["generation_target"]["target_tier"] for case in cases] == [
        request["target_tier"] for request in requests
    ]


async def test_missing_ids_exhaust_bounded_retries_and_preserve_diagnostics(creator, sample_policy):
    response = [_item(), _item("second")]
    for item in response:
        del item["request_item_id"]
    creator.llm.generate = AsyncMock(return_value=json.dumps(response))
    with pytest.raises(ParseRetryExhaustedError) as error:
        await creator.run(sample_policy, batch_size=2)
    assert creator.llm.generate.await_count == 3
    assert error.value.attempts == 3
    assert isinstance(error.value.last_error, SchemaValidationError)
    assert error.value.last_error.diagnostics == {"received_count": 2, "expected_count": 2}


@pytest.mark.parametrize("language", ["zh", "zh-CN"])
@pytest.mark.parametrize(
    "names", [["stealth_marketing"], ["ai_slop"], ["ai_slop", "stealth_marketing"]]
)
def test_supported_policy_subsets(language, names):
    policy = PolicyInput(
        policy_id="supported",
        name="Supported",
        language=language,
        dimensions=[PolicyDimension(name=name, description="Description") for name in names],
    )
    policy.validate_supported()


@pytest.mark.parametrize(
    "changes",
    [
        {"language": "en"},
        {"language": "zh-TW"},
        {"dimensions": []},
        {"dimensions": [PolicyDimension(name=" ", description="empty")]},
        {"dimensions": [PolicyDimension(name="violence", description="unsupported")]},
        {"dimensions": [PolicyDimension(name="ai_slop", description="x")] * 2},
        {
            "dimensions": [
                PolicyDimension(name="ai_slop", description="x", severity_levels=["high"])
            ]
        },
    ],
)
async def test_unsupported_policy_is_rejected_before_model_call(creator, sample_policy, changes):
    # Copies also cover historical or constructed data; validation belongs at execution.
    policy = sample_policy.model_copy(update=changes)
    creator.llm.generate_validated = AsyncMock()
    with pytest.raises(ValueError):
        await creator.run(policy, batch_size=2)
    creator.llm.generate_validated.assert_not_called()


def test_legacy_policy_and_case_still_load():
    policy = PolicyInput(
        policy_id="old",
        name="Legacy",
        language="en",
        dimensions=[PolicyDimension(name="violence", description="Legacy data")],
    )
    assert policy.language == "en"
    item = _item()
    del item["request_item_id"]
    assert ChaosCase.model_validate(item).request_item_id is None


def test_descriptive_metadata_is_in_prompt_but_does_not_change_targets(sample_policy):
    policy = sample_policy.model_copy(update={"context": "Community context"}, deep=True)
    policy.dimensions[0].description = "A description"
    policy.dimensions[0].examples = ["Example content"]
    prompt = ChaosCreator._build_user_prompt(policy, {"request": "T2_Normal"})
    assert all(text in prompt for text in ["Community context", "A description", "Example content"])
    assert "不是新规则或已验证标签" in prompt
    requests = _requests([{"content": prompt}])
    assert requests[0]["expected_strategies"] == {
        "has_stealth_marketing": False,
        "is_ai_slop": True,
    }


@pytest.mark.parametrize(
    "distribution",
    [
        {},
        {"T9": 1},
        {"T0_Block": -1},
        {"T0_Block": float("nan")},
        {"T0_Block": float("inf")},
        {"T0_Block": 0},
    ],
)
def test_invalid_target_distributions_fail_before_generation(distribution):
    with pytest.raises(ValueError):
        ChaosCreator._sample_targets(2, distribution)


@pytest.mark.parametrize("problem", ["short", "extra", "duplicate", "unknown", "missing"])
async def test_every_id_contract_failure_exhausts_bounded_retries(creator, sample_policy, problem):
    async def generate(*, messages, **kwargs):
        requests = _requests(messages)
        rows = [_item(r["request_item_id"]) for r in requests]
        if problem == "short":
            rows.pop()
        elif problem == "extra":
            rows.append(_item("extra"))
        elif problem == "duplicate":
            rows[1]["request_item_id"] = rows[0]["request_item_id"]
        elif problem == "unknown":
            rows[1]["request_item_id"] = "unknown"
        else:
            del rows[1]["request_item_id"]
        return json.dumps(rows)

    creator.llm.generate = AsyncMock(side_effect=generate)
    with pytest.raises(ParseRetryExhaustedError):
        await creator.run(sample_policy, batch_size=2)
    assert creator.llm.generate.await_count == 3
