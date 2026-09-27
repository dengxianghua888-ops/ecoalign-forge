"""Adapter for the packaged A/B handbook; custom packs have no A/B assumptions."""

from __future__ import annotations

import re

from ecoalign_forge._guidelines import GUIDELINES_TEXT
from ecoalign_forge.policy.compiler import compile_policy
from ecoalign_forge.policy.models import PolicyPack
from ecoalign_forge.schemas.policy import PolicyInput


def builtin_pack(policy: PolicyInput | None = None) -> PolicyPack:
    if policy:
        policy.validate_supported()
    texts = dict(re.findall(r"\| \*\*([AB]-\d{3})\*\* \| (.*?) \|", GUIDELINES_TEXT))

    def rule(rid):
        return {"op": "rule", "ref": rid}

    def label(dim):
        return {"op": "label", "ref": dim, "value": "hit"}

    rules = [
        dict(
            id=rid,
            dimension="stealth_marketing" if rid.startswith("A") else "ai_slop",
            text=text,
            points=0 if rid.startswith("A") else (2 if rid in {"B-002", "B-003", "B-004"} else 1),
            evidence="external"
            if rid in {"A-005", "B-004"}
            else "document_scope"
            if rid in {"B-002", "B-003"}
            else "text_span",
        )
        for rid, text in sorted(texts.items())
    ]
    rules += [
        dict(
            id="FIRSTHAND",
            dimension="ai_slop",
            text="Explicit first-hand experience: time, location, people, verifiable detail or an independent observation.",
            evidence="text_span",
        ),
        dict(
            id="DENSE",
            dimension="ai_slop",
            text="High information density without padding, boilerplate openings or repetitive paragraphs.",
            evidence="text_span",
        ),
        dict(
            id="AI-ASSISTED",
            dimension="ai_slop",
            text="The supplied text explicitly describes AI assistance in organizing a first-hand account.",
            evidence="text_span",
        ),
    ]
    b_ids = [f"B-{n:03}" for n in range(1, 7)]
    pack = PolicyPack.model_validate(
        dict(
            policy_id=policy.policy_id if policy else "builtin-content-distribution",
            version=policy.version if policy else "1.0",
            name=policy.name if policy else "内置中文内容分发 A/B",
            language=policy.language if policy else "zh",
            context=GUIDELINES_TEXT,
            dimensions=[
                dict(
                    id="stealth_marketing",
                    description="Private contact diversion",
                    labels=["hit", "clear"],
                    default="clear",
                    rows=[
                        dict(
                            label="hit",
                            when={
                                "op": "any",
                                "children": [rule(f"A-{n:03}") for n in range(1, 7)],
                            },
                        )
                    ],
                ),
                dict(
                    id="ai_slop",
                    description="Low-information repetitive content, not authorship detection",
                    labels=["hit", "clear"],
                    default="clear",
                    rows=[
                        dict(
                            label="hit",
                            when={
                                "op": "any",
                                "children": [
                                    {"op": "score", "ref": "ai_slop", "compare": "ge", "value": 3},
                                    rule("B-002"),
                                    rule("B-003"),
                                    rule("B-004"),
                                ],
                            },
                        )
                    ],
                ),
            ],
            actions=["T0_Block", "T1_Shadowban", "T2_Normal", "T3_Recommend"],
            rules=rules,
            exceptions=[
                dict(
                    id="firsthand-ai-exception",
                    when={"op": "all", "children": [rule("FIRSTHAND"), rule("AI-ASSISTED")]},
                    suppress=b_ids,
                )
            ],
            decisions=[
                dict(
                    id="both",
                    action="T0_Block",
                    when={"op": "all", "children": [label("stealth_marketing"), label("ai_slop")]},
                ),
                dict(id="marketing", action="T1_Shadowban", when=label("stealth_marketing")),
                dict(id="slop", action="T2_Normal", when=label("ai_slop")),
                dict(
                    id="recommend",
                    action="T3_Recommend",
                    when={
                        "op": "all",
                        "children": [
                            rule("FIRSTHAND"),
                            rule("DENSE"),
                            {
                                "op": "not",
                                "children": [{"op": "any", "children": [rule(r) for r in b_ids]}],
                            },
                        ],
                    },
                ),
                dict(id="default", action="T2_Normal"),
            ],
            severity={"T0_Block": 1, "T1_Shadowban": 0.7, "T2_Normal": 0.3, "T3_Recommend": 0},
        )
    )
    compile_policy(pack)
    return pack
