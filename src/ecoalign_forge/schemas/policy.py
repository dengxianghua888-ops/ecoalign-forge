"""PolicyInput & PolicyDimension — content moderation policy schema."""

from __future__ import annotations

from pydantic import BaseModel, Field

SUPPORTED_DIMENSIONS = frozenset({"stealth_marketing", "ai_slop"})
DEFAULT_SEVERITY_LEVELS = ("safe", "mild", "moderate", "severe")


class PolicyDimension(BaseModel):
    """A single moderation dimension within a policy."""

    name: str = Field(..., description="Supported execution topic: stealth_marketing or ai_slop")
    description: str = Field(
        ..., description="Descriptive metadata; does not redefine the fixed A/B rules"
    )
    severity_levels: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SEVERITY_LEVELS),
        description="Legacy metadata; only the default levels are supported for execution",
    )
    examples: list[str] = Field(
        default_factory=list,
        description="Descriptive example metadata, not verified labels or rule overrides",
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
    context: str = Field(
        default="", description="Descriptive platform context; does not override guidelines.md"
    )

    def validate_supported(self) -> None:
        """Reject unsupported execution settings without blocking historical data loading.

        Selected dimensions are sampling topics. The fixed A/B decision matrix still
        applies to every case; description, context and examples do not define new rules.
        """
        if self.language not in {"zh", "zh-CN"}:
            raise ValueError("Only zh and zh-CN policies are supported for execution")
        names = [dimension.name for dimension in self.dimensions]
        if not names or any(not name.strip() for name in names):
            raise ValueError("Policy dimensions must be non-empty")
        if len(set(names)) != len(names):
            raise ValueError("Policy dimensions must be unique")
        unsupported = set(names) - SUPPORTED_DIMENSIONS
        if unsupported:
            raise ValueError(f"Unsupported policy dimensions: {sorted(unsupported)}")
        for dimension in self.dimensions:
            if tuple(dimension.severity_levels) != DEFAULT_SEVERITY_LEVELS:
                raise ValueError(
                    f"Custom severity_levels are not supported for {dimension.name}; "
                    f"expected {list(DEFAULT_SEVERITY_LEVELS)}"
                )
