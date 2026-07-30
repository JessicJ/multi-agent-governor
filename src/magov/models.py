"""Typed inputs and outputs for the governor.

All normalized signals use a 0..1 range.  Keeping these values explicit makes
the policy inspectable and lets callers derive them with rules, an LLM, or
historical telemetry without coupling the governor to any one agent framework.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from math import isfinite
from typing import Any


class Mode(str, Enum):
    SINGLE = "single"
    CENTRALIZED = "centralized"
    INDEPENDENT = "independent"


class StopReason(str, Enum):
    BASELINE_SUFFICIENT = "baseline_sufficient"
    NOT_PARALLELIZABLE = "not_parallelizable"
    COORDINATION_DOMINATES = "coordination_dominates"
    CORRELATED_ERRORS = "correlated_errors"
    TARGET_REACHED = "target_reached"
    MARGINAL_GAIN_TOO_LOW = "marginal_gain_too_low"
    OBSERVED_PLATEAU = "observed_plateau"
    COST_BUDGET_REACHED = "cost_budget_reached"
    TOKEN_BUDGET_REACHED = "token_budget_reached"
    TIME_BUDGET_REACHED = "time_budget_reached"
    TOOL_BUDGET_REACHED = "tool_budget_reached"
    AGENT_CAP_REACHED = "agent_cap_reached"
    CAP_REACHED_INCOMPLETE = "cap_reached_incomplete"
    PLANNED_CAP_REACHED = "planned_cap_reached"
    RUNTIME_FAILURE = "runtime_failure"


@dataclass(frozen=True)
class TaskSignals:
    """Structural evidence about a task, independent of any agent vendor."""

    parallelizable_units: int = 1
    parallel_fraction: float = 0.0
    decomposition_confidence: float = 0.5
    context_coupling: float = 0.5
    shared_context_ratio: float = 0.5
    uncertainty: float = 0.5
    verification_value: float = 0.5
    failure_correlation: float = 0.5
    aggregation_difficulty: float = 0.5
    error_impact: float = 0.5

    def __post_init__(self) -> None:
        if (
            type(self.parallelizable_units) is not int
            or self.parallelizable_units < 1
        ):
            raise ValueError("parallelizable_units must be a positive integer")
        for name, value in asdict(self).items():
            if name == "parallelizable_units":
                continue
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True)
class BaselineObservation:
    """What happened when one agent attempted the task first."""

    confidence: float
    verified: bool = False
    hard_failure: bool = False
    cost_units: float = 1.0
    latency_seconds: float = 0.0

    def __post_init__(self) -> None:
        if type(self.verified) is not bool or type(self.hard_failure) is not bool:
            raise ValueError("verified and hard_failure must be booleans")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not isfinite(self.cost_units) or self.cost_units <= 0:
            raise ValueError("cost_units must be positive")
        if not isfinite(self.latency_seconds) or self.latency_seconds < 0:
            raise ValueError("latency_seconds cannot be negative")
        if self.hard_failure and self.confidence != 0.0:
            raise ValueError("a hard failure must have zero confidence")
        if self.hard_failure and self.verified:
            raise ValueError("a hard failure cannot be verified as successful")


@dataclass(frozen=True)
class Budget:
    """Policy and resource limits.

    Cost is normalized to the measured single-agent baseline.  For example,
    max_cost_multiplier=3 allows the whole attempt to cost at most three
    baseline runs.
    """

    max_agents: int = 6
    max_cost_multiplier: float = 3.0
    target_confidence: float = 0.90
    min_expected_gain: float = 0.025
    min_observed_gain: float = 0.015
    plateau_rounds: int = 2
    cost_weight: float = 0.055
    latency_weight: float = 0.05
    max_total_tokens: int | None = None
    max_wall_time_seconds: float | None = None
    max_tool_calls: int | None = None

    def __post_init__(self) -> None:
        if type(self.max_agents) is not int or self.max_agents < 1:
            raise ValueError("max_agents must be a positive integer")
        if (
            not isfinite(self.max_cost_multiplier)
            or self.max_cost_multiplier < 1
        ):
            raise ValueError("max_cost_multiplier must be at least 1")
        if not 0.0 <= self.target_confidence <= 1.0:
            raise ValueError("target_confidence must be between 0 and 1")
        if (
            not isfinite(self.min_expected_gain)
            or not isfinite(self.min_observed_gain)
            or self.min_expected_gain < 0
            or self.min_observed_gain < 0
        ):
            raise ValueError("gain thresholds cannot be negative")
        if type(self.plateau_rounds) is not int or self.plateau_rounds < 1:
            raise ValueError("plateau_rounds must be a positive integer")
        if (
            not isfinite(self.cost_weight)
            or not isfinite(self.latency_weight)
            or self.cost_weight < 0
            or self.latency_weight < 0
        ):
            raise ValueError("utility weights cannot be negative")
        if (
            self.max_total_tokens is not None
            and (
                type(self.max_total_tokens) is not int
                or self.max_total_tokens < 1
            )
        ):
            raise ValueError("max_total_tokens must be a positive integer")
        if (
            self.max_wall_time_seconds is not None
            and (
                not isfinite(self.max_wall_time_seconds)
                or self.max_wall_time_seconds <= 0
            )
        ):
            raise ValueError("max_wall_time_seconds must be positive")
        if (
            self.max_tool_calls is not None
            and (
                type(self.max_tool_calls) is not int
                or self.max_tool_calls < 1
            )
        ):
            raise ValueError("max_tool_calls must be a positive integer")


@dataclass(frozen=True)
class Score:
    code: str
    value: float
    explanation: str


@dataclass(frozen=True)
class Candidate:
    total_agents: int
    expected_confidence: float
    expected_cost_multiplier: float
    marginal_quality_gain: float
    marginal_latency_gain: float
    marginal_coordination_penalty: float
    marginal_cost_penalty: float
    net_marginal_utility: float


@dataclass(frozen=True)
class Decision:
    mode: Mode
    total_agents: int
    expected_confidence: float
    expected_cost_multiplier: float
    stop_reason: StopReason
    summary: str
    scores: tuple[Score, ...] = ()
    candidates: tuple[Candidate, ...] = ()

    @property
    def additional_agents(self) -> int:
        return self.total_agents - 1

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["mode"] = self.mode.value
        result["stop_reason"] = self.stop_reason.value
        result["additional_agents"] = self.additional_agents
        return result


@dataclass(frozen=True)
class RoundObservation:
    """Measured result after admitting another agent."""

    total_agents: int
    confidence: float
    cost_multiplier: float
    marginal_quality_gain: float
    novel_finding_ratio: float = 1.0
    total_tokens: int = 0
    wall_time_seconds: float = 0.0
    tool_calls: int = 0
    coverage_complete: bool = False
    unresolved_conflicts: int = 0

    def __post_init__(self) -> None:
        if type(self.total_agents) is not int or self.total_agents < 1:
            raise ValueError("total_agents must be a positive integer")
        for name in ("confidence", "novel_finding_ratio"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if not isfinite(self.cost_multiplier) or self.cost_multiplier <= 0:
            raise ValueError("cost_multiplier must be positive")
        if not isfinite(self.marginal_quality_gain):
            raise ValueError("marginal_quality_gain must be finite")
        for name in ("total_tokens", "tool_calls", "unresolved_conflicts"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if (
            not isfinite(self.wall_time_seconds)
            or self.wall_time_seconds < 0
        ):
            raise ValueError("wall_time_seconds cannot be negative")
        if type(self.coverage_complete) is not bool:
            raise ValueError("coverage_complete must be a boolean")


@dataclass(frozen=True)
class ScalingReview:
    should_continue: bool
    stop_reason: StopReason | None
    next_total_agents: int | None
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["stop_reason"] = (
            self.stop_reason.value if self.stop_reason is not None else None
        )
        return result


@dataclass
class DecisionTrace:
    scores: list[Score] = field(default_factory=list)

    def add(self, code: str, value: float, explanation: str) -> None:
        self.scores.append(
            Score(code=code, value=round(value, 4), explanation=explanation)
        )
