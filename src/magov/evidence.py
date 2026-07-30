"""Inspectable evidence records for Governor decisions.

The receipt intentionally stores observations and reasons instead of a model's
self-reported confidence.  It is small enough to display to a person and stable
enough to persist as local JSON for replay.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class DecisionAction(str, Enum):
    SINGLE = "single"
    START_MULTI = "start_multi"
    ADD_AGENT = "add_agent"
    STOP = "stop"
    INCOMPLETE_STOP = "incomplete_stop"


class EvidenceSource(str, Enum):
    TASK = "task"
    RUNTIME = "runtime"
    VERIFIER = "verifier"
    POLICY = "policy"


@dataclass(frozen=True)
class EvidenceFact:
    """One checkable reason used by a decision."""

    code: str
    statement: str
    source: EvidenceSource

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("evidence code cannot be empty")
        if not self.statement.strip():
            raise ValueError("evidence statement cannot be empty")


@dataclass(frozen=True)
class DecisionReceipt:
    """Human-readable and machine-readable record of one governance checkpoint."""

    decision_id: str
    task_id: str
    action: DecisionAction
    current_agents: int
    max_agents: int
    recommended_total_agents: int
    reasons: tuple[EvidenceFact, ...]
    remaining_risks: tuple[str, ...] = ()
    governance_tokens: int = 0
    total_task_tokens: int = 0
    policy_version: str = "experimental-unvalidated"

    def __post_init__(self) -> None:
        if not self.decision_id.strip() or not self.task_id.strip():
            raise ValueError("decision_id and task_id cannot be empty")
        if not self.policy_version.strip():
            raise ValueError("policy_version cannot be empty")
        if self.current_agents < 1:
            raise ValueError("current_agents must be at least 1")
        if self.max_agents < 1:
            raise ValueError("max_agents must be at least 1")
        if not 1 <= self.recommended_total_agents <= self.max_agents:
            raise ValueError(
                "recommended_total_agents must be between 1 and max_agents"
            )
        if self.current_agents > self.max_agents:
            raise ValueError("current_agents cannot exceed max_agents")
        if self.governance_tokens < 0 or self.total_task_tokens < 0:
            raise ValueError("token counts cannot be negative")
        if self.governance_tokens > self.total_task_tokens:
            raise ValueError("governance_tokens cannot exceed total_task_tokens")
        if not self.reasons:
            raise ValueError("a decision receipt must include at least one reason")

    @property
    def governance_token_share(self) -> float:
        if self.total_task_tokens == 0:
            return 0.0
        return self.governance_tokens / self.total_task_tokens

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["action"] = self.action.value
        result["reasons"] = [
            {
                "code": item.code,
                "statement": item.statement,
                "source": item.source.value,
            }
            for item in self.reasons
        ]
        result["governance_token_share"] = round(
            self.governance_token_share, 6
        )
        return result
