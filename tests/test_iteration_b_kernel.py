"""End-to-end contracts through real prompts, parsers, files and semantic gates."""

import json
from pathlib import Path

import pytest

from ecoalign_forge.demo.kernel_fixtures import fixture_candidate
from ecoalign_forge.engine.kernel import SynthesisKernel
from ecoalign_forge.policy.builtin import builtin_pack
from ecoalign_forge.policy.compiler import compile_policy
from ecoalign_forge.policy.models import PolicyPack
from ecoalign_forge.runtime.control import TransportError
from ecoalign_forge.runtime.journal import Journal
from ecoalign_forge.schemas.kernel import GenerationResult, RunConfig, SourceText, canonical
from tests.test_iteration_b_policy import pack_data


class RecordedTransport:
    def __init__(
        self, pack, *, text="Contact raven", reviewer=None, corrupt_stage=None, call_log=None
    ):
        self.compiled = compile_policy(pack)
        self.text = text
        self.reviewer = reviewer
        self.corrupt_stage = corrupt_stage
        self.calls = []
        self.call_log = call_log

    async def __call__(self, payload, aid, config):
        body = json.loads(payload["messages"][-1]["content"])
        data = body["input"]
        stage = payload["stage"]
        self.calls.append((stage, aid, body))
        if self.call_log:
            with Path(self.call_log).open("a") as f:
                f.write(aid + "\n")
                f.flush()
        if stage == self.corrupt_stage:
            raise TransportError("unknown")
        if stage == "generator":
            value = [
                dict(request_item_id=p["request_item_id"], content=self.text)
                for p in reversed(data["requests"])
            ]
        else:
            source = SourceText.model_validate(data["source"])
            ev = fixture_candidate(self.compiled, source, {"CONTACT"})
            if stage == "moderator":
                ev = ev.model_copy(update={"final_action": "allow"})
            if stage == "reviewer":
                value = (
                    self.reviewer(ev)
                    if self.reviewer
                    else dict(status="passed", reason="controlled fixture review", corrected=None)
                )
            else:
                value = ev.model_dump(mode="json")
        return GenerationResult(
            content=canonical(value), model=None, finish_reason="fixture", attempt_id=aid
        )


def kernel(tmp_path, transport=None, hook=None):
    return SynthesisKernel(
        data_dir=tmp_path / "data",
        datasets_dir=tmp_path / "datasets",
        transport=transport,
        hook=hook,
    )


@pytest.mark.asyncio
async def test_demo_real_readback_and_repeated_resume(tmp_path):
    k = kernel(tmp_path)
    result = await k.run(builtin_pack(), RunConfig())
    assert result["status"] == "completed"
    assert result["counts"]["completed"] == 5 and result["counts"]["dpo_pairs"] == 3
    assert result["counts"]["no_signal"] == 2
    assert result["review_stats"]["skipped"] == 5
    assert result["review_stats"]["consistency_rate"] is None
    path = Path(result["output_path"])
    before = path.read_bytes()
    pairs = [json.loads(line) for line in path.read_text().splitlines()]
    with_j = Journal(k.last_run_dir)
    for pair in pairs:
        gate = with_j.stage(pair["source_case_id"], "gate")
        assert json.loads(pair["chosen"]) == gate["final"]["evaluation"]
        assert all(
            r["returned_model"] is None
            for values in pair["lineage"]["request_responses"].values()
            for r in values
        )
    count = len(with_j.attempts())
    with_j.close()
    resumed = await k.resume(k.last_run_dir)
    assert resumed["counts"] == result["counts"] and path.read_bytes() == before
    with_j = Journal(k.last_run_dir)
    assert len(with_j.attempts()) == count
    with_j.close()


@pytest.mark.asyncio
async def test_custom_pack_same_content_different_decision_and_original_review(tmp_path):
    a = pack_data()
    b = pack_data()
    b["version"] = "opposite"
    b["decisions"][0]["action"] = "allow"
    results = []
    for i, data in enumerate([a, b]):
        p = PolicyPack.model_validate(data)
        transport = RecordedTransport(p)
        k = kernel(tmp_path / str(i), transport)
        r = await k.run(p, RunConfig(execution_mode="mock", num_samples=2))
        assert r["status"] == "completed"
        assert all(
            body["policy_hash"] == compile_policy(p).sha256 for _, _, body in transport.calls
        )
        review = next(body for stage, _, body in transport.calls if stage == "reviewer")
        assert review["input"]["source"]["content"] == "Contact raven"
        j = Journal(k.last_run_dir)
        results.append(j.stage(j.cases()[0]["id"], "gate")["final"]["evaluation"]["final_action"])
        j.close()
    assert results == ["review", "allow"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected_pairs,expected_failed",
    [("passed", 2, 0), ("corrected", 0, 0), ("abstain", 0, 2), ("failed", 0, 2)],
)
async def test_review_final_pair_and_failure_status(
    tmp_path, status, expected_pairs, expected_failed
):
    p = PolicyPack.model_validate(pack_data())

    def review(ev):
        if status == "corrected":
            # Valid structure but contradictory matrix: excluded, never paired.
            ev = ev.model_copy(update={"final_action": "allow"})
        return dict(
            status=status,
            reason="fixture",
            corrected=ev.model_dump(mode="json") if status == "corrected" else None,
        )

    k = kernel(tmp_path, RecordedTransport(p, reviewer=review))
    r = await k.run(p, RunConfig(execution_mode="mock", num_samples=2))
    assert r["counts"]["dpo_pairs"] == expected_pairs and r["counts"]["failed"] == expected_failed
    if status == "corrected":
        assert r["counts"]["excluded_cases"] == 2
    if status in {"failed", "abstain"}:
        assert r["review_stats"]["consistency_rate"] is None


