"""Version 2 public contracts for portable, resumable synthesis."""

from __future__ import annotations

import hashlib
import json
import warnings
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ecoalign_forge.schemas.execution import ExecutionMode


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def canonical(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class SourceText(Contract):
    source_id: str = Field(min_length=1)
    content: str = Field(min_length=1)

    @property
    def sha256(self) -> str:
        return text_hash(self.content)


class Evidence(Contract):
    rule_id: str
    kind: Literal["text_span", "document_scope"]
    source_id: str
    source_hash: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str
    reason: str = Field(min_length=1)


class CandidateEvaluation(Contract):
    """Structure-only candidate. Never implies factual or semantic acceptance."""

    labels: dict[str, str]
    rule_judgments: dict[str, Literal["hit", "miss", "unknown"]]
    evidence: tuple[Evidence, ...] = ()
    final_action: str = Field(min_length=1)
    decision_reason: str = Field(min_length=1)


class FinalEvaluation(Contract):
    evaluation: CandidateEvaluation
    policy_hash: str
    source_hash: str
    gate_version: str = "semantic-gate-1"
    decision_row_id: str
    scores: dict[str, int]
    severity: float | None = None
    review_status: Literal["passed", "corrected", "skipped"]


class GateResult(Contract):
    status: Literal["accepted", "excluded", "abstain"]
    reasons: tuple[str, ...]
    final: FinalEvaluation | None = None


class ReviewOutcome(Contract):
    status: Literal["passed", "corrected", "failed", "abstain", "skipped"]
    reason: str
    corrected: CandidateEvaluation | None = None

    @model_validator(mode="after")
    def coherent(self):
        if (self.status == "corrected") != (self.corrected is not None):
            raise ValueError("Only corrected review supplies a corrected evaluation")
        return self


class GeneratedItem(Contract):
    request_item_id: str
    content: str = Field(min_length=1)


class ModelSettings(Contract):
    model: str = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=4096, ge=1)
    reasoning_effort: str | None = None


class Price(Contract):
    """Frozen USD prices per million tokens, never represented as actual billing."""

    input_per_million: Decimal = Field(ge=0)
    output_per_million: Decimal = Field(ge=0)
    # Explicit upper bound for a request's input. Reject larger prompts before dispatch.
    max_input_tokens: int = Field(default=32768, ge=1)


class FrozenDict(dict):
    """A JSON-serializable mapping whose contents cannot change after validation."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("RunConfig mappings are immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable

    def __deepcopy__(self, memo):
        return self


class RunConfig(Contract):
    schema_version: Literal[2] = 2
    execution_mode: ExecutionMode = ExecutionMode.DEMO
    num_samples: int = Field(default=5, ge=1, le=10000, strict=True)
    batch_size: int = Field(default=5, ge=1, le=100)
    max_concurrent: int = Field(default=5, ge=1, le=50)
    rpm: int = Field(default=60, ge=1)
    tpm: int = Field(default=100000, ge=1)
    quota_group: str = Field(default="default", min_length=1)
    max_attempts: int = Field(default=3, ge=1, le=20)
    request_timeout: float = Field(default=120, gt=0)
    stream_idle_timeout: float = Field(default=30, gt=0)
    run_timeout: float = Field(default=3600, gt=0)
    max_run_cost: Decimal | None = Field(default=None, gt=0)
    prices: dict[str, Price] = Field(default_factory=dict)
    models: dict[str, ModelSettings] = Field(
        default_factory=lambda: {
            "generator": ModelSettings(model="openai/gpt-5.4-mini", temperature=0.9),
            "moderator": ModelSettings(model="openai/gpt-5.4-mini", temperature=0.5),
            "judge": ModelSettings(model="openai/gpt-5.4", temperature=0.2),
            "reviewer": ModelSettings(model="openai/gpt-5.4", temperature=0.1),
        }
    )
    persona: Literal["naive", "strict_paranoid", "lax_overlooker", "keyword_matcher"] = "naive"
    moderator_full_rules: bool = False
    enable_review: bool = True
    seed: int = 0
    min_label_distance: float = Field(default=0, ge=0, le=1)
    adaptive_sampling: bool = True

    @model_validator(mode="before")
    @classmethod
    def old_gap(cls, value):
        if isinstance(value, dict) and "min_preference_gap" in value:
            value = dict(value)
            if "min_label_distance" in value:
                raise ValueError("Provide only min_label_distance")
            warnings.warn(
                "min_preference_gap now aliases label distance, not severity gap",
                DeprecationWarning,
                stacklevel=2,
            )
            value["min_label_distance"] = value.pop("min_preference_gap")
        return value

    @model_validator(mode="after")
    def executable(self):
        if self.execution_mode == ExecutionMode.UNKNOWN:
            raise ValueError("unknown mode is historical only")
        if set(self.models) != {"generator", "moderator", "judge", "reviewer"}:
            raise ValueError("models must define all four stages")
        if self.execution_mode == ExecutionMode.LIVE:
            if self.max_run_cost is None:
                raise ValueError("live execution requires explicit max_run_cost")
            if any(m.model not in self.prices for m in self.models.values()):
                raise ValueError("live execution requires a price snapshot for every model")
        object.__setattr__(self, "models", FrozenDict(self.models))
        object.__setattr__(self, "prices", FrozenDict(self.prices))
        return self


class GenerationResult(Contract):
    content: str
    model: str | None
    provider_request_id: str | None = None
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    latency_seconds: float = 0
    attempt_id: str


class PreferencePair(Contract):
    schema_version: Literal[2] = 2
    pair_id: str
    prompt: str
    chosen: str
    rejected: str
    source_case_id: str
    label_distance: float = Field(ge=0, le=1)
    lineage: dict


class KernelCounts(Contract):
    requested: int
    generated: int = 0
    moderated: int = 0
    judged: int = 0
    completed: int = 0
    failed: int = 0
    unattempted: int = 0
    in_progress: int = 0
    accepted_cases: int = 0
    excluded_cases: int = 0
    no_signal: int = 0
    dpo_pairs: int = 0

    @model_validator(mode="after")
    def conserved(self):
        if any(v < 0 for v in self.model_dump().values()):
            raise ValueError("Counts cannot be negative")
        if self.completed + self.failed + self.unattempted + self.in_progress != self.requested:
            raise ValueError("Run counts do not conserve requested cases")
        if self.accepted_cases + self.excluded_cases != self.completed:
            raise ValueError("completed must equal accepted + excluded")
        if self.no_signal > self.accepted_cases:
            raise ValueError("no_signal must be a subset of accepted cases")
        return self
