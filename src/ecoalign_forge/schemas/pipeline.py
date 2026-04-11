"""Pipeline-level schemas: config, run state, result."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from ecoalign_forge.schemas.dpo import DPO_Pair


class PipelineStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineConfig(BaseModel):
    """Configuration for a single pipeline run."""

    num_samples: int = Field(default=10, ge=1, le=10000)
    batch_size: int = Field(default=10, ge=1, le=100)
    max_concurrent: int = Field(default=5, ge=1, le=50)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    min_preference_gap: float = Field(default=0.2, ge=0.0, le=1.0)


class PipelineRun(BaseModel):
    """State of a running pipeline."""

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    status: PipelineStatus = PipelineStatus.PENDING
    total: int = 0
    completed: int = 0
    failed: int = 0
    dpo_pairs_generated: int = 0
    progress_pct: float = 0.0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class PipelineResult(BaseModel):
    """Final result of a completed pipeline."""

    run_id: str
    total_cases: int
    total_evaluations: int
    total_dpo_pairs: int
    dpo_pairs: list[DPO_Pair] = Field(default_factory=list)
    output_path: str = ""
    avg_quality_score: float = 0.0
    interception_rate: float = 0.0  # FLAG + BLOCK / total
    dimension_stats: dict[str, dict] = Field(default_factory=dict)
