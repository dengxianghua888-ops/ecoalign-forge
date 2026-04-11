"""PolicyInput & PolicyDimension — content moderation policy schema."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PolicyDimension(BaseModel):
    """A single moderation dimension within a policy."""

    name: str = Field(..., description="Dimension identifier, e.g. 'violence', 'sexual'")
    description: str = Field(..., description="Human-readable description of this dimension")
    severity_levels: list[str] = Field(
        default=["safe", "mild", "moderate", "severe"],
        description="Ordered severity levels",
    )
    examples: list[str] = Field(
        default_factory=list,
        description="Example content for this dimension (positive / negative)",
    )


class PolicyInput(BaseModel):
    """Complete content moderation policy definition — the input to the pipeline."""

    policy_id: str = Field(..., description="Unique policy identifier")
    name: str = Field(..., description="Policy display name")
    version: str = "1.0"
    dimensions: list[PolicyDimension] = Field(
        ..., min_length=1, description="At least one moderation dimension required"
    )
    language: str = Field(default="zh", description="Target language (BCP-47)")
    context: str = Field(default="", description="Additional context for LLM agents")
