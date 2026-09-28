"""Recorded B demo: five sources with unavailable external facts left unknown."""

from __future__ import annotations

import json

from ecoalign_forge.policy.compiler import derive
from ecoalign_forge.schemas.kernel import (
    CandidateEvaluation,
    Evidence,
    GenerationResult,
    SourceText,
    canonical,
)

FIXTURE_VERSION = "iteration-b-2"
TEXTS = [
    "需要资料请加微信 raven123。",
    "众所周知，学习非常重要。五个技巧：学习、努力、坚持、用心、进步。坚持学习，持续努力。",
    "昨天我在朝阳公园测量了步行路线：2.4 公里，用时 31 分钟，北门有两处台阶。",
    "众所周知，坚持努力就会成功。五个技巧：努力、坚持、学习、用心、成功。加微信 raven123 领资料。",
    "普通问候：大家好。",
]
HITS = [
    {"A-001"},
    {"B-001", "B-005", "B-006"},
    {"FIRSTHAND", "DENSE"},
    {"A-001", "B-001", "B-005", "B-006"},
    set(),
]


def fixture_candidate(compiled, source, hits):
    states = {
        r.id: "unknown" if r.evidence == "external" else "hit" if r.id in hits else "miss"
        for r in compiled.pack.rules
    }
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
            reason="Recorded fixture assessment, not an independent human label",
        )
        for r in compiled.pack.rules
        if r.id in hits and r.evidence != "external"
    )
    return CandidateEvaluation(
        # Candidates require strings; unresolved defaults are proposals, never final
        # decisions. The gate must abstain when these unknown facts affect the result.
        labels={
            d.id: labels[d.id] if labels[d.id] is not None else d.default
            for d in compiled.pack.dimensions
        },
        rule_judgments=states,
        evidence=evidence,
        final_action=action if action is not None else compiled.pack.decisions[-1].action,
        decision_reason="Recorded policy fixture",
    )


class DemoTransport:
    def __init__(self, compiled):
        self.compiled = compiled
        if not {"A-001", "B-001", "FIRSTHAND", "DENSE"}.issubset(
            {r.id for r in compiled.pack.rules}
        ):
            raise ValueError(
                "Built-in recorded demo supports the built-in policy only; supply mock fixtures for custom packs"
            )

    async def __call__(self, payload, attempt_id, config):
        if config.execution_mode.value != "demo":
            raise ValueError("Recorded demo transport requires demo mode")
        body = json.loads(payload["messages"][-1]["content"])
        data = body["input"]
        stage = payload["stage"]
        if stage == "generator":
            output = [
                dict(request_item_id=p["request_item_id"], content=TEXTS[p["ordinal"] % 5])
                for p in data["requests"]
            ]
        else:
            source = SourceText.model_validate(data["source"])
            index = TEXTS.index(source.content)
            ev = fixture_candidate(self.compiled, source, HITS[index])
            if stage == "moderator" and index in {0, 2, 3}:
                ev = ev.model_copy(update={"final_action": "T2_Normal"})
            output = ev.model_dump(mode="json")
        return GenerationResult(
            content=canonical(output), model=None, attempt_id=attempt_id, finish_reason="fixture"
        )
