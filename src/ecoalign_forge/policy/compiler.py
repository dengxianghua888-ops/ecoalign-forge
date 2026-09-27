"""Compile one immutable snapshot and evaluate it with three-valued logic."""

from __future__ import annotations

from dataclasses import dataclass

from ecoalign_forge.policy.models import Condition, PolicyPack
from ecoalign_forge.schemas.kernel import (
    CandidateEvaluation,
    FinalEvaluation,
    GateResult,
    SourceText,
    canonical,
    text_hash,
)

Tri = bool | None


@dataclass(frozen=True)
class CompiledPolicy:
    snapshot: str
    sha256: str

    @property
    def pack(self) -> PolicyPack:
        # Fresh parse prevents mutation of nested dictionaries in a frozen Pydantic model.
        return PolicyPack.model_validate_json(self.snapshot)


def compile_policy(pack: PolicyPack) -> CompiledPolicy:
    def unique(values, name):
        if len(values) != len(set(values)) or any(not v.strip() for v in values):
            raise ValueError(f"{name} must be nonempty and unique")

    dims = {d.id: d for d in pack.dimensions}
    rules = {r.id: r for r in pack.rules}
    for values, name in [
        (list(dims), "dimensions"),
        ([d.id for d in pack.dimensions], "dimensions"),
        ([r.id for r in pack.rules], "rules"),
        (pack.actions, "actions"),
        ([r.id for r in pack.decisions], "decision rows"),
        ([r.id for r in pack.exceptions], "exceptions"),
    ]:
        unique(values, name)
    for rule in pack.rules:
        if rule.dimension not in dims:
            raise ValueError(f"Unknown dimension: {rule.dimension}")

    def check(c: Condition, allow_label: bool):
        if c.op == "rule" and c.ref not in rules:
            raise ValueError(f"Unknown rule: {c.ref}")
        if c.op == "score" and c.ref not in dims:
            raise ValueError(f"Unknown score dimension: {c.ref}")
        if c.op == "label" and (
            not allow_label or c.ref not in dims or c.value not in dims[c.ref].labels
        ):
            raise ValueError("Invalid/circular label reference")
        for child in c.children:
            check(child, allow_label)

    for d in pack.dimensions:
        unique(d.labels, "labels")
        if d.default not in d.labels or any(r.label not in d.labels for r in d.rows):
            raise ValueError("Unknown dimension label")
        for row in d.rows:
            check(row.when, False)
    for ex in pack.exceptions:
        check(ex.when, False)
        if not set(ex.suppress).issubset(rules):
            raise ValueError("Exception suppresses unknown rules")
    for i, row in enumerate(pack.decisions):
        if row.action not in pack.actions:
            raise ValueError("Unknown action")
        if row.when is None and i != len(pack.decisions) - 1:
            raise ValueError("Only the last decision row can be default")
        if row.when:
            check(row.when, True)
    if pack.decisions[-1].when is not None:
        raise ValueError("Decision table requires a default row")
    if pack.severity is not None and (
        set(pack.severity) != set(pack.actions)
        or any(not 0 <= v <= 1 for v in pack.severity.values())
    ):
        raise ValueError("severity must map every action to [0,1]")
    snapshot = canonical(pack)
    return CompiledPolicy(snapshot, text_hash(snapshot))


def condition(
    c: Condition,
    hits: dict[str, Tri],
    scores: dict[str, tuple[int, int]],
    labels: dict[str, str | None],
) -> Tri:
    if c.op == "rule":
        return hits[c.ref]
    if c.op == "label":
        return None if labels[c.ref] is None else labels[c.ref] == c.value
    if c.op == "score":
        low, high = scores[c.ref]
        n = c.value
        if c.compare == "eq":
            return True if low == high == n else False if n < low or n > high else None
        if c.compare == "ge":
            return True if low >= n else False if high < n else None
        if c.compare == "gt":
            return True if low > n else False if high <= n else None
        if c.compare == "le":
            return True if high <= n else False if low > n else None
        return True if high < n else False if low >= n else None
    values = [condition(x, hits, scores, labels) for x in c.children]
    if c.op == "not":
        return None if values[0] is None else not values[0]
    if c.op == "all":
        return False if False in values else None if None in values else True
    return True if True in values else None if None in values else False


