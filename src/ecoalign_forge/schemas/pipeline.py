"""Pipeline configuration, terminal states and conserved case counts."""

from __future__ import annotations

import warnings
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, Field, computed_field, model_validator

from ecoalign_forge.schemas.dpo import DPO_Pair
from ecoalign_forge.schemas.execution import ExecutionMode


class PipelineStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def exit_code(self) -> int:
        return {self.COMPLETED: 0, self.PARTIAL_FAILED: 3, self.CANCELLED: 130}.get(self, 1)


class PipelineConfig(BaseModel):
    """Configuration for a single pipeline run."""

    num_samples: int = Field(default=10, ge=1, le=10000)
    batch_size: int = Field(default=10, ge=1, le=100)
    max_concurrent: int = Field(default=5, ge=1, le=50)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    min_preference_gap: float = Field(default=0.2, ge=0.0, le=1.0)


class RunCounts(BaseModel):
    requested: int = Field(default=0, ge=0)
    generated: int = Field(default=0, ge=0)
    moderated: int = Field(default=0, ge=0)
    judged: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    unattempted: int = Field(default=0, ge=0)
    no_signal: int = Field(default=0, ge=0)
    dpo_pairs: int = Field(default=0, ge=0)

    def assert_conserved(self) -> None:
        if self.completed + self.failed + self.unattempted != self.requested:
            raise ValueError("completed + failed + unattempted must equal requested")


class PipelineRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    status: PipelineStatus = PipelineStatus.PENDING
    execution_mode: ExecutionMode = ExecutionMode.UNKNOWN
    fixture_version: str | None = None
    counts: RunCounts = Field(default_factory=RunCounts)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    diagnostics_path: str = ""

    @model_validator(mode="before")
    @classmethod
    def read_legacy_counts(cls, data):
        if isinstance(data, dict) and "counts" not in data:
            data = dict(data)
            requested = data.get("total", 0)
            completed = data.get("completed", 0)
            failed = data.get("failed", 0)
            data["counts"] = dict(
                requested=requested,
                completed=completed,
                failed=failed,
                unattempted=max(0, requested - completed - failed),
                dpo_pairs=data.get("dpo_pairs_generated", 0),
            )
        return data

    @computed_field
    @property
    def total(self) -> int:
        return self.counts.requested

    @computed_field
    @property
    def completed(self) -> int:
        return self.counts.completed

    @computed_field
    @property
    def failed(self) -> int:
        return self.counts.failed

    @computed_field
    @property
    def dpo_pairs_generated(self) -> int:
        return self.counts.dpo_pairs

    @computed_field
    @property
    def progress_pct(self) -> float:
        return self.completed / self.total * 100 if self.total else 0.0


class PipelineResult(BaseModel):
    run_id: str
    status: PipelineStatus = PipelineStatus.COMPLETED
    execution_mode: ExecutionMode = ExecutionMode.UNKNOWN
    fixture_version: str | None = None
    counts: RunCounts = Field(default_factory=RunCounts)
    error: str | None = None
    diagnostics_path: str = ""
    total_cases: int
    total_evaluations: int
    total_dpo_pairs: int
    dpo_pairs: list[DPO_Pair] = Field(default_factory=list)
    output_path: str = ""
    avg_decision_severity: float = Field(
        default=0.0, validation_alias=AliasChoices("avg_decision_severity", "avg_quality_score")
    )
    avg_pair_quality_heuristic: float | None = None
    interception_rate: float = 0.0
    dimension_stats: dict[str, dict] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def warn_legacy_quality(cls, data):
        if isinstance(data, dict) and "avg_quality_score" in data:
            warnings.warn(
                "avg_quality_score input is deprecated; use avg_decision_severity",
                DeprecationWarning,
                stacklevel=2,
            )
        return data

    @property
    def avg_quality_score(self) -> float:
        warnings.warn(
            "avg_quality_score is deprecated; use avg_decision_severity",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.avg_decision_severity