@pytest.mark.asyncio
async def test_unknown_default_pause_then_explicit_skip(tmp_path):
    p = PolicyPack.model_validate(pack_data())
    transport = RecordedTransport(p, corrupt_stage="judge")
    k = kernel(tmp_path, transport)
    r = await k.run(p, RunConfig(execution_mode="mock", num_samples=1))
    assert r["status"] == "paused" and r["exit_code"] == 4 and r["counts"]["in_progress"] == 1
    count = len(transport.calls)
    repeated = await k.resume(k.last_run_dir)
    assert repeated["unknown_attempts"] == r["unknown_attempts"] and len(transport.calls) == count
    done = await k.resume(
        k.last_run_dir, unknown_decisions={aid: "skip" for aid in r["unknown_attempts"]}
    )
    assert done["status"] == "failed" and done["counts"]["failed"] == 1


@pytest.mark.asyncio
async def test_committed_stage_not_recalled_after_fatal(tmp_path):
    p = PolicyPack.model_validate(pack_data())
    transport = RecordedTransport(p)

    def hook(event, data):
        if event == "stage_committed" and data["stage"] == "moderator":
            raise RuntimeError("fault")

    k = kernel(tmp_path, transport, hook)
    first = await k.run(p, RunConfig(execution_mode="mock", num_samples=1))
    assert first["status"] == "failed"
    k.hook = None
    resumed = await k.resume(k.last_run_dir)
    assert resumed["status"] == "completed"
    assert [s for s, _, _ in transport.calls].count("moderator") == 1
    assert [s for s, _, _ in transport.calls].count("generator") == 1


@pytest.mark.asyncio
async def test_missing_id_never_enters_moderator(tmp_path):
    p = PolicyPack.model_validate(pack_data())
    calls = []

    async def bad(payload, aid, config):
        calls.append(payload["stage"])
        return GenerationResult(
            content='[{"content":"no id"}]', model=None, attempt_id=aid, finish_reason="fixture"
        )

    k = kernel(tmp_path, bad)
    r = await k.run(p, RunConfig(execution_mode="mock", num_samples=2, max_attempts=2))
    assert r["status"] == "failed" and r["counts"]["generated"] == 0
    assert calls == ["generator", "generator"]


@pytest.mark.asyncio
async def test_budget_pause_and_only_upward_revision(tmp_path):
    from decimal import Decimal

    data = pack_data()
    p = PolicyPack.model_validate(data)
    transport = RecordedTransport(p)
    defaults = RunConfig()
    cfg = RunConfig(
        execution_mode="live",
        num_samples=1,
        max_run_cost=".000001",
        tpm=1000000,
        prices={
            m.model: dict(input_per_million=1, output_per_million=2)
            for m in defaults.models.values()
        },
    )
    k = kernel(tmp_path, transport)
    paused = await k.run(p, cfg)
    assert paused["pause_reason"] == "budget_exhausted" and not transport.calls
    with pytest.raises(ValueError, match="increase"):
        await k.resume(k.last_run_dir, max_run_cost=Decimal(".0000001"))
    completed = await k.resume(k.last_run_dir, max_run_cost=Decimal("1"), extend_seconds=10)
    assert completed["status"] == "completed"
    assert Decimal(completed["budget"]["unresolved_reserved_usd"]) > 0  # missing usage is not free


@pytest.mark.asyncio
@pytest.mark.parametrize("language,text", [("zh", "联系鸦青 🐦"), ("ar", "تواصل مع رافن 🐦")])
async def test_multilingual_pipeline_unicode_labels(tmp_path, language, text):
    data = pack_data()
    data["language"] = language
    data["dimensions"][0].update(
        labels=["有联系", "无联系"],
        default="无联系",
        rows=[dict(label="有联系", when=dict(op="rule", ref="CONTACT"))],
    )
    data["decisions"][0]["when"]["value"] = "有联系"
    pack = PolicyPack.model_validate(data)
    k = kernel(tmp_path, RecordedTransport(pack, text=text))
    r = await k.run(pack, RunConfig(execution_mode="mock", num_samples=1))
    assert r["status"] == "completed" and r["avg_decision_severity"] is None
    pair = json.loads(Path(r["output_path"]).read_text().splitlines()[0])
    chosen = json.loads(pair["chosen"])
    assert chosen["evidence"][0]["quote"] == text and chosen["labels"]["contact"] == "有联系"
    messages = json.loads(
        (Path(r["output_path"]).parent / "trl_conversational.jsonl").read_text().splitlines()[0]
    )["prompt"]
    assert json.loads(messages[-1]["content"])["language"] == language


@pytest.mark.asyncio
async def test_model_cannot_skip_enabled_review(tmp_path):
    pack = PolicyPack.model_validate(pack_data())
    k = kernel(
        tmp_path,
        RecordedTransport(
            pack, reviewer=lambda _: dict(status="skipped", reason="bypass", corrected=None)
        ),
    )
    result = await k.run(pack, RunConfig(execution_mode="mock", num_samples=1))
    assert result["status"] == "failed" and result["counts"]["dpo_pairs"] == 0
