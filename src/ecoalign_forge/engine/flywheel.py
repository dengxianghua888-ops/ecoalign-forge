"""Synthesis round history; downstream quality has not been evaluated.

Severity and pair heuristics are descriptive signals. Neither is evidence of
model improvement or convergence, so those outcomes remain explicitly unknown.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import orjson

from ecoalign_forge.exceptions import EcoAlignError
from ecoalign_forge.schemas.execution import ExecutionMode

logger = logging.getLogger(__name__)


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


@dataclass(init=False)
class RoundMetrics:
    """Descriptive metrics for one synthesis run, not training evaluation."""

    round_id: int
    timestamp: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())
    execution_mode: ExecutionMode = ExecutionMode.UNKNOWN
    run_id: str | None = None
    total_dpo_pairs: int = 0
    avg_preference_gap: float = 0.0
    interception_rate: float = 0.0
    avg_decision_severity: float = 0.0
    avg_pair_quality_heuristic: float | None = None
    cohens_kappa: float = 0.0
    krippendorffs_alpha: float = 0.0
    correction_rate: float | None = None
    moderator_model: str | None = None
    judge_model: str | None = None

    def __init__(
        self,
        round_id: int,
        timestamp: str | None = None,
        total_dpo_pairs: int = 0,
        avg_preference_gap: float = 0.0,
        interception_rate: float = 0.0,
        avg_quality_score: float | None = None,
        cohens_kappa: float = 0.0,
        krippendorffs_alpha: float = 0.0,
        correction_rate: float | None = None,
        moderator_model: str | None = None,
        judge_model: str | None = None,
        *,
        execution_mode: ExecutionMode = ExecutionMode.UNKNOWN,
        run_id: str | None = None,
        avg_decision_severity: float | None = None,
        avg_pair_quality_heuristic: float | None = None,
    ) -> None:
        if avg_quality_score is not None:
            warnings.warn(
                "avg_quality_score is deprecated; use avg_decision_severity",
                DeprecationWarning,
                stacklevel=2,
            )
            if avg_decision_severity is None:
                avg_decision_severity = avg_quality_score
        self.round_id = round_id
        self.timestamp = timestamp if timestamp is not None else datetime.now(tz=UTC).isoformat()
        self.execution_mode = ExecutionMode(execution_mode)
        self.run_id = run_id
        self.total_dpo_pairs = total_dpo_pairs
        self.avg_preference_gap = avg_preference_gap
        self.interception_rate = interception_rate
        self.avg_decision_severity = 0.0 if avg_decision_severity is None else avg_decision_severity
        self.avg_pair_quality_heuristic = avg_pair_quality_heuristic
        self.cohens_kappa = cohens_kappa
        self.krippendorffs_alpha = krippendorffs_alpha
        self.correction_rate = correction_rate
        self.moderator_model = moderator_model
        self.judge_model = judge_model

    @property
    def avg_quality_score(self) -> float:
        """One-release compatibility alias for the historical severity field."""
        warnings.warn(
            "avg_quality_score is deprecated; use avg_decision_severity",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.avg_decision_severity

    def to_dict(self) -> dict:
        return {
            "round_id": self.round_id,
            "timestamp": self.timestamp,
            "execution_mode": self.execution_mode.value,
            "run_id": self.run_id,
            "total_dpo_pairs": self.total_dpo_pairs,
            "avg_preference_gap": _rounded(self.avg_preference_gap),
            "interception_rate": _rounded(self.interception_rate),
            "avg_decision_severity": _rounded(self.avg_decision_severity),
            "avg_pair_quality_heuristic": _rounded(self.avg_pair_quality_heuristic),
            "cohens_kappa": _rounded(self.cohens_kappa),
            "krippendorffs_alpha": _rounded(self.krippendorffs_alpha),
            "correction_rate": _rounded(self.correction_rate),
            "moderator_model": self.moderator_model,
            "judge_model": self.judge_model,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> RoundMetrics:
        data = dict(raw)
        if "avg_quality_score" in data:
            legacy = data.pop("avg_quality_score")
            if "avg_decision_severity" not in data:
                warnings.warn(
                    "Legacy avg_quality_score loaded as avg_decision_severity",
                    DeprecationWarning,
                    stacklevel=2,
                )
                data["avg_decision_severity"] = legacy
        data.setdefault("execution_mode", ExecutionMode.UNKNOWN)
        return cls(**data)


@dataclass
class FlyWheelState:
    """Mode-isolated round history with no inferred model-quality evidence."""

    execution_mode: ExecutionMode = ExecutionMode.UNKNOWN
    current_round: int = 0
    rounds: list[RoundMetrics] = field(default_factory=list)
    cumulative_dpo_pairs: int = 0

    def __post_init__(self) -> None:
        self.execution_mode = ExecutionMode(self.execution_mode)

    def add_round(self, metrics: RoundMetrics) -> None:
        if metrics.execution_mode != self.execution_mode:
            raise EcoAlignError("Cannot combine flywheel rounds with different execution modes")
        self.rounds.append(metrics)
        self.cumulative_dpo_pairs += metrics.total_dpo_pairs
        self.current_round = metrics.round_id

    @property
    def quality_trend(self) -> list[float]:
        """No independent model evaluation exists in this Alpha."""
        return []

    @property
    def quality_improvement(self) -> None:
        return None

    @property
    def round_over_round_improvement(self) -> None:
        return None

    @property
    def severity_trend(self) -> list[float]:
        return [r.avg_decision_severity for r in self.rounds]

    @property
    def pair_quality_heuristic_trend(self) -> list[float | None]:
        return [r.avg_pair_quality_heuristic for r in self.rounds]

    def to_dict(self) -> dict:
        return {
            "execution_mode": self.execution_mode.value,
            "current_round": self.current_round,
            "rounds": [r.to_dict() for r in self.rounds],
            "severity_trend": [_rounded(q) for q in self.severity_trend],
            "pair_quality_heuristic_trend": [
                _rounded(q) for q in self.pair_quality_heuristic_trend
            ],
            "quality_trend": [],
            "cumulative_dpo_pairs": self.cumulative_dpo_pairs,
            "quality_improvement": None,
            "evaluation_status": "not_evaluated",
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(orjson.dumps(self.to_dict(), option=orjson.OPT_INDENT_2))

    @classmethod
    def load(cls, path: Path) -> FlyWheelState:
        if not path.exists():
            return cls()
        raw = orjson.loads(path.read_bytes())
        if not isinstance(raw, dict):
            raise ValueError("Flywheel state must be a JSON object")
        state = cls(execution_mode=ExecutionMode(raw.get("execution_mode", "unknown")))
        state.current_round = raw.get("current_round", 0)
        state.cumulative_dpo_pairs = raw.get("cumulative_dpo_pairs", 0)
        for record in raw.get("rounds", []):
            metrics = RoundMetrics.from_dict(record)
            if metrics.execution_mode != state.execution_mode:
                raise EcoAlignError("Flywheel state and round execution modes do not match")
            state.rounds.append(metrics)
        # Legacy quality_trend/improvement described severity; never load them
        # as evidence of model quality or synthesize observations from them.
        return state


class FlyWheelOrchestrator:
    """Record synthesis rounds without claiming an unmeasured training loop."""

    def __init__(
        self,
        state_path: Path | None = None,
        convergence_threshold: float = 0.01,
        max_rounds: int = 10,
        *,
        execution_mode: ExecutionMode = ExecutionMode.UNKNOWN,
    ) -> None:
        self.execution_mode = ExecutionMode(execution_mode)
        self._state_path = state_path or (
            Path("./data") / self.execution_mode.value / "flywheel_state.json"
        )
        if self._state_path.exists():
            self.state = FlyWheelState.load(self._state_path)
            if self.state.execution_mode != self.execution_mode:
                raise EcoAlignError("Existing flywheel execution mode does not match the new run")
        else:
            self.state = FlyWheelState(execution_mode=self.execution_mode)
        # Retain the old argument for call compatibility; no heuristic threshold
        # is used to decide whether an unmeasured model has converged.
        self.convergence_threshold = convergence_threshold
        self.max_rounds = max_rounds

    def record_round(self, metrics: RoundMetrics) -> None:
        self.state.add_round(metrics)
        self.state.save(self._state_path)
        logger.info(
            "Recorded synthesis round %s (%s): %s DPO pairs; model quality not evaluated",
            metrics.round_id,
            metrics.execution_mode.value,
            metrics.total_dpo_pairs,
        )

    @property
    def has_converged(self) -> None:
        """Unknown until a separately defined independent evaluation is run."""
        return None

    @property
    def should_continue(self) -> bool:
        """Only the explicit round limit controls continuation in this Alpha."""
        return self.state.current_round < self.max_rounds

    def get_summary(self) -> dict:
        return {
            "execution_mode": self.execution_mode.value,
            "total_rounds": self.state.current_round,
            "cumulative_dpo_pairs": self.state.cumulative_dpo_pairs,
            "severity_trend": self.state.severity_trend,
            "pair_quality_heuristic_trend": self.state.pair_quality_heuristic_trend,
            "quality_trend": [],
            "total_improvement": None,
            "converged": None,
            "evaluation_status": "not_evaluated",
            "rounds_detail": [r.to_dict() for r in self.state.rounds],
        }