def derive(
    compiled: CompiledPolicy, judgments: dict[str, str]
) -> tuple[dict, str | None, str | None, dict]:
    pack = compiled.pack
    hits = {
        r.id: {"hit": True, "miss": False, "unknown": None}[judgments[r.id]] for r in pack.rules
    }

    def score(values):
        return {
            d.id: (
                sum(r.points for r in pack.rules if r.dimension == d.id and values[r.id] is True),
                sum(
                    r.points
                    for r in pack.rules
                    if r.dimension == d.id and values[r.id] is not False
                ),
            )
            for d in pack.dimensions
        }

    original_scores = score(hits)
    effective = dict(hits)
    for ex in pack.exceptions:
        applies = condition(ex.when, hits, original_scores, {})
        for rid in ex.suppress:
            if applies is True:
                effective[rid] = False
            elif applies is None and effective[rid] is not False:
                effective[rid] = None
    scores = score(effective)
    labels = {}
    for d in pack.dimensions:
        labels[d.id] = d.default
        for row in d.rows:
            result = condition(row.when, effective, scores, {})
            if result is None:
                labels[d.id] = None
                break
            if result:
                labels[d.id] = row.label
                break
    for row in pack.decisions:
        result = True if row.when is None else condition(row.when, effective, scores, labels)
        if result is None:
            return labels, None, None, scores
        if result:
            return labels, row.action, row.id, scores
    raise AssertionError("Compiled policy has no default")


def validate_final(
    compiled: CompiledPolicy, source: SourceText, candidate: CandidateEvaluation, review_status: str
) -> GateResult:
    pack = compiled.pack
    rules = {r.id: r for r in pack.rules}
    reasons = []
    if set(candidate.rule_judgments) != set(rules):
        return GateResult(status="excluded", reasons=("rule_set_mismatch",))
    if set(candidate.labels) != {d.id for d in pack.dimensions}:
        reasons.append("dimension_set_mismatch")
    for d in pack.dimensions:
        if candidate.labels.get(d.id) not in d.labels:
            reasons.append(f"invalid_label:{d.id}")
    if candidate.final_action not in pack.actions:
        reasons.append("invalid_action")
    evidence_by_rule = {}
    for ev in candidate.evidence:
        if ev.rule_id not in rules:
            reasons.append(f"unknown_evidence_rule:{ev.rule_id}")
            continue
        evidence_by_rule.setdefault(ev.rule_id, []).append(ev)
        if ev.source_id != source.source_id or ev.source_hash != source.sha256:
            reasons.append(f"evidence_source_mismatch:{ev.rule_id}")
        if (
            not 0 <= ev.start < ev.end <= len(source.content)
            or source.content[ev.start : ev.end] != ev.quote
        ):
            reasons.append(f"evidence_span_mismatch:{ev.rule_id}")
        if ev.kind != rules[ev.rule_id].evidence:
            reasons.append(f"evidence_kind_mismatch:{ev.rule_id}")
        if ev.kind == "document_scope":
            if (ev.start, ev.end) != (0, len(source.content)):
                reasons.append(f"document_scope_incomplete:{ev.rule_id}")
            if review_status not in {"passed", "corrected"}:
                reasons.append(f"document_scope_unreviewed:{ev.rule_id}")
    for rid, state in candidate.rule_judgments.items():
        if rules[rid].evidence == "external" and state == "hit":
            return GateResult(status="abstain", reasons=(f"external_material_unavailable:{rid}",))
        if state == "hit" and rid not in evidence_by_rule:
            reasons.append(f"missing_evidence:{rid}")
    labels, action, row, scores = derive(compiled, candidate.rule_judgments)
    if any(v is None for v in labels.values()) or action is None:
        return GateResult(status="abstain", reasons=("unknown_affects_decision",))
    if labels != candidate.labels:
        reasons.append("derived_labels_mismatch")
    if action != candidate.final_action:
        reasons.append("decision_matrix_mismatch")
    if review_status not in {"passed", "corrected", "skipped"}:
        reasons.append("review_not_accepted")
    if reasons:
        return GateResult(status="excluded", reasons=tuple(reasons))
    return GateResult(
        status="accepted",
        reasons=("policy_internal_consistency",),
        final=FinalEvaluation(
            evaluation=candidate,
            policy_hash=compiled.sha256,
            source_hash=source.sha256,
            decision_row_id=row,
            scores={k: lo for k, (lo, hi) in scores.items() if lo == hi},
            severity=pack.severity[action] if pack.severity else None,
            review_status=review_status,
        ),
    )
