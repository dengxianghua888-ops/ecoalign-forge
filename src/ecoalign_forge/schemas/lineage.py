"""DataLineage — 数据血缘追踪元数据。

记录每个 DPO_Pair 的完整生产过程：哪个策略版本、哪些模型、
什么 persona、guidelines 哈希等，支持数据版本溯源和回归分析。
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class DataLineage(BaseModel):
    """DPO 数据血缘追踪。"""

    # 策略溯源
    source_policy_id: str = Field(..., description="策略 ID")
    source_policy_version: str = Field(
        default="v1", description="策略版本号"
    )

    # 模型溯源
    chaos_model: str = Field(..., description="ChaosCreator 使用的 LLM 模型")
    moderator_model: str = Field(..., description="Moderator 使用的 LLM 模型")
    judge_model: str = Field(..., description="SupremeJudge 使用的 LLM 模型")

    # 审核配置溯源
    moderator_persona: str = Field(
        default="naive", description="Moderator 的 persona 类型"
    )
    guidelines_hash: str = Field(
        ..., description="guidelines.md 内容的 SHA-256 哈希（前 12 位）"
    )

    # 管道溯源
    pipeline_run_id: str = Field(..., description="管道运行 ID")
    batch_index: int = Field(default=0, description="批次序号")

    # 时间戳
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=UTC),
        description="数据生成时间 (UTC)",
    )

    # 质量指标（由下游评分模块填充）
    quality_scores: dict[str, float] = Field(
        default_factory=dict,
        description="各维度质量评分",
    )

    @staticmethod
    def hash_content(content: str) -> str:
        """计算内容的 SHA-256 哈希（取前 12 位）。"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
