"""DPO_Pair — the final Direct Preference Optimization training pair."""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, Field

from ecoalign_forge.schemas.lineage import DataLineage


class DPO_Pair(BaseModel):
    """A chosen/rejected preference pair for DPO training."""

    pair_id: str = Field(default_factory=lambda: str(uuid4()))
    prompt: str = Field(..., description="The moderation prompt (policy + content)")
    chosen: str = Field(..., description="The preferred (correct) response")
    rejected: str = Field(..., description="The dis-preferred (incorrect) response")
    chosen_score: float = Field(..., ge=0.0, le=1.0)
    rejected_score: float = Field(..., ge=0.0, le=1.0)
    preference_gap: float = Field(..., ge=0.0, le=1.0, description="chosen - rejected score gap")
    dimension: str = Field(..., description="Target policy dimension")
    difficulty: str = Field(..., description="Case difficulty level")
    source_case_id: str = Field(..., description="Trace back to original ChaosCase")

    # 数据血缘追踪（Phase 1.6）
    lineage: DataLineage | None = Field(
        default=None, description="数据血缘元数据，记录完整生产过程"
    )
