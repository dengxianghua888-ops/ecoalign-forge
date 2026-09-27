"""Policy/gate contracts: labels are extensible, evidence stays source-bound."""

import itertools

import pytest
from pydantic import ValidationError

from ecoalign_forge.policy.builtin import builtin_pack
from ecoalign_forge.policy.compiler import compile_policy, derive, validate_final
from ecoalign_forge.policy.models import PolicyPack
from ecoalign_forge.schemas.kernel import CandidateEvaluation, Evidence, RunConfig, SourceText


def pack_data():
    return dict(
        policy_id="community",
        version="2.7",
        name="Community",
        language="en",
        dimensions=[
            dict(
                id="contact",
                description="Contact",
                labels=["present", "absent"],
                default="absent",
                rows=[dict(label="present", when=dict(op="rule", ref="CONTACT"))],
            )
        ],
        actions=["allow", "review"],
        rules=[dict(id="CONTACT", dimension="contact", text="Contact ID present")],
        decisions=[
            dict(
                id="contact", action="review", when=dict(op="label", ref="contact", value="present")
            ),
            dict(id="default", action="allow"),
        ],
    )


def candidate(compiled, source, hits):
    states = {r.id: "hit" if r.id in hits else "miss" for r in compiled.pack.rules}
    labels, action, _, _ = derive(compiled, states)
    evidence = tuple(
        Evidence(
            rule_id=r.id,
            kind=r.evidence,
            source_id=source.source_id,
            source_hash=source.sha256,
            start=0,
            end=len(source.content),
            quote=source.content,
            reason="Recorded source assessment",
        )
        for r in compiled.pack.rules
        if r.id in hits and r.evidence != "external"
    )
    return CandidateEvaluation(
        labels=labels,
        rule_judgments=states,
        evidence=evidence,
        final_action=action,
        decision_reason="Recorded policy decision",
    )


@pytest.mark.parametrize(
    "language,text", [("zh", "联系微信：鸦青"), ("en", "Contact raven"), ("ar", "تواصل مع رافن 🐦")]
)
def test_unicode_exact_evidence(language, text):
    data = pack_data()
    data["language"] = language
    data["actions"] = ["允许", "复核"]
    data["decisions"][0]["action"] = "复核"
    data["decisions"][1]["action"] = "允许"
    c = compile_policy(PolicyPack.model_validate(data))
    s = SourceText(source_id="1", content=text)
    ev = candidate(c, s, {"CONTACT"})
    result = validate_final(c, s, ev, "passed")
    assert result.final.evaluation.final_action == "复核" and result.final.severity is None
    bad = ev.model_copy(
        update={"evidence": (ev.evidence[0].model_copy(update={"quote": "invented"}),)}
    )
    assert validate_final(c, s, bad, "passed").status == "excluded"


def test_same_content_opposite_packs():
    a = pack_data()
    b = pack_data()
    b["version"] = "3"
    b["decisions"][0]["action"] = "allow"
    source = SourceText(source_id="same", content="Contact raven")
    compiled = [compile_policy(PolicyPack.model_validate(x)) for x in [a, b]]
    finals = [
        validate_final(p, source, candidate(p, source, {"CONTACT"}), "passed").final
        for p in compiled
    ]
    assert [f.evaluation.final_action for f in finals] == ["review", "allow"]
    assert finals[0].policy_hash != finals[1].policy_hash


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (False, False, "T2_Normal"),
        (True, False, "T1_Shadowban"),
        (False, True, "T2_Normal"),
        (True, True, "T0_Block"),
    ],
)
def test_builtin_matrix_all_actions(a, b, expected):
    c = compile_policy(builtin_pack())
    source = SourceText(source_id="1", content="可检查的全文")
    ev = candidate(c, source, ({"A-001"} if a else set()) | ({"B-003"} if b else set()))
    assert ev.final_action == expected
    for action in c.pack.actions:
        outcome = validate_final(
            c, source, ev.model_copy(update={"final_action": action}), "passed"
        )
        assert (outcome.status == "accepted") == (action == expected)


def test_thresholds_exception_and_recommendation():
    c = compile_policy(builtin_pack())
    source = SourceText(source_id="1", content="我用 AI 整理昨日亲历的测量记录")
    for hits, action in [
        ({"B-001", "B-005"}, "T2_Normal"),
        ({"B-001", "B-005", "B-006"}, "T2_Normal"),
        ({"FIRSTHAND", "DENSE"}, "T3_Recommend"),
        ({"FIRSTHAND", "DENSE", "B-001"}, "T2_Normal"),
        ({"FIRSTHAND", "DENSE", "AI-ASSISTED", "B-003"}, "T3_Recommend"),
    ]:
        ev = candidate(c, source, hits)
        assert validate_final(c, source, ev, "passed").final.evaluation.final_action == action
    assert candidate(c, source, {"B-001", "B-005"}).labels["ai_slop"] == "clear"
    assert candidate(c, source, {"B-001", "B-005", "B-006"}).labels["ai_slop"] == "hit"


def test_unknown_is_not_miss_and_scope_requires_review():
    c = compile_policy(builtin_pack())
    source = SourceText(source_id="1", content="完整文章")
    ev = candidate(c, source, set())
    ev = ev.model_copy(update={"rule_judgments": dict(ev.rule_judgments, **{"A-001": "unknown"})})
    assert validate_final(c, source, ev, "passed").status == "abstain"
    assert (
        validate_final(c, source, candidate(c, source, {"B-003"}), "skipped").status == "excluded"
    )
    external = candidate(c, source, {"A-005"})
    assert validate_final(c, source, external, "passed").status == "abstain"


@pytest.mark.parametrize("mutation", ["duplicate", "reference", "label", "default", "code"])
def test_compile_rejects_before_execution(mutation):
    d = pack_data()
    if mutation == "duplicate":
        d["rules"] *= 2
    if mutation == "reference":
        d["decisions"][0]["when"] = dict(op="rule", ref="missing")
    if mutation == "label":
        d["dimensions"][0]["default"] = "other"
    if mutation == "default":
        d["decisions"].pop()
    if mutation == "code":
        d["decisions"][0]["when"] = dict(op="eval", value="danger")
    with pytest.raises((ValueError, ValidationError)):
        compile_policy(PolicyPack.model_validate(d))


def test_snapshot_is_immutable_and_candidate_can_be_wrong():
    c = compile_policy(PolicyPack.model_validate(pack_data()))
    first = c.sha256
    p = c.pack
    p.model_copy(update={"version": "new"})
    assert c.sha256 == first and c.pack.version == "2.7"
    source = SourceText(source_id="1", content="Contact raven")
    wrong = candidate(c, source, {"CONTACT"}).model_copy(update={"final_action": "allow"})
    assert CandidateEvaluation.model_validate_json(wrong.model_dump_json()) == wrong
    assert validate_final(c, source, wrong, "passed").status == "excluded"


def test_run_config_price_and_alias():
    with pytest.raises(ValidationError):
        RunConfig(execution_mode="live")
    with pytest.warns(DeprecationWarning):
        cfg = RunConfig(min_preference_gap=0.5)
    assert cfg.min_label_distance == 0.5
    for values in itertools.product(["hit", "miss", "unknown"], repeat=1):
        c = compile_policy(PolicyPack.model_validate(pack_data()))
        _, action, _, _ = derive(c, {"CONTACT": values[0]})
        assert action == {"hit": "review", "miss": "allow", "unknown": None}[values[0]]
